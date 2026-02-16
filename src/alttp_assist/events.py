from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Optional

from alttp_assist.constants import (
    BOOLEAN_ITEMS,
    DIRECTION_NAMES,
    DUNGEON_DESCRIPTIONS,
    GAMEPLAY_MODULES,
    ITEM_DROP_IDS,
    OVERWORLD_NAMES,
    TIERED_ITEMS,
    _LINK_BODY_OFFSET_X,
    _LINK_BODY_OFFSET_Y,
    _direction_label,
)
from alttp_assist.game_state import GameState
from alttp_assist.rom.data import RomData

if TYPE_CHECKING:
    from alttp_assist.proximity import ProximityTracker


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
                 proximity: Optional[ProximityTracker] = None):
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

        # Overworld screen change -- use coordinate-derived screen so
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

        # Item acquired (slot 0 -> non-zero; skip if either read was None)
        for key in _INVENTORY_KEYS:
            if (prev.raw.get(key) == 0 and curr.raw.get(key) is not None
                    and curr.raw.get(key) != 0):
                name = curr.item_name(key)
                if name:
                    events.append(Event(
                        "ITEM_ACQUIRED", EventPriority.MEDIUM,
                        f"Acquired: {name}!",
                        {"item": key, "name": name},
                    ))

        # Equipment upgrade (skip if either read was None)
        for key in ("sword", "shield", "armor", "gloves"):
            if (prev.raw.get(key) is not None and curr.raw.get(key) is not None
                    and curr.get(key) > prev.get(key)):
                name = TIERED_ITEMS[key].get(curr.get(key), "unknown")
                events.append(Event(
                    "EQUIPMENT_UPGRADE", EventPriority.MEDIUM,
                    f"Equipment upgrade: {name}!",
                    {"item": key, "name": name},
                ))

        # Key acquired (0xFF = uninitialised / outside dungeon, not a real count)
        curr_keys = curr.get("keys")
        prev_keys = prev.get("keys")
        if (curr.raw.get("keys") is not None and prev.raw.get("keys") is not None
                and curr_keys != 0xFF and prev_keys != 0xFF
                and curr_keys > prev_keys):
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
            # Import ProximityTracker locally to avoid circular import
            # at module level.
            from alttp_assist.proximity import ProximityTracker
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
