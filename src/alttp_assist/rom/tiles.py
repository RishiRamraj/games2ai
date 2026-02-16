"""Tile attribute system for ALttP.

Maps tile attribute bytes to human-readable names.  Provides graphic-based
map16 identification for overworld tiles (more reliable than attribute-only
lookup since multiple objects share the same tile attribute byte).
"""

from __future__ import annotations

from typing import ClassVar, Optional


# From zelda3 tile_detect.c — maps the tile attribute byte to a human name.
# Only interesting/interactable tile types are listed; unlisted = passable ground.
TILE_TYPE_NAMES: dict[int, str] = {
    0x01: "wall", 0x02: "wall", 0x03: "wall",
    0x04: "thick grass",  # indoor: wall (handled in game_state.py)
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
    0x54: "liftable boulder", 0x55: "liftable boulder", 0x56: "liftable boulder",
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


# Map16 index -> human name, keyed by the graphic tiles drawn.
# Many visually distinct objects share the same tile attribute byte
# (e.g. signs, pots, and skulls all use "liftable" attrs 0x54-0x56).
# This table lets the accessibility layer report what the player sees.
MAP16_NAME: dict[int, str] = {
    0x0036: "bush",
    0x0064: "gravestone", 0x006F: "gravestone",
    0x0190: "gravestone", 0x019A: "gravestone",
    0x01A0: "gravestone", 0x038F: "gravestone",
    0x0101: "sign",
    0x020F: "liftable rock",
    0x0239: "liftable rock",
    0x023B: "dark rock", 0x023C: "dark rock",
    0x023D: "dark rock", 0x023E: "dark rock",
    0x0226: "dashable rocks", 0x0227: "dashable rocks",
    0x0228: "dashable rocks", 0x0229: "dashable rocks",
    0x036D: "liftable pot", 0x036E: "liftable pot",
    0x0374: "liftable pot", 0x0375: "liftable pot",
}
