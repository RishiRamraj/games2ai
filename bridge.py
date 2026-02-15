#!/usr/bin/env python3
"""
ALttP Accessibility Bridge
===========================
Dedicated A Link to the Past accessibility guide that polls emulator memory,
detects game events locally in Python, and calls Claude only when something
meaningful happens -- producing screen-reader-friendly narration for a
blind player.

Setup:
  1. In retroarch.cfg, set:
       network_cmd_enable = "true"
       network_cmd_port = "55355"
  2. pip install anthropic
  3. export ANTHROPIC_API_KEY=sk-ant-...
  4. Launch RetroArch with bsnes-mercury core and ALttP ROM
  5. python bridge.py
"""

import argparse
import json
import os
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

try:
    import anthropic
except ImportError:
    sys.exit("Missing dependency: pip install anthropic")


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
}


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


# ─── Game State ───────────────────────────────────────────────────────────────

@dataclass
class GameState:
    """Snapshot of all watched ALttP memory values."""
    raw: dict[str, Optional[int]] = field(default_factory=dict)
    timestamp: float = 0.0

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

    @property
    def direction_name(self) -> str:
        return DIRECTION_NAMES.get(self.get("direction"), "unknown")

    @property
    def location_name(self) -> str:
        module = self.get("main_module")
        if module == 0x07:
            room = self.get("dungeon_room")
            return f"Dungeon room {room:#06x}"
        screen = self.get("ow_screen")
        return OVERWORLD_NAMES.get(screen, f"Overworld {screen:#04x}")

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
            f"Keys: {self.get('keys')}",
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

    def to_summary_dict(self) -> dict:
        """Compact dict for Claude context."""
        return {
            "position": {
                "x": self.get("link_x"),
                "y": self.get("link_y"),
                "direction": self.direction_name,
            },
            "location": {
                "name": self.location_name,
                "world": self.world_name,
                "indoors": self.is_indoors,
                "ow_screen": self.get("ow_screen"),
                "dungeon_room": self.get("dungeon_room"),
                "floor": self.get("floor"),
            },
            "health": {
                "current": self.hp_hearts,
                "max": self.max_hp_hearts,
                "magic": self.get("magic"),
            },
            "resources": {
                "rupees": self.get("rupees"),
                "bombs": self.get("bombs"),
                "arrows": self.get("arrows"),
                "keys": self.get("keys"),
            },
            "equipment": {
                "sword": SWORD_NAMES.get(self.get("sword"), "unknown"),
                "shield": SHIELD_NAMES.get(self.get("shield"), "unknown"),
                "armor": ARMOR_NAMES.get(self.get("armor"), "unknown"),
                "gloves": GLOVE_NAMES.get(self.get("gloves"), "unknown"),
            },
            "game_mode": MODULE_NAMES.get(self.get("main_module"), "unknown"),
            "link_state": LINK_STATE_NAMES.get(self.get("link_state"), "unknown"),
            "progress": {
                "pendants": self.get("pendants"),
                "crystals": self.get("crystals"),
                "progress_indicator": self.get("progress"),
            },
        }


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


# All inventory keys that can be acquired (0 -> non-zero)
_INVENTORY_KEYS = (
    list(BOOLEAN_ITEMS.keys())
    + ["bow", "boomerang", "mushroom_powder", "flute_shovel", "mirror",
       "bottle_1", "bottle_2", "bottle_3", "bottle_4"]
)


