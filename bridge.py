#!/usr/bin/env python3
"""
ALttP Accessibility Bridge
===========================
A Link to the Past accessibility tool that polls RetroArch emulator memory,
detects game events, and provides screen-reader-friendly output for
blind and visually impaired players.

Setup:
  1. In retroarch.cfg set:
       network_cmd_enable = "true"
       network_cmd_port = "55355"
  2. Launch RetroArch with bsnes-mercury core and your ALttP ROM
  3. python bridge.py
"""

import argparse
import json
import os
import re
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from rom_reader import RomData, SpriteCategory, SPRITE_TYPE_NAMES, load_rom


# ─── Memory Address Table ────────────────────────────────────────────────────
# Maps field names to (SNES A-bus address, byte_length) tuples.
# Uses standard $7E:xxxx WRAM notation compatible with bsnes-mercury.

MEMORY_MAP: dict[str, tuple[int, int]] = {
    # Position
    "link_y":           (0x7E0020, 2),
    "link_x":           (0x7E0022, 2),
    "direction":        (0x7E002F, 1),

    # Game mode
    "main_module":      (0x7E0010, 1),
    "submodule":        (0x7E0011, 1),
    "indoors":          (0x7E001B, 1),

    # Location
    "ow_screen":        (0x7E008A, 2),
    "dungeon_room":     (0x7E00A0, 2),
    "floor":            (0x7E00A4, 1),
    "world":            (0x7E007B, 1),
    "lower_level":      (0x7E00EE, 1),

    # Overworld tile offset variables (for tile attribute lookups)
    "ow_offset_base_y": (0x7E0708, 2),
    "ow_offset_mask_y": (0x7E070A, 2),
    "ow_offset_base_x": (0x7E070C, 2),
    "ow_offset_mask_x": (0x7E070E, 2),

    # Health
    "hp":               (0x7EF36D, 1),
    "max_hp":           (0x7EF36C, 1),
    "magic":            (0x7EF36E, 1),

    # Resources
    "bombs":            (0x7EF343, 1),
    "arrows":           (0x7EF377, 1),
    "rupees":           (0x7EF360, 2),
    "keys":             (0x7EF36F, 1),

    # Equipment
    "sword":            (0x7EF359, 1),
    "shield":           (0x7EF35A, 1),
    "armor":            (0x7EF35B, 1),
    "gloves":           (0x7EF357, 1),
    "boots":            (0x7EF358, 1),
    "flippers":         (0x7EF35C, 1),
    "moon_pearl":       (0x7EF35D, 1),

    # Inventory
    "bow":              (0x7EF340, 1),
    "boomerang":        (0x7EF341, 1),
    "hookshot":         (0x7EF342, 1),
    "mushroom_powder":  (0x7EF344, 1),
    "fire_rod":         (0x7EF345, 1),
    "ice_rod":          (0x7EF346, 1),
    "bombos":           (0x7EF347, 1),
    "ether":            (0x7EF348, 1),
    "quake":            (0x7EF349, 1),
    "lamp":             (0x7EF34A, 1),
    "hammer":           (0x7EF34B, 1),
    "flute_shovel":     (0x7EF34C, 1),
    "bug_net":          (0x7EF34D, 1),
    "book":             (0x7EF34E, 1),
    "bottle_1":         (0x7EF34F, 1),
    "bottle_2":         (0x7EF350, 1),
    "bottle_3":         (0x7EF351, 1),
    "bottle_4":         (0x7EF352, 1),
    "cane_somaria":     (0x7EF353, 1),
    "cane_byrna":       (0x7EF354, 1),
    "magic_cape":       (0x7EF355, 1),
    "mirror":           (0x7EF356, 1),

    # Input
    "joypad_dir":       (0x7E00F0, 1),  # filtered_joypad high byte: U D L R in bits 3-0

    # Status
    "link_state":       (0x7E005D, 1),
    "damage_timer":     (0x7E0046, 1),
    "pit_proximity":    (0x7E005B, 1),

    # Progress
    "pendants":         (0x7EF374, 1),
    "crystals":         (0x7EF37A, 1),
    "progress":         (0x7EF3C5, 1),

    # Dungeon-specific
    "floor_level":      (0x7E00EE, 1),
    "trap_doors":       (0x7E0468, 1),
    "ganon_state":      (0x7E04C5, 1),

    # Dialog
    "dialog_id":        (0x7E1CF0, 2),  # dialogue_message_index
}


# ─── Text Dump ────────────────────────────────────────────────────────────────
# Loads dialog messages from a text dump (text.txt) so that on-screen text
# can be spoken by the screen reader.

_CONTROL_CODE_RE = re.compile(r'\*[0-9A-Za-z]+')
_GRAPHIC_RE = re.compile(r'\|[^|]*\|')


def _clean_dialog_text(raw: str) -> str:
    """Strip ALttP control codes for screen reader output."""
    lines: list[str] = []
    for line in raw.split('\n'):
        line = line.strip()
        if not line:
            continue
        # Remove *XX control codes and |graphic| insertions
        line = _CONTROL_CODE_RE.sub('', line)
        line = _GRAPHIC_RE.sub('', line)
        # Skip Hylian glyph-only lines
        if all(c in '\u2020\u00a7\u00bb ' for c in line):
            continue
        # Remove leading telepathy/fortune/menu prefix (single char C/B/A)
        if len(line) > 1 and line[0] in 'CBA' and line[1].isupper():
            line = line[1:]
        line = line.strip()
        if line:
            lines.append(line)
    return ' '.join(lines)


def load_text_dump(path: str) -> list[str]:
    """Parse a text dump file into an ordered list of dialog messages."""
    try:
        with open(path) as f:
            content = f.read()
    except FileNotFoundError:
        return []

    # Skip header -- actual text starts after "The Text Dump" heading
    marker = "The Text Dump"
    idx = content.find(marker)
    if idx >= 0:
        rest = content[idx:]
        nl = rest.find('\n\n')
        content = rest[nl:] if nl >= 0 else rest

    # Split on blank lines to separate individual messages
    raw_messages = re.split(r'\n\s*\n', content.strip())

    messages: list[str] = []
    for raw in raw_messages:
        cleaned = _clean_dialog_text(raw)
        if cleaned:
            messages.append(cleaned)
    return messages


# ─── Lookup Tables ────────────────────────────────────────────────────────────

DIRECTION_NAMES = {
    0: "north",
    2: "south",
    4: "west",
    6: "east",
}

SWORD_NAMES = {
    0: "no sword",
    1: "Fighter's Sword",
    2: "Master Sword",
    3: "Tempered Sword",
    4: "Golden Sword",
}

SHIELD_NAMES = {
    0: "no shield",
    1: "Fighter's Shield",
    2: "Fire Shield",
    3: "Mirror Shield",
}

ARMOR_NAMES = {
    0: "Green Mail",
    1: "Blue Mail",
    2: "Red Mail",
}

GLOVE_NAMES = {
    0: "no gloves",
    1: "Power Glove",
    2: "Titan's Mitt",
}

BOW_NAMES = {
    0: "none",
    1: "Bow",
    2: "Bow with Silver Arrows",
    3: "Silver Bow",
}

BOOMERANG_NAMES = {
    0: "none",
    1: "Blue Boomerang",
    2: "Red Boomerang",
}

MUSHROOM_POWDER_NAMES = {
    0: "none",
    1: "Mushroom",
    2: "Magic Powder",
}

FLUTE_SHOVEL_NAMES = {
    0: "none",
    1: "Shovel",
    2: "Flute (inactive)",
    3: "Flute",
}

MIRROR_NAMES = {
    0: "none",
    1: "Magic Scroll",
    2: "Magic Mirror",
}

BOTTLE_NAMES = {
    0: "no bottle",
    1: "Mushroom",
    2: "Empty Bottle",
    3: "Red Potion",
    4: "Green Potion",
    5: "Blue Potion",
    6: "Bee",
    7: "Golden Bee",
    8: "Fairy",
}

MODULE_NAMES = {
    0x00: "Title/Triforce",
    0x01: "File Select",
    0x02: "Copy/Erase",
    0x04: "Save Menu",
    0x05: "Loading",
    0x06: "Pre-Dungeon",
    0x07: "Dungeon",
    0x08: "Pre-Dungeon (Map)",
    0x09: "Overworld",
    0x0A: "Special Overworld",
    0x0B: "Special Overworld",
    0x0E: "Text/Dialog",
    0x0F: "Closing Dialog",
    0x10: "Shop/Interact",
    0x11: "Inventory Screen",
    0x12: "Death",
    0x13: "Boss Victory",
    0x14: "Dungeon Clear",
    0x15: "Fade Transition",
    0x17: "Dungeon Cutscene",
    0x19: "Ganon/Triforce Room",
    0x1A: "End Credits",
    0x1B: "Save and Continue",
}

LINK_STATE_NAMES = {
    0x00: "standing",
    0x01: "falling into hole",
    0x02: "recoiling",
    0x03: "spin attack",
    0x04: "rolling back",
    0x05: "tile transition",
    0x06: "falling (long)",
    0x09: "attacked",
    0x0D: "hovering",
    0x11: "swimming",
    0x14: "dashing",
    0x17: "using item",
    0x1C: "falling",
    0x1E: "dying",
}

# Overworld screen names (Light World 0x00-0x3F, Dark World 0x40-0x7F)
OVERWORLD_NAMES = {
    # Light World
    0x00: "Lost Woods (north)",
    0x02: "Lumberjack Tree area",
    0x03: "West Death Mountain",
    0x05: "East Death Mountain",
    0x07: "Death Mountain Summit",
    0x0A: "Spectacle Rock",
    0x0F: "Zora's Waterfall",
    0x10: "Lost Woods (south)",
    0x12: "Fortune Teller",
    0x14: "Master Sword Clearing",
    0x15: "Hyrule Castle (north)",
    0x16: "Hyrule Castle (east)",
    0x17: "Witch's Hut area",
    0x18: "Kakariko Village",
    0x1A: "Haunted Grove",
    0x1B: "Hyrule Castle",
    0x1C: "Hyrule Castle (east grounds)",
    0x1E: "Eastern Palace",
    0x22: "Sanctuary",
    0x25: "Graveyard",
    0x28: "Kakariko (south)",
    0x29: "Sahasrahla's area",
    0x2A: "Central Hyrule Field",
    0x2B: "Link's House",
    0x2C: "Eastern Hyrule",
    0x2E: "Eastern Palace grounds",
    0x30: "Desert of Mystery",
    0x32: "Flute Boy's Meadow",
    0x33: "Lake Hylia (north)",
    0x34: "Waterfall of Wishing",
    0x35: "Lake Hylia",
    0x37: "Lake Hylia Island",
    0x3A: "Dam",
    0x3B: "Ice Rod Cave area",

    # Dark World
    0x40: "Skull Woods",
    0x43: "West Dark Death Mountain",
    0x45: "East Dark Death Mountain",
    0x47: "Turtle Rock",
    0x4A: "Ganon's Tower area",
    0x58: "Village of Outcasts",
    0x5A: "Stumpy's Clearing",
    0x5B: "Pyramid of Power",
    0x5E: "Palace of Darkness",
    0x62: "Dark Sanctuary area",
    0x68: "Thieves' Town",
    0x69: "Dark World Archery",
    0x6A: "Dark World Center",
    0x6B: "Swamp Palace area",
    0x70: "Misery Mire",
    0x72: "Dig Game",
    0x73: "Dark World Swamp",
    0x75: "Ice Palace area",
    0x77: "Dark World Lake Hylia",
}

