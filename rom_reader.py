#!/usr/bin/env python3
"""
ALttP ROM Reader
================
Parses A Link to the Past ROM files to extract room geometry, sprite
placements, and door/object layouts for accessibility descriptions.

ROM format: 1MB LoROM (.sfc), optional 512-byte SMC header.
All offsets assume headerless ROM unless noted.
"""

from __future__ import annotations

import struct
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ─── Constants ───────────────────────────────────────────────────────────────

EXPECTED_TITLE = "THE LEGEND OF ZELDA"
ROM_SIZE = 1048576  # 1MB

# Room header pointer table: 320 entries × 2-byte LE, bank $04
ROOM_HEADER_PTR_TABLE = 0x27502
ROOM_HEADER_BANK_BASE = 0x20000  # bank $04 maps $8000-$FFFF → ROM 0x20000+

# Room sprite pointer table: 320 entries × 2-byte LE, bank $09
ROOM_SPRITE_PTR_TABLE = 0x4D62E
ROOM_SPRITE_BANK_BASE = 0x48000  # bank $09 maps $8000-$FFFF → ROM 0x48000+

# Room object pointer table: 320 entries × 3-byte SNES addresses (bank $0B-$0C)
# SNES $1F:8000 → LoROM offset 0xF8000
ROOM_OBJECT_PTR_TABLE = 0xF8000

# Overworld sprite pointer tables
OW_SPRITE_PTR_TABLE_LW = 0x4C881   # Light World screens 0x00-0x3F
OW_SPRITE_PTR_TABLE_LW2 = 0x4C901  # Light World screens 0x40-0x7F (special)
OW_SPRITE_PTR_TABLE_DW = 0x4CA21   # Dark World screens

NUM_ROOMS = 320
NUM_OW_SCREENS = 128

# Room header tag1 flags
TAG1_NOTHING = 0x00
TAG1_NPC = 0x01
TAG1_DARK_ROOM = 0x02
TAG1_KILL_TO_OPEN = 0x08
TAG1_MOVING_FLOOR = 0x04
TAG1_MOVING_WATER = 0x06
TAG1_WATER_GATES = 0x0A

# Room header tag2 flags
TAG2_NOTHING = 0x00


# ─── Sprite Type Classification ──────────────────────────────────────────────

class SpriteCategory:
    ENEMY = "enemy"
    BOSS = "boss"
    NPC = "npc"
    INTERACTABLE = "interactable"
    HAZARD = "hazard"
    OBJECT = "object"
    UNKNOWN = "unknown"