class EventDetector:
    """Compares previous and current GameState to emit events."""

    def detect(self, prev: GameState, curr: GameState) -> list[Event]:
        events: list[Event] = []

        curr_mod = curr.get("main_module")
        prev_mod = prev.get("main_module")

        # Death
        if curr_mod == 0x12 and prev_mod != 0x12:
            events.append(Event("DEATH", EventPriority.HIGH, "You died!"))
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
            events.append(Event(
                "ROOM_CHANGE", EventPriority.MEDIUM,
                f"Entered dungeon room {room:#06x}. Floor: {curr.get('floor')}.",
                {"room": room},
            ))

        # Overworld screen change
        if (curr.get("ow_screen") != prev.get("ow_screen")
                and curr.is_on_overworld):
            screen = curr.get("ow_screen")
            area = OVERWORLD_NAMES.get(screen, f"area {screen:#04x}")
            events.append(Event(
                "ROOM_CHANGE", EventPriority.MEDIUM,
                f"Entered {area}.",
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
            events.append(Event(
                "DUNGEON_ENTER_EXIT", EventPriority.MEDIUM,
                "Entered a dungeon.",
                {"entered": True},
            ))
        elif prev_mod == 0x07 and curr_mod == 0x09:
            events.append(Event(
                "DUNGEON_ENTER_EXIT", EventPriority.MEDIUM,
                "Exited the dungeon to the overworld.",
                {"entered": False},
            ))

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

        # Key acquired
        if curr.get("keys") > prev.get("keys"):
            events.append(Event(
                "KEY_ACQUIRED", EventPriority.LOW,
                f"Got a key! Keys: {curr.get('keys')}.",
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

        return events


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


def read_memory(ra: RetroArchClient) -> GameState:
    """Read all ALttP memory addresses into a GameState."""
    raw: dict[str, Optional[int]] = {}
    for name, (addr, length) in MEMORY_MAP.items():
        data = ra.read_core_memory(addr, length)
        if data is not None:
            raw[name] = int.from_bytes(data, "little") if length <= 4 else int.from_bytes(data, "little")
        else:
            raw[name] = None
    return GameState(raw=raw, timestamp=time.time())


# ─── Claude Bridge ────────────────────────────────────────────────────────────

# Events that trigger Claude narration (others are local-only)
CLAUDE_EVENTS = {
    "ROOM_CHANGE",
    "WORLD_TRANSITION",
    "DUNGEON_ENTER_EXIT",
    "PROGRESS_MILESTONE",
    "BOSS_VICTORY",
}

SYSTEM_PROMPT = (
    "You are an accessibility guide for a blind player playing "
    "The Legend of Zelda: A Link to the Past on SNES.\n\n"
    "Your role:\n"
    "- Describe the game world spatially so the player can navigate.\n"
    "- When the player enters a new area, briefly describe what is there, "
    "what dangers to expect, and which directions lead somewhere.\n"
    "- Give concise, actionable guidance. No visual descriptions of colors "
    "or graphics -- focus on spatial layout, enemies, items, and navigation.\n"
    "- When the player asks a question, answer based on your knowledge of "
    "ALttP and the current game state provided.\n"
    "- Keep responses short (2-4 sentences typically). The player is using "
    "a screen reader so brevity matters.\n"
    "- Never use emojis. Plain text only.\n"
    "- You receive game state as JSON with position, location, health, "
    "inventory, and recent events. Use this to give context-aware guidance."
)


class ClaudeBridge:
    """Calls Claude for contextual narration on game events and player questions."""

    def __init__(self, model: str = "claude-sonnet-4-20250514",
                 max_tokens: int = 300):
        self.client = anthropic.Anthropic()
        self.model = model
        self.max_tokens = max_tokens
        self.conversation: list[dict] = []
        self.last_call_time: float = 0.0
        self.min_interval: float = 3.0
        self._lock = threading.Lock()

    def call(self, prompt: str, game_state: GameState,
             events: Optional[list[Event]] = None,
             prefix: str = "[Guide]") -> Optional[str]:
        """Call Claude with game context. Streams output to stdout.

        Thread-safe: only one call at a time via internal lock.
        """
        with self._lock:
            return self._call_locked(prompt, game_state, events, prefix)

    def _call_locked(self, prompt: str, game_state: GameState,
                     events: Optional[list[Event]],
                     prefix: str) -> Optional[str]:
        # Rate limit
        elapsed = time.time() - self.last_call_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)

        # Build context message
        context_parts = []
        if events:
            event_list = [{"kind": e.kind, "message": e.message} for e in events]
            context_parts.append(
                f"[Recent Events]\n{json.dumps(event_list, indent=2)}")
        context_parts.append(
            f"[Game State]\n{json.dumps(game_state.to_summary_dict(), indent=2)}")
        if prompt:
            context_parts.append(f"[Player]\n{prompt}")

        user_msg = {"role": "user", "content": "\n\n".join(context_parts)}
        self.conversation.append(user_msg)
        trimmed = self.conversation[-20:]

        full_response: list[str] = []
        print(f"\n{prefix} ", end="", flush=True)

        try:
            with self.client.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                system=SYSTEM_PROMPT,
                messages=trimmed,
            ) as stream:
                for text in stream.text_stream:
                    print(text, end="", flush=True)
                    full_response.append(text)
        except Exception as e:
            print(f"(Claude error: {e})", flush=True)
            self.last_call_time = time.time()
            return None

        response_text = "".join(full_response)
        print(flush=True)

        self.conversation.append({"role": "assistant", "content": response_text})
        self.last_call_time = time.time()
        return response_text


# ─── Memory Poller (Background Thread) ────────────────────────────────────────

class MemoryPoller:
    """Polls emulator memory at ~4 Hz, detects events, triggers output."""

    def __init__(self, ra: RetroArchClient, bridge: ClaudeBridge,
                 poll_hz: float = 4.0):
        self.ra = ra
        self.bridge = bridge
        self.poll_interval = 1.0 / poll_hz
        self.detector = EventDetector()
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

    def _poll_loop(self):
        prev_state: Optional[GameState] = None

        while self._running:
            try:
                new_state = read_memory(self.ra)

                # Skip if we didn't get valid data
                if new_state.raw.get("main_module") is None:
                    time.sleep(self.poll_interval)
                    continue

                with self._state_lock:
                    self._state = new_state

                # Initial report when gameplay first detected
                module = new_state.get("main_module")
                if not self._initial_report_done and module in (0x07, 0x09):
                    self._initial_report_done = True
                    print(f"\n[Info] Connected. {new_state.world_name}, "
                          f"{new_state.location_name}.")
                    print(f"[Info] {new_state.format_health()}. "
                          f"Facing {new_state.direction_name}.", flush=True)

                # Detect events
                if prev_state is not None:
                    events = self.detector.detect(prev_state, new_state)
                    if events:
                        self._handle_events(events, new_state)

                prev_state = new_state

            except Exception:
                pass  # Don't crash the polling thread

            time.sleep(self.poll_interval)

    def _handle_events(self, events: list[Event], state: GameState):
        """Route events to local output or Claude narration."""
        local_events: list[Event] = []
        claude_events: list[Event] = []

        for event in events:
            if event.kind in CLAUDE_EVENTS:
                claude_events.append(event)
            else:
                local_events.append(event)

        # Print local events immediately
        for event in local_events:
            if event.priority == EventPriority.HIGH:
                print(f"\n[Alert] {event.message}", flush=True)
            else:
                print(f"\n[Info] {event.message}", flush=True)

        # Batch Claude events into one narration call
        if claude_events:
            for event in claude_events:
                print(f"\n[Info] {event.message}", flush=True)
            self.bridge.call("", state, claude_events)


# ─── Slash Commands ───────────────────────────────────────────────────────────

def handle_slash_command(cmd: str, poller: MemoryPoller,
                         ra: RetroArchClient) -> bool:
    """Handle a slash command. Returns True if the command was recognized."""
    cmd = cmd.strip().lower()

    if cmd == "/pos":
        state = poller.get_state()
        if state:
            print(f"[Info] {state.format_position()}")
        else:
            print("[Info] No game state available yet.")
        return True

    if cmd == "/health":
        state = poller.get_state()
        if state:
            print(f"[Info] {state.format_resources()}")
        else:
            print("[Info] No game state available yet.")
        return True

    if cmd == "/items":
        state = poller.get_state()
        if state:
            print(f"[Info] {state.format_equipment()}")
            print(f"[Info] {state.format_inventory()}")
        else:
            print("[Info] No game state available yet.")
        return True

    if cmd == "/progress":
        state = poller.get_state()
        if state:
            print(f"[Info] {state.format_progress()}")
        else:
            print("[Info] No game state available yet.")
        return True

    if cmd == "/status":
        status = ra.get_status()
        version = ra.get_version()
        if status:
            print(f"[Info] RetroArch status: {status}")
        else:
            print("[Info] RetroArch: no response (not connected or game not running).")
        if version:
            print(f"[Info] RetroArch version: {version}")
        return True

    if cmd == "/help":
        print("[Info] Commands:")
        print("  /pos      - Current position, room, direction")
        print("  /health   - Health, magic, resources")
        print("  /items    - Equipment and inventory")
        print("  /progress - Pendants, crystals, progress")
        print("  /status   - RetroArch connection status")
        print("  /help     - This help message")
        print("  /quit     - Exit")
        print("  (Type anything else to ask the guide a question)")
        return True

    return False


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="ALttP Accessibility Bridge - Screen-reader-friendly game guide",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
A Link to the Past accessibility bridge that polls emulator memory,
detects game events, and provides screen-reader-friendly narration.

Examples:
  python bridge.py
  python bridge.py --port 55356
  python bridge.py --model claude-sonnet-4-20250514
""",
    )
    parser.add_argument("--host", default="127.0.0.1",
                        help="RetroArch host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=55355,
                        help="RetroArch UDP port (default: 55355)")
    parser.add_argument("--model", default="claude-sonnet-4-20250514",
                        help="Claude model to use")
    parser.add_argument("--poll-hz", type=float, default=4.0,
                        help="Memory poll rate in Hz (default: 4)")
    args = parser.parse_args()

    # Check API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[Error] Set ANTHROPIC_API_KEY environment variable first.")
        print("  export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    # Connect to RetroArch
    ra = RetroArchClient(host=args.host, port=args.port)
    ra.connect()

    print("[Info] Testing RetroArch connection...")
    version = ra.get_version()
    if version:
        print(f"[Info] RetroArch version: {version}")
    else:
        print("[Info] No response from RetroArch. Make sure:")
        print("  1. RetroArch is running with A Link to the Past loaded")
        print('  2. network_cmd_enable = "true" in retroarch.cfg')
        print("  Continuing anyway -- will poll until connected.")

    status = ra.get_status()
    if status:
        print(f"[Info] Status: {status}")

    # Start bridge and poller
    bridge = ClaudeBridge(model=args.model)
    poller = MemoryPoller(ra, bridge, poll_hz=args.poll_hz)
    poller.start()

    print("[Info] ALttP Accessibility Bridge started.")
    print("[Info] Type /help for commands, or ask the guide a question.")

    try:
        while True:
            try:
                user_input = input("[You] ").strip()
            except EOFError:
                break

            if not user_input:
                continue

            if user_input == "/quit":
                break

            if user_input.startswith("/"):
                if handle_slash_command(user_input, poller, ra):
                    continue
                print("[Info] Unknown command. Type /help for a list.")
                continue

            # Player question -- send to Claude with current game state
            state = poller.get_state()
            if state is None:
                state = GameState()
            bridge.call(user_input, state, prefix="[Guide]")

    except KeyboardInterrupt:
        print("\n[Info] Interrupted.")
    finally:
        poller.stop()
        ra.close()
        print("[Info] Goodbye.")


if __name__ == "__main__":
    main()