# Accessibility descriptions for overworld areas.
# Each entry describes exits, hazards, landmarks, and NPCs.
OVERWORLD_DESCRIPTIONS: dict[int, str] = {
    # Light World
    0x00: ("Dense maze of trees. Follow the correct path or be sent back "
           "to the entrance. Soldiers patrol the area early in the game."),
    0x02: ("Open clearing with a distinctive tree. Accessible from Death "
           "Mountain to the east and Lost Woods to the west."),
    0x03: ("Rocky mountain path with falling boulders and narrow ledges. "
           "Cave entrances along the way. South exit leads to foothills."),
    0x05: ("High mountain terrain. Spiral Cave and Spectacle Rock "
           "entrances nearby. Watch for falling rocks."),
    0x07: ("The peak of Death Mountain. Tower of Hera entrance is here. "
           "Warp tile available."),
    0x0A: ("A prominent landmark on Death Mountain. Two rock formations "
           "overlook Hyrule below. Mirror warp point."),
    0x0F: ("Rushing waterfall at the northeast corner of the map. Zora "
           "sells flippers here. Deep water blocks passage without flippers."),
    0x10: ("Southern edge of the Lost Woods. A mushroom can be found here. "
           "Path leads south to Kakariko Village."),
    0x12: ("Small clearing with the Fortune Teller's hut. Pay rupees for "
           "hints about your quest."),
    0x14: ("Sacred grove deep in the Lost Woods. The Master Sword pedestal "
           "awaits one who holds all three pendants."),
    0x15: ("The north face of Hyrule Castle. Castle walls block passage. "
           "Guards patrol the area."),
    0x16: ("Eastern grounds of Hyrule Castle. Open field with scattered "
           "bushes. Connects to Witch's Hut area to the east."),
    0x17: ("Path near the Witch's Hut. Bring a mushroom to the witch for "
           "Magic Powder. Potion shop nearby."),
    0x18: ("A bustling village with many houses and shops. Friendly NPCs "
           "offer information and items. Multiple building entrances."),
    0x1A: ("A quiet clearing in the woods south of Kakariko. The Flute "
           "Boy once played music here."),
    0x1B: ("The castle entrance and courtyard. Guards are on high alert. "
           "Secret passages exist in the garden bushes."),
    0x1E: ("The entrance to the Eastern Palace. Stone building in the "
           "eastern region. First dungeon of the quest."),
    0x22: ("A safe haven north of the castle. The priest offers shelter. "
           "Heal and save your progress here."),
    0x25: ("Rows of tombstones. Some graves can be pushed to reveal "
           "secrets. Ghosts may appear."),
    0x28: ("Southern part of Kakariko Village. Library and more houses. "
           "Connects to the main village to the north."),
    0x29: ("The elder Sahasrahla's hideout. Seek his wisdom about the "
           "pendants and the Master Sword."),
    0x2A: ("Wide open field in the heart of Hyrule. Good landmark for "
           "orientation. Paths lead in all directions."),
    0x2B: ("Your home. A safe spot to rest. South of Hyrule Castle, "
           "east of the swamp."),
    0x2C: ("Open terrain between Link's House and the Eastern Palace. "
           "Scattered enemies and bushes."),
    0x2E: ("The area surrounding the Eastern Palace entrance. Stone "
           "ruins and hedges line the path."),
    0x30: ("Vast sandy desert in the southwest. Vultures circle overhead. "
           "Desert Palace entrance is here. Book of Mudora needed."),
    0x32: ("A green meadow south of the Haunted Grove. Peaceful area "
           "with few enemies."),
    0x33: ("The northern shore of Lake Hylia. Shallow water near the "
           "edges. Islands visible to the south."),
    0x34: ("A magical waterfall. Throw items into the fairy fountain "
           "for upgrades."),
    0x35: ("A large body of water. Swimming required for exploration. "
           "Ice Rod cave accessible from the east shore."),
    0x37: ("A small island in the middle of Lake Hylia. Accessible "
           "by swimming or warping."),
    0x3A: ("A stone dam controlling the water flow. A switch inside "
           "can drain the water to open passages."),
    0x3B: ("Rocky terrain near Lake Hylia. The Ice Rod cave entrance "
           "is hidden among the rocks."),

    # Dark World
    0x40: ("Twisted dark forest. Multiple entrances lead underground "
           "to Skull Woods dungeon. Trees look menacing."),
    0x43: ("Dark World version of Death Mountain west side. Hostile "
           "terrain with stronger enemies than the Light World."),
    0x45: ("Dark Death Mountain east side. Turtle Rock dungeon entrance "
           "is nearby. Requires Quake Medallion."),
    0x47: ("Turtle Rock entrance area on Dark Death Mountain. The rock "
           "formation resembles a giant turtle."),
    0x4A: ("The base of Ganon's Tower atop Dark Death Mountain. All "
           "seven crystals are needed to break the seal."),
    0x58: ("Dark World version of Kakariko Village. Hostile inhabitants "
           "have replaced the villagers. Thieves' Town dungeon below."),
    0x5A: ("Dark World version of the Haunted Grove. A creature named "
           "Stumpy stands where the Flute Boy was."),
    0x5B: ("A massive pyramid in the center of the Dark World. Ganon "
           "lurks within. A crack in the side leads to the final battle."),
    0x5E: ("Dark World eastern region. The Palace of Darkness entrance "
           "is here. First Dark World dungeon."),
    0x62: ("Dark World mirror of the Sanctuary area. Hostile version "
           "of the safe haven."),
    0x68: ("Dark World version of Kakariko. Thieves' Town dungeon "
           "entrance is disguised as a building."),
    0x69: ("Dark World area with an archery mini-game. Test your aim "
           "for rupee prizes."),
    0x6A: ("Central Dark World field. Rough terrain with stronger "
           "monsters roaming."),
    0x6B: ("Dark World swamp region. Swamp Palace dungeon entrance "
           "is here. Flooded terrain requires swimming."),
    0x70: ("A dismal swamp in the Dark World southwest. Requires the "
           "Ether Medallion to open the Misery Mire dungeon entrance."),
    0x72: ("Dark World area with a digging mini-game. Pay rupees to "
           "dig for buried treasures."),
    0x73: ("Murky swamp waters in the Dark World. Dangerous terrain "
           "with limited solid ground."),
    0x75: ("Frozen Dark World lake. Ice Palace dungeon entrance is on "
           "an island. Requires Flippers to reach."),
    0x77: ("Dark World version of Lake Hylia. Darker, more dangerous "
           "waters filled with enemies."),
}


# ─── Dungeon Room Mapping ────────────────────────────────────────────────────
# Maps dungeon room IDs (from $7E00A0) to dungeon names.
# Room IDs are assigned on a 16-wide grid in ALttP.
# This mapping covers the major rooms; unknown rooms fall back to
# "Unknown dungeon" in the UI.

DUNGEON_ROOMS: dict[int, str] = {}

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

for _dname, _rooms in _DUNGEON_ROOM_DATA.items():
    for _rid in _rooms:
        DUNGEON_ROOMS[_rid] = _dname


DUNGEON_DESCRIPTIONS: dict[str, str] = {
    "Hyrule Castle": (
        "The fortified castle at the center of Hyrule. "
        "Soldiers patrol the halls. Dark sewers lie below. "
        "Princess Zelda is held captive in the basement."
    ),
    "Eastern Palace": (
        "A grand stone palace in eastern Hyrule. "
        "Home to the Pendant of Courage. "
        "Watch for Armos statues that come alive and eyegore enemies. "
        "The boss is the Armos Knights."
    ),
    "Desert Palace": (
        "A sand-filled palace in the southwestern desert. "
        "Home to the Pendant of Power. "
        "Requires the Book of Mudora to enter. "
        "Beware of shifting sands. The boss is Lanmolas."
    ),
    "Tower of Hera": (
        "A tall tower on Death Mountain's summit. "
        "Home to the Pendant of Wisdom. "
        "Multiple floors connected by holes in the ground. "
        "Moldorm, the boss, fights on a platform with no railing."
    ),
    "Castle Tower": (
        "Agahnim's tower atop Hyrule Castle. "
        "Climb through guarded floors to confront the wizard. "
        "Requires the Master Sword to enter. "
        "Reflect Agahnim's magic with your sword to defeat him."
    ),
    "Palace of Darkness": (
        "The first Dark World dungeon, a massive fortress in the east. "
        "Dark rooms require the Lamp. Maze-like passages with switches. "
        "The boss is the Helmasaur King. Use the Hammer on its mask."
    ),
    "Swamp Palace": (
        "A water-filled dungeon in the Dark World swamp. "
        "Flooded rooms require swimming. Water levels change with switches. "
        "The boss is Arrghus. Pull the puffballs off with the Hookshot."
    ),
    "Skull Woods": (
        "A dungeon beneath the Dark World's twisted forest. "
        "Multiple outdoor entrances lead to different sections. "
        "Fire traps and moving floors. "
        "The boss is Mothula. Watch for the moving floor and spikes."
    ),
    "Thieves' Town": (
        "Hidden beneath a building in the Village of Outcasts. "
        "Dark rooms and bombable walls hide secrets. "
        "A mysterious maiden awaits rescue. "
        "The boss is Blind the Thief. Light from windows is key."
    ),
    "Ice Palace": (
        "A frozen dungeon on an island in the Dark World lake. "
        "Slippery ice floors and falling ice hazards. "
        "Requires the Fire Rod to melt ice blocks. "
        "The boss is Kholdstare, encased in ice."
    ),
    "Misery Mire": (
        "A dungeon in the Dark World's dismal swamp. "
        "Requires the Ether Medallion to enter. "
        "Flooded floors and Wizzrobes throughout. "
        "The boss is Vitreous, a giant eye surrounded by smaller eyes."
    ),
    "Turtle Rock": (
        "A dungeon inside a rock formation on Dark Death Mountain. "
        "Requires the Quake Medallion to enter. "
        "Lava pits and pipe mazes. Uses both Fire and Ice Rods. "
        "The boss is Trinexx, a three-headed turtle."
    ),
    "Ganon's Tower": (
        "The final dungeon atop Dark Death Mountain. "
        "Requires all seven crystals to break the seal. "
        "Combines puzzles and enemies from all previous dungeons. "
        "Agahnim waits at the top, then the path to Ganon opens."
    ),
}


# Boolean items: key -> display name
BOOLEAN_ITEMS = {
    "hookshot": "Hookshot",
    "fire_rod": "Fire Rod",
    "ice_rod": "Ice Rod",
    "bombos": "Bombos Medallion",
    "ether": "Ether Medallion",
    "quake": "Quake Medallion",
    "lamp": "Lamp",
    "hammer": "Hammer",
    "bug_net": "Bug Net",
    "book": "Book of Mudora",
    "cane_somaria": "Cane of Somaria",
    "cane_byrna": "Cane of Byrna",
    "magic_cape": "Magic Cape",
    "boots": "Pegasus Boots",
    "flippers": "Zora's Flippers",
    "moon_pearl": "Moon Pearl",
}

# Items with named tiers: key -> {value: name}
TIERED_ITEMS = {
    "bow": BOW_NAMES,
    "boomerang": BOOMERANG_NAMES,
    "mushroom_powder": MUSHROOM_POWDER_NAMES,
    "flute_shovel": FLUTE_SHOVEL_NAMES,
    "mirror": MIRROR_NAMES,
    "sword": SWORD_NAMES,
    "shield": SHIELD_NAMES,
    "armor": ARMOR_NAMES,
    "gloves": GLOVE_NAMES,
}

# Gameplay modules where event detection should be active
GAMEPLAY_MODULES = {0x07, 0x09, 0x0A, 0x0B, 0x0E, 0x0F, 0x10}


# ─── Sprite / Enemy Tables ───────────────────────────────────────────────────
# Sprite table in WRAM: 16 slots (index 0-15), one byte per slot per property.
# Positions are 16-bit, split across high/low byte tables.

SPRITE_TABLE = {
    "positions": (0x7E0D00, 64),   # Y_lo[16] X_lo[16] Y_hi[16] X_hi[16]
    "states":    (0x7E0DD0, 16),   # sprite state (0 = inactive)
    "types":     (0x7E0E20, 16),   # sprite type / enemy ID
}

# Sprite type IDs that are enemies.  Maps ID -> name.
# Only entries here are treated as threats for proximity alerts.
ENEMY_NAMES: dict[int, str] = {
    # Overworld enemies
    0x01: "Raven",
    0x02: "Vulture",
    0x08: "Octorok",
    0x09: "Octorok",
    0x0C: "Buzzblob",
    0x0D: "Snapdragon",
    0x0E: "Octoballoon",
    0x10: "Hinox",
    0x11: "Moblin",
    0x12: "Mini Helmasaur",
    0x15: "Antifairy",
    0x18: "Mini Moldorm",
    0x19: "Poe",
    0x1A: "Leever",
    0x23: "Red Bari",
    0x24: "Blue Bari",
    0x26: "Hardhat Beetle",
    0x27: "Deadrock",
    0x29: "Zora",
    0x2B: "Pikit",
    # Hyrule Castle / soldiers
    0x41: "Green Soldier",
    0x42: "Blue Soldier",
    0x43: "Red Soldier",
    0x44: "Red Soldier",
    0x45: "Blue Archer",
    0x46: "Green Archer",
    0x47: "Blue Soldier",
    0x48: "Red Soldier",
    0x49: "Red Bomb Soldier",
    0x4A: "Green Bomb Soldier",
    # Dungeon enemies
    0x53: "Armos",
    0x6A: "Ball and Chain Trooper",
    0x58: "Crab",
    0x83: "Green Eyegore",
    0x84: "Red Eyegore",
    0x85: "Stalfos",
    0x86: "Kodongo",
    0x8B: "Spike Trap",
    0x90: "Wallmaster",
    0x91: "Stalfos Knight",
    0x9B: "Wizzrobe",
    0xA5: "Firesnake",
    0xA7: "Water Tektite",
    # Bosses
    0x54: "Armos Knight",
    0x55: "Lanmola",
    0x88: "Mothula",
    0x92: "Helmasaur King",
    0xCB: "Blind",
    0xCE: "Vitreous",
    0xD6: "Ganon",
    0xD7: "Agahnim",
}

# Item drop sprite type IDs (0xD8-0xE5).  When an enemy dies it may
# respawn in the same slot with one of these types.
ITEM_DROP_IDS: set[int] = set(range(0xD8, 0xE6))

# Detection radius in pixels (16 px = 1 tile)
ENEMY_DETECT_RADIUS = 112   # ~7 tiles
INTERACT_RADIUS = 24        # ~1.5 tiles — for non-enemy sprite announcements


@dataclass
class Sprite:
    """One entry from the SNES sprite table."""
    index: int
    type_id: int
    state: int
    x: int
    y: int

    @property
    def is_active(self) -> bool:
        return self.state != 0 and self.type_id != 0

    @property
    def is_enemy(self) -> bool:
        return self.type_id in ENEMY_NAMES

    @property
    def name(self) -> str:
        entry = SPRITE_TYPE_NAMES.get(self.type_id)
        if entry:
            return entry[0]
        return ENEMY_NAMES.get(self.type_id, f"sprite {self.type_id:#04x}")

    @property
    def category(self) -> str:
        entry = SPRITE_TYPE_NAMES.get(self.type_id)
        return entry[1] if entry else SpriteCategory.UNKNOWN


def _direction_label(dx: int, dy: int) -> str:
    """Compass direction from Link to a target.

    Positive dy = target is south; positive dx = target is east.
    Uses a 3:1 ratio threshold so that (dx=-80, dy=6) reports "west"
    rather than "southwest".
    """
    if abs(dx) < 8 and abs(dy) < 8:
        return "here"
    if abs(dx) > abs(dy) * 3:
        return "west" if dx < 0 else "east"
    if abs(dy) > abs(dx) * 3:
        return "north" if dy < 0 else "south"
    ns = "north" if dy < 0 else "south"
    ew = "west" if dx < 0 else "east"
    return f"{ns}{ew}"


# ─── Game State ───────────────────────────────────────────────────────────────

# Link's sprite origin ($7E:0020/0022) is the top-left corner.
# His visual centre (body, not head) is offset from that origin.
_LINK_BODY_OFFSET_X = 8    # half of 16px sprite width
_LINK_BODY_OFFSET_Y = 8    # body centre, below the head


@dataclass
class TrackedObject:
    """A game object tracked across frames with optional velocity."""
    key: str                    # stable ID
    world_x: int                # absolute pixel position
    world_y: int
    type_id: int                # sprite/object type identifier
    name: str                   # human-readable name
    category: str               # sprite category or "static"
    is_dynamic: bool            # True for live WRAM sprites
    last_seen: float            # timestamp when last observed
    zone: Optional[str] = None  # "approach", "nearby", "facing", or None
    vx: float = 0.0             # velocity in pixels/sec (EMA-smoothed)
    vy: float = 0.0
    _prev_x: int = 0            # previous frame position (internal)
    _prev_y: int = 0
    _prev_time: float = 0.0     # previous frame timestamp