# Comprehensive sprite type table: id -> (name, category)
SPRITE_TYPE_NAMES: dict[int, tuple[str, str]] = {
    # ── Enemies ──
    0x01: ("Raven", SpriteCategory.ENEMY),
    0x02: ("Vulture", SpriteCategory.ENEMY),
    0x08: ("Octorok (1-way)", SpriteCategory.ENEMY),
    0x09: ("Octorok (4-way)", SpriteCategory.ENEMY),
    0x0A: ("Cucco", SpriteCategory.NPC),
    0x0C: ("Buzzblob", SpriteCategory.ENEMY),
    0x0D: ("Snapdragon", SpriteCategory.ENEMY),
    0x0E: ("Octoballoon", SpriteCategory.ENEMY),
    0x0F: ("Octoballoon baby", SpriteCategory.ENEMY),
    0x10: ("Hinox", SpriteCategory.ENEMY),
    0x11: ("Moblin", SpriteCategory.ENEMY),
    0x12: ("Mini Helmasaur", SpriteCategory.ENEMY),
    0x13: ("Thieves' Town Grate", SpriteCategory.OBJECT),
    0x15: ("Antifairy", SpriteCategory.HAZARD),
    0x16: ("Elder", SpriteCategory.NPC),
    0x17: ("Hylian villager", SpriteCategory.NPC),
    0x18: ("Mini Moldorm", SpriteCategory.ENEMY),
    0x19: ("Poe", SpriteCategory.ENEMY),
    0x1A: ("Leever", SpriteCategory.ENEMY),
    0x1B: ("Arrow target", SpriteCategory.OBJECT),
    0x1C: ("Statue pullable", SpriteCategory.INTERACTABLE),
    0x1E: ("Crystal switch", SpriteCategory.INTERACTABLE),
    0x1F: ("Sick Kid", SpriteCategory.NPC),
    0x20: ("Sluggula", SpriteCategory.ENEMY),
    0x21: ("Water switch", SpriteCategory.INTERACTABLE),
    0x22: ("Ropa", SpriteCategory.ENEMY),
    0x23: ("Red Bari", SpriteCategory.ENEMY),
    0x24: ("Blue Bari", SpriteCategory.ENEMY),
    0x25: ("Talking tree", SpriteCategory.NPC),
    0x26: ("Hardhat Beetle", SpriteCategory.ENEMY),
    0x27: ("Deadrock", SpriteCategory.ENEMY),
    0x28: ("Storyteller", SpriteCategory.NPC),
    0x29: ("Zora", SpriteCategory.ENEMY),
    0x2A: ("Weathervane", SpriteCategory.OBJECT),
    0x2B: ("Pikit", SpriteCategory.ENEMY),
    0x2C: ("Maiden at sanctuary", SpriteCategory.NPC),
    0x2D: ("Apple tree", SpriteCategory.OBJECT),
    0x2F: ("Master Sword", SpriteCategory.OBJECT),
    0x30: ("Devalant (non-shooter)", SpriteCategory.ENEMY),
    0x31: ("Devalant (shooter)", SpriteCategory.ENEMY),
    0x33: ("Rupee crab", SpriteCategory.ENEMY),
    0x35: ("Toppo", SpriteCategory.ENEMY),
    0x37: ("Popo", SpriteCategory.ENEMY),
    0x38: ("Popo (2)", SpriteCategory.ENEMY),
    0x39: ("Cane of Byrna spark", SpriteCategory.HAZARD),
    0x3B: ("Hylian guard", SpriteCategory.NPC),
    0x3D: ("Bush hoarder", SpriteCategory.ENEMY),
    0x3E: ("Bombable guard", SpriteCategory.NPC),
    0x3F: ("Whirlpool", SpriteCategory.HAZARD),

    0x40: ("open chest", SpriteCategory.INTERACTABLE),

    # ── Soldiers ──
    0x41: ("Green Soldier", SpriteCategory.ENEMY),
    0x42: ("Blue Soldier", SpriteCategory.ENEMY),
    0x43: ("Red Javelin Soldier", SpriteCategory.ENEMY),
    0x44: ("Red Sword Soldier", SpriteCategory.ENEMY),
    0x45: ("Blue Archer Soldier", SpriteCategory.ENEMY),
    0x46: ("Green Archer Soldier", SpriteCategory.ENEMY),
    0x47: ("Blue Javelin Soldier", SpriteCategory.ENEMY),
    0x48: ("Red Javelin Soldier (2)", SpriteCategory.ENEMY),
    0x49: ("Red Bomb Soldier", SpriteCategory.ENEMY),
    0x4A: ("Green Bomb Soldier", SpriteCategory.ENEMY),
    0x4B: ("lantern", SpriteCategory.OBJECT),

    # ── Dungeon enemies ──
    0x53: ("Armos", SpriteCategory.ENEMY),
    0x54: ("Armos Knight", SpriteCategory.BOSS),
    0x55: ("Lanmola", SpriteCategory.BOSS),
    0x56: ("Fireball Zora", SpriteCategory.ENEMY),
    0x57: ("Walking Zora", SpriteCategory.ENEMY),
    0x58: ("Desert Crab", SpriteCategory.ENEMY),
    0x59: ("Lost Woods Bird", SpriteCategory.ENEMY),
    0x5B: ("Spark (clockwise)", SpriteCategory.HAZARD),
    0x5C: ("Spark (counterclockwise)", SpriteCategory.HAZARD),
    0x5D: ("Roller (vertical)", SpriteCategory.HAZARD),
    0x5E: ("Roller (horizontal)", SpriteCategory.HAZARD),
    0x60: ("Roller (diagonal)", SpriteCategory.HAZARD),
    0x61: ("Beamos", SpriteCategory.HAZARD),
    0x63: ("Debirando", SpriteCategory.ENEMY),
    0x64: ("Debirando (falling)", SpriteCategory.ENEMY),
    0x66: ("Wall cannon (vertical)", SpriteCategory.HAZARD),
    0x67: ("Wall cannon (horizontal)", SpriteCategory.HAZARD),
    0x68: ("Ball and Chain Trooper", SpriteCategory.ENEMY),
    0x69: ("Cannon Soldier", SpriteCategory.ENEMY),
    0x6A: ("Ball and Chain Trooper", SpriteCategory.ENEMY),
    0x6B: ("Rat", SpriteCategory.ENEMY),
    0x6C: ("Rope", SpriteCategory.ENEMY),
    0x6D: ("Keese", SpriteCategory.ENEMY),
    0x6E: ("Helmasaur King Fireball", SpriteCategory.HAZARD),
    0x6F: ("Leever", SpriteCategory.ENEMY),
    0x70: ("Fairy activation", SpriteCategory.INTERACTABLE),
    0x71: ("Uncle / Priest", SpriteCategory.NPC),
    0x72: ("Running Man", SpriteCategory.NPC),
    0x73: ("Bottle Vendor", SpriteCategory.NPC),
    0x74: ("Princess Zelda", SpriteCategory.NPC),
    0x76: ("Zelda", SpriteCategory.NPC),
    0x77: ("Pipe Down", SpriteCategory.OBJECT),
    0x78: ("Pipe Up", SpriteCategory.OBJECT),
    0x79: ("Pipe Right", SpriteCategory.OBJECT),
    0x7A: ("Pipe Left", SpriteCategory.OBJECT),
    0x7B: ("Good Bee", SpriteCategory.NPC),
    0x7C: ("Hylian inscription", SpriteCategory.OBJECT),
    0x7D: ("Thief hoarder", SpriteCategory.NPC),
    0x7E: ("Bug-catching Kid", SpriteCategory.NPC),
    0x80: ("Moldorm (Eye)", SpriteCategory.BOSS),
    0x81: ("Moldorm", SpriteCategory.BOSS),
    0x82: ("Telepathic tile", SpriteCategory.INTERACTABLE),
    0x83: ("Green Eyegore", SpriteCategory.ENEMY),
    0x84: ("Red Eyegore", SpriteCategory.ENEMY),
    0x85: ("Stalfos", SpriteCategory.ENEMY),
    0x86: ("Kodongo", SpriteCategory.ENEMY),
    0x87: ("Kodongo fire", SpriteCategory.HAZARD),
    0x88: ("Mothula", SpriteCategory.BOSS),
    0x89: ("Mothula beam", SpriteCategory.HAZARD),
    0x8A: ("Spike Trap", SpriteCategory.HAZARD),
    0x8B: ("Gibdo", SpriteCategory.ENEMY),
    0x8C: ("Arrghus", SpriteCategory.BOSS),
    0x8D: ("Arrghus spawn", SpriteCategory.BOSS),
    0x8E: ("Terrorpin", SpriteCategory.ENEMY),
    0x8F: ("Blob", SpriteCategory.ENEMY),
    0x90: ("Wallmaster", SpriteCategory.ENEMY),
    0x91: ("Stalfos Knight", SpriteCategory.ENEMY),
    0x92: ("Helmasaur King", SpriteCategory.BOSS),
    0x93: ("Bumper", SpriteCategory.HAZARD),
    0x95: ("Laser Eye (right)", SpriteCategory.HAZARD),
    0x96: ("Laser Eye (left)", SpriteCategory.HAZARD),
    0x97: ("Laser Eye (down)", SpriteCategory.HAZARD),
    0x98: ("Laser Eye (up)", SpriteCategory.HAZARD),
    0x99: ("Pengator", SpriteCategory.ENEMY),
    0x9A: ("Kyameron", SpriteCategory.ENEMY),
    0x9B: ("Wizzrobe", SpriteCategory.ENEMY),
    0xA0: ("Babasu", SpriteCategory.ENEMY),
    0xA1: ("Babusu", SpriteCategory.HAZARD),
    0xA2: ("Haunted grove hopper", SpriteCategory.ENEMY),
    0xA3: ("Lumberjack tree pull", SpriteCategory.OBJECT),
    0xA4: ("Teleport bug", SpriteCategory.HAZARD),
    0xA5: ("Firesnake", SpriteCategory.ENEMY),
    0xA6: ("Hover", SpriteCategory.HAZARD),
    0xA7: ("Water Tektite", SpriteCategory.ENEMY),
    0xA8: ("Antifairy Circle", SpriteCategory.HAZARD),
    0xA9: ("Green Eyegore (mimic)", SpriteCategory.ENEMY),
    0xAA: ("Red Eyegore (mimic)", SpriteCategory.ENEMY),
    0xAB: ("Yellow Stalfos", SpriteCategory.ENEMY),
    0xAC: ("Kodongo", SpriteCategory.ENEMY),
    0xAD: ("Flames", SpriteCategory.HAZARD),
    0xAE: ("Mothula platform", SpriteCategory.HAZARD),
    0xB1: ("Four-way fireball", SpriteCategory.HAZARD),
    0xB2: ("Guruguru Bar (clockwise)", SpriteCategory.HAZARD),
    0xB3: ("Guruguru Bar (counterclockwise)", SpriteCategory.HAZARD),
    0xB4: ("Winder", SpriteCategory.ENEMY),
    0xB5: ("Draw bridge", SpriteCategory.OBJECT),
    0xB6: ("Rupee pull", SpriteCategory.INTERACTABLE),
    0xB9: ("Red Rupee Crab", SpriteCategory.ENEMY),
    0xBA: ("Red Bari", SpriteCategory.ENEMY),
    0xBB: ("Blue Bari", SpriteCategory.ENEMY),
    0xBC: ("Tektite", SpriteCategory.ENEMY),

    # ── Bosses ──
    0xC8: ("Blind", SpriteCategory.BOSS),
    0xC9: ("Blind laser", SpriteCategory.HAZARD),
    0xCB: ("Kholdstare", SpriteCategory.BOSS),
    0xCC: ("Kholdstare shell", SpriteCategory.BOSS),
    0xCE: ("Vitreous", SpriteCategory.BOSS),
    0xCF: ("Vitreous (small)", SpriteCategory.BOSS),
    0xD0: ("Viterous lightning", SpriteCategory.HAZARD),
    0xD1: ("Catfish", SpriteCategory.NPC),
    0xD2: ("Agahnim teleport", SpriteCategory.HAZARD),
    0xD3: ("Bully / Pink Ball", SpriteCategory.ENEMY),
    0xD4: ("Whirlpool", SpriteCategory.HAZARD),
    0xD6: ("Ganon", SpriteCategory.BOSS),
    0xD7: ("Agahnim", SpriteCategory.BOSS),
    # ── Item drops (0xD8-0xE6) ──
    0xD8: ("Heart", SpriteCategory.INTERACTABLE),
    0xD9: ("Green Rupee", SpriteCategory.INTERACTABLE),
    0xDA: ("Blue Rupee", SpriteCategory.INTERACTABLE),
    0xDB: ("Red Rupee", SpriteCategory.INTERACTABLE),
    0xDC: ("Bombs (1)", SpriteCategory.INTERACTABLE),
    0xDD: ("Bombs (4)", SpriteCategory.INTERACTABLE),
    0xDE: ("Bombs (8)", SpriteCategory.INTERACTABLE),
    0xDF: ("Small Magic Jar", SpriteCategory.INTERACTABLE),
    0xE0: ("Large Magic Jar", SpriteCategory.INTERACTABLE),
    0xE1: ("Arrows (5)", SpriteCategory.INTERACTABLE),
    0xE2: ("Arrows (10)", SpriteCategory.INTERACTABLE),

    # ── NPCs / overworld characters ──
    0xE3: ("Fairy", SpriteCategory.NPC),
    0xE4: ("Small Key", SpriteCategory.INTERACTABLE),
    0xE5: ("Big Key", SpriteCategory.INTERACTABLE),
    0xE8: ("Mushroom", SpriteCategory.INTERACTABLE),
    0xE9: ("Fake Master Sword", SpriteCategory.OBJECT),
    0xEB: ("Shopkeeper", SpriteCategory.NPC),
    0xED: ("Maiden", SpriteCategory.NPC),
    0xF2: ("Chest game guy", SpriteCategory.NPC),
    0xF4: ("Sahasrahla", SpriteCategory.NPC),
    0xF5: ("Old Man on mountain", SpriteCategory.NPC),
    0xF7: ("Witch", SpriteCategory.NPC),
    0xF9: ("Waterfall fairy", SpriteCategory.NPC),
}


