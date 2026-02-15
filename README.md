# ALttP Accessibility Bridge

A Link to the Past accessibility tool that polls RetroArch emulator memory, detects game events, and provides screen-reader-friendly output for blind and visually impaired players.

No external dependencies -- uses only the Python standard library.

## Prerequisites

**RetroArch** with the bsnes-mercury core:

```bash
sudo apt install retroarch libretro-bsnes-mercury-accuracy
```

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
python bridge.py

# Custom RetroArch port
python bridge.py --port 55356

# Custom text dump path
python bridge.py --text /path/to/text.txt

# Adjust poll rate
python bridge.py --poll-hz 8
```

## Commands

| Command    | Description                       |
|------------|-----------------------------------|
| `pos`      | Current position, room, direction |
| `health`   | Health, magic, resources          |
| `items`    | Equipment and inventory           |
| `enemies`  | Nearby enemies and directions     |
| `progress` | Pendants, crystals, progress      |
| `status`   | RetroArch connection status       |
| `help`     | List commands                     |
| `quit`     | Exit                              |

## Event System

The bridge polls ~50 memory addresses at ~4 Hz and detects game events by diffing consecutive states:

- Damage taken, low health warning, death
- Item, key, and equipment pickups
- Room and area changes (overworld and dungeon)
- Dungeon enter/exit, floor changes
- World transitions (light/dark)
- Enemy proximity alerts with compass direction
- Dialog text (read from a text dump file)
- Swimming, pit warnings, boss victories
- Progress milestones (pendants, crystals)

## Dialog Text

Place `text.txt` (an ALttP text dump) next to `bridge.py`. When the game displays dialog, the bridge looks up the message and speaks the text. Without the file, it falls back to announcing that text appeared.

## Troubleshooting

**No response from RetroArch**
- Ensure RetroArch is running with ALttP loaded (not just the menu)
- Verify `network_cmd_enable = "true"` in retroarch.cfg
- Check the port matches (`--port` flag vs retroarch.cfg)

**Memory reads return None**
- The core must support `READ_CORE_MEMORY` (bsnes-mercury does)
- Make sure a game is actively running (not paused in the RetroArch menu)