class ObjectTracker:
    """Frame-to-frame object tracking with velocity computation."""

    _VELOCITY_ALPHA = 0.3   # EMA smoothing factor
    _STALE_TIMEOUT = 2.0    # seconds before removing unseen dynamic objects
    _SPEED_THRESHOLD = 20.0 # px/sec — below this, velocity is jitter

    def __init__(self) -> None:
        self._objects: dict[str, TrackedObject] = {}

    def clear(self) -> None:
        """Reset all tracking (call on room/screen transition)."""
        self._objects.clear()

    def get(self, key: str) -> Optional[TrackedObject]:
        return self._objects.get(key)

    def all_objects(self) -> list[TrackedObject]:
        return list(self._objects.values())

    def active_dynamic(self) -> list[TrackedObject]:
        return [o for o in self._objects.values() if o.is_dynamic]

    def update_static(self, features: list[tuple[str, int, int, str]],
                      now: float) -> None:
        """Update static feature tracking from _get_features() output."""
        seen_keys: set[str] = set()
        for key, px, py, desc in features:
            seen_keys.add(key)
            obj = self._objects.get(key)
            if obj is None:
                self._objects[key] = TrackedObject(
                    key=key, world_x=px, world_y=py, type_id=0,
                    name=desc, category="static", is_dynamic=False,
                    last_seen=now,
                )
            else:
                obj.world_x = px
                obj.world_y = py
                obj.last_seen = now
        # Remove static features no longer in the list
        stale = [k for k, o in self._objects.items()
                 if not o.is_dynamic and k not in seen_keys]
        for k in stale:
            del self._objects[k]

    def update_sprites(self, sprites: list[Sprite], now: float) -> None:
        """Update dynamic sprite tracking from GameState.sprites."""
        seen_keys: set[str] = set()
        for s in sprites:
            if not s.is_active:
                continue
            if s.category == SpriteCategory.UNKNOWN:
                continue
            key = f"sprite:{s.index}"
            seen_keys.add(key)
            obj = self._objects.get(key)
            if obj is not None and obj.is_dynamic:
                # Slot reuse detection: type changed -> new entity
                if obj.type_id != s.type_id:
                    obj = None
            if obj is None:
                self._objects[key] = TrackedObject(
                    key=key, world_x=s.x, world_y=s.y,
                    type_id=s.type_id, name=s.name,
                    category=s.category, is_dynamic=True,
                    last_seen=now,
                    _prev_x=s.x, _prev_y=s.y, _prev_time=now,
                )
            else:
                # Compute velocity via EMA
                dt = now - obj._prev_time
                if dt > 0.001:
                    raw_vx = (s.x - obj._prev_x) / dt
                    raw_vy = (s.y - obj._prev_y) / dt
                    a = self._VELOCITY_ALPHA
                    obj.vx = a * raw_vx + (1 - a) * obj.vx
                    obj.vy = a * raw_vy + (1 - a) * obj.vy
                obj._prev_x = obj.world_x
                obj._prev_y = obj.world_y
                obj._prev_time = now
                obj.world_x = s.x
                obj.world_y = s.y
                obj.type_id = s.type_id
                obj.name = s.name
                obj.category = s.category
                obj.last_seen = now
        # Mark unseen dynamic sprites (don't remove yet — prune_stale handles that)

    def prune_stale(self, now: float) -> None:
        """Remove dynamic objects not seen for _STALE_TIMEOUT seconds."""
        stale = [k for k, o in self._objects.items()
                 if o.is_dynamic and (now - o.last_seen) > self._STALE_TIMEOUT]
        for k in stale:
            del self._objects[k]

    def approaching_link(self, obj: TrackedObject,
                         link_x: int, link_y: int) -> Optional[str]:
        """Check if a dynamic sprite is moving toward Link.

        Returns a direction string (e.g. "from the east") if the sprite's
        velocity vector points toward Link with speed > threshold, else None.
        """
        speed = (obj.vx ** 2 + obj.vy ** 2) ** 0.5
        if speed < self._SPEED_THRESHOLD:
            return None
        # Vector from sprite to Link
        to_link_x = link_x - obj.world_x
        to_link_y = link_y - obj.world_y
        # Dot product: positive means moving toward Link
        dot = obj.vx * to_link_x + obj.vy * to_link_y
        if dot <= 0:
            return None
        # Direction the sprite is coming FROM (opposite of velocity)
        return _direction_label(-int(obj.vx), -int(obj.vy))


# Pixel offsets from Link's position to the tile ahead, indexed by direction.
# Link's hitbox is ~16px; we probe 16px ahead of his center.
_FACING_OFFSETS: dict[int, tuple[int, int]] = {
    0: (8, -2),    # north
    2: (8, 24),    # south
    4: (-2, 12),   # west
    6: (18, 12),   # east
}

# Dungeon tile attribute table: $7F:2000 (g_ram+0x12000)
_DUNG_TILEATTR_ADDR = 0x7F2000
# Overworld tile map16 table: $7E:2000 (g_ram+0x2000)
_OW_TILEATTR_ADDR = 0x7E2000


@dataclass
class GameState:
    """Snapshot of all watched ALttP memory values."""
    raw: dict[str, Optional[int]] = field(default_factory=dict)
    sprites: list[Sprite] = field(default_factory=list)
    timestamp: float = 0.0
    rom_data: Optional[RomData] = field(default=None, repr=False)
    facing_tile: int = -1  # tile attribute byte for the tile Link is facing

    def get(self, key: str, default: int = 0) -> int:
        v = self.raw.get(key)
        return v if v is not None else default

    @property
    def hp_hearts(self) -> float:
        """Current HP in hearts (each heart = 8 units)."""
        return self.get("hp") / 8.0

    @property
    def max_hp_hearts(self) -> float:
        return self.get("max_hp") / 8.0

    # Tiles that act as walls indoors but have different meaning outdoors
    # (from zelda3 tile_detect.c TileDetect_ExecuteInner)
    _INDOOR_WALL_TILES = {0x04, 0x0B, 0x6C, 0x6D, 0x6E, 0x6F}

    @property
    def facing_tile_name(self) -> Optional[str]:
        """Human name for the tile Link is facing, or None if passable."""
        from rom_reader import TILE_TYPE_NAMES
        if self.facing_tile < 0:
            return None
        if self.get("indoors") and self.facing_tile in self._INDOOR_WALL_TILES:
            return "wall"
        return TILE_TYPE_NAMES.get(self.facing_tile)

    @property
    def direction_name(self) -> str:
        return DIRECTION_NAMES.get(self.get("direction"), "unknown")

    @property
    def dungeon_name(self) -> str:
        """Name of the current dungeon based on room ID, or empty string."""
        room = self.get("dungeon_room")
        return DUNGEON_ROOMS.get(room, "")

    @property
    def location_name(self) -> str:
        module = self.get("main_module")
        if module == 0x07:
            room = self.get("dungeon_room")
            name = DUNGEON_ROOMS.get(room)
            if name:
                return f"{name}, room {room:#06x}"
            return f"Dungeon room {room:#06x}"
        screen = self.ow_screen_from_coords
        if screen is None:
            screen = self.get("ow_screen")
        return OVERWORLD_NAMES.get(screen, f"Overworld {screen:#04x}")

    @property
    def area_description(self) -> str:
        """Accessibility description of the current area."""
        module = self.get("main_module")
        if module == 0x07:
            # Dungeon: try ROM-based full description first
            if self.rom_data:
                room_id = self.get("dungeon_room")
                room = self.rom_data.get_room(room_id)
                if room and (room.sprites or room.doors or
                             (room.header and room.header.tag1)):
                    return room.to_full()
            name = self.dungeon_name
            return DUNGEON_DESCRIPTIONS.get(name, "")
        # Overworld: static description + ROM sprite listing
        screen = self.ow_screen_from_coords
        if screen is None:
            screen = self.get("ow_screen")
        desc = OVERWORLD_DESCRIPTIONS.get(screen, "")
        if self.rom_data:
            sprite_text = self.rom_data.format_ow_sprites(screen)
            if sprite_text:
                desc = f"{desc} {sprite_text}" if desc else sprite_text
        return desc

    @property
    def area_brief(self) -> str:
        """Brief ROM-based description of the current dungeon room."""
        if not self.rom_data or self.get("main_module") != 0x07:
            return ""
        room_id = self.get("dungeon_room")
        room = self.rom_data.get_room(room_id)
        if room and (room.sprites or room.doors or
                     (room.header and room.header.tag1)):
            return room.to_brief()
        return ""

    @property
    def world_name(self) -> str:
        return "Dark World" if self.get("world") else "Light World"

    @property
    def is_indoors(self) -> bool:
        return bool(self.get("indoors"))

    @property
    def is_in_dungeon(self) -> bool:
        return self.get("main_module") == 0x07

    @property
    def is_on_overworld(self) -> bool:
        return self.get("main_module") == 0x09

    @property
    def ow_screen_from_coords(self) -> Optional[int]:
        """Compute overworld screen index from Link's absolute coordinates.

        The overworld is an 8x8 grid of 512x512-pixel screens.  Link's
        coordinates at $0020/$0022 are absolute on the overworld, so
        dividing by 512 gives the screen row/column.  This works even
        inside 'large areas' where $008A stays constant.
        """
        if not self.is_on_overworld:
            return None
        x = self.get("link_x")
        y = self.get("link_y")
        col = (x >> 9) & 7
        row = (y >> 9) & 7
        screen = row * 8 + col
        if self.get("world"):  # Dark World
            screen += 0x40
        return screen

    def item_name(self, key: str) -> Optional[str]:
        """Get human-readable name for an item slot, or None if empty."""
        val = self.get(key)
        if key in BOOLEAN_ITEMS:
            return BOOLEAN_ITEMS[key] if val else None
        if key in TIERED_ITEMS:
            name = TIERED_ITEMS[key].get(val)
            return name if name and name != "none" else None
        if key.startswith("bottle_"):
            name = BOTTLE_NAMES.get(val)
            return name if name and name != "no bottle" else None
        return None

    def _format_hearts(self, value: float) -> str:
        return f"{int(value)}" if value == int(value) else f"{value:.1f}"

    def format_health(self) -> str:
        return (f"{self._format_hearts(self.hp_hearts)}/"
                f"{self._format_hearts(self.max_hp_hearts)} hearts")

    def format_position(self) -> str:
        return (
            f"Position: ({self.get('link_x')}, {self.get('link_y')}), "
            f"facing {self.direction_name}. "
            f"Location: {self.location_name}, {self.world_name}"
            f"{', indoors' if self.is_indoors else ', outdoors'}."
        )

    def format_resources(self) -> str:
        parts = [
            f"Health: {self.format_health()}",
            f"Magic: {self.get('magic')}",
            f"Rupees: {self.get('rupees')}",
            f"Bombs: {self.get('bombs')}",
            f"Arrows: {self.get('arrows')}",
            f"Keys: {self.get('keys') if self.get('keys') != 0xFF else 0}",
        ]
        return ". ".join(parts) + "."

    def format_equipment(self) -> str:
        parts = []
        for key in ("sword", "shield", "armor", "gloves"):
            name = TIERED_ITEMS[key].get(self.get(key))
            if name and not name.startswith("no "):
                parts.append(name)
        for key in ("boots", "flippers", "moon_pearl"):
            if self.get(key):
                parts.append(BOOLEAN_ITEMS[key])
        return "Equipment: " + (", ".join(parts) if parts else "none") + "."

    def format_inventory(self) -> str:
        items = []
        for key in ("bow", "boomerang", "mushroom_powder", "flute_shovel", "mirror"):
            name = self.item_name(key)
            if name:
                items.append(name)
        for key in ("hookshot", "fire_rod", "ice_rod", "bombos", "ether", "quake",
                     "lamp", "hammer", "bug_net", "book",
                     "cane_somaria", "cane_byrna", "magic_cape"):
            name = self.item_name(key)
            if name:
                items.append(name)
        for key in ("bottle_1", "bottle_2", "bottle_3", "bottle_4"):
            name = self.item_name(key)
            if name:
                items.append(name)
        return "Inventory: " + (", ".join(items) if items else "empty") + "."

    def format_progress(self) -> str:
        pendants_val = self.get("pendants")
        crystals_val = self.get("crystals")
        pendant_names = []
        if pendants_val & 0x04:
            pendant_names.append("Courage (green)")
        if pendants_val & 0x02:
            pendant_names.append("Power (blue)")
        if pendants_val & 0x01:
            pendant_names.append("Wisdom (red)")
        crystal_count = bin(crystals_val).count("1")
        parts = [
            f"Pendants: {', '.join(pendant_names) if pendant_names else 'none'}",
            f"Crystals: {crystal_count}/7",
            f"Progress indicator: {self.get('progress')}",
        ]
        return ". ".join(parts) + "."

    def nearby_enemies(self, radius: int = ENEMY_DETECT_RADIUS) -> list[dict]:
        """Return active enemies within *radius* pixels of Link, sorted by distance."""
        link_x = self.get("link_x")
        link_y = self.get("link_y")
        result: list[dict] = []
        r_sq = radius * radius
        for s in self.sprites:
            if not s.is_active or not s.is_enemy:
                continue
            dx = s.x - link_x
            dy = s.y - link_y
            dist_sq = dx * dx + dy * dy
            if dist_sq <= r_sq:
                result.append({
                    "index": s.index,
                    "type_id": s.type_id,
                    "name": s.name,
                    "distance": int(dist_sq ** 0.5),
                    "direction": _direction_label(dx, dy),
                })
        result.sort(key=lambda e: e["distance"])
        return result

    def nearby_sprites(self, radius: int = INTERACT_RADIUS) -> list[dict]:
        """Return all active non-enemy sprites within *radius* pixels of Link."""
        link_x = self.get("link_x")
        link_y = self.get("link_y")
        result: list[dict] = []
        r_sq = radius * radius
        for s in self.sprites:
            if not s.is_active or s.is_enemy:
                continue
            if s.category == SpriteCategory.UNKNOWN:
                continue
            dx = s.x - link_x
            dy = s.y - link_y
            dist_sq = dx * dx + dy * dy
            if dist_sq <= r_sq:
                result.append({
                    "index": s.index,
                    "type_id": s.type_id,
                    "name": s.name,
                    "category": s.category,
                    "distance": int(dist_sq ** 0.5),
                    "direction": _direction_label(dx, dy),
                })
        result.sort(key=lambda e: e["distance"])
        return result

    def format_enemies(self) -> str:
        enemies = self.nearby_enemies()
        if not enemies:
            return "No enemies nearby."
        parts = [f"{e['name']} to the {e['direction']}" for e in enemies]
        return "Nearby: " + ", ".join(parts) + "."