# ─── Door Type Names ─────────────────────────────────────────────────────────

# Door encoding (from zelda3 reimplementation):
#   Low byte:  PPPP DD00  (P = position 0-11, D = direction 0-3)
#   High byte: TTTTTTTT   (door type)
DOOR_DIRECTION_NAMES = {
    0: "north",
    1: "south",
    2: "west",
    3: "east",
}

DOOR_TYPE_NAMES: dict[int, str] = {
    0:  "open doorway",
    2:  "normal doorway",
    4:  "passage",
    6:  "entrance door",
    8:  "waterfall tunnel",
    10: "entrance (large)",
    12: "entrance (large, alt)",
    14: "cave entrance",
    16: "cave entrance (alt)",
    18: "exit to overworld",
    20: "throne room",
    22: "staircase",
    24: "shutter (two-way)",
    26: "invisible door",
    28: "small key door",
    30: "small key door (alt)",
    32: "staircase (locked 0)",
    34: "staircase (locked 1)",
    36: "staircase (locked 2)",
    38: "staircase (locked 3)",
    40: "breakable wall",
    42: "breakable wall (alt)",
    44: "breakable wall (alt 2)",
    46: "breakable wall (alt 3)",
    48: "large explosion wall",
    50: "slashable curtain",
    64: "regular door",
    68: "shutter",
    70: "warp room door",
    72: "shutter trap (upper-right)",
    74: "shutter trap (down-left)",
}


# ─── Object Type Names ───────────────────────────────────────────────────────

# Room object type IDs from the 3-byte room object entries.
# Derived from the zelda3 reimplementation (snesrev/zelda3).
# Only objects relevant for accessibility descriptions are included;
# structural elements (walls, ceilings, floor tiles) are omitted.
#
# Subtype 0: obj_type = p2                        (range 0x00-0xF7)
# Subtype 1: obj_type = 0x100 + computed_index    (range 0x100-0x17F)
# Subtype 2: obj_type = 0x200 + (p2 & 0x3F)      (range 0x200-0x23F)

