# ALttP Accessibility Bridge

A Link to the Past accessibility guide that polls emulator memory, detects game events locally, and calls Claude only when something meaningful happens -- producing screen-reader-friendly narration for a blind player.

## Architecture

```
┌─────────────┐  UDP :55355   ┌──────────────────────────────────────────┐
│  RetroArch  │◄─────────────►│              bridge.py                   │
│  (bsnes)    │ READ_CORE_MEM │                                          │
└─────────────┘               │  ┌────────────┐    ┌─────────────────┐  │
                              │  │ MemoryPoller│───►│  EventDetector  │  │
                              │  │  (~4 Hz)    │    │  (diff states)  │  │
                              │  └────────────┘    └────────┬────────┘  │
                              │                             │ events    │
                              │  ┌──────────┐    ┌──────────▼────────┐  │
                              │  │  Input    │───►│   ClaudeBridge    │  │
                              │  │  (stdin)  │    │ (called on events │  │
                              │  └──────────┘    │  + user questions) │  │
                              │                  └──────────┬────────┘  │
                              │                             │           │
                              │                    stdout (plain text)  │
                              └──────────────────────────────────────────┘
```

## Prerequisites

**System packages** (Ubuntu/Debian):

```bash
sudo apt install retroarch libretro-bsnes-mercury-accuracy
```

**Python packages:**

```bash
pip install -r requirements.txt
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
export ANTHROPIC_API_KEY=sk-ant-...

# Start the bridge (RetroArch must be running with ALttP loaded)
python bridge.py

# Custom RetroArch port
python bridge.py --port 55356

# Different Claude model
python bridge.py --model claude-sonnet-4-20250514

# Adjust poll rate
python bridge.py --poll-hz 8
```

## Commands

| Command     | Description                         |
|-------------|-------------------------------------|
| `/pos`      | Current position, room, direction   |
| `/health`   | Health, magic, resources            |
| `/items`    | Equipment and inventory             |
| `/progress` | Pendants, crystals, progress        |
| `/status`   | RetroArch connection status         |
| `/help`     | List commands                       |
| `/quit`     | Exit                                |

Type anything else to ask the guide a question (calls Claude).

## Event System

The bridge polls ~50 memory addresses at ~4 Hz and detects game events by diffing consecutive states. Events fall into two categories:

### Local-only (instant, no API call)

Printed immediately with `[Info]` or `[Alert]` prefix:

- **Damage taken** -- shows exact health remaining
- **Low health warning** -- triggered at 2 hearts or below
- **Death**
- **Item/key pickup** -- with item name
- **Health restored**
- **Near pit warning**
- **Swimming state changes**
- **Entered/exited building**

### Claude narration (API call)

Printed with `[Guide]` prefix after streaming from Claude:

- **Room/area change** -- Claude describes the new area contextually
- **Dungeon enter/exit** -- Claude gives orientation
- **World transition** -- light/dark world change
- **Progress milestones** -- pendants, crystals
- **Boss victory**
- **Player questions** -- anything typed without a `/` prefix

## Output Format

```
[Info] Connected. Light World, Kakariko Village.
[Info] 3/5 hearts. Facing north.
[Guide] You entered Eastern Palace. Head north through the main hall. Watch for enemies.
[Alert] Damage taken! Health: 2/5 hearts.
[Alert] Low health! Only 1/5 hearts remaining.
[Info] Acquired: Bow!
[Guide] You picked up the Bow. You can now shoot arrows with the Y button.
[You] where should I go next?
[Guide] Head east. There is a locked door -- you have 1 key.
```

- `[Info]` -- local event descriptions (no Claude call)
- `[Alert]` -- urgent local events (no Claude call)
- `[Guide]` -- Claude narration (API call)
- `[You]` -- player input prompt

No emojis. Plain text only. Designed for screen readers.

## How It Works

1. A background thread polls RetroArch via UDP `READ_CORE_MEMORY` commands at ~4 Hz, reading ~50 ALttP memory addresses covering position, health, inventory, equipment, game mode, and progress.

2. Each poll cycle, the `EventDetector` compares the new state against the previous state and emits typed events (damage, room change, item pickup, etc.).

3. Local events print instantly. Events that benefit from context (room changes, milestones) are batched and sent to Claude with the current game state as JSON.

4. Claude's system prompt is tuned for spatial narration and accessibility -- no visual descriptions, just layout, threats, and navigation guidance.

5. The main thread handles player input: slash commands are answered locally from the current `GameState`, and freeform questions are sent to Claude.

## Troubleshooting

**"No response from RetroArch"**
- Ensure RetroArch is running with ALttP loaded (not just the menu)
- Verify `network_cmd_enable = "true"` in retroarch.cfg
- Check the port matches (`--port` flag vs retroarch.cfg)

**Memory reads return None**
- The core must support `READ_CORE_MEMORY` (bsnes-mercury does)
- Make sure a game is actively running (not paused in the RetroArch menu)

**"Set ANTHROPIC_API_KEY"**
- Export your API key: `export ANTHROPIC_API_KEY=sk-ant-...`
