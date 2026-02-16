# ALttP Accessibility Bridge — Developer Guide

## Project Purpose
An accessibility bridge for **A Link to the Past** (ALttP) that polls the RetroArch emulator's memory via UDP, detects game events in real time, and produces screen-reader-friendly text output for blind and visually impaired players.

## Files
- **`bridge.py`** — Main bridge: memory polling, event detection, proximity/cone scanning, map rendering, CLI
- **`rom_reader.py`** — Parses the ALttP ROM for room geometry, sprites, doors, objects, tile attributes
- **`dump.json`** — Debug snapshot written by `--dump` flag or `dump` command at runtime

## ROM Location
`/home/rishi/.config/retroarch/downloads/Legend of Zelda, The - A Link to the Past (USA).sfc`

## Running
```bash
# Normal mode (screen-reader output)
python bridge.py --rom <path-to-rom>

# With ASCII map
python bridge.py --rom <path-to-rom> --map

# Single-shot debug dump
python bridge.py --rom <path-to-rom> --dump

# Map snapshot (renders once and exits)
python bridge.py --rom <path-to-rom> --map-snap
```

## Architecture Overview

### Communication
- `RetroArchClient` sends UDP commands to RetroArch on port 55355
- `READ_CORE_MEMORY <addr> <len>` reads SNES memory via the bsnes-mercury core
- Addresses use SNES A-bus notation: `$7E:xxxx` = WRAM, `$7F:xxxx` = extended WRAM

### Polling Loop (`MemoryPoller`)
1. Reads all `MEMORY_MAP` addresses + sprite table into a `GameState` snapshot
2. `EventDetector.detect(prev, curr)` compares two frames for events
3. `ProximityTracker.check(state)` scans for nearby objects and cone tiles
4. Events sorted by priority, printed via `_say()`
5. Sleeps `1/poll_hz` (default 30 Hz)

### Key Classes in bridge.py

| Class | Purpose |
|---|---|
| `GameState` | Snapshot of all watched memory values with helper properties |
| `EventDetector` | Frame-diff event detection (damage, room change, blocked, items, etc.) |
| `ProximityTracker` | Zone-based proximity announcements + forward cone scan |
| `ObjectTracker` | Frame-to-frame object tracking with EMA velocity for dynamic sprites |
| `TrackedObject` | Single tracked entity (static feature or dynamic sprite) |
| `MapRenderer` | ASCII map rendering in terminal |
| `RetroArchClient` | UDP client for RetroArch network command interface |
| `MemoryPoller` | Main polling loop orchestrating everything |

### Key Classes in rom_reader.py

| Class | Purpose |
|---|---|
| `RomData` | Top-level ROM data container with room/sprite lookup methods |
| `RoomData` | Parsed room: header, doors, objects, sprites |
| `RoomHeader` | Room metadata (tileset, floor, layout, etc.) |
| `RoomObject` | Dungeon object with tile position and category |
| `DoorObject` | Door with direction, position, type |
| `RoomSprite` | Sprite placement from ROM |

## SNES Memory Map (Key Addresses)

### Link State
| Address | Size | Field | Notes |
|---|---|---|---|
| `$7E:0020` | 2 | `link_y` | Absolute Y position (pixels) |
| `$7E:0022` | 2 | `link_x` | Absolute X position (pixels) |
| `$7E:002F` | 1 | `direction` | 0=N, 2=S, 4=W, 6=E |
| `$7E:005D` | 1 | `link_state` | Animation state (0=standing, 1=falling, etc.) |
| `$7E:00F0` | 1 | `joypad_dir` | Held joypad high byte: B Y Sl St **U D L R** in bits 7-0; `& 0x0F` extracts directions |

### Game Mode
| Address | Size | Field | Notes |
|---|---|---|---|
| `$7E:0010` | 1 | `main_module` | Current game module (0x07=Dungeon, 0x09=Overworld, 0x12=Death, etc.) |
| `$7E:0011` | 1 | `submodule` | Sub-state within module; 0=normal gameplay, non-zero=transition/animation |
| `$7E:001B` | 1 | `indoors` | 0=outdoors, 1=indoors |