OBJECT_TYPE_NAMES: dict[int, tuple[str, str]] = {
    # type_id -> (name, category)
    # Categories: stairs, chest, pit, water, block, switch, torch,
    #             hazard, interactable, feature

    # ── Subtype 0 (structural with gameplay relevance) ──
    0x21: ("mini stairs", "stairs"),
    0x38: ("statue", "feature"),
    0x3D: ("standing torch", "torch"),
    0x5E: ("block", "block"),
    0x87: ("floor torch", "torch"),
    0x88: ("statue", "feature"),
    0x89: ("block", "block"),
    0x92: ("blue peg block", "block"),
    0x93: ("orange peg block", "block"),
    0x96: ("hammer peg block", "block"),
    0xA4: ("hole", "pit"),
    0xB8: ("blue switch block", "switch"),
    0xB9: ("red switch block", "switch"),
    0xBD: ("hammer peg", "block"),
    0xC8: ("water floor", "water"),
    0xC9: ("water floor", "water"),
    0xD1: ("water floor", "water"),
    0xDE: ("spike block", "hazard"),
    0xDF: ("spike floor", "hazard"),
    0xE3: ("conveyor belt (north)", "hazard"),
    0xE4: ("conveyor belt (south)", "hazard"),
    0xE5: ("conveyor belt (west)", "hazard"),
    0xE6: ("conveyor belt (east)", "hazard"),

    # ── Subtype 1 (discrete gameplay objects) ──
    0x10D: ("prison cell", "feature"),
    0x113: ("telepathic tile", "interactable"),
    0x116: ("hammer peg", "block"),
    0x118: ("cell lock", "interactable"),
    0x119: ("chest", "chest"),
    0x11A: ("open chest", "chest"),
    0x11B: ("staircase", "stairs"),
    0x11C: ("staircase", "stairs"),
    0x11D: ("staircase", "stairs"),
    0x11E: ("staircase going up", "stairs"),
    0x11F: ("staircase going down", "stairs"),
    0x120: ("staircase going up", "stairs"),
    0x121: ("staircase going down", "stairs"),
    0x126: ("staircase going up", "stairs"),
    0x127: ("staircase going up", "stairs"),
    0x128: ("staircase going down", "stairs"),
    0x129: ("staircase going down", "stairs"),
    0x12B: ("staircase going down", "stairs"),
    0x12C: ("large block", "block"),
    0x12F: ("pot", "interactable"),
    0x131: ("big chest", "chest"),
    0x132: ("big chest (open)", "chest"),
    0x133: ("staircase", "stairs"),
    0x147: ("bomb floor", "interactable"),
    0x14A: ("warp tile", "interactable"),
    0x150: ("floor switch", "switch"),
    0x151: ("skull pot", "interactable"),
    0x152: ("blue peg", "block"),
    0x153: ("red peg", "block"),
    0x163: ("fake floor switch", "hazard"),
    0x164: ("fireball shooter", "hazard"),
    0x165: ("medusa head", "hazard"),
    0x166: ("hole", "pit"),
    0x167: ("bombable wall (north)", "interactable"),
    0x168: ("bombable wall (south)", "interactable"),
    0x169: ("bombable wall (west)", "interactable"),
    0x16A: ("bombable wall (east)", "interactable"),
    0x174: ("boss entrance", "interactable"),
    0x175: ("minigame chest", "chest"),

    # ── Subtype 2 (single-tile objects) ──
    0x21C: ("fairy pot", "interactable"),
    0x21D: ("statue", "feature"),
    0x21E: ("star tile", "switch"),
    0x21F: ("star tile", "switch"),
    0x220: ("torch (lit)", "torch"),
    0x221: ("barrel", "interactable"),
    0x22D: ("floor stairs up", "stairs"),
    0x22E: ("floor stairs down", "stairs"),
    0x22F: ("floor stairs down", "stairs"),
    0x231: ("staircase", "stairs"),
    0x232: ("staircase", "stairs"),
    0x234: ("block", "block"),
    0x235: ("water ladder", "interactable"),
    0x236: ("water ladder", "interactable"),
    0x237: ("water gate", "interactable"),
}


# ─── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class RoomHeader:
    room_id: int
    bg2: int = 0
    palette: int = 0
    blockset: int = 0
    spriteset: int = 0
    bgmove: int = 0
    tag1: int = 0
    tag2: int = 0
    plane1_z: int = 0
    plane2_z: int = 0
    msg_id: int = 0
    raw: bytes = b""

    @property
    def is_dark(self) -> bool:
        return self.tag1 == TAG1_DARK_ROOM

    @property
    def has_kill_to_open(self) -> bool:
        return self.tag1 == TAG1_KILL_TO_OPEN

    @property
    def has_moving_floor(self) -> bool:
        return self.tag1 == TAG1_MOVING_FLOOR

    @property
    def has_moving_water(self) -> bool:
        return self.tag1 == TAG1_MOVING_WATER

    @property
    def has_water_gates(self) -> bool:
        return self.tag1 == TAG1_WATER_GATES


@dataclass
class RoomSprite:
    x_tile: int
    y_tile: int
    sprite_type: int
    is_lower_layer: bool = False
    aux_data: int = 0

    @property
    def name(self) -> str:
        entry = SPRITE_TYPE_NAMES.get(self.sprite_type)
        return entry[0] if entry else f"sprite {self.sprite_type:#04x}"

    @property
    def category(self) -> str:
        entry = SPRITE_TYPE_NAMES.get(self.sprite_type)
        return entry[1] if entry else SpriteCategory.UNKNOWN


@dataclass
class DoorObject:
    direction: int
    door_type: int
    position: int = 0

    @property
    def direction_name(self) -> str:
        return DOOR_DIRECTION_NAMES.get(self.direction, f"direction {self.direction:#04x}")

    @property
    def type_name(self) -> str:
        return DOOR_TYPE_NAMES.get(self.door_type, f"door type {self.door_type:#04x}")


@dataclass
class RoomObject:
    x_tile: int
    y_tile: int
    object_type: int

    @property
    def name(self) -> str:
        entry = OBJECT_TYPE_NAMES.get(self.object_type)
        return entry[0] if entry else f"object {self.object_type:#04x}"

    @property
    def category(self) -> str:
        entry = OBJECT_TYPE_NAMES.get(self.object_type)
        return entry[1] if entry else "unknown"


def _dedup_sprites(sprites: list[RoomSprite]) -> list[RoomSprite]:
    """Remove duplicate sprites of the same type at adjacent tiles.

    Some objects (e.g. lanterns) use two sprite slots for lit/unlit
    states at neighbouring positions.  Collapse these into one entry.
    """
    kept: list[RoomSprite] = []
    seen: set[int] = set()  # indices already consumed
    by_type: dict[int, list[int]] = {}
    for i, s in enumerate(sprites):
        by_type.setdefault(s.sprite_type, []).append(i)
    for indices in by_type.values():
        for i in indices:
            if i in seen:
                continue
            seen.add(i)
            kept.append(sprites[i])
            si = sprites[i]
            # Mark adjacent same-type sprites as duplicates
            for j in indices:
                if j in seen:
                    continue
                sj = sprites[j]
                if abs(si.x_tile - sj.x_tile) <= 1 and abs(si.y_tile - sj.y_tile) <= 1:
                    seen.add(j)
    return kept


