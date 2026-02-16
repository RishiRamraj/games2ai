"""CLI entry point for ALttP Accessibility Bridge."""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Optional

from alttp_assist.map_renderer import MapRenderer
from alttp_assist.poller import MemoryPoller, dump_state, handle_command, _say
from alttp_assist.retroarch import RetroArchClient, read_memory
from alttp_assist.rom.data import RomData
from alttp_assist.rom.parser import load_rom
from alttp_assist.text import load_text_dump


_ESC_WINDOW = 2.0


def _is_bare_escape() -> bool:
    """After reading ``\\x1b``, return True for a bare Escape press.

    Consumes any trailing bytes if the Escape was actually the start of an
    ANSI escape sequence (arrow keys, function keys, etc.).
    """
    import select

    if select.select([sys.stdin], [], [], 0.05)[0]:
        while select.select([sys.stdin], [], [], 0.01)[0]:
            sys.stdin.read(1)
        return False
    return True


def _map_loop():
    """Map-mode input loop.  Press Escape twice within 2 s to exit."""
    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    try:
        old = termios.tcgetattr(fd)
    except termios.error:
        while True:
            time.sleep(1)
        return

    try:
        tty.setcbreak(fd)
        esc_time = 0.0
        while True:
            rlist, _, _ = select.select([sys.stdin], [], [], 0.5)
            if not rlist:
                if esc_time and (time.monotonic() - esc_time) >= _ESC_WINDOW:
                    esc_time = 0.0
                continue

            ch = sys.stdin.read(1)
            if ch != '\x1b':
                continue
            if not _is_bare_escape():
                continue

            now = time.monotonic()
            if esc_time and (now - esc_time) < _ESC_WINDOW:
                return
            esc_time = now
            _say("Press Escape again to exit.")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _text_loop(poller: MemoryPoller, ra: RetroArchClient):
    """Text-mode input loop with cbreak.  Press Escape twice within 2 s to exit."""
    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    try:
        old = termios.tcgetattr(fd)
    except termios.error:
        _text_loop_basic(poller, ra)
        return

    try:
        tty.setcbreak(fd)
        esc_time = 0.0
        buf: list[str] = []

        while True:
            rlist, _, _ = select.select([sys.stdin], [], [], 0.5)
            if not rlist:
                if esc_time and (time.monotonic() - esc_time) >= _ESC_WINDOW:
                    esc_time = 0.0
                continue

            ch = sys.stdin.read(1)

            # --- Escape handling ---
            if ch == '\x1b':
                if not _is_bare_escape():
                    continue
                now = time.monotonic()
                if esc_time and (now - esc_time) < _ESC_WINDOW:
                    sys.stdout.write('\n')
                    sys.stdout.flush()
                    return
                esc_time = now
                _say("Press Escape again to exit.")
                continue

            # Any other key resets the escape timer
            esc_time = 0.0

            # --- Enter: submit command ---
            if ch in ('\r', '\n'):
                sys.stdout.write('\n')
                sys.stdout.flush()
                line = ''.join(buf).strip()
                buf.clear()
                if line:
                    if line.lower() in ("quit", "/quit"):
                        return
                    if not handle_command(line, poller, ra):
                        _say(f"Unknown command: {line}. Type help for a list.")
                continue

            # --- Backspace ---
            if ch in ('\x7f', '\x08'):
                if buf:
                    buf.pop()
                    sys.stdout.write('\b \b')
                    sys.stdout.flush()
                continue

            # --- Ctrl+D (EOF) ---
            if ch == '\x04':
                sys.stdout.write('\n')
                sys.stdout.flush()
                return

            # --- Printable character ---
            if ch >= ' ':
                buf.append(ch)
                sys.stdout.write(ch)
                sys.stdout.flush()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _text_loop_basic(poller: MemoryPoller, ra: RetroArchClient):
    """Fallback text-mode loop using ``input()`` when stdin is not a terminal."""
    while True:
        try:
            user_input = input().strip()
        except EOFError:
            break
        if not user_input:
            continue
        if user_input.lower() in ("quit", "/quit"):
            break
        if handle_command(user_input, poller, ra):
            continue
        _say(f"Unknown command: {user_input}. Type help for a list.")


