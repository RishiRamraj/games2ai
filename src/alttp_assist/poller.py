"""Memory polling loop, state dump, and command handling."""

from __future__ import annotations

import json
import threading
import time
from typing import Optional

from alttp_assist.constants import (
    LINK_STATE_NAMES,
    MEMORY_MAP,
    MODULE_NAMES,
    _direction_label,
)
from alttp_assist.events import Event, EventDetector, _EVENT_SORT_KEY
from alttp_assist.game_state import GameState
from alttp_assist.map_renderer import MapRenderer
from alttp_assist.proximity import ProximityTracker
from alttp_assist.retroarch import RetroArchClient, read_memory
from alttp_assist.rom.data import RomData


def _say(text: str) -> None:
    """Print a single line of output suitable for a screen reader."""
    print(text, flush=True)


class MemoryPoller:
    """Polls emulator memory at ~30 Hz, detects events, prints output."""

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
        map_interval = 0.25
        last_map_render = 0.0

        while self._running:
            try:
                new_state = read_memory(self.ra, self.rom_data)

                if new_state.raw.get("main_module") is None:
                    time.sleep(self.poll_interval)
                    continue

                with self._state_lock:
                    self._state = new_state

                module = new_state.get("main_module")
                if not self._initial_report_done and module in (0x07, 0x09):
                    self._initial_report_done = True

                all_events: list[Event] = []
                if prev_state is not None:
                    all_events.extend(self.detector.detect(prev_state, new_state))
                all_events.extend(self.proximity.check(new_state))

                all_events.sort(key=lambda e: _EVENT_SORT_KEY.get(e.kind, 2))

                if self.map_mode and self._map_renderer:
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
                pass

            time.sleep(self.poll_interval)


def dump_state(state: GameState, path: str = "dump.json") -> str:
    """Write a comprehensive state snapshot to a JSON file for debugging."""
    data: dict = {}

    data["raw_memory"] = {k: (f"0x{v:X}" if v is not None else None)
                          for k, v in state.raw.items()}

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

    data["nearby_enemies"] = state.nearby_enemies()

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

    data["area_description"] = state.area_description
    data["area_brief"] = state.area_brief

    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    return path


_NO_STATE = "No game state available yet."

COMMANDS: dict[str, str] = {
    "pos":      "Current position, room, and direction",
    "look":     "Description of the current area",
    "health":   "Health, magic, and resources",
    "items":    "Equipment and inventory",
    "enemies":  "Nearby enemies and directions",
    "heal":     "Restore one heart of health",
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
                for line in desc.split("\n"):
                    if line.strip():
                        _say(line.strip())
            else:
                _say("No description available for this area.")
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

    if cmd == "heal":
        state = poller.get_state()
        if not state:
            _say(_NO_STATE)
        else:
            hp = state.get("hp")
            max_hp = state.get("max_hp")
            if hp >= max_hp:
                _say("Already at full health.")
            else:
                new_hp = min(hp + 8, max_hp)
                addr = MEMORY_MAP["hp"][0]
                ra.write_core_memory(addr, bytes([new_hp]))
                hearts = new_hp / 8.0
                label = f"{int(hearts)}" if hearts == int(hearts) else f"{hearts:.1f}"
                _say(f"Healed to {label}/{int(max_hp / 8)} hearts.")
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