def _pluralize(name: str) -> str:
    """Pluralize a name, handling parenthetical suffixes.

    Examples:
        "chest"                 → "chests"
        "crystal switch"        → "crystal switches"
        "stairs going up"       → "stairs going up"  (already plural)
        "bombable wall (north)" → "bombable walls (north)"
        "Spark (clockwise)"     → "Sparks (clockwise)"
        "Armos"                 → "Armos"  (already ends in s)
    """
    # Split off parenthetical suffix if present
    paren_idx = name.find("(")
    if paren_idx > 0:
        base = name[:paren_idx].rstrip()
        suffix = " " + name[paren_idx:]
    else:
        base = name
        suffix = ""

    # Skip if any word already looks plural
    if any(w.endswith("s") for w in base.split()):
        return name
    # Add -es for sibilant endings
    if base.endswith(("ch", "sh", "x", "z")):
        return base + "es" + suffix
    return base + "s" + suffix


@dataclass
class RoomData:
    room_id: int
    header: Optional[RoomHeader] = None
    sprites: list[RoomSprite] = field(default_factory=list)
    doors: list[DoorObject] = field(default_factory=list)
    objects: list[RoomObject] = field(default_factory=list)
    dungeon_name: str = ""

    def _classify_sprites(self) -> dict[str, list[str]]:
        """Group sprite names by category (after dedup)."""
        groups: dict[str, list[str]] = {}
        for s in _dedup_sprites(self.sprites):
            cat = s.category
            groups.setdefault(cat, []).append(s.name)
        return groups

    def _format_sprite_group(self, names: list[str]) -> str:
        """Format a list of sprite names with counts."""
        counts = Counter(names)
        parts = []
        for name, count in counts.items():
            if count > 1:
                parts.append(f"{count} {_pluralize(name)}")
            else:
                parts.append(name)
        return ", ".join(parts)

    def _format_doors(self) -> str:
        """Format door list for descriptions.

        De-duplicates doors at the same (direction, position) by preferring
        the more specific type over the generic "open doorway" (type 0).
        """
        if not self.doors:
            return ""
        # De-duplicate: when two doors share direction+position, drop the
        # generic "open doorway" (type 0) in favour of the specific one.
        by_loc: dict[tuple[int, int], list[DoorObject]] = {}
        for d in self.doors:
            by_loc.setdefault((d.direction, d.position), []).append(d)
        deduped: list[DoorObject] = []
        for group in by_loc.values():
            specific = [d for d in group if d.door_type != 0]
            deduped.extend(specific if specific else group)
        parts = []
        for d in deduped:
            parts.append(f"{d.type_name} to the {d.direction_name}")
        return ", ".join(parts)

    def _format_conditions(self) -> list[str]:
        """List room conditions from header tags."""
        conditions = []
        if self.header:
            if self.header.is_dark:
                conditions.append("Dark room")
            if self.header.has_kill_to_open:
                conditions.append("Defeat all enemies to open the doors")
            if self.header.has_moving_floor:
                conditions.append("Moving floor")
            if self.header.has_moving_water:
                conditions.append("Moving water")
            if self.header.has_water_gates:
                conditions.append("Water level gates")
        return conditions

    def _get_object_groups(self) -> dict[str, list[str]]:
        """Group objects by category for descriptions."""
        groups: dict[str, list[str]] = {}
        for obj in self.objects:
            cat = obj.category
            if cat:
                groups.setdefault(cat, []).append(obj.name)
        return groups

    def to_brief(self) -> str:
        """Brief description auto-announced on room change."""
        parts = []

        # Dungeon name + room ID
        if self.dungeon_name:
            parts.append(f"{self.dungeon_name}, room {self.room_id:#06x}")
        else:
            parts.append(f"Room {self.room_id:#06x}")

        # Conditions
        conditions = self._format_conditions()
        if conditions:
            parts.append(". ".join(conditions))

        # Doors
        door_text = self._format_doors()
        if door_text:
            parts.append(f"Exits: {door_text}")

        # Enemies/bosses
        sprite_groups = self._classify_sprites()
        for cat in (SpriteCategory.BOSS, SpriteCategory.ENEMY):
            if cat in sprite_groups:
                parts.append(self._format_sprite_group(sprite_groups[cat]))

        return ". ".join(parts) + "."

    def to_full(self) -> str:
        """Full description for 'look' command."""
        lines = []

        # Header line
        if self.dungeon_name:
            lines.append(f"{self.dungeon_name}, room {self.room_id:#06x}.")
        else:
            lines.append(f"Room {self.room_id:#06x}.")

        # Conditions
        conditions = self._format_conditions()
        if conditions:
            for cond in conditions:
                if cond == "Dark room":
                    lines.append("This room is dark. Use the Lamp to see.")
                elif cond == "Defeat all enemies to open the doors":
                    lines.append("Defeat all enemies to open the doors.")
                else:
                    lines.append(f"{cond}.")

        # Exits
        door_text = self._format_doors()
        if door_text:
            lines.append(f"Exits: {door_text}.")

        # Features from objects
        obj_groups = self._get_object_groups()
        feature_cats = ("chest", "stairs", "switch", "torch", "block", "interactable", "feature")
        feature_parts = []
        for cat in feature_cats:
            if cat in obj_groups:
                feature_parts.append(self._format_sprite_group(obj_groups[cat]))
        if feature_parts:
            lines.append(f"Features: {', '.join(feature_parts)}.")

        # Hazards from objects and sprites
        hazard_parts = []
        if "hazard" in obj_groups:
            hazard_parts.extend(obj_groups["hazard"])
        if "pit" in obj_groups:
            hazard_parts.extend(obj_groups["pit"])
        if "water" in obj_groups:
            hazard_parts.extend(obj_groups["water"])
        sprite_groups = self._classify_sprites()
        if SpriteCategory.HAZARD in sprite_groups:
            hazard_parts.extend(sprite_groups[SpriteCategory.HAZARD])
        if hazard_parts:
            lines.append(f"Hazards: {self._format_sprite_group(hazard_parts)}.")

        # Enemies
        if SpriteCategory.ENEMY in sprite_groups:
            lines.append(f"Enemies: {self._format_sprite_group(sprite_groups[SpriteCategory.ENEMY])}.")

        # Bosses
        if SpriteCategory.BOSS in sprite_groups:
            lines.append(f"Boss: {self._format_sprite_group(sprite_groups[SpriteCategory.BOSS])}.")

        # NPCs
        if SpriteCategory.NPC in sprite_groups:
            lines.append(f"NPCs: {self._format_sprite_group(sprite_groups[SpriteCategory.NPC])}.")

        # Interactable sprites
        if SpriteCategory.INTERACTABLE in sprite_groups:
            lines.append(f"Interactables: {self._format_sprite_group(sprite_groups[SpriteCategory.INTERACTABLE])}.")

        return "\n".join(lines)


# ─── Tile Type Names ────────────────────────────────────────────────────────
# From zelda3 tile_detect.c — maps the tile attribute byte to a human name.
# Only interesting/interactable tile types are listed; unlisted = passable ground.

