"""RetroArch UDP client and memory reading."""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass, field
from typing import Optional

from alttp_assist.constants import (
    MEMORY_MAP,
    SPRITE_TABLE,
    _DUNG_TILEATTR_ADDR,
    _FACING_OFFSETS,
    _OW_TILEATTR_ADDR,
)
from alttp_assist.game_state import GameState, Sprite
from alttp_assist.rom.data import RomData


@dataclass
class RetroArchClient:
    """Communicates with RetroArch via its UDP network command interface."""
    host: str = "127.0.0.1"
    port: int = 55355
    timeout: float = 1.0
    _sock: Optional[socket.socket] = field(default=None, repr=False)

    def connect(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(self.timeout)

    def _send_command(self, cmd: str) -> str:
        if not self._sock:
            self.connect()
        self._sock.sendto(cmd.encode(), (self.host, self.port))
        try:
            data, _ = self._sock.recvfrom(65535)
            return data.decode("utf-8", errors="replace").strip()
        except socket.timeout:
            return ""

    def get_status(self) -> str:
        return self._send_command("GET_STATUS")

    def get_version(self) -> str:
        return self._send_command("VERSION")

    def read_core_memory(self, address: int, length: int) -> Optional[bytes]:
        cmd = f"READ_CORE_MEMORY {address:X} {length}"
        resp = self._send_command(cmd)
        if not resp or resp.startswith("READ_CORE_MEMORY -1"):
            return None
        parts = resp.split()
        if len(parts) < 3:
            return None
        try:
            return bytes(int(b, 16) for b in parts[2:])
        except (ValueError, IndexError):
            return None

    def write_core_memory(self, address: int, data: bytes) -> bool:
        hex_bytes = " ".join(f"{b:02X}" for b in data)
        cmd = f"WRITE_CORE_MEMORY {address:X} {hex_bytes}"
        resp = self._send_command(cmd)
        return bool(resp) and "WRITE_CORE_MEMORY -1" not in resp

    def close(self):
        if self._sock:
            self._sock.close()


def read_memory(ra: RetroArchClient,
                rom_data: Optional[RomData] = None) -> GameState:
    """Read all ALttP memory addresses into a GameState."""
    raw: dict[str, Optional[int]] = {}
    for name, (addr, length) in MEMORY_MAP.items():
        data = ra.read_core_memory(addr, length)
        if data is not None:
            raw[name] = int.from_bytes(data, "little")
        else:
            raw[name] = None

    # Read sprite table (3 bulk reads: positions, states, types)
    sprites: list[Sprite] = []
    pos_addr, pos_len = SPRITE_TABLE["positions"]
    st_addr,  st_len  = SPRITE_TABLE["states"]
    ty_addr,  ty_len  = SPRITE_TABLE["types"]

    pos_data = ra.read_core_memory(pos_addr, pos_len)
    st_data  = ra.read_core_memory(st_addr,  st_len)
    ty_data  = ra.read_core_memory(ty_addr,  ty_len)

    if pos_data and st_data and ty_data:
        for i in range(16):
            y = pos_data[i] | (pos_data[32 + i] << 8)
            x = pos_data[16 + i] | (pos_data[48 + i] << 8)
            sprites.append(Sprite(
                index=i,
                type_id=ty_data[i],
                state=st_data[i],
                x=x,
                y=y,
            ))

    # Read the tile attribute for the tile Link is facing
    facing_tile = -1
    direction = raw.get("direction")
    link_x = raw.get("link_x")
    link_y = raw.get("link_y")
    module = raw.get("main_module")
    if direction is not None and link_x and link_y and module in (0x07, 0x09):
        off = _FACING_OFFSETS.get(direction)
        if off:
            px = link_x + off[0]
            py = link_y + off[1]
            tx = (px >> 3) & 63
            ty = py & 0x1f8
            if module == 0x07:
                lower = raw.get("lower_level", 0)
                dung_off = (ty & ~7) * 8 + tx + (0x1000 if lower else 0)
                tile_data = ra.read_core_memory(_DUNG_TILEATTR_ADDR + dung_off, 1)
                if tile_data:
                    facing_tile = tile_data[0]
            elif rom_data and rom_data.map16_to_map8 is not None:
                base_y = raw.get("ow_offset_base_y", 0)
                mask_y = raw.get("ow_offset_mask_y", 0)
                base_x = raw.get("ow_offset_base_x", 0)
                mask_x = raw.get("ow_offset_mask_x", 0)
                ow_tx = (px >> 3)
                t = ((py - base_y) & mask_y) * 8
                t |= ((ow_tx - base_x) & mask_x)
                ow_off = t >> 1
                tile_data = ra.read_core_memory(_OW_TILEATTR_ADDR + ow_off * 2, 2)
                if tile_data:
                    map16_idx = int.from_bytes(tile_data, "little")
                    facing_tile = rom_data.ow_tile_attr(map16_idx, ow_tx, py)

    return GameState(raw=raw, sprites=sprites, timestamp=time.time(),
                     rom_data=rom_data, facing_tile=facing_tile)