### Location
| Address | Size | Field | Notes |
|---|---|---|---|
| `$7E:008A` | 2 | `ow_screen` | Overworld screen ID (can stay constant across "large areas") |
| `$7E:00A0` | 2 | `dungeon_room` | Current dungeon room ID |
| `$7E:007B` | 1 | `world` | 0=Light World, 1=Dark World |

### Tile Tables
| Address | Size | Purpose |
|---|---|---|
| `$7E:2000` | 8192 | Overworld map16 tile table (4096 entries × 2 bytes) |
| `$7F:2000` | 8192 | Dungeon tile attribute table (64×64 grid, 2 levels) |

### Scroll Offset Variables (for OW tile lookups)
| Address | Field | Purpose |
|---|---|---|
| `$7E:0708` | `ow_offset_base_y` | Y scroll base (pixels) |
| `$7E:070A` | `ow_offset_mask_y` | Y scroll mask |
| `$7E:070C` | `ow_offset_base_x` | X scroll base (tile units) |
| `$7E:070E` | `ow_offset_mask_x` | X scroll mask |

**OW tile offset formula:**
```python
t = ((py - base_y) & mask_y) * 8
t |= ((tx - base_x) & mask_x)
ow_off = t >> 1
# Read 2 bytes at $7E:2000 + ow_off * 2 → map16 index
```
Note: `py` is in pixel units, `tx` is in 8px tile units. This asymmetry is how ALttP's scroll engine works.

## Tile Identification System

### Three-Layer Lookup (Overworld)
1. **map16 index** — read from WRAM `$7E:2000` table (16×16 pixel tiles)
2. **Graphic-based name** — `RomData._MAP16_NAME` maps specific map16 indices to names (most reliable for overworld)
3. **Tile attribute** — map16 → map8 → tileattr chain via ROM tables → `TILE_TYPE_NAMES` (fallback)

### Why Graphic-Based ID Matters
Multiple distinct objects share the same tile attribute (e.g., attr `0x54` = liftable boulder, sign, AND pot). The map16 index uniquely identifies the visual graphic, so `_MAP16_NAME` provides reliable names.

### Dungeon Tiles
Read directly from `$7F:2000` attribute table. Indoor walls use a separate set of attribute values (`GameState._INDOOR_WALL_TILES`).

### Opened Chest Detection
Dungeon chests in ROM have a "chest" category. At runtime, `_get_features()` reads the live WRAM tile attribute — if it's `0x27` (hookshot target), the chest has been opened and is renamed "open chest."

## Proximity System

### Two-Ring Zone Model
- **Ring 2 (Approach):** `APPROACH_DIST = 96` px (~12 tiles) — "Approaching {name} to the {dir}."
- **Ring 1 (Nearby):** `NEARBY_DIST = 56` px (~7 tiles) — "Nearing {name} to the {dir}."
- **Facing:** Within Ring 1 AND Link faces the object — "Facing {name}."

### Zone State Machine
`None → "approach" → "nearby" → "facing"` with downgrades:
- Leave Ring 1 → downgrade from "nearby" to "approach"
- Leave Ring 2 → reset to None (re-entering will re-alert)

### What Gets Tracked
- **Dungeon features:** doors (from ROM + WRAM doorway scan), objects (chests, switches, blocks, torches, stairs, pits), non-enemy sprites
- **Overworld ROM sprites:** enemies, NPCs, hazards (whirlpools, etc.)
- **Overworld tile features:** sign, gravestone, liftable rock/boulder, dark rock, dashable rocks, cactus, liftable pot, chest (via `_get_ow_tile_features()` bulk WRAM read)
- **Dynamic sprites:** live WRAM sprite table (16 slots), tracked with EMA velocity

### What is NOT Tracked by Zones
- **Bushes** — removed from `_PROXIMITY_TILE_NAMES`; only reported by cone
- **Walls, water, ground** — environmental; only reported by cone