TILE_TYPE_NAMES: dict[int, str] = {
    0x01: "wall", 0x02: "wall", 0x03: "wall",
    0x04: "thick grass",  # indoor: wall (handled in bridge.py)
    0x08: "deep water", 0x09: "shallow water",
    0x0A: "water ladder",
    0x0D: "spike floor",
    0x0E: "ice floor", 0x0F: "ice floor",
    0x1C: "ledge",
    0x1D: "stairs", 0x1E: "stairs", 0x1F: "stairs",
    0x20: "pit",
    0x22: "stairs",
    0x26: "wall",
    0x27: "hookshot target",
    0x28: "ledge (north)", 0x29: "ledge (south)",
    0x2A: "ledge (east)", 0x2B: "ledge (west)",
    0x40: "thick grass",
    0x42: "gravestone",
    0x43: "wall",
    0x44: "cactus",
    0x46: "sign",
    0x48: "diggable ground", 0x4A: "diggable ground",
    0x4B: "warp tile",
    0x50: "bush", 0x51: "bush",
    0x52: "liftable rock", 0x53: "liftable rock",
    0x54: "liftable pot", 0x55: "liftable pot", 0x56: "liftable pot",
    0x57: "dashable rocks",
    0x58: "chest", 0x59: "chest", 0x5A: "chest",
    0x5B: "chest", 0x5C: "chest", 0x5D: "chest",
    0x60: "rupee tile",
    0x67: "crystal peg",
    0x68: "conveyor (north)", 0x69: "conveyor (south)",
    0x6A: "conveyor (west)", 0x6B: "conveyor (east)",
    # 0x70-0x7F: TileBehavior_ManipulablyReplaced — pushable blocks/statues
    0x70: "pushable block", 0x71: "pushable block",
    0x72: "pushable block", 0x73: "pushable block",
    0x74: "pushable block", 0x75: "pushable block",
    0x76: "pushable block", 0x77: "pushable block",
    0x78: "pushable block", 0x79: "pushable block",
    0x7A: "pushable block", 0x7B: "pushable block",
    0x7C: "pushable block", 0x7D: "pushable block",
    0x7E: "pushable block", 0x7F: "pushable block",
    0x8E: "entrance", 0x8F: "entrance",
}

# ROM table addresses (SNES LoROM) for overworld tile attribute lookup
_MAP16_TO_MAP8_SNES = 0x8F8000   # 3752 * 4 uint16 entries
_MAP16_TO_MAP8_COUNT = 3752 * 4
_MAP8_TO_TILEATTR_SNES = 0x8E9459  # 512 uint8 entries
_MAP8_TO_TILEATTR_COUNT = 512


@dataclass
class RomData:
    """All parsed ROM data, keyed by room/screen ID."""
    room_data: dict[int, RoomData] = field(default_factory=dict)
    ow_sprites: dict[int, list[RoomSprite]] = field(default_factory=dict)
    dialog_strings: list[str] = field(default_factory=list)
    # Tile attribute lookup tables (loaded from ROM)
    map16_to_map8: Optional[list[int]] = field(default=None, repr=False)
    map8_to_tileattr: Optional[bytes] = field(default=None, repr=False)

    def get_room(self, room_id: int) -> Optional[RoomData]:
        return self.room_data.get(room_id)

    def get_ow_sprites(self, screen_id: int) -> list[RoomSprite]:
        return self.ow_sprites.get(screen_id, [])

    def ow_tile_attr(self, map16_index: int, x: int, y: int) -> int:
        """Look up the overworld tile attribute for a map16 tile.

        *map16_index* comes from the WRAM overworld_tileattr table at
        $7E:2000.  *x* is in 8-px tile units, *y* in pixel units (only
        the low bits select the sub-tile within the map16 cell).

        Returns the tile attribute byte (see TILE_TYPE_NAMES).
        """
        if self.map16_to_map8 is None or self.map8_to_tileattr is None:
            return 0
        t = map16_index * 4
        t |= (y & 8) >> 2
        t |= (x & 1)
        if t < 0 or t >= len(self.map16_to_map8):
            return 0
        map8 = self.map16_to_map8[t]
        idx = map8 & 0x1FF
        if idx >= len(self.map8_to_tileattr):
            return 0
        rv = self.map8_to_tileattr[idx]
        if 0x10 <= rv < 0x1C:
            rv |= (map8 >> 14) & 1
        return rv

    def format_ow_sprites(self, screen_id: int) -> str:
        """Format overworld sprite listing for a screen."""
        sprites = _dedup_sprites(self.get_ow_sprites(screen_id))
        if not sprites:
            return ""
        groups: dict[str, list[str]] = {}
        for s in sprites:
            groups.setdefault(s.category, []).append(s.name)
        parts = []
        for cat in (SpriteCategory.ENEMY, SpriteCategory.NPC, SpriteCategory.BOSS,
                     SpriteCategory.HAZARD, SpriteCategory.INTERACTABLE,
                     SpriteCategory.OBJECT):
            if cat in groups:
                counts = Counter(groups[cat])
                for name, count in counts.items():
                    if count > 1:
                        parts.append(f"{count} {_pluralize(name)}")
                    else:
                        parts.append(name)
        if parts:
            return "Creatures: " + ", ".join(parts) + "."
        return ""


