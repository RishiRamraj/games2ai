"""Proximity tracking — zone-based announcements and cone scanning."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

from alttp_assist.constants import (
    DIRECTION_NAMES,
    _DUNG_TILEATTR_ADDR,
    _LINK_BODY_OFFSET_X,
    _LINK_BODY_OFFSET_Y,
    _OW_TILEATTR_ADDR,
    _direction_label,
)
from alttp_assist.game_state import GameState, Sprite
from alttp_assist.rom.data import RomData, RoomData, SpriteCategory, _dedup_sprites
from alttp_assist.rom.tiles import TILE_TYPE_NAMES

if TYPE_CHECKING:
    from alttp_assist.retroarch import RetroArchClient


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


class ProximityTracker:
    """Announces nearby room features as Link approaches them.

    Tracks two distance zones per feature (approach / nearby) and only
    announces when Link crosses a threshold boundary inward.  Resets
    tracking on room change.
    """

    APPROACH_DIST = 96   # ~12 tiles
    NEARBY_DIST = 56     # ~7 tiles

    # Exact door tile positions from zelda3 kDoorPositionToTilemapOffs tables.
    # Key: (direction, position), Value: (x_tile, y_tile) in the 64x64 room grid.
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

    _CONE_IGNORE_TILES = frozenset({"diggable ground", "hookshot target"})

    def __init__(self, ra: Optional[RetroArchClient] = None) -> None:
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
        from alttp_assist.events import Event, EventPriority

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
        from alttp_assist.events import Event, EventPriority

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

    def _scan_cone(self, state: GameState) -> str:
        """Scan tiles in a 45deg cone ahead of Link and describe all visible
        interactable tiles, with line-of-sight occlusion.

        Reports every unobscured interactable tile/object from closest to
        farthest.  A tile is obscured if any other solid tile in the cone
        lies on the Bresenham line between Link and that tile.
        """
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
        visible: list[tuple[str, str]] = []  # (name, side)

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

        *room_tx*, *room_ty* are in the 64x64 room grid.
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

    def _get_features(self, room: RoomData,
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
        # Dungeon objects use 8-px tile units (64x64 grid = 512x512 px room)
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

        Reads the 64x64 tile attribute table at $7F:2000 and finds tiles
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
