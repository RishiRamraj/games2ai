# ALttP Accessibility Navigator

A Link to the Past accessibility tool that polls RetroArch emulator memory, detects game events, and provides screen-reader-friendly output for blind and visually impaired players.

No external dependencies -- uses only the Python standard library.

## Installation

```bash
# Install from source (editable/dev mode)
pip install -e .

# Or install normally
pip install .
```

This creates the `alttp-navi` command. You can also run via `python -m alttp_assist`.

## Prerequisites

**RetroArch** with the bsnes-mercury core:

```bash
sudo apt install retroarch libretro-bsnes-mercury-accuracy
```

**ALttP ROM** — a US version `.sfc` file (1 MB, headerless or with 512-byte SMC header).

## RetroArch Configuration

Edit `~/.config/retroarch/retroarch.cfg` and ensure:

```ini
network_cmd_enable = "true"
network_cmd_port = "55355"
```

Or toggle it in the RetroArch UI: **Settings > Network > Network Commands > ON**

## Usage

```bash
# Start the bridge (RetroArch must be running with ALttP loaded)
alttp-navi --rom /path/to/rom.sfc

# With live ASCII map overlay
alttp-navi --rom /path/to/rom.sfc --map

# Map with proximity proximity overlays
alttp-navi --rom /path/to/rom.sfc --map --map-overlay

# Single-shot map snapshot (renders once and exits)
alttp-navi --rom /path/to/rom.sfc --map-snap

# Debug state dump (writes dump.json and exits)
alttp-navi --rom /path/to/rom.sfc --dump

# Diagnostic mode (shows distance/tile data with proximity events)
alttp-navi --rom /path/to/rom.sfc --diag

# Custom RetroArch port or poll rate
alttp-navi --rom /path/to/rom.sfc --port 55356 --poll-hz 15
```

## Commands

Type these while the bridge is running:

| Command    | Description                            |
|------------|----------------------------------------|
| `pos`      | Current position, room, direction      |
| `look`     | Description of the current area        |
| `scan`     | List all nearby objects with distances  |
| `health`   | Health, magic, resources               |
| `items`    | Equipment and inventory                |
| `enemies`  | Nearby enemies and directions          |
| `progress` | Pendants, crystals, progress           |
| `dump`     | Write full state snapshot to dump.json |
| `status`   | RetroArch connection status            |
| `help`     | List commands                          |
| `quit`     | Exit                                   |

## Spatial Awareness

The bridge provides three layers of spatial information:

### Proximity Zones

Two concentric rings around Link announce objects as he approaches:

- **Ring 2 (~12 tiles)** — "Approaching chest to the north."
- **Ring 1 (~7 tiles)** — "Nearing chest to the north."
- **Facing** — "Facing chest." (within Ring 1 and looking at the object)

Tracked objects: doors, chests, switches, pushable blocks, torches, stairs, pits, signs, gravestones, rocks, pots, enemies, NPCs, and other interactable features.

### Forward Cone

A 45-degree cone scan ahead of Link reports all visible interactable tiles (walls, bushes, water, ledges, etc.) with line-of-sight occlusion. Objects behind closer obstacles are hidden. Reports use cardinal directions.

### Blocked Detection

When Link walks into an obstacle, the bridge identifies what's blocking him: "Blocked by bush." / "Blocked by wall."

## Event Detection

The bridge polls ~50 memory addresses at 30 Hz and detects game events by comparing consecutive frames:

- Damage taken, low health warning, death (with game over menu options)
- Camera transitions with direction
- Item, key, and equipment pickups
- Room and area changes with area descriptions
- Dungeon enter/exit with dungeon descriptions, floor changes
- World transitions (light/dark)
- Enemy proximity alerts with compass direction
- Dialog text (read from a text dump file)
- Swimming, pit warnings, boss victories
- Progress milestones (pendants, crystals)

## Object Tracking

Dynamic sprites (enemies, NPCs, projectiles) are tracked frame-to-frame with velocity computation. The tracker detects sprite slot reuse (e.g., enemy dies and drops an item) and resets tracking for the new entity.

## Area Descriptions

When moving between overworld screens or entering dungeons, the bridge announces the area name along with a description covering exits, hazards, landmarks, and key information. Use the `look` command at any time to hear the description of your current area. All 13 dungeons (Hyrule Castle through Ganon's Tower) are identified by room ID and described with boss names, required items, and key mechanics.

## Dialog Text

Place `text.txt` (an ALttP text dump) next to the package's `cli.py`, or pass `--text /path/to/text.txt`. When the game displays dialog, the bridge looks up the message and speaks the text. Without the file, it falls back to announcing that text appeared.

## ASCII Map

The `--map` flag renders a live ASCII map in the terminal showing the area around Link. Tile types are represented as characters (`#` = wall, `~` = water, `.` = pit, `C` = chest, etc.). Link is shown as a directional arrow. Use `--map-overlay` to visualize proximity rings and the forward cone.

## Troubleshooting

**No response from RetroArch**
- Ensure RetroArch is running with ALttP loaded (not just the menu)
- Verify `network_cmd_enable = "true"` in retroarch.cfg
- Check the port matches (`--port` flag vs retroarch.cfg)

**Memory reads return None**
- The core must support `READ_CORE_MEMORY` (bsnes-mercury does)
- Make sure a game is actively running (not paused in the RetroArch menu)

**No ROM data (missing room/sprite info)**
- Pass `--rom /path/to/rom.sfc` so the bridge can parse room layouts and sprite placements from the ROM