# ─── Dungeon room mapping (copied from bridge.py for room labeling) ──────────

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
    """Check the internal ROM title at SNES $00FFC0 (LoROM: file offset 0x7FC0)."""
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
        # Read 2-byte LE pointer
        ptr_addr = ptr_base + room_id * 2
        if ptr_addr + 2 > len(rom):
            continue
        ptr = struct.unpack_from("<H", rom, ptr_addr)[0]

        # Convert bank-relative pointer to ROM offset
        rom_offset = offset + ROOM_HEADER_BANK_BASE + (ptr - 0x8000)
        if rom_offset + 14 > len(rom):
            continue

        raw = rom[rom_offset:rom_offset + 14]

        # Parse the 14-byte header
        # Byte layout (from ALttP disassembly):
        # 0-1: BG2 property
        # 2:   Palette
        # 3:   Blockset
        # 4:   Spriteset
        # 5:   BG move
        # 6:   Tag1
        # 7:   Tag2
        # 8:   Plane1 Z
        # 9:   Plane2 Z
        # 10-11: Message ID
        # 12-13: (more flags)
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

        # Convert bank-relative pointer to ROM offset
        rom_offset = offset + ROOM_SPRITE_BANK_BASE + (ptr - 0x8000)
        if rom_offset >= len(rom):
            continue

        # First byte is the sort order, skip it
        rom_offset += 1

        room_sprites: list[RoomSprite] = []
        max_sprites = 30  # Safety limit

        while rom_offset + 3 <= len(rom) and len(room_sprites) < max_sprites:
            b0 = rom[rom_offset]
            if b0 == 0xFF:
                break

            b1 = rom[rom_offset + 1]
            b2 = rom[rom_offset + 2]

            # Byte 0: Y position (6 bits) + layer flag (bit 7)
            # Byte 1: X position (6 bits) + aux bits
            # Byte 2: Sprite type
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
    """Parse one layer of room data: 3-byte objects, optional doors.

    Data format (from zelda3 reimplementation):
      3-byte object entries until 0xFFF0 or 0xFFFF.
      0xFFF0 → door entries (2-byte each) follow, terminated by 0xFFFF.
      0xFFFF → layer ends with no doors.

    Object encoding (3 bytes: p0, p1, p2):
      Subtype 0 (p2 < 0xF8, low 6 bits of p0 != 0xFC):
        X = (p0 >> 2) & 0x3F, Y = (p1 >> 2) & 0x3F, type = p2
      Subtype 1 (p2 >= 0xF8, low 6 bits of p0 != 0xFC):
        X = (p0 >> 2) & 0x3F, Y = (p1 >> 2) & 0x3F
        type = (p2 & 7) << 4 | (p1 & 3) << 2 | (p0 & 3)  [0x100+ range]
      Subtype 2 (low 6 bits of p0 == 0xFC):
        X = ((p0 & 3) << 4 | (p1 >> 4)) & 0x3F
        Y = ((p1 & 0x0F) << 2 | (p2 >> 6)) & 0x3F
        type = (p2 & 0x3F)  [0x200+ range]

    Door encoding (2 bytes):
      Low byte:  PPPPDD00  (P=position, D=direction 0=N 1=S 2=W 3=E)
      High byte: door type

    Returns (objects, doors, next_pos).
    """
    objects: list[RoomObject] = []
    doors: list[DoorObject] = []
    obj_count = 0

    while pos + 2 <= len(rom) and obj_count < max_objects:
        w = struct.unpack_from("<H", rom, pos)[0]

        if w == 0xFFFF:
            # Layer ends, no doors
            pos += 2
            return objects, doors, pos

        if w == 0xFFF0:
            # Objects end, doors follow
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
            # Subtype 2
            x_tile = ((p0 & 3) << 4 | (p1 >> 4)) & 0x3F
            y_tile = ((p1 & 0x0F) << 2 | (p2 >> 6)) & 0x3F
            obj_type = 0x200 + (p2 & 0x3F)
        elif p2 >= 0xF8:
            # Subtype 1
            x_tile = (p0 >> 2) & 0x3F
            y_tile = (p1 >> 2) & 0x3F
            obj_type = 0x100 + ((p2 & 7) << 4 | (p1 & 3) << 2 | (p0 & 3))
        else:
            # Subtype 0
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
    """Parse room object/door data for all 320 rooms.

    Room data format (from zelda3 reimplementation):
    - 2-byte header: floor byte + layout/quadrant byte
    - Layer 1 objects + optional doors (terminated by 0xFFFF)
    - Layer 2 objects + optional doors (terminated by 0xFFFF)
    - Layer 3 objects + optional doors (terminated by 0xFFFF)

    Returns dict mapping room_id -> (objects, doors).
    """
    result: dict[int, tuple[list[RoomObject], list[DoorObject]]] = {}
    ptr_base = offset + ROOM_OBJECT_PTR_TABLE

    for room_id in range(NUM_ROOMS):
        ptr_addr = ptr_base + room_id * 3
        if ptr_addr + 3 > len(rom):
            continue

        # 3-byte SNES address (little-endian)
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

        # Skip 2-byte header (floor + layout/quadrant)
        pos = rom_off + 2

        all_objects: list[RoomObject] = []
        all_doors: list[DoorObject] = []

        # Parse 3 layers
        for _ in range(3):
            layer_objs, layer_doors, pos = _parse_object_layer(rom, pos)
            all_objects.extend(layer_objs)
            all_doors.extend(layer_doors)

        result[room_id] = (all_objects, all_doors)

    return result


def _parse_ow_sprites(rom: bytes, offset: int) -> dict[int, list[RoomSprite]]:
    """Parse overworld sprite tables."""
    ow_sprites: dict[int, list[RoomSprite]] = {}

    # Light World: two tables for screens 0x00-0x7F
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

            # Bank $09: ROM = 0x48000 + (ptr - 0x8000)
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


# ─── Dialog Text Decoding ────────────────────────────────────────────────────
# ALttP US ROM encodes dialog using a custom compression scheme:
#   - 95-char alphabet, 97-entry dictionary, and command bytes.
#   - Text starts at SNES $9C:8000, bank-switches to $8E:DF40.

_DIALOG_ALPHABET = [
    # 0-25: A-Z
    "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M",
    "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z",
    # 26-51: a-z
    "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
    "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z",
    # 52-61: 0-9
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
    # 62-66: punctuation
    "!", "?", "-", ".", ",",
    # 67-70: special punctuation
    "...", ">", "(", ")",
    # 71-75: graphic tiles (empty for accessibility)
    "", "", "", "", "",
    # 76: double quote
    "\"",
    # 77-80: direction arrows (empty for accessibility)
    "", "", "", "",
    # 81: apostrophe
    "'",
    # 82-88: heart graphics (empty for accessibility)
    "", "", "", "", "", "", "",
    # 89: space
    " ",
    # 90: less-than
    "<",
    # 91-94: button icons (empty for accessibility)
    "", "", "", "",
]

_DIALOG_DICTIONARY = [
    "    ", "   ", "  ", "'s ", "and ",
    "are ", "all ", "ain", "and", "at ",
    "ast", "an", "at", "ble", "ba",
    "be", "bo", "can ", "che", "com",
    "ck", "des", "di", "do", "en ",
    "er ", "ear", "ent", "ed ", "en",
    "er", "ev", "for", "fro", "give ",
    "get", "go", "have", "has", "her",
    "hi", "ha", "ight ", "ing ", "in",
    "is", "it", "just", "know", "ly ",
    "la", "lo", "man", "ma", "me",
    "mu", "n't ", "non", "not", "open",
    "ound", "out ", "of", "on", "or",
    "per", "ple", "pow", "pro", "re ",
    "re", "some", "se", "sh", "so",
    "st", "ter ", "thin", "ter", "tha",
    "the", "thi", "to", "tr", "up",
    "ver", "with", "wa", "we", "wh",
    "wi", "you", "Her", "Tha", "The",
    "Thi", "You",
]