def main():
    parser = argparse.ArgumentParser(
        description="ALttP Accessibility Bridge - screen-reader-friendly game events",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
A Link to the Past accessibility bridge that polls emulator memory,
detects game events, and provides screen-reader-friendly output.

Examples:
  alttp-navi --rom /path/to/rom.sfc
  alttp-navi --rom /path/to/rom.sfc --map
""",
    )
    parser.add_argument("--host", default="127.0.0.1",
                        help="RetroArch host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=55355,
                        help="RetroArch UDP port (default: 55355)")
    parser.add_argument("--poll-hz", type=float, default=30.0,
                        help="Memory poll rate in Hz (default: 30)")
    parser.add_argument("--rom", default=None,
                        help="Path to ALttP ROM file (.sfc) for geometric room descriptions")
    parser.add_argument("--text", default=None,
                        help="Path to ALttP text dump file (default: text.txt next to script)")
    parser.add_argument("--diag", action="store_true",
                        help="Diagnostic mode: show raw IDs and categories for all detected features")
    parser.add_argument("--dump", nargs="?", const="dump.json", default=None,
                        metavar="FILE",
                        help="Single-shot: read memory once, write state to FILE (default: dump.json), and exit")
    parser.add_argument("--map", action="store_true",
                        help="ASCII map mode: render a live tile map instead of text events")
    parser.add_argument("--map-overlay", action="store_true",
                        help="Show detection cone and radii around Link (requires --map)")
    parser.add_argument("--map-snap", action="store_true",
                        help="Single-shot: print one ASCII map frame with overlay and exit")
    args = parser.parse_args()

    # Load ROM data if provided
    rom_data: Optional[RomData] = None
    if args.rom:
        if args.diag:
            _say(f"Loading ROM: {args.rom}")
        rom_data = load_rom(args.rom, verbose=args.diag)
        if args.diag:
            if rom_data:
                _say("ROM data loaded. Room descriptions will use ROM geometry.")
            else:
                _say("Failed to load ROM. Falling back to static descriptions.")

    # Load dialog text: prefer ROM-extracted dialog, fall back to text dump
    dialog_messages: list[str] = []
    if rom_data and rom_data.dialog_strings:
        dialog_messages = rom_data.dialog_strings
    else:
        text_path = args.text or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "text.txt")
        dialog_messages = load_text_dump(text_path)

    # Connect to RetroArch
    ra = RetroArchClient(host=args.host, port=args.port)
    ra.connect()

    while True:
        version = ra.get_version()
        if version:
            break
        if not args.map:
            _say("Waiting for RetroArch.")
        try:
            time.sleep(5)
        except KeyboardInterrupt:
            ra.close()
            sys.exit(0)

    # Single-shot dump mode
    if args.dump:
        state = read_memory(ra, rom_data)
        if state.raw.get("main_module") is None:
            _say("Could not read game state. Is a game loaded?")
            ra.close()
            sys.exit(1)
        out = dump_state(state, args.dump)
        _say(f"State dumped to {out}.")
        ra.close()
        sys.exit(0)

    # Single-shot map snapshot
    if args.map_snap:
        state = read_memory(ra, rom_data)
        if state.raw.get("main_module") is None:
            _say("Could not read game state. Is a game loaded?")
            ra.close()
            sys.exit(1)
        renderer = MapRenderer(overlay=True)
        renderer.render(state, ra, rom_data, snapshot=True)
        print()
        ra.close()
        sys.exit(0)

    # Map mode: clear screen
    if args.map:
        print("\033[2J\033[H", end="", flush=True)

    # Start poller
    poller = MemoryPoller(ra, poll_hz=args.poll_hz,
                          dialog_messages=dialog_messages,
                          rom_data=rom_data,
                          diag=args.diag,
                          map_mode=args.map,
                          map_overlay=args.map_overlay)
    poller.start()

    if not args.map:
        _say("Connected! Hey, Listen!")

    try:
        if args.map:
            _map_loop()
            print("\033[2J\033[H", end="", flush=True)
        else:
            _text_loop(poller, ra)

    except KeyboardInterrupt:
        if args.map:
            print("\033[2J\033[H", end="", flush=True)
        _say("Interrupted.")
    finally:
        poller.stop()
        ra.close()
        _say("Goodbye.")