# ─── Events ──────────────────────────────────────────────────────────────────

class EventPriority(Enum):
    LOW = auto()
    MEDIUM = auto()
    HIGH = auto()


@dataclass
class Event:
    kind: str
    priority: EventPriority
    message: str
    data: dict = field(default_factory=dict)


# Output sort order: blocked movement first, enemy alerts second, rest last.
_EVENT_SORT_KEY: dict[str, int] = {
    "BLOCKED": 0,
    "ENEMY_NEARBY": 1,
    "DAMAGE_TAKEN": 1,
    "LOW_HEALTH": 1,
    "NEAR_PIT": 1,
    "DEATH": 1,
    # Everything else defaults to 2 via .get(kind, 2)
}


# All inventory keys that can be acquired (0 -> non-zero)
_INVENTORY_KEYS = (
    list(BOOLEAN_ITEMS.keys())
    + ["bow", "boomerang", "mushroom_powder", "flute_shovel", "mirror",
       "bottle_1", "bottle_2", "bottle_3", "bottle_4"]
)


class EventDetector:
    """Compares previous and current GameState to emit events."""

    def __init__(self, dialog_messages: Optional[list[str]] = None,
                 rom_data: Optional[RomData] = None,
                 proximity: Optional['ProximityTracker'] = None):
        self.dialog_messages = dialog_messages or []
        self.rom_data = rom_data
        self.proximity = proximity
        self._blocked_count: int = 0
        self._blocked_announced: bool = False

    def detect(self, prev: GameState, curr: GameState) -> list[Event]:
        events: list[Event] = []

        curr_mod = curr.get("main_module")
        prev_mod = prev.get("main_module")

        # Death
        if curr_mod == 0x12 and prev_mod != 0x12:
            events.append(Event("DEATH", EventPriority.HIGH,
                "You died!\nSave and Continue\nSave and Quit\n"
                "Do not Save and Continue"))
            return events

        # Only detect most events during gameplay
        if curr_mod not in GAMEPLAY_MODULES and prev_mod not in GAMEPLAY_MODULES:
            return events

        prev_hp = prev.get("hp")
        curr_hp = curr.get("hp")

        # Damage taken
        if curr_hp < prev_hp and prev_hp > 0:
            events.append(Event(
                "DAMAGE_TAKEN", EventPriority.HIGH,
                f"Damage taken! Health: {curr.format_health()}.",
                {"prev_hp": prev_hp, "curr_hp": curr_hp},
            ))

        # Low health warning (crossing the 2-heart threshold)
        if curr_hp <= 16 and curr_hp > 0 and prev_hp > 16:
            events.append(Event(
                "LOW_HEALTH", EventPriority.HIGH,
                f"Low health! Only {curr.format_health()} remaining.",
            ))

        # Near pit
        if curr.get("pit_proximity") in (1, 2) and prev.get("pit_proximity") == 0:
            events.append(Event("NEAR_PIT", EventPriority.HIGH,
                                "Warning: near a pit!"))

        # Dungeon room change
        if (curr.get("dungeon_room") != prev.get("dungeon_room")
                and curr.is_in_dungeon):
            room = curr.get("dungeon_room")
            dungeon = curr.dungeon_name
            msg = dungeon if dungeon else f"Room {room:#06x}"
            events.append(Event(
                "ROOM_CHANGE", EventPriority.MEDIUM, msg,
                {"room": room, "dungeon": dungeon},
            ))

        # Overworld screen change — use coordinate-derived screen so
        # transitions within "large areas" (where $008A stays constant)
        # are still detected.
        curr_ow = curr.ow_screen_from_coords
        prev_ow = prev.ow_screen_from_coords
        if curr_ow is not None and curr_ow != prev_ow:
            screen = curr_ow
            area_id = curr.get("ow_screen")
            area = (OVERWORLD_NAMES.get(screen)
                    or OVERWORLD_NAMES.get(area_id)
                    or f"Area {screen:#04x}")
            events.append(Event(
                "ROOM_CHANGE", EventPriority.MEDIUM, area,
                {"screen": screen, "name": area},
            ))

        # World transition (light/dark)
        if curr.get("world") != prev.get("world"):
            events.append(Event(
                "WORLD_TRANSITION", EventPriority.MEDIUM,
                f"Transitioned to the {curr.world_name}.",
            ))

        # Dungeon enter / exit
        if prev_mod == 0x09 and curr_mod == 0x07:
            dungeon = curr.dungeon_name or "a dungeon"
            desc = DUNGEON_DESCRIPTIONS.get(curr.dungeon_name, "")
            msg = f"Entered {dungeon}."
            if desc:
                msg += f" {desc}"
            events.append(Event(
                "DUNGEON_ENTER_EXIT", EventPriority.MEDIUM, msg,
                {"entered": True, "dungeon": dungeon},
            ))
        elif prev_mod == 0x07 and curr_mod == 0x09:
            events.append(Event(
                "DUNGEON_ENTER_EXIT", EventPriority.MEDIUM,
                "Exited the dungeon to the overworld.",
                {"entered": False},
            ))

        # Camera transition (submodule goes from 0 to non-zero during gameplay)
        curr_sub = curr.get("submodule", 0)
        prev_sub = prev.get("submodule", 0)
        if curr_mod in (0x07, 0x09) and curr_sub != 0 and prev_sub == 0:
            dir_name = DIRECTION_NAMES.get(curr.get("direction"), "")
            msg = (f"Transitioning to the {dir_name}."
                   if dir_name else "Transitioning.")
            events.append(Event("TRANSITION", EventPriority.LOW, msg))

        # Floor change
        if curr.is_in_dungeon and curr.get("floor") != prev.get("floor"):
            events.append(Event(
                "FLOOR_CHANGE", EventPriority.MEDIUM,
                f"Changed floors. Now on floor {curr.get('floor')}.",
                {"floor": curr.get("floor")},
            ))

        # Entered / exited building
        if curr.get("indoors") != prev.get("indoors"):
            if curr.is_indoors:
                events.append(Event("ENTERED_BUILDING", EventPriority.LOW,
                                    "Entered a building."))
            else:
                events.append(Event("ENTERED_BUILDING", EventPriority.LOW,
                                    "Exited to the outdoors."))

        # Item acquired (slot 0 -> non-zero)
        for key in _INVENTORY_KEYS:
            if prev.get(key) == 0 and curr.get(key) != 0:
                name = curr.item_name(key)
                if name:
                    events.append(Event(
                        "ITEM_ACQUIRED", EventPriority.MEDIUM,
                        f"Acquired: {name}!",
                        {"item": key, "name": name},
                    ))

        # Equipment upgrade
        for key in ("sword", "shield", "armor", "gloves"):
            if curr.get(key) > prev.get(key):
                name = TIERED_ITEMS[key].get(curr.get(key), "unknown")
                events.append(Event(
                    "EQUIPMENT_UPGRADE", EventPriority.MEDIUM,
                    f"Equipment upgrade: {name}!",
                    {"item": key, "name": name},
                ))

        # Key acquired (0xFF = uninitialised / outside dungeon, not a real count)
        curr_keys = curr.get("keys")
        prev_keys = prev.get("keys")
        if curr_keys != 0xFF and prev_keys != 0xFF and curr_keys > prev_keys:
            events.append(Event(
                "KEY_ACQUIRED", EventPriority.LOW,
                f"Got a key! Keys: {curr_keys}.",
            ))

        # Health restored
        if curr_hp > prev_hp and prev_hp > 0 and curr_mod != 0x12:
            events.append(Event(
                "HEALTH_RESTORED", EventPriority.LOW,
                f"Health restored. {curr.format_health()}.",
            ))

        # Progress milestones
        if curr.get("pendants") != prev.get("pendants"):
            events.append(Event(
                "PROGRESS_MILESTONE", EventPriority.MEDIUM,
                "Pendant acquired!",
                {"pendants": curr.get("pendants")},
            ))
        if curr.get("crystals") != prev.get("crystals"):
            count = bin(curr.get("crystals")).count("1")
            events.append(Event(
                "PROGRESS_MILESTONE", EventPriority.MEDIUM,
                f"Crystal acquired! ({count}/7)",
                {"crystals": curr.get("crystals")},
            ))

        # Boss victory
        if curr_mod == 0x13 and prev_mod != 0x13:
            events.append(Event("BOSS_VICTORY", EventPriority.MEDIUM,
                                "Boss defeated!"))

        # Swimming state
        curr_state = curr.get("link_state")
        prev_state = prev.get("link_state")
        if curr_state == 0x11 and prev_state != 0x11:
            events.append(Event("SWIMMING", EventPriority.LOW,
                                "Entered water."))
        elif prev_state == 0x11 and curr_state != 0x11:
            events.append(Event("SWIMMING", EventPriority.LOW,
                                "Exited water."))

        # Dialog / text box appeared
        if curr_mod == 0x0E and prev_mod != 0x0E:
            dialog_id = curr.get("dialog_id")
            text = ""
            if self.dialog_messages and 0 <= dialog_id < len(self.dialog_messages):
                text = self.dialog_messages[dialog_id]
            events.append(Event(
                "DIALOG", EventPriority.MEDIUM,
                text if text else "Text appeared on screen.",
            ))

        # Enemy proximity
        if curr_mod in GAMEPLAY_MODULES:
            curr_nearby = curr.nearby_enemies()
            prev_nearby = prev.nearby_enemies()
            curr_set = {(e["index"], e["type_id"]) for e in curr_nearby}
            prev_set = {(e["index"], e["type_id"]) for e in prev_nearby}

            new_ids = curr_set - prev_set
            if new_ids:
                for e in curr_nearby:
                    if (e["index"], e["type_id"]) in new_ids:
                        events.append(Event(
                            "ENEMY_NEARBY", EventPriority.HIGH,
                            f"{e['name']} to the {e['direction']}!",
                        ))

        # Item drops: a sprite slot that was an enemy now holds an item
        if curr_mod in GAMEPLAY_MODULES:
            for cs in curr.sprites:
                if cs.type_id not in ITEM_DROP_IDS or not cs.is_active:
                    continue
                # Check if this slot previously held something else
                if cs.index < len(prev.sprites):
                    ps = prev.sprites[cs.index]
                    if ps.type_id == cs.type_id and ps.is_active:
                        continue  # same item, already announced
                events.append(Event(
                    "ITEM_DROP", EventPriority.MEDIUM,
                    f"{cs.name} dropped!",
                ))

        # Non-enemy sprite proximity (NPCs, interactables, objects)
        if curr_mod in GAMEPLAY_MODULES:
            curr_spr = curr.nearby_sprites()
            prev_spr = prev.nearby_sprites()
            curr_spr_set = {(e["index"], e["type_id"]) for e in curr_spr}
            prev_spr_set = {(e["index"], e["type_id"]) for e in prev_spr}

            new_spr = curr_spr_set - prev_spr_set
            if new_spr:
                for e in curr_spr:
                    if (e["index"], e["type_id"]) in new_spr:
                        events.append(Event(
                            "SPRITE_NEARBY", EventPriority.MEDIUM,
                            f"{e['name']} to the {e['direction']}.",
                        ))

        # Blocked movement: directional input held but Link isn't moving
        if curr_mod in GAMEPLAY_MODULES:
            joypad = curr.get("joypad_dir", 0) & 0x0F
            pos_same = (curr.get("link_x") == prev.get("link_x")
                        and curr.get("link_y") == prev.get("link_y"))
            if joypad and pos_same:
                self._blocked_count += 1
                if self._blocked_count >= 1 and not self._blocked_announced:
                    blocker = self._identify_blocker(curr)
                    msg = f"Blocked by {blocker}." if blocker else "Blocked."
                    events.append(Event(
                        "BLOCKED", EventPriority.MEDIUM, msg))
                    self._blocked_announced = True
            else:
                self._blocked_count = 0
                self._blocked_announced = False

        return events

    def _identify_blocker(self, state: GameState) -> Optional[str]:
        """Return the name of whatever is blocking Link, or None."""
        # Check tracked objects that Link is facing (closest first)
        if self.proximity:
            link_x = state.get("link_x") + _LINK_BODY_OFFSET_X
            link_y = state.get("link_y") + _LINK_BODY_OFFSET_Y
            link_dir = DIRECTION_NAMES.get(state.get("direction"))
            best_dist = float("inf")
            best_name: Optional[str] = None
            for obj in self.proximity._tracker.all_objects():
                if obj.zone not in ("facing", "nearby"):
                    continue
                dx = obj.world_x - link_x
                dy = obj.world_y - link_y
                direction = _direction_label(dx, dy)
                if direction != link_dir and direction != "here":
                    continue
                dist = (dx * dx + dy * dy) ** 0.5
                if dist < best_dist:
                    best_dist = dist
                    best_name = obj.name
            if best_name:
                return best_name
            # Probe tiles ahead using graphic-based names, skipping
            # ignored tiles (hookshot target, diggable ground) to find
            # the actual visual blocker.
            ignore = ProximityTracker._CONE_IGNORE_TILES
            indoors = bool(state.get("indoors"))
            ltx = (state.get("link_x") + 8) >> 3
            lty = (state.get("link_y") + 12) >> 3
            offsets = {0: (0, -1), 2: (0, 1), 4: (-1, 0), 6: (1, 0)}
            step = offsets.get(state.get("direction"), (0, 0))
            for i in range(1, 4):
                tx = ltx + step[0] * i
                ty = lty + step[1] * i
                name = self.proximity._read_tile_name(state, tx, ty, indoors)
                if name and name not in ignore:
                    return name
        return None