# Command byte lengths: 1 = standalone, 2 = followed by a parameter byte.
# Covers bytes 0x67-0x7F (25 entries). Index 24 (0x7F) is EndMessage.
_DIALOG_CMD_LENGTHS = [
    1, 1, 1, 1, 2, 2, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1,
    2, 2, 2, 2, 1, 1, 1, 1, 1,
]

_DIALOG_CMD_NAMES = [
    "NextPic", "Choose", "Item", "Name", "Window", "Number",
    "Position", "ScrollSpd", "Selchg", "Unused_Crash", "Choose3",
    "Choose2", "Scroll", "1", "2", "3", "Color",
    "Wait", "Sound", "Speed", "Unused_Mark", "Unused_Mark2",
    "Unused_Clear", "Waitkey",
]

# SNES addresses for the two dialog text banks (US ROM).
_DIALOG_ROM_ADDRS = [0x9C8000, 0x8EDF40]


def _parse_dialog_strings(rom: bytes, offset: int) -> list[str]:
    """Decode all dialog strings from the ROM.

    Returns an ordered list where index N is dialog message N (matching
    the dialog_id read from WRAM $012C at runtime).
    """
    addr_idx = 0
    pos = _snes_to_rom(_DIALOG_ROM_ADDRS[addr_idx]) + offset

    messages: list[str] = []
    current: list[str] = []

    while pos < len(rom):
        b = rom[pos]
        pos += 1

        if b == 0xFF:
            # Finish — end of all dialog data
            if current:
                text = " ".join("".join(current).split()).strip()
                messages.append(text)
            break

        if b == 0x7F:
            # EndMessage — save current message
            text = " ".join("".join(current).split()).strip()
            messages.append(text)
            current = []
            continue

        if b == 0x80:
            # Switch to next ROM bank
            addr_idx += 1
            if addr_idx < len(_DIALOG_ROM_ADDRS):
                pos = _snes_to_rom(_DIALOG_ROM_ADDRS[addr_idx]) + offset
            else:
                break
            continue

        if b <= 0x5E:
            # Alphabet character lookup
            current.append(_DIALOG_ALPHABET[b])
            continue

        if 0x67 <= b <= 0x7E:
            # Command byte
            cmd_idx = b - 0x67
            cmd_len = _DIALOG_CMD_LENGTHS[cmd_idx]

            # Accessibility substitutions
            if cmd_idx < len(_DIALOG_CMD_NAMES):
                name = _DIALOG_CMD_NAMES[cmd_idx]
                if name == "Name":
                    current.append("Link")
                elif name in ("1", "2", "3", "Scroll"):
                    current.append(" ")

            # Skip parameter byte if command is 2 bytes
            if cmd_len == 2 and pos < len(rom):
                pos += 1
            continue

        if b >= 0x88:
            # Dictionary lookup
            dict_idx = b - 0x88
            if dict_idx < len(_DIALOG_DICTIONARY):
                current.append(_DIALOG_DICTIONARY[dict_idx])
            continue

        # Bytes 0x5F-0x66 and 0x81-0x87 are unused; skip.

    return messages


# ─── Main Entry Point ────────────────────────────────────────────────────────

def load_rom(path: str, verbose: bool = False) -> Optional[RomData]:
    """Load and parse an ALttP ROM file.

    Returns RomData with all parsed room data, or None if the ROM
    is invalid or cannot be read.  Set *verbose* to print progress.
    """
    rom_path = Path(path)
    if not rom_path.exists():
        print(f"ROM file not found: {path}")
        return None

    rom = rom_path.read_bytes()

    # Detect and skip SMC header
    header_size = _detect_header(rom)
    if header_size:
        print(f"Detected {header_size}-byte SMC header, skipping.")

    # Validate ROM title
    if not _validate_title(rom, header_size):
        if verbose:
            print(f"Warning: ROM title does not match expected '{EXPECTED_TITLE}'.")
            print("Proceeding anyway, but data may be incorrect.")

    offset = header_size

    # Parse room headers
    headers = _parse_room_headers(rom, offset)
    if verbose:
        print(f"Parsed {len(headers)} room headers.")

    # Parse room sprites
    sprites = _parse_room_sprites(rom, offset)
    if verbose:
        sprite_count = sum(len(v) for v in sprites.values())
        print(f"Parsed sprites for {len(sprites)} rooms ({sprite_count} total sprites).")

    # Parse room objects/doors (with graceful fallback)
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

    # Parse overworld sprites
    ow_sprites = _parse_ow_sprites(rom, offset)
    if verbose:
        ow_count = sum(len(v) for v in ow_sprites.values())
        print(f"Parsed overworld sprites for {len(ow_sprites)} screens ({ow_count} total).")

    # Parse dialog text
    try:
        dialog_strings = _parse_dialog_strings(rom, offset)
        if verbose:
            print(f"Parsed {len(dialog_strings)} dialog strings.")
    except Exception as e:
        if verbose:
            print(f"Warning: Dialog parsing failed ({e}). "
                  "Dialog text will not be available from ROM.")
        dialog_strings = []

    # Assemble RoomData for each room
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

    # Extract tile attribute lookup tables for overworld tile detection
    map16_to_map8: Optional[list[int]] = None
    map8_to_tileattr: Optional[bytes] = None
    try:
        m16_off = _snes_to_rom(_MAP16_TO_MAP8_SNES) + offset
        m8_off = _snes_to_rom(_MAP8_TO_TILEATTR_SNES) + offset
        m16_data = rom[m16_off:m16_off + _MAP16_TO_MAP8_COUNT * 2]
        map16_to_map8 = list(struct.unpack_from(
            f"<{_MAP16_TO_MAP8_COUNT}H", m16_data))
        map8_to_tileattr = rom[m8_off:m8_off + _MAP8_TO_TILEATTR_COUNT]
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


# ─── CLI for Testing ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python rom_reader.py <rom_path> [room_id_hex]")
        sys.exit(1)

    rom_path = sys.argv[1]
    data = load_rom(rom_path)
    if not data:
        sys.exit(1)

    if len(sys.argv) >= 3:
        # Show specific room
        room_id = int(sys.argv[2], 16)
        room = data.get_room(room_id)
        if room:
            print()
            print("=== Brief ===")
            print(room.to_brief())
            print()
            print("=== Full ===")
            print(room.to_full())
        else:
            print(f"Room {room_id:#06x} not found.")
    else:
        # Show summary of interesting rooms
        print("\nRooms with sprites:")
        for rid in sorted(data.room_data.keys()):
            rd = data.room_data[rid]
            if rd.sprites:
                names = [s.name for s in rd.sprites]
                dungeon = f" ({rd.dungeon_name})" if rd.dungeon_name else ""
                print(f"  Room {rid:#06x}{dungeon}: {', '.join(names)}")
