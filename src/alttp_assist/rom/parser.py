"""ROM parsing functions for ALttP.

Reads room headers, sprites, objects/doors, overworld sprites, dialog text,
and tile attribute tables from the ROM file.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Optional

from alttp_assist.rom.data import (
    DOOR_DIRECTION_NAMES,
    EXPECTED_TITLE,
    MAP16_TO_MAP8_COUNT,
    MAP16_TO_MAP8_SNES,
    MAP8_TO_TILEATTR_COUNT,
    MAP8_TO_TILEATTR_SNES,
    NUM_ROOMS,
    OBJECT_TYPE_NAMES,
    OW_SPRITE_PTR_TABLE_DW,
    OW_SPRITE_PTR_TABLE_LW,
    ROOM_HEADER_BANK_BASE,
    ROOM_HEADER_PTR_TABLE,
    ROOM_OBJECT_PTR_TABLE,
    ROOM_SPRITE_BANK_BASE,
    ROOM_SPRITE_PTR_TABLE,
    DoorObject,
    RomData,
    RoomData,
    RoomHeader,
    RoomObject,
    RoomSprite,
)
from alttp_assist.rom.dialog import parse_dialog_strings


# ─── Dungeon room mapping ────────────────────────────────────────────────────

_DUNGEON_ROOM_DATA: dict[str, list[int]] = {
    "Hyrule Castle": [
        0x01, 0x02, 0x11, 0x12, 0x21, 0x22, 0x32,
        0x41, 0x50, 0x51, 0x52, 0x55, 0x60, 0x61,
        0x62, 0x70, 0x71, 0x72, 0x80, 0x81, 0x82,
    ],
    "Eastern Palace": [
        0x89, 0x98, 0x99, 0x9A, 0xA8, 0xA9, 0xAA,
        0xB8, 0xB9, 0xBA, 0xC8, 0xC9, 0xD8, 0xD9, 0xDA,
    ],
    "Desert Palace": [
        0x33, 0x43, 0x53, 0x63, 0x73, 0x83, 0x84, 0x85,
    ],
    "Tower of Hera": [
        0x07, 0x17, 0x27, 0x77, 0xA7,
    ],
    "Castle Tower": [
        0x20, 0x30, 0x40, 0xB0, 0xC0, 0xD0, 0xE0,
    ],
    "Palace of Darkness": [
        0x09, 0x0A, 0x0B, 0x19, 0x1A, 0x1B, 0x2A, 0x2B,
        0x3A, 0x3B, 0x4A, 0x4B, 0x5A, 0x5B, 0x6A, 0x6B,
    ],
    "Swamp Palace": [
        0x06, 0x16, 0x26, 0x28, 0x34, 0x35, 0x36, 0x37,
        0x38, 0x46, 0x66, 0x76,
    ],
    "Skull Woods": [
        0x39, 0x49, 0x56, 0x57, 0x58, 0x59,
        0x67, 0x68, 0x87, 0x88,
    ],
    "Thieves' Town": [
        0x44, 0x45, 0x64, 0x65, 0xAB, 0xAC,
        0xBB, 0xBC, 0xCB, 0xCC, 0xDB, 0xDC,
    ],
    "Ice Palace": [
        0x0E, 0x1E, 0x1F, 0x2E, 0x3E, 0x3F, 0x4E, 0x5E, 0x5F,
        0x6E, 0x7E, 0x7F, 0x8E, 0x9E, 0x9F, 0xAE, 0xBE, 0xBF,
        0xCE, 0xDE,
    ],
    "Misery Mire": [
        0x90, 0x91, 0x92, 0x93, 0xA0, 0xA1, 0xA2, 0xA3,
        0xB1, 0xB2, 0xB3, 0xC1, 0xC2, 0xC3, 0xD1, 0xD2,
    ],
    "Turtle Rock": [
        0x04, 0x13, 0x14, 0x15, 0x23, 0x24, 0x25,
        0xB4, 0xB5, 0xB6, 0xC4, 0xC5, 0xC6, 0xD4, 0xD5, 0xD6,
    ],
    "Ganon's Tower": [
        0x0C, 0x0D, 0x1C, 0x1D, 0x3C, 0x3D, 0x4C, 0x4D,
        0x5C, 0x5D, 0x6C, 0x6D, 0x7C, 0x7D, 0x8C, 0x8D,
        0x95, 0x96, 0x9C, 0x9D,
    ],
}

_ROOM_TO_DUNGEON: dict[int, str] = {}
for _dname, _rooms in _DUNGEON_ROOM_DATA.items():
    for _rid in _rooms:
        _ROOM_TO_DUNGEON[_rid] = _dname


# ─── ROM Parsing Functions ────────────────────────────────────────────────────

def _detect_header(rom_data: bytes) -> int:
    """Detect and return SMC header size (0 or 512)."""
    if len(rom_data) % 1024 == 512:
        return 512
    return 0


def _validate_title(rom: bytes, offset: int) -> bool:
    """Check the internal ROM title at SNES $00FFC0."""
    title_offset = offset + 0x7FC0
    if title_offset + 21 > len(rom):
        return False
    title = rom[title_offset:title_offset + 21].decode("ascii", errors="replace").rstrip()
    return title.startswith(EXPECTED_TITLE)


def _snes_to_rom(snes_addr: int) -> int:
    """Convert a SNES LoROM address to a file offset (headerless)."""
    bank = (snes_addr >> 16) & 0x7F
    offset = snes_addr & 0xFFFF
    return (bank * 0x8000) + (offset - 0x8000)


def _parse_room_headers(rom: bytes, offset: int) -> dict[int, RoomHeader]:
    """Parse room headers for all 320 rooms."""
    headers: dict[int, RoomHeader] = {}
    ptr_base = offset + ROOM_HEADER_PTR_TABLE

    for room_id in range(NUM_ROOMS):
        ptr_addr = ptr_base + room_id * 2
        if ptr_addr + 2 > len(rom):
            continue
        ptr = struct.unpack_from("<H", rom, ptr_addr)[0]

        rom_offset = offset + ROOM_HEADER_BANK_BASE + (ptr - 0x8000)
        if rom_offset + 14 > len(rom):
            continue

        raw = rom[rom_offset:rom_offset + 14]

        bg2 = struct.unpack_from("<H", raw, 0)[0]
        palette = raw[2]
        blockset = raw[3]
        spriteset = raw[4]
        bgmove = raw[5]
        tag1 = raw[6]
        tag2 = raw[7]
        plane1_z = raw[8]
        plane2_z = raw[9]
        msg_id = struct.unpack_from("<H", raw, 10)[0]

        headers[room_id] = RoomHeader(
            room_id=room_id,
            bg2=bg2,
            palette=palette,
            blockset=blockset,
            spriteset=spriteset,
            bgmove=bgmove,
            tag1=tag1,
            tag2=tag2,
            plane1_z=plane1_z,
            plane2_z=plane2_z,
            msg_id=msg_id,
            raw=raw,
        )

    return headers


def _parse_room_sprites(rom: bytes, offset: int) -> dict[int, list[RoomSprite]]:
    """Parse room sprite data for all 320 rooms."""
    sprites: dict[int, list[RoomSprite]] = {}
    ptr_base = offset + ROOM_SPRITE_PTR_TABLE

    for room_id in range(NUM_ROOMS):
        ptr_addr = ptr_base + room_id * 2
        if ptr_addr + 2 > len(rom):
            continue
        ptr = struct.unpack_from("<H", rom, ptr_addr)[0]

        rom_offset = offset + ROOM_SPRITE_BANK_BASE + (ptr - 0x8000)
        if rom_offset >= len(rom):
            continue

        rom_offset += 1  # skip sort order byte

        room_sprites: list[RoomSprite] = []
        max_sprites = 30

        while rom_offset + 3 <= len(rom) and len(room_sprites) < max_sprites:
            b0 = rom[rom_offset]
            if b0 == 0xFF:
                break

            b1 = rom[rom_offset + 1]
            b2 = rom[rom_offset + 2]

            y_tile = b0 & 0x1F
            is_lower = bool(b0 & 0x80)
            x_tile = b1 & 0x1F
            aux = ((b0 & 0x60) >> 3) | ((b1 & 0x60) >> 5)
            sprite_type = b2

            room_sprites.append(RoomSprite(
                x_tile=x_tile,
                y_tile=y_tile,
                sprite_type=sprite_type,
                is_lower_layer=is_lower,
                aux_data=aux,
            ))

            rom_offset += 3

        sprites[room_id] = room_sprites

    return sprites


def _parse_object_layer(rom: bytes, pos: int, max_objects: int = 200,
                        ) -> tuple[list[RoomObject], list[DoorObject], int]:
    """Parse one layer of room data: 3-byte objects, optional doors."""
    objects: list[RoomObject] = []
    doors: list[DoorObject] = []
    obj_count = 0

    while pos + 2 <= len(rom) and obj_count < max_objects:
        w = struct.unpack_from("<H", rom, pos)[0]

        if w == 0xFFFF:
            pos += 2
            return objects, doors, pos

        if w == 0xFFF0:
            pos += 2
            door_count = 0
            while pos + 2 <= len(rom) and door_count < 16:
                dw = struct.unpack_from("<H", rom, pos)[0]
                if dw == 0xFFFF:
                    pos += 2
                    return objects, doors, pos

                door_dir = dw & 3
                door_pos = (dw >> 4) & 0xF
                door_type = (dw >> 8) & 0xFF

                if door_dir in DOOR_DIRECTION_NAMES:
                    doors.append(DoorObject(
                        direction=door_dir,
                        door_type=door_type,
                        position=door_pos,
                    ))

                pos += 2
                door_count += 1
            return objects, doors, pos

        if pos + 3 > len(rom):
            break

        p0 = rom[pos]
        p1 = rom[pos + 1]
        p2 = rom[pos + 2]

        if (p0 & 0xFC) == 0xFC:
            x_tile = ((p0 & 3) << 4 | (p1 >> 4)) & 0x3F
            y_tile = ((p1 & 0x0F) << 2 | (p2 >> 6)) & 0x3F
            obj_type = 0x200 + (p2 & 0x3F)
        elif p2 >= 0xF8:
            x_tile = (p0 >> 2) & 0x3F
            y_tile = (p1 >> 2) & 0x3F
            obj_type = 0x100 + ((p2 & 7) << 4 | (p1 & 3) << 2 | (p0 & 3))
        else:
            x_tile = (p0 >> 2) & 0x3F
            y_tile = (p1 >> 2) & 0x3F
            obj_type = p2

        if obj_type in OBJECT_TYPE_NAMES:
            objects.append(RoomObject(
                x_tile=x_tile,
                y_tile=y_tile,
                object_type=obj_type,
            ))

        pos += 3
        obj_count += 1

    return objects, doors, pos


def _parse_room_objects(rom: bytes, offset: int) -> dict[int, tuple[list[RoomObject], list[DoorObject]]]:
    """Parse room object/door data for all 320 rooms."""
    result: dict[int, tuple[list[RoomObject], list[DoorObject]]] = {}
    ptr_base = offset + ROOM_OBJECT_PTR_TABLE

    for room_id in range(NUM_ROOMS):
        ptr_addr = ptr_base + room_id * 3
        if ptr_addr + 3 > len(rom):
            continue

        b0 = rom[ptr_addr]
        b1 = rom[ptr_addr + 1]
        b2 = rom[ptr_addr + 2]
        snes_addr = b0 | (b1 << 8) | (b2 << 16)

        if snes_addr == 0 or snes_addr == 0xFFFFFF:
            continue

        try:
            rom_off = _snes_to_rom(snes_addr) + offset
        except (ValueError, OverflowError):
            continue

        if rom_off < 0 or rom_off >= len(rom):
            continue

        pos = rom_off + 2  # skip 2-byte header

        all_objects: list[RoomObject] = []
        all_doors: list[DoorObject] = []

        for _ in range(3):
            layer_objs, layer_doors, pos = _parse_object_layer(rom, pos)
            all_objects.extend(layer_objs)
            all_doors.extend(layer_doors)

        result[room_id] = (all_objects, all_doors)

    return result


def _parse_ow_sprites(rom: bytes, offset: int) -> dict[int, list[RoomSprite]]:
    """Parse overworld sprite tables."""
    ow_sprites: dict[int, list[RoomSprite]] = {}

    for table_offset, screen_start in [
        (OW_SPRITE_PTR_TABLE_LW, 0x00),
        (OW_SPRITE_PTR_TABLE_DW, 0x40),
    ]:
        ptr_base = offset + table_offset
        num_screens = 64

        for i in range(num_screens):
            screen_id = screen_start + i
            ptr_addr = ptr_base + i * 2
            if ptr_addr + 2 > len(rom):
                continue
            ptr = struct.unpack_from("<H", rom, ptr_addr)[0]

            rom_off = offset + 0x48000 + (ptr - 0x8000)
            if rom_off < 0 or rom_off >= len(rom):
                continue

            screen_sprites: list[RoomSprite] = []
            max_count = 30

            while rom_off + 3 <= len(rom) and len(screen_sprites) < max_count:
                b0 = rom[rom_off]
                if b0 == 0xFF:
                    break

                b1 = rom[rom_off + 1]
                b2 = rom[rom_off + 2]

                y_tile = b0 & 0x3F
                x_tile = b1 & 0x3F
                sprite_type = b2

                screen_sprites.append(RoomSprite(
                    x_tile=x_tile,
                    y_tile=y_tile,
                    sprite_type=sprite_type,
                ))

                rom_off += 3

            if screen_sprites:
                ow_sprites[screen_id] = screen_sprites

    return ow_sprites


def load_rom(path: str, verbose: bool = False) -> Optional[RomData]:
    """Load and parse an ALttP ROM file.

    Returns RomData with all parsed room data, or None if the ROM
    is invalid or cannot be read.
    """
    rom_path = Path(path)
    if not rom_path.exists():
        print(f"ROM file not found: {path}")
        return None

    rom = rom_path.read_bytes()

    header_size = _detect_header(rom)
    if header_size:
        print(f"Detected {header_size}-byte SMC header, skipping.")

    if not _validate_title(rom, header_size):
        if verbose:
            print(f"Warning: ROM title does not match expected '{EXPECTED_TITLE}'.")
            print("Proceeding anyway, but data may be incorrect.")

    offset = header_size

    headers = _parse_room_headers(rom, offset)
    if verbose:
        print(f"Parsed {len(headers)} room headers.")

    sprites = _parse_room_sprites(rom, offset)
    if verbose:
        sprite_count = sum(len(v) for v in sprites.values())
        print(f"Parsed sprites for {len(sprites)} rooms ({sprite_count} total sprites).")

    try:
        objects_doors = _parse_room_objects(rom, offset)
        if verbose:
            obj_count = sum(len(o) for o, _ in objects_doors.values())
            door_count = sum(len(d) for _, d in objects_doors.values())
            print(f"Parsed objects for {len(objects_doors)} rooms "
                  f"({obj_count} objects, {door_count} doors).")
    except Exception as e:
        if verbose:
            print(f"Warning: Room object parsing failed ({e}). "
                  "Door/object data will not be available.")
        objects_doors = {}

    ow_sprites = _parse_ow_sprites(rom, offset)
    if verbose:
        ow_count = sum(len(v) for v in ow_sprites.values())
        print(f"Parsed overworld sprites for {len(ow_sprites)} screens ({ow_count} total).")

    try:
        dialog_strings = parse_dialog_strings(rom, offset)
        if verbose:
            print(f"Parsed {len(dialog_strings)} dialog strings.")
    except Exception as e:
        if verbose:
            print(f"Warning: Dialog parsing failed ({e}). "
                  "Dialog text will not be available from ROM.")
        dialog_strings = []

    room_data: dict[int, RoomData] = {}
    for room_id in range(NUM_ROOMS):
        header = headers.get(room_id)
        room_sprites = sprites.get(room_id, [])
        room_objects, room_doors = objects_doors.get(room_id, ([], []))
        dungeon = _ROOM_TO_DUNGEON.get(room_id, "")

        room_data[room_id] = RoomData(
            room_id=room_id,
            header=header,
            sprites=room_sprites,
            doors=room_doors,
            objects=room_objects,
            dungeon_name=dungeon,
        )

    map16_to_map8: Optional[list[int]] = None
    map8_to_tileattr: Optional[bytes] = None
    try:
        m16_off = _snes_to_rom(MAP16_TO_MAP8_SNES) + offset
        m8_off = _snes_to_rom(MAP8_TO_TILEATTR_SNES) + offset
        m16_data = rom[m16_off:m16_off + MAP16_TO_MAP8_COUNT * 2]
        map16_to_map8 = list(struct.unpack_from(
            f"<{MAP16_TO_MAP8_COUNT}H", m16_data))
        map8_to_tileattr = rom[m8_off:m8_off + MAP8_TO_TILEATTR_COUNT]
        if verbose:
            print(f"Loaded tile attribute tables "
                  f"(map16→map8: {len(map16_to_map8)}, "
                  f"map8→attr: {len(map8_to_tileattr)}).")
    except Exception as e:
        if verbose:
            print(f"Warning: Tile attribute table extraction failed ({e}).")

    return RomData(room_data=room_data, ow_sprites=ow_sprites,
                   dialog_strings=dialog_strings,
                   map16_to_map8=map16_to_map8,
                   map8_to_tileattr=map8_to_tileattr)