# ─── RetroArch Client ─────────────────────────────────────────────────────────

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
            raw[name] = int.from_bytes(data, "little") if length <= 4 else int.from_bytes(data, "little")
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
            # Pixel coordinates of the tile Link is facing
            px = link_x + off[0]
            py = link_y + off[1]
            # zelda3 convention: x in 8-px tile units, y in pixel units
            tx = (px >> 3) & 63
            ty = py & 0x1f8  # align to 8-px boundary, keep 6-bit tile range
            if module == 0x07:
                # Indoor: read directly from dung_bg2_attr_table ($7F:2000)
                lower = raw.get("lower_level", 0)
                dung_off = (ty & ~7) * 8 + tx + (0x1000 if lower else 0)
                tile_data = ra.read_core_memory(_DUNG_TILEATTR_ADDR + dung_off, 1)
                if tile_data:
                    facing_tile = tile_data[0]
            elif rom_data and rom_data.map16_to_map8 is not None:
                # Overworld: read map16 index from WRAM, then look up via ROM tables
                # base_x/mask_x are in tile units (already >> 3 in WRAM)
                base_y = raw.get("ow_offset_base_y", 0)
                mask_y = raw.get("ow_offset_mask_y", 0)
                base_x = raw.get("ow_offset_base_x", 0)
                mask_x = raw.get("ow_offset_mask_x", 0)
                ow_tx = (px >> 3)  # tile units for overworld (wider range)
                t = ((py - base_y) & mask_y) * 8
                t |= ((ow_tx - base_x) & mask_x)
                ow_off = t >> 1  # uint16 index
                tile_data = ra.read_core_memory(_OW_TILEATTR_ADDR + ow_off * 2, 2)
                if tile_data:
                    map16_idx = int.from_bytes(tile_data, "little")
                    facing_tile = rom_data.ow_tile_attr(map16_idx, ow_tx, py)

    return GameState(raw=raw, sprites=sprites, timestamp=time.time(),
                     rom_data=rom_data, facing_tile=facing_tile)



# ─── Screen-Reader Output ─────────────────────────────────────────────────────
# All user-facing output goes through _say() so it is clean for screen readers:
#   - one complete thought per line
#   - no decorative brackets, box-drawing, or emoji
#   - immediate flush so the reader picks it up right away

def _say(text: str) -> None:
    """Print a single line of output suitable for a screen reader."""
    print(text, flush=True)


# ─── Proximity Tracker ───────────────────────────────────────────────────────

