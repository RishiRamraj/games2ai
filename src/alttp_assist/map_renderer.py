"""ASCII map renderer for ALttP bridge."""

from __future__ import annotations

import time
from typing import Optional

from alttp_assist.constants import (
    ITEM_DROP_IDS,
    _DUNG_TILEATTR_ADDR,
    _LINK_BODY_OFFSET_X,
    _LINK_BODY_OFFSET_Y,
    _OW_TILEATTR_ADDR,
)
from alttp_assist.events import Event
from alttp_assist.game_state import GameState
from alttp_assist.proximity import ProximityTracker
from alttp_assist.retroarch import RetroArchClient
from alttp_assist.rom.data import RomData


class MapRenderer:
    """Renders a live ASCII map of the area around Link in the terminal."""

    VP_W = 32
    VP_H = 24

    TILE_CHARS: dict[int, str] = {
        0x00: ' ',
        0x01: '#', 0x02: '#', 0x03: '#', 0x26: '#', 0x43: '#',
        0x0B: '#', 0x6C: '#', 0x6D: '#', 0x6E: '#', 0x6F: '#',
        0x08: '~', 0x09: '~',
        0x20: 'O',
        0x0D: 'X',
        0x0E: '=', 0x0F: '=',
        0x1D: '>', 0x1E: '>', 0x1F: '>', 0x22: '>',
        0x1C: '_', 0x28: '_', 0x29: '_', 0x2A: '_', 0x2B: '_',
        0x58: '*', 0x59: '*', 0x5A: '*', 0x5B: '*', 0x5C: '*', 0x5D: '*',
        0x30: '+', 0x31: '+', 0x32: '+', 0x33: '+',
        0x34: '+', 0x35: '+', 0x36: '+', 0x37: '+',
        0x50: 'B', 0x51: 'B',
        0x52: 'R', 0x53: 'R',
        **{i: 'P' for i in range(0x70, 0x80)},
        0x04: ',', 0x40: ',',
        0x27: 'H',
        0x4B: 'W',
        0x54: 'R', 0x55: 'R', 0x56: 'R',
    }

    LINK_CHARS: dict[int, str] = {0: '^', 2: 'v', 4: '<', 6: '>'}

    _OVERLAY_PASSABLE = {'.', ' ', ','}
    _CONE_CHAR = ':'
    _NEARBY_CHAR = '1'
    _APPROACH_CHAR = '2'

    _EVENT_TTL = 5.0

    def __init__(self, overlay: bool = False) -> None:
        self._frame_count = 0
        self.overlay = overlay
        self._event_log: list[tuple[float, str]] = []

    def render(self, state: GameState, ra: RetroArchClient,
               rom_data: Optional[RomData] = None,
               events: Optional[list[Event]] = None,
               snapshot: bool = False) -> None:
        module = state.get("main_module")
        link_x = state.get("link_x")
        link_y = state.get("link_y")
        indoors = state.get("indoors")

        if module not in (0x07, 0x09) or not link_x or not link_y:
            print(f"\033[HWaiting for gameplay... (module={module:#04x})\033[K\033[J",
                  end="", flush=True)
            return

        grid = [['.' for _ in range(self.VP_W)] for _ in range(self.VP_H)]

        body_x = link_x + _LINK_BODY_OFFSET_X
        body_y = link_y + _LINK_BODY_OFFSET_Y
        vp_px = body_x - (self.VP_W // 2) * 8
        vp_py = body_y - (self.VP_H // 2) * 8

        if module == 0x07:
            self._fill_dungeon(grid, ra, state, vp_px, vp_py, indoors)
        elif module == 0x09 and rom_data:
            self._fill_overworld(grid, ra, state, rom_data, vp_px, vp_py)

        if self.overlay:
            self._draw_overlay(grid, state.get("direction"),
                               (self.VP_W // 2), (self.VP_H // 2))

        for s in state.sprites:
            if not s.is_active:
                continue
            sx = (s.x + _LINK_BODY_OFFSET_X - vp_px) // 8
            sy = (s.y + _LINK_BODY_OFFSET_Y - vp_py) // 8
            if 0 <= sx < self.VP_W and 0 <= sy < self.VP_H:
                if s.is_enemy:
                    grid[sy][sx] = 'E'
                elif s.type_id in ITEM_DROP_IDS:
                    grid[sy][sx] = 'I'

        lx = (body_x - vp_px) // 8
        ly = (body_y - vp_py) // 8
        direction = state.get("direction")
        link_ch = self.LINK_CHARS.get(direction, '@')
        for row in (ly, ly + 1):
            if 0 <= row < self.VP_H:
                for col in (lx - 1, lx):
                    if 0 <= col < self.VP_W:
                        grid[row][col] = link_ch

        self._frame_count += 1
        eol = "\033[K"

        now = time.monotonic()
        if events:
            for e in events:
                self._event_log.append((now, e.message))
        self._event_log = [(t, m) for t, m in self._event_log
                           if now - t < self._EVENT_TTL]

        map_width = self.VP_W * 2
        sidebar_gap = "  "
        lines: list[str] = []
        for i, row in enumerate(grid):
            map_line = ''.join(ch * 2 for ch in row)
            if self.overlay and i < len(self._event_log):
                _, msg = self._event_log[-(i + 1)]
                lines.append(map_line + sidebar_gap + msg + eol)
            else:
                lines.append(map_line + eol)

        lines.append(eol)
        room_info = state.location_name
        hp_str = state.format_health()
        lines.append(
            f"Pos: ({link_x},{link_y})  "
            f"Dir: {state.direction_name}  "
            f"HP: {hp_str}  "
            f"Loc: {room_info}" + eol
        )
        if self.overlay:
            lines.append(
                f": cone  "
                f"{self._NEARBY_CHAR} nearby({ProximityTracker.NEARBY_DIST}px)  "
                f"{self._APPROACH_CHAR} approach({ProximityTracker.APPROACH_DIST}px)" + eol
            )
        if snapshot:
            clean = [line.replace(eol, '') for line in lines]
            print('\n'.join(clean), end="", flush=True)
        else:
            print("\033[H" + '\n'.join(lines) + "\033[J", end="", flush=True)

    def _fill_dungeon(self, grid: list[list[str]],
                      ra: RetroArchClient, state: GameState,
                      vp_px: int, vp_py: int, indoors: int) -> None:
        lower = state.get("lower_level", 0)
        base = _DUNG_TILEATTR_ADDR + (0x1000 if lower else 0)
        data = ra.read_core_memory(base, 4096)
        if not data or len(data) < 4096:
            return

        indoor_walls = GameState._INDOOR_WALL_TILES

        for gy in range(self.VP_H):
            for gx in range(self.VP_W):
                px = vp_px + gx * 8
                py = vp_py + gy * 8
                tx = (px >> 3) & 63
                ty = (py >> 3) & 63
                off = ty * 64 + tx
                if 0 <= off < 4096:
                    attr = data[off]
                    if indoors and attr in indoor_walls:
                        grid[gy][gx] = '#'
                    else:
                        grid[gy][gx] = self._tile_char(attr, indoors)

    def _fill_overworld(self, grid: list[list[str]],
                        ra: RetroArchClient, state: GameState,
                        rom_data: RomData, vp_px: int, vp_py: int) -> None:
        base_y = state.get("ow_offset_base_y", 0)
        mask_y = state.get("ow_offset_mask_y", 0)
        base_x = state.get("ow_offset_base_x", 0)
        mask_x = state.get("ow_offset_mask_x", 0)

        if not mask_y or not mask_x:
            return

        map16_data = ra.read_core_memory(_OW_TILEATTR_ADDR, 8192)
        if not map16_data or len(map16_data) < 8192:
            return

        for gy in range(self.VP_H):
            for gx in range(self.VP_W):
                px = vp_px + gx * 8
                py = vp_py + gy * 8
                ow_tx = px >> 3
                t = ((py - base_y) & mask_y) * 8
                t |= ((ow_tx - base_x) & mask_x)
                ow_off = t >> 1
                byte_off = ow_off * 2
                if 0 <= byte_off < 8190:
                    map16_idx = int.from_bytes(
                        map16_data[byte_off:byte_off + 2], "little")
                    attr = rom_data.ow_tile_attr(map16_idx, ow_tx, py)
                    grid[gy][gx] = self._tile_char(attr, False)

    def _tile_char(self, attr: int, indoors: int) -> str:
        ch = self.TILE_CHARS.get(attr)
        if ch:
            return ch
        if attr == 0x04 and not indoors:
            return ','
        return '.'

    def _draw_overlay(self, grid: list[list[str]], direction: int,
                      cx: int, cy: int) -> None:
        passable = self._OVERLAY_PASSABLE

        approach_r = ProximityTracker.APPROACH_DIST / 8.0
        nearby_r = ProximityTracker.NEARBY_DIST / 8.0

        rings = [
            (approach_r, self._APPROACH_CHAR),
            (nearby_r, self._NEARBY_CHAR),
        ]
        for gy in range(self.VP_H):
            for gx in range(self.VP_W):
                if grid[gy][gx] not in passable:
                    continue
                dx = gx - cx
                dy = gy - cy
                dist = (dx * dx + dy * dy) ** 0.5
                for radius, ch in rings:
                    if abs(dist - radius) < 0.7:
                        grid[gy][gx] = ch
                        break

        cone = ProximityTracker._CONE_OFFSETS.get(direction)
        if cone:
            for ring in cone:
                for dx, dy in ring:
                    gx = cx + dx
                    gy = cy + dy
                    if (0 <= gx < self.VP_W and 0 <= gy < self.VP_H
                            and grid[gy][gx] in passable):
                        grid[gy][gx] = self._CONE_CHAR
