"""Game state snapshot for ALttP bridge."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from alttp_assist.constants import (
    BOOLEAN_ITEMS,
    BOTTLE_NAMES,
    DIRECTION_NAMES,
    DUNGEON_DESCRIPTIONS,
    DUNGEON_ROOMS,
    ENEMY_DETECT_RADIUS,
    ENEMY_NAMES,
    INTERACT_RADIUS,
    OVERWORLD_DESCRIPTIONS,
    OVERWORLD_NAMES,
    TIERED_ITEMS,
    _direction_label,
)
from alttp_assist.rom.data import RomData, SpriteCategory, SPRITE_TYPE_NAMES
from alttp_assist.rom.tiles import TILE_TYPE_NAMES


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


@dataclass
class GameState:
    """Snapshot of all watched ALttP memory values."""
    raw: dict[str, Optional[int]] = field(default_factory=dict)
    sprites: list[Sprite] = field(default_factory=list)
    timestamp: float = 0.0
    rom_data: Optional[RomData] = field(default=None, repr=False)
    facing_tile: int = -1

    def get(self, key: str, default: int = 0) -> int:
        v = self.raw.get(key)
        return v if v is not None else default

    @property
    def hp_hearts(self) -> float:
        return self.get("hp") / 8.0

    @property
    def max_hp_hearts(self) -> float:
        return self.get("max_hp") / 8.0

    _INDOOR_WALL_TILES = {0x04, 0x0B, 0x6C, 0x6D, 0x6E, 0x6F}

    @property
    def facing_tile_name(self) -> Optional[str]:
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
        module = self.get("main_module")
        if module == 0x07:
            if self.rom_data:
                room_id = self.get("dungeon_room")
                room = self.rom_data.get_room(room_id)
                if room and (room.sprites or room.doors or
                             (room.header and room.header.tag1)):
                    return room.to_full()
            name = self.dungeon_name
            return DUNGEON_DESCRIPTIONS.get(name, "")
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
        if not self.is_on_overworld:
            return None
        x = self.get("link_x")
        y = self.get("link_y")
        col = (x >> 9) & 7
        row = (y >> 9) & 7
        screen = row * 8 + col
        if self.get("world"):
            screen += 0x40
        return screen

    def item_name(self, key: str) -> Optional[str]:
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