### Cone Scanner (`_scan_cone`)
- 45° cone ahead of Link, 8 tiles deep
- Reads ALL tiles, overlays tracked objects for more specific labels
- Bresenham line-of-sight occlusion (closer tiles block farther ones)
- Reports with pure cardinal directions (no diagonals), newline-separated
- Ignored tiles: `{"diggable ground", "hookshot target"}`
- Suppressed for 2 seconds after area change (`_AREA_CHANGE_COOLDOWN`)

## Blocked Movement Detection
- Fires when `joypad_dir & 0x0F` (direction held) AND position unchanged for 1+ polls
- `_identify_blocker()` finds what's blocking: checks tracked objects in facing/nearby zone first, then probes 1-3 tiles ahead using `_read_tile_name()`, skipping ignored tiles

## Event Detection (`EventDetector`)

Key events detected by frame comparison:
- `DEATH` — module → 0x12; prints game over menu options
- `DAMAGE_TAKEN` / `LOW_HEALTH` — HP decrease
- `ROOM_CHANGE` — dungeon room or overworld screen change
- `TRANSITION` — submodule goes 0→non-zero during gameplay (camera scroll); includes direction
- `DUNGEON_ENTER_EXIT` — module transitions between 0x07 and 0x09
- `WORLD_TRANSITION` — light/dark world change
- `BLOCKED` — directional input held but Link not moving
- `ITEM_ACQUIRED` — inventory slot goes from 0 to non-zero
- Dialog detection via `dialog_id` memory address

## Link's Body Centre
```python
_LINK_BODY_OFFSET_X = 8   # half of 16px sprite width
_LINK_BODY_OFFSET_Y = 8   # body centre, below the head
```
All distance calculations use body centre, not sprite origin.

## Map Renderer
- ASCII map of visible area (32×24 tiles = 256×192 px SNES screen)
- Link drawn as 2×2 character block (direction arrow), offset 1 tile west
- Overlay rings for approach/nearby zones
- Tile characters: `#`=wall, `~`=water, `.`=pit, `^`=stairs, `C`=chest, etc.
- Event ticker shown below map

## Common Pitfalls

### Joypad Address
`$7E:00F0` is a single byte containing `B Y Sl St U D L R`. Directions are in the **low nibble** (`& 0x0F`). Do NOT read from `$7E:00F1` (that's the low byte with A/X/L/R buttons, zeroes in low nibble). Despite the SNES convention of high/low bytes, ALttP stores the direction byte at `$F0`.

### Overworld Tile Offset Asymmetry
The WRAM offset formula uses **pixel** Y but **8px tile** X. This is not a bug — it matches ALttP's scroll engine.

### Dataclass ClassVar
When adding class-level constants (like `_MAP16_NAME`) to a `@dataclass`, use `ClassVar[dict[...]]` annotation. Otherwise Python treats it as a mutable default field and raises `ValueError`.

### Map16 Shared Attributes
Tile attribute `0x54` is shared by liftable boulder, sign, and pot on the overworld. Always prefer `ow_tile_name()` (graphic-based) over `ow_tile_attr()` for overworld identification.

### Opened Chests
Opened dungeon chests have tile attribute `0x27` (same as hookshot target). The bridge cross-references ROM chest data with live WRAM to distinguish them.

### Sprite Slot Reuse
When an enemy dies and drops an item, the same sprite slot gets reused with a different `type_id`. `ObjectTracker.update_sprites()` detects this and creates a fresh `TrackedObject`.

## Debugging
```bash
# Dump full state to JSON
python bridge.py --rom <rom> --dump

# Runtime dump command (type "dump" while bridge is running)
dump

# Diagnostic mode (shows distance/tile info with proximity events)
python bridge.py --rom <rom> --diag
```

The dump includes: raw memory values, interpreted state, live sprites, ROM data for current area, and area descriptions. Use it to diagnose misidentified tiles or missing detections.