class ProximityTracker:
    """Announces nearby room features as Link approaches them.

    Tracks two distance zones per feature (approach / nearby) and only
    announces when Link crosses a threshold boundary inward.  Resets
    tracking on room change.
    """

    APPROACH_DIST = 96   # ~12 tiles
    NEARBY_DIST = 56     # ~7 tiles

    # Exact door tile positions from zelda3 kDoorPositionToTilemapOffs tables.
    # Key: (direction, position), Value: (x_tile, y_tile) in the 64×64 room grid.
    # Positions 0-5: upper/left half; 6-11: lower/right half of big rooms.
    _DOOR_TILE_POS: dict[tuple[int, int], tuple[int, int]] = {
        # North doors
        (0, 0): (14, 4), (0, 1): (30, 4), (0, 2): (46, 4),
        (0, 3): (14, 7), (0, 4): (30, 7), (0, 5): (46, 7),
        (0, 6): (14, 36), (0, 7): (30, 36), (0, 8): (46, 36),
        (0, 9): (14, 39), (0, 10): (30, 39), (0, 11): (46, 39),
        # South doors
        (1, 0): (14, 26), (1, 1): (30, 26), (1, 2): (46, 26),
        (1, 3): (14, 23), (1, 4): (30, 23), (1, 5): (46, 23),
        (1, 6): (14, 58), (1, 7): (30, 58), (1, 8): (46, 58),
        (1, 9): (14, 55), (1, 10): (30, 55), (1, 11): (46, 55),
        # West doors
        (2, 0): (2, 15), (2, 1): (2, 31), (2, 2): (2, 47),
        (2, 3): (5, 15), (2, 4): (5, 31), (2, 5): (5, 47),
        (2, 6): (34, 15), (2, 7): (34, 31), (2, 8): (34, 47),
        (2, 9): (37, 15), (2, 10): (37, 31), (2, 11): (37, 47),
        # East doors
        (3, 0): (26, 15), (3, 1): (26, 31), (3, 2): (26, 47),
        (3, 3): (23, 15), (3, 4): (23, 31), (3, 5): (23, 47),
        (3, 6): (58, 15), (3, 7): (58, 31), (3, 8): (58, 47),
        (3, 9): (55, 15), (3, 10): (55, 31), (3, 11): (55, 47),
    }

    # Object categories worth announcing
    _ANNOUNCE_CATEGORIES = {"chest", "stairs", "pit", "hazard", "switch",
                            "block", "water", "wall", "shrub", "feature",
                            "torch", "interactable"}

    # Overworld tile names (from WRAM tile table) worth tracking as zone features.
    # These are interactable objects that only exist as tile attributes, not ROM sprites.
    _PROXIMITY_TILE_NAMES = frozenset({
        "sign", "gravestone", "liftable rock", "liftable boulder",
        "dark rock", "dashable rocks", "cactus", "liftable pot", "chest",
    })

    # Doorway tile attribute values (from zelda3 tile_detect.c TileHandlerIndoor_22)
    _DOORWAY_TILES = frozenset(range(0x30, 0x38))

    # 45° cone tile offsets per direction, grouped by distance (1-8 tiles).
    # Each entry is (dx, dy) in 8-px tile units relative to Link's tile.
    _CONE_OFFSETS: dict[int, list[list[tuple[int, int]]]] = {
        0: [  # north (-y)
            [(0, -1)],
            [(-1, -2), (0, -2), (1, -2)],
            [(-1, -3), (0, -3), (1, -3)],
            [(-2, -4), (-1, -4), (0, -4), (1, -4), (2, -4)],
            [(-2, -5), (-1, -5), (0, -5), (1, -5), (2, -5)],
            [(-3, -6), (-2, -6), (-1, -6), (0, -6), (1, -6), (2, -6), (3, -6)],
            [(-3, -7), (-2, -7), (-1, -7), (0, -7), (1, -7), (2, -7), (3, -7)],
            [(-4, -8), (-3, -8), (-2, -8), (-1, -8), (0, -8), (1, -8), (2, -8), (3, -8), (4, -8)],
        ],
        2: [  # south (+y)
            [(0, 1)],
            [(-1, 2), (0, 2), (1, 2)],
            [(-1, 3), (0, 3), (1, 3)],
            [(-2, 4), (-1, 4), (0, 4), (1, 4), (2, 4)],
            [(-2, 5), (-1, 5), (0, 5), (1, 5), (2, 5)],
            [(-3, 6), (-2, 6), (-1, 6), (0, 6), (1, 6), (2, 6), (3, 6)],
            [(-3, 7), (-2, 7), (-1, 7), (0, 7), (1, 7), (2, 7), (3, 7)],
            [(-4, 8), (-3, 8), (-2, 8), (-1, 8), (0, 8), (1, 8), (2, 8), (3, 8), (4, 8)],
        ],
        4: [  # west (-x)
            [(-1, 0)],
            [(-2, -1), (-2, 0), (-2, 1)],
            [(-3, -1), (-3, 0), (-3, 1)],
            [(-4, -2), (-4, -1), (-4, 0), (-4, 1), (-4, 2)],
            [(-5, -2), (-5, -1), (-5, 0), (-5, 1), (-5, 2)],
            [(-6, -3), (-6, -2), (-6, -1), (-6, 0), (-6, 1), (-6, 2), (-6, 3)],
            [(-7, -3), (-7, -2), (-7, -1), (-7, 0), (-7, 1), (-7, 2), (-7, 3)],
            [(-8, -4), (-8, -3), (-8, -2), (-8, -1), (-8, 0), (-8, 1), (-8, 2), (-8, 3), (-8, 4)],
        ],
        6: [  # east (+x)
            [(1, 0)],
            [(2, -1), (2, 0), (2, 1)],
            [(3, -1), (3, 0), (3, 1)],
            [(4, -2), (4, -1), (4, 0), (4, 1), (4, 2)],
            [(5, -2), (5, -1), (5, 0), (5, 1), (5, 2)],
            [(6, -3), (6, -2), (6, -1), (6, 0), (6, 1), (6, 2), (6, 3)],
            [(7, -3), (7, -2), (7, -1), (7, 0), (7, 1), (7, 2), (7, 3)],
            [(8, -4), (8, -3), (8, -2), (8, -1), (8, 0), (8, 1), (8, 2), (8, 3), (8, 4)],
        ],
    }

    _AREA_CHANGE_COOLDOWN = 2.0  # seconds to suppress zone 1 + cone after area change

    def __init__(self, ra: Optional['RetroArchClient'] = None) -> None:
        self._ra = ra
        self._current_room: int = -1
        self._current_ow_screen: int = -1
        self._tracker = ObjectTracker()
        self._doorway_features: list[tuple[str, int, int, str]] = []
        self._last_cone: str = ""  # last announced cone description
        self._last_direction: int = -1  # track Link's facing direction
        self._area_change_time: float = 0.0  # timestamp of last area transition

    def _zone_transition(self, obj: TrackedObject, dist: float,
                         direction: str, link_dir_name: Optional[str],
                         is_facing: bool) -> Optional[Event]:
        """Evaluate zone state machine for a tracked object.

        Returns an Event if a zone boundary was crossed, else None.
        Updates obj.zone in place.
        """
        prev_zone = obj.zone
        diag = {"key": obj.key, "dist": int(dist),
                "tile": (obj.world_x // 16, obj.world_y // 16)}

        event: Optional[Event] = None

        if is_facing and prev_zone != "facing":
            msg = f"Facing {obj.name.capitalize()}."
            event = Event("FACING", EventPriority.MEDIUM, msg, diag)
            obj.zone = "facing"
        elif dist <= self.NEARBY_DIST and prev_zone not in ("nearby", "facing"):
            msg = f"Nearing {obj.name.capitalize()} to the {direction}."
            event = Event("PROXIMITY", EventPriority.MEDIUM, msg, diag)
            obj.zone = "nearby"
        elif dist <= self.APPROACH_DIST and prev_zone is None:
            msg = f"Approaching {obj.name.capitalize()} to the {direction}."
            # Add velocity info for dynamic sprites
            if obj.is_dynamic:
                speed = (obj.vx ** 2 + obj.vy ** 2) ** 0.5
                if speed > ObjectTracker._SPEED_THRESHOLD:
                    from_dir = _direction_label(-int(obj.vx), -int(obj.vy))
                    msg = (f"Approaching {obj.name.capitalize()} to the {direction}, "
                           f"moving from the {from_dir}.")
            event = Event("PROXIMITY", EventPriority.LOW, msg, diag)
            obj.zone = "approach"

        # Downgrade zone when object drifts outward, so re-entry re-alerts
        if prev_zone == "facing" and not is_facing:
            if dist <= self.NEARBY_DIST:
                obj.zone = "nearby"
            elif dist <= self.APPROACH_DIST:
                obj.zone = "approach"
            else:
                obj.zone = None
        elif prev_zone == "nearby" and dist > self.NEARBY_DIST:
            if dist <= self.APPROACH_DIST:
                obj.zone = "approach"
            else:
                obj.zone = None
        elif dist > self.APPROACH_DIST and prev_zone is not None:
            obj.zone = None

        return event

    def check(self, state: GameState) -> list[Event]:
        """Return proximity events for the current poll cycle."""
        if not state.rom_data:
            return []

        now = state.timestamp
        # Use Link's body centre for distance to tile-based features
        link_x = state.get("link_x") + _LINK_BODY_OFFSET_X
        link_y = state.get("link_y") + _LINK_BODY_OFFSET_Y
        features: list[tuple[str, int, int, str]] = []

        if state.is_in_dungeon:
            room_id = state.get("dungeon_room")
            if room_id != self._current_room:
                self._current_room = room_id
                self._tracker.clear()
                self._area_change_time = now
                # Scan WRAM tilemap for implicit doorway tiles
                if self._ra:
                    self._doorway_features = self._scan_doorways(
                        link_x, link_y, state.get("lower_level", 0))
            room = state.rom_data.get_room(room_id)
            if room:
                features = self._get_features(room, link_x, link_y)
                features.extend(self._doorway_features)
        elif state.is_on_overworld:
            ow_screen = state.ow_screen_from_coords
            if ow_screen is not None and ow_screen != self._current_ow_screen:
                self._current_ow_screen = ow_screen
                self._tracker.clear()
                self._area_change_time = now
            if ow_screen is not None:
                features = self._get_ow_features(state.rom_data, ow_screen)
                features.extend(
                    self._get_ow_tile_features(state, link_x, link_y))

        # Update tracker with static features and dynamic sprites
        self._tracker.update_static(features, now)
        self._tracker.update_sprites(state.sprites, now)
        self._tracker.prune_stale(now)

        events: list[Event] = []
        link_dir_name = DIRECTION_NAMES.get(state.get("direction"))
        in_cooldown = (now - self._area_change_time) < self._AREA_CHANGE_COOLDOWN

        # Process all tracked objects (static + dynamic) through zone state machine
        for obj in self._tracker.all_objects():
            dx = obj.world_x - link_x
            dy = obj.world_y - link_y
            dist = (dx * dx + dy * dy) ** 0.5
            direction = _direction_label(dx, dy)

            is_facing = (dist <= self.NEARBY_DIST
                         and link_dir_name
                         and (direction == link_dir_name
                              or direction == "here"))

            event = self._zone_transition(obj, dist, direction,
                                          link_dir_name, is_facing)
            if event:
                # During cooldown, suppress zone 1 events (nearby/facing)
                if in_cooldown and event.kind in ("FACING", "PROXIMITY"):
                    if obj.zone in ("nearby", "facing"):
                        continue
                events.append(event)

        # Reset cone cache when Link turns (direction change = new scan)
        direction = state.get("direction")
        if direction != self._last_direction:
            self._last_direction = direction
            self._last_cone = ""

        # Tile-cone scan (suppressed during area-change cooldown)
        if not in_cooldown:
            cone_msg = self._scan_cone(state)
            if cone_msg and cone_msg != self._last_cone:
                events.append(Event("CONE_TILE", EventPriority.LOW, cone_msg))
                self._last_cone = cone_msg

        # De-duplicate by message text, preserving order
        seen_msgs: set[str] = set()
        unique: list[Event] = []
        for e in events:
            if e.message not in seen_msgs:
                seen_msgs.add(e.message)
                unique.append(e)
        return unique

    def scan(self, state: GameState) -> list[str]:
        """List all features within approach range, sorted by distance."""
        if not state.rom_data:
            return []

        # Use Link's body centre for distance to tile-based features
        link_x = state.get("link_x") + _LINK_BODY_OFFSET_X
        link_y = state.get("link_y") + _LINK_BODY_OFFSET_Y
        features: list[tuple[str, int, int, str]] = []

        if state.is_in_dungeon:
            room_id = state.get("dungeon_room")
            room = state.rom_data.get_room(room_id)
            if room:
                features = self._get_features(room, link_x, link_y)
                features.extend(self._doorway_features)
        elif state.is_on_overworld:
            ow_screen = state.ow_screen_from_coords
            if ow_screen is not None:
                features = self._get_ow_features(state.rom_data, ow_screen)
                features.extend(
                    self._get_ow_tile_features(state, link_x, link_y))

        results: list[tuple[float, str]] = []

        # Static features
        for _key, px, py, desc in features:
            dx = px - link_x
            dy = py - link_y
            dist = (dx * dx + dy * dy) ** 0.5
            if dist <= self.APPROACH_DIST:
                direction = _direction_label(dx, dy)
                results.append((dist, f"{desc.capitalize()} to the {direction}, "
                                      f"{int(dist)} pixels away."))

        # Dynamic sprites from tracker
        for obj in self._tracker.active_dynamic():
            dx = obj.world_x - link_x
            dy = obj.world_y - link_y
            dist = (dx * dx + dy * dy) ** 0.5
            if dist <= self.APPROACH_DIST:
                direction = _direction_label(dx, dy)
                entry = (f"{obj.name.capitalize()} to the {direction}, "
                         f"{int(dist)} pixels away")
                speed = (obj.vx ** 2 + obj.vy ** 2) ** 0.5
                if speed > ObjectTracker._SPEED_THRESHOLD:
                    move_dir = _direction_label(int(obj.vx), int(obj.vy))
                    entry += f", moving {move_dir}"
                entry += "."
                results.append((dist, entry))

        results.sort(key=lambda r: r[0])
        return [r[1] for r in results]

    _CONE_IGNORE_TILES = frozenset({"diggable ground", "hookshot target"})

    def _scan_cone(self, state: GameState) -> str:
        """Scan tiles in a 45° cone ahead of Link and describe all visible
        interactable tiles, with line-of-sight occlusion.

        Reports every unobscured interactable tile/object from closest to
        farthest.  A tile is obscured if any other solid tile in the cone
        lies on the Bresenham line between Link and that tile.
        """
        from rom_reader import TILE_TYPE_NAMES

        if not self._ra:
            return ""
        direction = state.get("direction")
        cone = self._CONE_OFFSETS.get(direction)
        if cone is None:
            return ""

        link_x = state.get("link_x")
        link_y = state.get("link_y")
        if not link_x or not link_y:
            return ""
        if state.get("main_module") not in (0x07, 0x09):
            return ""

        indoors = state.get("indoors")

        # Link's tile position (8-px grid)
        ltx = (link_x + 8) >> 3   # centre of hitbox
        lty = (link_y + 12) >> 3

        # Unit vector toward Link along the cone's primary axis
        _CLOSER: dict[int, tuple[int, int]] = {
            0: (0, 1), 2: (0, -1), 4: (1, 0), 6: (-1, 0),
        }
        closer = _CLOSER.get(direction, (0, 0))

        # Phase 1: read all tiles in the cone, classify solid/interactable ones
        solid: dict[tuple[int, int], str] = {}

        for ring in cone:
            for dx, dy in ring:
                tx = ltx + dx
                ty = lty + dy
                name = self._read_tile_name(state, tx, ty, indoors)
                if name and name in self._CONE_IGNORE_TILES:
                    name = None
                if name:
                    # Ledges are detected late; place them one tile closer
                    if name.startswith("ledge"):
                        pos = (dx + closer[0], dy + closer[1])
                        if pos != (0, 0):  # don't place on Link's tile
                            solid[pos] = name
                    else:
                        solid[(dx, dy)] = name

        # Phase 2: overlay tracked objects (ring 1/2 features + dynamic sprites)
        # that fall within the cone — more specific labels override raw tiles
        cone_set: set[tuple[int, int]] = set()
        for ring in cone:
            for dx, dy in ring:
                cone_set.add((dx, dy))

        for obj in self._tracker.all_objects():
            obj_dx = (obj.world_x >> 3) - ltx
            obj_dy = (obj.world_y >> 3) - lty
            if (obj_dx, obj_dy) in cone_set:
                solid[(obj_dx, obj_dy)] = obj.name

        # Phase 3: occlusion — keep only tiles with clear line-of-sight
        visible: list[tuple[int, str, str]] = []  # (distance, name, side)

        for ring in cone:
            for dx, dy in ring:
                if (dx, dy) not in solid:
                    continue
                # Check if any solid tile on the line from Link to here blocks it
                obscured = False
                for cell in self._bresenham(0, 0, dx, dy):
                    if cell in solid:
                        obscured = True
                        break
                if obscured:
                    continue
                name = solid[(dx, dy)]
                # Snap to pure cardinal (no diagonals) — pick dominant axis
                if abs(dx) >= abs(dy):
                    cardinal = "east" if dx > 0 else "west"
                else:
                    cardinal = "south" if dy > 0 else "north"
                visible.append((name, cardinal))

        if not visible:
            return ""

        seen: set[tuple[str, str]] = set()
        parts: list[str] = []
        for name, cardinal in visible:
            if (name, cardinal) not in seen:
                seen.add((name, cardinal))
                parts.append(f"{name.capitalize()} to the {cardinal}")
        return "\n".join(p + "." for p in parts)

    @staticmethod
    def _bresenham(x0: int, y0: int, x1: int, y1: int,
                   ) -> list[tuple[int, int]]:
        """Return cells on a Bresenham line, excluding both endpoints."""
        cells: list[tuple[int, int]] = []
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x1 > x0 else (-1 if x1 < x0 else 0)
        sy = 1 if y1 > y0 else (-1 if y1 < y0 else 0)
        err = dx - dy
        x, y = x0, y0
        while True:
            if (x, y) != (x0, y0) and (x, y) != (x1, y1):
                cells.append((x, y))
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy
        return cells

    @staticmethod
    def _cone_side(direction: int, dx: int, dy: int) -> str:
        """Return 'left'/'right'/'' for an offset relative to a direction."""
        if direction == 0:    # north: +x is right
            return "right" if dx > 0 else ("left" if dx < 0 else "")
        if direction == 2:    # south: -x is right
            return "right" if dx < 0 else ("left" if dx > 0 else "")
        if direction == 4:    # west: -y is right
            return "right" if dy < 0 else ("left" if dy > 0 else "")
        if direction == 6:    # east: +y is right
            return "right" if dy > 0 else ("left" if dy < 0 else "")
        return ""

    def _read_tile_attr(self, state: GameState, tx: int, ty: int) -> int:
        """Read a single tile attribute at tile coords (tx, ty).
        Returns -1 on failure."""
        module = state.get("main_module")
        if module == 0x07:
            # Dungeon: read from WRAM attribute table
            ctx = tx & 63
            cty = (ty * 8) & 0x1F8  # convert tile row to byte offset
            off = cty * 8 + ctx + (0x1000 if state.get("lower_level", 0) else 0)
            data = self._ra.read_core_memory(_DUNG_TILEATTR_ADDR + off, 1)
            return data[0] if data else -1
        elif module == 0x09 and state.rom_data:
            # Overworld: map16 lookup via ROM tables
            px = tx * 8
            py = ty * 8
            base_y = state.get("ow_offset_base_y", 0)
            mask_y = state.get("ow_offset_mask_y", 0)
            base_x = state.get("ow_offset_base_x", 0)
            mask_x = state.get("ow_offset_mask_x", 0)
            t = ((py - base_y) & mask_y) * 8
            t |= ((tx - base_x) & mask_x)
            ow_off = t >> 1
            tile_data = self._ra.read_core_memory(
                _OW_TILEATTR_ADDR + ow_off * 2, 2)
            if tile_data:
                map16_idx = int.from_bytes(tile_data, "little")
                return state.rom_data.ow_tile_attr(map16_idx, tx, py)
            return -1
        return -1

    def _read_tile_attr_at(self, room_tx: int, room_ty: int,
                           link_y: int) -> int:
        """Read dungeon tile attribute at room-relative tile coords.

        *room_tx*, *room_ty* are in the 64×64 room grid.
        *link_y* is used to determine upper/lower level offset.
        """
        if not self._ra:
            return -1
        ctx = room_tx & 63
        cty = (room_ty * 8) & 0x1F8
        # Use link_y to determine the room quadrant for lower_level;
        # for simplicity we always use level 0 here (most chests are on BG2)
        off = cty * 8 + ctx
        data = self._ra.read_core_memory(_DUNG_TILEATTR_ADDR + off, 1)
        return data[0] if data else -1

    def _read_tile_name(self, state: GameState, tx: int, ty: int,
                        indoors: bool) -> Optional[str]:
        """Read a tile and return its human name, or None.

        Uses graphic-based identification on the overworld (map16 index)
        for reliable object names, falling back to the tile attribute.
        """
        from rom_reader import TILE_TYPE_NAMES
        module = state.get("main_module")

        # Overworld: try graphic-based name first via map16 index
        if module == 0x09 and state.rom_data:
            px = tx * 8
            py = ty * 8
            base_y = state.get("ow_offset_base_y", 0)
            mask_y = state.get("ow_offset_mask_y", 0)
            base_x = state.get("ow_offset_base_x", 0)
            mask_x = state.get("ow_offset_mask_x", 0)
            t = ((py - base_y) & mask_y) * 8
            t |= ((tx - base_x) & mask_x)
            ow_off = t >> 1
            tile_data = self._ra.read_core_memory(
                _OW_TILEATTR_ADDR + ow_off * 2, 2)
            if tile_data:
                map16_idx = int.from_bytes(tile_data, "little")
                gfx_name = state.rom_data.ow_tile_name(map16_idx)
                if gfx_name:
                    return gfx_name
                attr = state.rom_data.ow_tile_attr(map16_idx, tx, py)
                return TILE_TYPE_NAMES.get(attr)
            return None

        # Dungeon: use tile attribute
        attr = self._read_tile_attr(state, tx, ty)
        if attr < 0:
            return None
        if indoors and attr in GameState._INDOOR_WALL_TILES:
            return "wall"
        return TILE_TYPE_NAMES.get(attr)

    def _get_features(self, room: 'RoomData',
                      link_x: int = 0, link_y: int = 0,
                      ) -> list[tuple[str, int, int, str]]:
        """Extract announceable features as (key, px, py, description).

        Dungeon objects/sprites use BG-tilemap-relative coordinates, but
        Link's position is absolute.  We derive the room's absolute origin
        from Link's current position (rooms are 512-px aligned).
        """
        features: list[tuple[str, int, int, str]] = []

        # Room origin in absolute pixel coordinates
        room_ox = (link_x >> 9) << 9
        room_oy = (link_y >> 9) << 9

        # Doors — exact tile position from zelda3 tables
        for door in room.doors:
            tile = self._DOOR_TILE_POS.get((door.direction, door.position))
            if tile:
                px = room_ox + tile[0] * 8
                py = room_oy + tile[1] * 8
                key = f"door:{door.door_type}:{door.direction}:{door.position}"
                features.append((key, px, py, door.type_name))

        # Objects — filtered to interesting categories
        # Dungeon objects use 8-px tile units (64×64 grid = 512×512 px room)
        for obj in room.objects:
            if obj.category in self._ANNOUNCE_CATEGORIES:
                px = room_ox + obj.x_tile * 8
                py = room_oy + obj.y_tile * 8
                key = f"obj:{obj.object_type}:{obj.x_tile}:{obj.y_tile}"
                name = obj.name
                # Check WRAM to see if a closed chest has been opened
                if obj.category == "chest" and "open" not in name and self._ra:
                    attr = self._read_tile_attr_at(
                        obj.x_tile, obj.y_tile, link_y)
                    if attr == 0x27:
                        name = "open " + name
                features.append((key, px, py, name))

        # ROM sprites — all categories except enemy (live enemies handled
        # separately via the sprite table with real-time positions).
        for spr in room.sprites:
            if spr.category not in (SpriteCategory.ENEMY, SpriteCategory.UNKNOWN):
                px = room_ox + spr.x_tile * 16
                py = room_oy + spr.y_tile * 16
                key = f"spr:{spr.sprite_type}:{spr.x_tile}:{spr.y_tile}"
                features.append((key, px, py, spr.name))

        return features

    def _get_ow_features(self, rom_data: RomData,
                         screen: int) -> list[tuple[str, int, int, str]]:
        """Extract announceable overworld sprites as (key, px, py, desc).

        Overworld sprite tile coordinates are relative to the 32x32 tile
        screen.  To get absolute pixel positions we offset by the screen's
        position in the 8x8 grid (each screen = 512 px).
        """
        from rom_reader import _dedup_sprites
        sprites = _dedup_sprites(rom_data.get_ow_sprites(screen))
        if not sprites:
            return []
        # Screen origin in absolute pixels
        col = screen & 7
        row = (screen >> 3) & 7
        ox = col * 512
        oy = row * 512
        features: list[tuple[str, int, int, str]] = []
        for spr in sprites:
            if spr.category == SpriteCategory.UNKNOWN:
                continue
            # Enemies are handled by the live sprite table, but ROM
            # positions are static; include them so the approach zone
            # still fires for patrol-route enemies.
            px = ox + spr.x_tile * 16
            py = oy + spr.y_tile * 16
            key = f"ow:{spr.sprite_type}:{spr.x_tile}:{spr.y_tile}"
            features.append((key, px, py, spr.name))
        return features

    def _get_ow_tile_features(self, state: GameState,
                               link_x: int, link_y: int,
                               ) -> list[tuple[str, int, int, str]]:
        """Scan nearby overworld tiles and return interactable ones as features.

        Bulk-reads the 8 KB WRAM overworld tile table ($7E:2000) once per
        call, then scans map16 cells within APPROACH_DIST of Link's body
        centre.  Returns interactable tiles (bushes, signs, rocks, etc.)
        as ``(key, px, py, name)`` features suitable for the ObjectTracker.
        """
        from rom_reader import TILE_TYPE_NAMES

        if not self._ra or not state.rom_data:
            return []

        bulk = self._ra.read_core_memory(_OW_TILEATTR_ADDR, 8192)
        if not bulk:
            return []

        base_y = state.get("ow_offset_base_y", 0)
        mask_y = state.get("ow_offset_mask_y", 0)
        base_x = state.get("ow_offset_base_x", 0)
        mask_x = state.get("ow_offset_mask_x", 0)
        rom = state.rom_data

        # Scan radius in map16 tiles (16 px each), +1 buffer to avoid
        # edge flicker when features are right at the APPROACH_DIST boundary.
        radius = (self.APPROACH_DIST // 16) + 1
        cx = link_x // 16
        cy = link_y // 16

        features: list[tuple[str, int, int, str]] = []

        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                m16x = cx + dx
                m16y = cy + dy

                # 8-px tile coords of top-left sub-tile in this map16 cell
                tx = m16x * 2
                py_px = m16y * 16  # pixel Y

                # WRAM offset (scroll-aware)
                t = ((py_px - base_y) & mask_y) * 8
                t |= ((tx - base_x) & mask_x)
                ow_off = t >> 1

                byte_off = ow_off * 2
                if byte_off < 0 or byte_off + 2 > len(bulk):
                    continue

                map16_idx = int.from_bytes(
                    bulk[byte_off:byte_off + 2], "little")

                # Graphic-based name first, then attribute fallback
                name = rom.ow_tile_name(map16_idx)
                if not name:
                    attr = rom.ow_tile_attr(map16_idx, tx, py_px)
                    name = TILE_TYPE_NAMES.get(attr)

                if name and name in self._PROXIMITY_TILE_NAMES:
                    feat_x = m16x * 16 + 8  # centre of map16 cell
                    feat_y = m16y * 16 + 8
                    key = f"owtile:{m16x}:{m16y}"
                    features.append((key, feat_x, feat_y, name))

        return features

    def _scan_doorways(self, link_x: int, link_y: int,
                       lower_level: int,
                       ) -> list[tuple[str, int, int, str]]:
        """Scan WRAM dungeon attribute table for doorway tiles.

        Reads the 64×64 tile attribute table at $7F:2000 and finds tiles
        with types 0x30-0x37 (doorway/transition tiles from zelda3
        TileHandlerIndoor_22).  Groups adjacent tiles into clusters and
        returns each as an "open doorway" feature at the cluster center.
        """
        if not self._ra:
            return []
        base = _DUNG_TILEATTR_ADDR + (0x1000 if lower_level else 0)
        data = self._ra.read_core_memory(base, 4096)
        if not data or len(data) < 4096:
            return []

        # Find all doorway tiles
        doorway_set: set[tuple[int, int]] = set()
        for y in range(64):
            row_off = y * 64
            for x in range(64):
                if data[row_off + x] in self._DOORWAY_TILES:
                    doorway_set.add((x, y))
        if not doorway_set:
            return []

        # Group into connected clusters (flood fill)
        remaining = set(doorway_set)
        clusters: list[set[tuple[int, int]]] = []
        while remaining:
            seed = remaining.pop()
            cluster = {seed}
            queue = [seed]
            while queue:
                cx, cy = queue.pop()
                for nx, ny in ((cx-1, cy), (cx+1, cy),
                               (cx, cy-1), (cx, cy+1)):
                    if (nx, ny) in remaining:
                        remaining.discard((nx, ny))
                        cluster.add((nx, ny))
                        queue.append((nx, ny))
            clusters.append(cluster)

        # Convert to features at cluster center (absolute coordinates)
        room_ox = (link_x >> 9) << 9
        room_oy = (link_y >> 9) << 9
        features: list[tuple[str, int, int, str]] = []
        for cluster in clusters:
            cx = sum(t[0] for t in cluster) // len(cluster)
            cy = sum(t[1] for t in cluster) // len(cluster)
            px = room_ox + cx * 8
            py = room_oy + cy * 8
            key = f"doorway:{cx}:{cy}"
            features.append((key, px, py, "open doorway"))
        return features


# ─── ASCII Map Renderer ──────────────────────────────────────────────────────

class MapRenderer:
    """Renders a live ASCII map of the area around Link in the terminal."""

    # Viewport size in 8px tiles (matches SNES visible screen 256x192)
    VP_W = 32
    VP_H = 24

    # Tile attribute byte -> ASCII character
    TILE_CHARS: dict[int, str] = {
        0x00: ' ',
        # Walls
        0x01: '#', 0x02: '#', 0x03: '#', 0x26: '#', 0x43: '#',
        # Indoor wall tiles (0x04 is grass outdoors, wall indoors)
        0x0B: '#', 0x6C: '#', 0x6D: '#', 0x6E: '#', 0x6F: '#',
        # Water
        0x08: '~', 0x09: '~',
        # Pit
        0x20: 'O',
        # Spikes / hazards
        0x0D: 'X',
        # Ice
        0x0E: '=', 0x0F: '=',
        # Stairs
        0x1D: '>', 0x1E: '>', 0x1F: '>', 0x22: '>',
        # Ledges
        0x1C: '_', 0x28: '_', 0x29: '_', 0x2A: '_', 0x2B: '_',
        # Chests
        0x58: '*', 0x59: '*', 0x5A: '*', 0x5B: '*', 0x5C: '*', 0x5D: '*',
        # Doors / doorways
        0x30: '+', 0x31: '+', 0x32: '+', 0x33: '+',
        0x34: '+', 0x35: '+', 0x36: '+', 0x37: '+',
        # Bushes
        0x50: 'B', 0x51: 'B',
        # Rocks
        0x52: 'R', 0x53: 'R',
        # Pushable blocks
        **{i: 'P' for i in range(0x70, 0x80)},
        # Thick grass
        0x04: ',', 0x40: ',',
        # Hookshot target
        0x27: 'H',
        # Warp tile
        0x4B: 'W',
        # Pots
        0x54: 'R', 0x55: 'R', 0x56: 'R',
    }

    # Link direction -> character
    LINK_CHARS: dict[int, str] = {0: '^', 2: 'v', 4: '<', 6: '>'}

    # Characters for overlay zones (only drawn on passable tiles)
    _OVERLAY_PASSABLE = {'.', ' ', ','}
    _CONE_CHAR = ':'
    _NEARBY_CHAR = '1'     # nearby radius
    _APPROACH_CHAR = '2'   # approach radius

    _EVENT_TTL = 5.0  # seconds before sidebar events expire

    def __init__(self, overlay: bool = False) -> None:
        self._frame_count = 0
        self.overlay = overlay
        self._event_log: list[tuple[float, str]] = []

    def render(self, state: GameState, ra: RetroArchClient,
               rom_data: Optional[RomData] = None,
               events: Optional[list[Event]] = None,
               snapshot: bool = False) -> None:
        """Render one frame of the ASCII map to the terminal."""
        module = state.get("main_module")
        link_x = state.get("link_x")
        link_y = state.get("link_y")
        indoors = state.get("indoors")

        if module not in (0x07, 0x09) or not link_x or not link_y:
            # Not in gameplay — show a placeholder
            print(f"\033[HWaiting for gameplay... (module={module:#04x})\033[K\033[J",
                  end="", flush=True)
            return

        # Build the tile grid
        grid = [['.' for _ in range(self.VP_W)] for _ in range(self.VP_H)]

        # Centre viewport on Link's body (not sprite origin)
        body_x = link_x + _LINK_BODY_OFFSET_X
        body_y = link_y + _LINK_BODY_OFFSET_Y
        vp_px = body_x - (self.VP_W // 2) * 8
        vp_py = body_y - (self.VP_H // 2) * 8

        if module == 0x07:
            self._fill_dungeon(grid, ra, state, vp_px, vp_py, indoors)
        elif module == 0x09 and rom_data:
            self._fill_overworld(grid, ra, state, rom_data, vp_px, vp_py)

        # Overlay detection zones (cone + radii) on passable tiles
        if self.overlay:
            self._draw_overlay(grid, state.get("direction"),
                               (self.VP_W // 2), (self.VP_H // 2))

        # Overlay sprites (their coords are also sprite-origin, so apply
        # the same body offset for consistent placement)
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

        # Overlay Link (two tiles tall, centred on body)
        lx = (body_x - vp_px) // 8
        ly = (body_y - vp_py) // 8
        direction = state.get("direction")
        link_ch = self.LINK_CHARS.get(direction, '@')
        for row in (ly, ly + 1):
            if 0 <= row < self.VP_H:
                for col in (lx - 1, lx):
                    if 0 <= col < self.VP_W:
                        grid[row][col] = link_ch

        # Render to terminal — use \033[K (clear to EOL) on every line
        # and \033[J (clear to end of screen) after the last line so
        # shorter frames don't leave ghost characters from previous ones.
        self._frame_count += 1
        eol = "\033[K"

        # Update the event sidebar log
        now = time.monotonic()
        if events:
            for e in events:
                self._event_log.append((now, e.message))
        # Expire old entries
        self._event_log = [(t, m) for t, m in self._event_log
                           if now - t < self._EVENT_TTL]

        # Build map lines with optional event sidebar on the right
        map_width = self.VP_W * 2  # each tile is doubled horizontally
        sidebar_gap = "  "
        lines: list[str] = []
        for i, row in enumerate(grid):
            map_line = ''.join(ch * 2 for ch in row)
            if self.overlay and i < len(self._event_log):
                _, msg = self._event_log[-(i + 1)]  # newest first
                lines.append(map_line + sidebar_gap + msg + eol)
            else:
                lines.append(map_line + eol)

        # Status line
        lines.append(eol)
        room_info = state.location_name
        hp_str = state.format_health()
        lines.append(
            f"Pos: ({link_x},{link_y})  "
            f"Dir: {state.direction_name}  "
            f"HP: {hp_str}  "
            f"Loc: {room_info}" + eol
        )
        # Overlay legend
        if self.overlay:
            lines.append(
                f": cone  "
                f"{self._NEARBY_CHAR} nearby({ProximityTracker.NEARBY_DIST}px)  "
                f"{self._APPROACH_CHAR} approach({ProximityTracker.APPROACH_DIST}px)" + eol
            )
        # Output the frame
        if snapshot:
            # Strip ANSI escapes for clean single-shot output
            clean = [line.replace(eol, '') for line in lines]
            print('\n'.join(clean), end="", flush=True)
        else:
            # Cursor home, draw frame, then clear everything below
            print("\033[H" + '\n'.join(lines) + "\033[J", end="", flush=True)

    def _fill_dungeon(self, grid: list[list[str]],
                      ra: RetroArchClient, state: GameState,
                      vp_px: int, vp_py: int, indoors: int) -> None:
        """Fill the grid with dungeon tile attributes via bulk WRAM read."""
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
                # Convert to tile coords in the 64x64 dungeon grid
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
        """Fill the grid with overworld tile attributes via bulk WRAM read."""
        base_y = state.get("ow_offset_base_y", 0)
        mask_y = state.get("ow_offset_mask_y", 0)
        base_x = state.get("ow_offset_base_x", 0)
        mask_x = state.get("ow_offset_mask_x", 0)

        if not mask_y or not mask_x:
            return

        # Bulk-read the entire map16 WRAM table (4096 uint16 entries = 8192 bytes)
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
        """Map a tile attribute byte to an ASCII character."""
        ch = self.TILE_CHARS.get(attr)
        if ch:
            return ch
        # Outdoor: 0x04 is grass
        if attr == 0x04 and not indoors:
            return ','
        return '.'

    def _draw_overlay(self, grid: list[list[str]], direction: int,
                      cx: int, cy: int) -> None:
        """Draw detection radii and facing cone onto passable grid cells.

        cx, cy are Link's grid position (viewport centre).
        Radii are drawn outermost-first so inner zones overwrite outer.
        """
        passable = self._OVERLAY_PASSABLE

        # Convert pixel radii to tile units (8px per tile)
        approach_r = ProximityTracker.APPROACH_DIST / 8.0  # ~12 tiles
        nearby_r = ProximityTracker.NEARBY_DIST / 8.0      # ~7 tiles

        # Draw radius rings (outermost first).  A cell is on a ring if
        # its distance from centre is within ±0.7 tiles of the radius.
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

        # Draw the facing cone (from ProximityTracker._CONE_OFFSETS)
        cone = ProximityTracker._CONE_OFFSETS.get(direction)
        if cone:
            for ring in cone:
                for dx, dy in ring:
                    gx = cx + dx
                    gy = cy + dy
                    if (0 <= gx < self.VP_W and 0 <= gy < self.VP_H
                            and grid[gy][gx] in passable):
                        grid[gy][gx] = self._CONE_CHAR


# ─── Memory Poller (Background Thread) ────────────────────────────────────────

class MemoryPoller:
    """Polls emulator memory at ~4 Hz, detects events, prints output."""

    def __init__(self, ra: RetroArchClient, poll_hz: float = 30.0,
                 dialog_messages: Optional[list[str]] = None,
                 rom_data: Optional[RomData] = None,
                 diag: bool = False,
                 map_mode: bool = False,
                 map_overlay: bool = False):
        self.ra = ra
        self.poll_interval = 1.0 / poll_hz
        self.rom_data = rom_data
        self.diag = diag
        self.map_mode = map_mode
        self.proximity = ProximityTracker(ra=ra)
        self.detector = EventDetector(dialog_messages, rom_data,
                                      proximity=self.proximity)
        self._map_renderer: Optional[MapRenderer] = (
            MapRenderer(overlay=map_overlay) if map_mode else None)
        self._state: Optional[GameState] = None
        self._state_lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._initial_report_done = False

    def get_state(self) -> Optional[GameState]:
        with self._state_lock:
            return self._state

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def _diag_dump_room(self, state: GameState) -> None:
        """Print raw feature data for the current room (diagnostic mode)."""
        if not state.rom_data or not state.is_in_dungeon:
            return
        room_id = state.get("dungeon_room")
        room = state.rom_data.get_room(room_id)
        if not room:
            return
        _say(f"[DIAG] Room {room_id:#06x} feature dump:")
        _say(f"[DIAG] Link at pixel ({state.get('link_x')}, {state.get('link_y')})")
        if room.header:
            _say(f"[DIAG] Header: tag1={room.header.tag1:#04x} "
                 f"tag2={room.header.tag2:#04x}")
        for door in room.doors:
            _say(f"[DIAG]   DOOR  dir={door.direction:#04x}({door.direction_name})  "
                 f"type={door.door_type:#04x}({door.type_name})  "
                 f"pos={door.position}")
        for obj in room.objects:
            _say(f"[DIAG]   OBJ   type={obj.object_type:#04x}  "
                 f"cat={obj.category:<12s}  name={obj.name:<24s}  "
                 f"tile=({obj.x_tile}, {obj.y_tile})")
        for spr in room.sprites:
            _say(f"[DIAG]   SPR   type={spr.sprite_type:#04x}  "
                 f"cat={spr.category:<12s}  name={spr.name:<24s}  "
                 f"tile=({spr.x_tile}, {spr.y_tile})  "
                 f"layer={'lower' if spr.is_lower_layer else 'upper'}")
        if not room.doors and not room.objects and not room.sprites:
            _say("[DIAG]   (no features)")

    def _poll_loop(self):
        prev_state: Optional[GameState] = None
        # Map mode renders at ~4 Hz regardless of poll rate
        map_interval = 0.25
        last_map_render = 0.0

        while self._running:
            try:
                new_state = read_memory(self.ra, self.rom_data)

                # Skip if we didn't get valid data
                if new_state.raw.get("main_module") is None:
                    time.sleep(self.poll_interval)
                    continue

                with self._state_lock:
                    self._state = new_state

                # Mark initial report done silently (location/health
                # are available via the look/health commands).
                module = new_state.get("main_module")
                if not self._initial_report_done and module in (0x07, 0x09):
                    self._initial_report_done = True

                # Detect events and proximity, then output sorted by priority:
                # 1. Blocked movement  2. Enemy proximity  3. Everything else
                all_events: list[Event] = []
                if prev_state is not None:
                    all_events.extend(self.detector.detect(prev_state, new_state))
                all_events.extend(self.proximity.check(new_state))

                all_events.sort(key=lambda e: _EVENT_SORT_KEY.get(e.kind, 2))

                if self.map_mode and self._map_renderer:
                    # Render ASCII map at ~4 Hz
                    now = time.monotonic()
                    if now - last_map_render >= map_interval:
                        self._map_renderer.render(
                            new_state, self.ra, self.rom_data, all_events)
                        last_map_render = now
                else:
                    for event in all_events:
                        if self.diag and event.kind in ("PROXIMITY", "FACING"):
                            _say(f"  [DIAG] {event.message} | {event.data}")
                        else:
                            _say(event.message)
                        if self.diag and event.kind == "ROOM_CHANGE":
                            self._diag_dump_room(new_state)

                prev_state = new_state

            except Exception:
                pass  # Don't crash the polling thread

            time.sleep(self.poll_interval)


# ─── State Dump ──────────────────────────────────────────────────────────────

def dump_state(state: GameState, path: str = "dump.json") -> str:
    """Write a comprehensive state snapshot to a JSON file for debugging.

    Includes raw memory, bridge interpretations, ROM room data, and live
    sprites so classification errors can be compared against what is
    actually on screen.
    """
    data: dict = {}

    # Raw memory values
    data["raw_memory"] = {k: (f"0x{v:X}" if v is not None else None)
                          for k, v in state.raw.items()}

    # Bridge interpretations
    data["interpreted"] = {
        "location": state.location_name,
        "world": state.world_name,
        "indoors": state.is_indoors,
        "in_dungeon": state.is_in_dungeon,
        "on_overworld": state.is_on_overworld,
        "direction": state.direction_name,
        "main_module": MODULE_NAMES.get(state.get("main_module"),
                                         f"unknown ({state.get('main_module'):#04x})"),
        "link_state": LINK_STATE_NAMES.get(state.get("link_state"),
                                            f"unknown ({state.get('link_state'):#04x})"),
        "health": state.format_health(),
        "position": {"x": state.get("link_x"), "y": state.get("link_y")},
        "dungeon_room": f"0x{state.get('dungeon_room'):04X}",
        "ow_screen": f"0x{state.get('ow_screen'):04X}",
        "ow_screen_from_coords": (f"0x{state.ow_screen_from_coords:02X}"
                                   if state.ow_screen_from_coords is not None
                                   else None),
    }

    # Live sprite table (from emulator memory)
    live_sprites = []
    for s in state.sprites:
        if s.is_active:
            live_sprites.append({
                "slot": s.index,
                "type_id": f"0x{s.type_id:02X}",
                "name": s.name,
                "is_enemy": s.is_enemy,
                "state": s.state,
                "x": s.x,
                "y": s.y,
            })
    data["live_sprites"] = live_sprites

    # Nearby enemies (bridge's proximity calculation)
    data["nearby_enemies"] = state.nearby_enemies()

    # ROM room data (static placement from cartridge)
    rom_section: dict = {"available": False}
    if state.rom_data:
        rom_section["available"] = True
        if state.is_in_dungeon:
            room_id = state.get("dungeon_room")
            room = state.rom_data.get_room(room_id)
            if room:
                rom_section["room_id"] = f"0x{room.room_id:04X}"
                rom_section["dungeon"] = room.dungeon_name

                if room.header:
                    rom_section["header"] = {
                        "tag1": f"0x{room.header.tag1:02X}",
                        "tag2": f"0x{room.header.tag2:02X}",
                        "is_dark": room.header.is_dark,
                        "kill_to_open": room.header.has_kill_to_open,
                        "moving_floor": room.header.has_moving_floor,
                        "spriteset": room.header.spriteset,
                    }

                rom_section["sprites"] = [
                    {
                        "type_id": f"0x{s.sprite_type:02X}",
                        "name": s.name,
                        "category": s.category,
                        "tile": [s.x_tile, s.y_tile],
                        "layer": "lower" if s.is_lower_layer else "upper",
                    }
                    for s in room.sprites
                ]

                rom_section["doors"] = [
                    {
                        "direction": d.direction_name,
                        "type": d.type_name,
                        "type_id": f"0x{d.door_type:02X}",
                        "position": d.position,
                    }
                    for d in room.doors
                ]

                rom_section["objects"] = [
                    {
                        "type_id": f"0x{o.object_type:02X}",
                        "name": o.name,
                        "category": o.category,
                        "tile": [o.x_tile, o.y_tile],
                    }
                    for o in room.objects
                ]

                rom_section["brief"] = room.to_brief()
                rom_section["full"] = room.to_full()

        elif state.is_on_overworld:
            screen = state.get("ow_screen")
            rom_section["ow_screen"] = f"0x{screen:04X}"
            rom_section["ow_sprites"] = [
                {
                    "type_id": f"0x{s.sprite_type:02X}",
                    "name": s.name,
                    "category": s.category,
                    "tile": [s.x_tile, s.y_tile],
                }
                for s in state.rom_data.get_ow_sprites(screen)
            ]

    data["rom_data"] = rom_section

    # Area description (what the bridge would announce)
    data["area_description"] = state.area_description
    data["area_brief"] = state.area_brief

    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    return path


# ─── Commands ─────────────────────────────────────────────────────────────────

_NO_STATE = "No game state available yet."

COMMANDS: dict[str, str] = {
    "pos":      "Current position, room, and direction",
    "look":     "Description of the current area",
    "health":   "Health, magic, and resources",
    "items":    "Equipment and inventory",
    "enemies":  "Nearby enemies and directions",
    "scan":     "Nearby room features (doors, chests, hazards)",
    "dump":     "Write full state snapshot to dump.json",
    "diag":     "Dump raw room features (diagnostic)",
    "progress": "Pendants, crystals, and progress",
    "status":   "RetroArch connection status",
    "help":     "List available commands",
    "quit":     "Exit the program",
}


def handle_command(cmd: str, poller: MemoryPoller,
                   ra: RetroArchClient) -> bool:
    """Handle a command. Returns True if recognized."""
    cmd = cmd.strip().lower().lstrip("/")

    if cmd == "pos":
        state = poller.get_state()
        _say(state.format_position() if state else _NO_STATE)
        return True

    if cmd == "look":
        state = poller.get_state()
        if not state:
            _say(_NO_STATE)
        else:
            _say(state.location_name + ".")
            desc = state.area_description
            if desc:
                # ROM full descriptions are multi-line; print each line
                for line in desc.split("\n"):
                    if line.strip():
                        _say(line.strip())
            else:
                _say("No description available for this area.")
            # Append WRAM-detected doorways not covered by ROM doors
            dw = poller.proximity._doorway_features
            if dw and state.is_in_dungeon:
                link_x = state.get("link_x")
                link_y = state.get("link_y")
                room_cx = ((link_x >> 9) << 9) + 256
                room_cy = ((link_y >> 9) << 9) + 256
                dirs = []
                for _key, px, py, _desc in dw:
                    dirs.append(_direction_label(px - room_cx, py - room_cy))
                seen: set[str] = set()
                unique = [d for d in dirs if not (d in seen or seen.add(d))]
                exits = ", ".join(f"open doorway to the {d}" for d in unique)
                _say(f"Detected exits: {exits}.")
        return True

    if cmd == "health":
        state = poller.get_state()
        _say(state.format_resources() if state else _NO_STATE)
        return True

    if cmd == "items":
        state = poller.get_state()
        if state:
            _say(state.format_equipment())
            _say(state.format_inventory())
        else:
            _say(_NO_STATE)
        return True

    if cmd == "enemies":
        state = poller.get_state()
        _say(state.format_enemies() if state else _NO_STATE)
        return True

    if cmd == "scan":
        state = poller.get_state()
        if not state:
            _say(_NO_STATE)
        else:
            features = poller.proximity.scan(state)
            if features:
                _say("Nearby features:")
                for f in features:
                    _say(f"  {f}")
            else:
                _say("No features nearby.")
        return True

    if cmd == "dump" or cmd.startswith("dump "):
        state = poller.get_state()
        if not state:
            _say(_NO_STATE)
        else:
            parts = cmd.split(maxsplit=1)
            path = parts[1] if len(parts) > 1 else "dump.json"
            out = dump_state(state, path)
            _say(f"State dumped to {out}.")
        return True

    if cmd == "diag":
        state = poller.get_state()
        if not state:
            _say(_NO_STATE)
        else:
            poller._diag_dump_room(state)
        return True

    if cmd == "progress":
        state = poller.get_state()
        _say(state.format_progress() if state else _NO_STATE)
        return True

    if cmd == "status":
        status = ra.get_status()
        version = ra.get_version()
        _say(f"RetroArch status: {status}" if status
             else "RetroArch not responding.")
        if version:
            _say(f"RetroArch version: {version}")
        return True

    if cmd == "help":
        _say("Available commands:")
        for name, desc in COMMANDS.items():
            _say(f"  {name} - {desc}")
        return True

    return False


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="ALttP Accessibility Bridge - screen-reader-friendly game events",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
A Link to the Past accessibility bridge that polls emulator memory,
detects game events, and provides screen-reader-friendly output.

Examples:
  python bridge.py
  python bridge.py --port 55356
""",
    )
    parser.add_argument("--host", default="127.0.0.1",
                        help="RetroArch host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=55355,
                        help="RetroArch UDP port (default: 55355)")
    parser.add_argument("--poll-hz", type=float, default=30.0,
                        help="Memory poll rate in Hz (default: 30)")
    parser.add_argument("--rom", default=None,
                        help="Path to ALttP ROM file (.sfc) for geometric room descriptions")
    parser.add_argument("--text", default=None,
                        help="Path to ALttP text dump file (default: text.txt next to bridge.py)")
    parser.add_argument("--diag", action="store_true",
                        help="Diagnostic mode: show raw IDs and categories for all detected features")
    parser.add_argument("--dump", nargs="?", const="dump.json", default=None,
                        metavar="FILE",
                        help="Single-shot: read memory once, write state to FILE (default: dump.json), and exit")
    parser.add_argument("--map", action="store_true",
                        help="ASCII map mode: render a live tile map instead of text events")
    parser.add_argument("--map-overlay", action="store_true",
                        help="Show detection cone and radii around Link (requires --map)")
    parser.add_argument("--map-snap", action="store_true",
                        help="Single-shot: print one ASCII map frame with overlay and exit")
    args = parser.parse_args()

    # Load ROM data if provided
    rom_data: Optional[RomData] = None
    if args.rom:
        if args.diag:
            _say(f"Loading ROM: {args.rom}")
        rom_data = load_rom(args.rom, verbose=args.diag)
        if args.diag:
            if rom_data:
                _say("ROM data loaded. Room descriptions will use ROM geometry.")
            else:
                _say("Failed to load ROM. Falling back to static descriptions.")

    # Load dialog text: prefer ROM-extracted dialog, fall back to text dump
    dialog_messages: list[str] = []
    if rom_data and rom_data.dialog_strings:
        dialog_messages = rom_data.dialog_strings
    else:
        text_path = args.text or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "text.txt")
        dialog_messages = load_text_dump(text_path)

    # Connect to RetroArch
    ra = RetroArchClient(host=args.host, port=args.port)
    ra.connect()

    while True:
        version = ra.get_version()
        if version:
            break
        if not args.map:
            _say("Waiting for RetroArch.")
        try:
            time.sleep(5)
        except KeyboardInterrupt:
            ra.close()
            sys.exit(0)

    # Single-shot dump mode: read once, write file, exit
    if args.dump:
        state = read_memory(ra, rom_data)
        if state.raw.get("main_module") is None:
            _say("Could not read game state. Is a game loaded?")
            ra.close()
            sys.exit(1)
        out = dump_state(state, args.dump)
        _say(f"State dumped to {out}.")
        ra.close()
        sys.exit(0)

    # Single-shot map snapshot: render one frame and exit
    if args.map_snap:
        state = read_memory(ra, rom_data)
        if state.raw.get("main_module") is None:
            _say("Could not read game state. Is a game loaded?")
            ra.close()
            sys.exit(1)
        renderer = MapRenderer(overlay=True)
        renderer.render(state, ra, rom_data, snapshot=True)
        print()  # trailing newline
        ra.close()
        sys.exit(0)

    # Map mode: clear screen before starting
    if args.map:
        print("\033[2J\033[H", end="", flush=True)

    # Start poller
    poller = MemoryPoller(ra, poll_hz=args.poll_hz,
                          dialog_messages=dialog_messages,
                          rom_data=rom_data,
                          diag=args.diag,
                          map_mode=args.map,
                          map_overlay=args.map_overlay)
    poller.start()

    if not args.map:
        _say("Connected.")

    try:
        if args.map:
            # Map mode: block on KeyboardInterrupt only (Ctrl+C to quit).
            # No command prompt — the terminal is used for the map display.
            while True:
                time.sleep(1)
        else:
            while True:
                try:
                    user_input = input().strip()
                except EOFError:
                    break

                if not user_input:
                    continue

                if user_input.lower() in ("quit", "/quit"):
                    break

                if handle_command(user_input, poller, ra):
                    continue

                _say(f"Unknown command: {user_input}. Type help for a list.")

    except KeyboardInterrupt:
        if args.map:
            print("\033[2J\033[H", end="", flush=True)
        _say("Interrupted.")
    finally:
        poller.stop()
        ra.close()
        _say("Goodbye.")


if __name__ == "__main__":
    main()
