"""ROM data models for ALttP room geometry, sprites, doors, and objects."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from alttp_assist.rom.tiles import MAP16_NAME, TILE_TYPE_NAMES


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

# ROM table addresses (SNES LoROM) for overworld tile attribute lookup
MAP16_TO_MAP8_SNES = 0x8F8000   # 3752 * 4 uint16 entries
MAP16_TO_MAP8_COUNT = 3752 * 4
MAP8_TO_TILEATTR_SNES = 0x8E9459  # 512 uint8 entries
MAP8_TO_TILEATTR_COUNT = 512


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

OBJECT_TYPE_NAMES: dict[int, tuple[str, str]] = {
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
    """Remove duplicate sprites of the same type at adjacent tiles."""
    kept: list[RoomSprite] = []
    seen: set[int] = set()
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
            for j in indices:
                if j in seen:
                    continue
                sj = sprites[j]
                if abs(si.x_tile - sj.x_tile) <= 1 and abs(si.y_tile - sj.y_tile) <= 1:
                    seen.add(j)
    return kept


def _pluralize(name: str) -> str:
    """Pluralize a name, handling parenthetical suffixes."""
    paren_idx = name.find("(")
    if paren_idx > 0:
        base = name[:paren_idx].rstrip()
        suffix = " " + name[paren_idx:]
    else:
        base = name
        suffix = ""

    if any(w.endswith("s") for w in base.split()):
        return name
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
        """Format door list for descriptions."""
        if not self.doors:
            return ""
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

        if self.dungeon_name:
            parts.append(f"{self.dungeon_name}, room {self.room_id:#06x}")
        else:
            parts.append(f"Room {self.room_id:#06x}")

        conditions = self._format_conditions()
        if conditions:
            parts.append(". ".join(conditions))

        door_text = self._format_doors()
        if door_text:
            parts.append(f"Exits: {door_text}")

        sprite_groups = self._classify_sprites()
        for cat in (SpriteCategory.BOSS, SpriteCategory.ENEMY):
            if cat in sprite_groups:
                parts.append(self._format_sprite_group(sprite_groups[cat]))

        return ". ".join(parts) + "."

    def to_full(self) -> str:
        """Full description for 'look' command."""
        lines = []

        if self.dungeon_name:
            lines.append(f"{self.dungeon_name}, room {self.room_id:#06x}.")
        else:
            lines.append(f"Room {self.room_id:#06x}.")

        conditions = self._format_conditions()
        if conditions:
            for cond in conditions:
                if cond == "Dark room":
                    lines.append("This room is dark. Use the Lamp to see.")
                elif cond == "Defeat all enemies to open the doors":
                    lines.append("Defeat all enemies to open the doors.")
                else:
                    lines.append(f"{cond}.")

        door_text = self._format_doors()
        if door_text:
            lines.append(f"Exits: {door_text}.")

        obj_groups = self._get_object_groups()
        feature_cats = ("chest", "stairs", "switch", "torch", "block", "interactable", "feature")
        feature_parts = []
        for cat in feature_cats:
            if cat in obj_groups:
                feature_parts.append(self._format_sprite_group(obj_groups[cat]))
        if feature_parts:
            lines.append(f"Features: {', '.join(feature_parts)}.")

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

        if SpriteCategory.ENEMY in sprite_groups:
            lines.append(f"Enemies: {self._format_sprite_group(sprite_groups[SpriteCategory.ENEMY])}.")

        if SpriteCategory.BOSS in sprite_groups:
            lines.append(f"Boss: {self._format_sprite_group(sprite_groups[SpriteCategory.BOSS])}.")

        if SpriteCategory.NPC in sprite_groups:
            lines.append(f"NPCs: {self._format_sprite_group(sprite_groups[SpriteCategory.NPC])}.")

        if SpriteCategory.INTERACTABLE in sprite_groups:
            lines.append(f"Interactables: {self._format_sprite_group(sprite_groups[SpriteCategory.INTERACTABLE])}.")

        return "\n".join(lines)


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

    def ow_tile_name(self, map16_index: int) -> Optional[str]:
        """Return a graphic-based name for a map16 tile, or None."""
        return MAP16_NAME.get(map16_index)

    def ow_tile_attr(self, map16_index: int, x: int, y: int) -> int:
        """Look up the overworld tile attribute for a map16 tile."""
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
