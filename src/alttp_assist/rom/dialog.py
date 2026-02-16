"""ALttP dialog text decoding from ROM.

Decodes the custom compression scheme used in the US ROM:
  - 95-char alphabet, 97-entry dictionary, and command bytes.
  - Text starts at SNES $9C:8000, bank-switches to $8E:DF40.
"""

from __future__ import annotations


_DIALOG_ALPHABET = [
    # 0-25: A-Z
    "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M",
    "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z",
    # 26-51: a-z
    "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
    "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z",
    # 52-61: 0-9
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
    # 62-66: punctuation
    "!", "?", "-", ".", ",",
    # 67-70: special punctuation
    "...", ">", "(", ")",
    # 71-75: graphic tiles (empty for accessibility)
    "", "", "", "", "",
    # 76: double quote
    "\"",
    # 77-80: direction arrows (empty for accessibility)
    "", "", "", "",
    # 81: apostrophe
    "'",
    # 82-88: heart graphics (empty for accessibility)
    "", "", "", "", "", "", "",
    # 89: space
    " ",
    # 90: less-than
    "<",
    # 91-94: button icons (empty for accessibility)
    "", "", "", "",
]

_DIALOG_DICTIONARY = [
    "    ", "   ", "  ", "'s ", "and ",
    "are ", "all ", "ain", "and", "at ",
    "ast", "an", "at", "ble", "ba",
    "be", "bo", "can ", "che", "com",
    "ck", "des", "di", "do", "en ",
    "er ", "ear", "ent", "ed ", "en",
    "er", "ev", "for", "fro", "give ",
    "get", "go", "have", "has", "her",
    "hi", "ha", "ight ", "ing ", "in",
    "is", "it", "just", "know", "ly ",
    "la", "lo", "man", "ma", "me",
    "mu", "n't ", "non", "not", "open",
    "ound", "out ", "of", "on", "or",
    "per", "ple", "pow", "pro", "re ",
    "re", "some", "se", "sh", "so",
    "st", "ter ", "thin", "ter", "tha",
    "the", "thi", "to", "tr", "up",
    "ver", "with", "wa", "we", "wh",
    "wi", "you", "Her", "Tha", "The",
    "Thi", "You",
]

# Command byte lengths: 1 = standalone, 2 = followed by a parameter byte.
# Covers bytes 0x67-0x7F (25 entries). Index 24 (0x7F) is EndMessage.
_DIALOG_CMD_LENGTHS = [
    1, 1, 1, 1, 2, 2, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1,
    2, 2, 2, 2, 1, 1, 1, 1, 1,
]

_DIALOG_CMD_NAMES = [
    "NextPic", "Choose", "Item", "Name", "Window", "Number",
    "Position", "ScrollSpd", "Selchg", "Unused_Crash", "Choose3",
    "Choose2", "Scroll", "1", "2", "3", "Color",
    "Wait", "Sound", "Speed", "Unused_Mark", "Unused_Mark2",
    "Unused_Clear", "Waitkey",
]

# SNES addresses for the two dialog text banks (US ROM).
_DIALOG_ROM_ADDRS = [0x9C8000, 0x8EDF40]


def _snes_to_rom(snes_addr: int) -> int:
    """Convert a SNES LoROM address to a file offset (headerless)."""
    bank = (snes_addr >> 16) & 0x7F
    offset = snes_addr & 0xFFFF
    return (bank * 0x8000) + (offset - 0x8000)


def parse_dialog_strings(rom: bytes, offset: int) -> list[str]:
    """Decode all dialog strings from the ROM.

    Returns an ordered list where index N is dialog message N (matching
    the dialog_id read from WRAM $012C at runtime).
    """
    addr_idx = 0
    pos = _snes_to_rom(_DIALOG_ROM_ADDRS[addr_idx]) + offset

    messages: list[str] = []
    current: list[str] = []

    while pos < len(rom):
        b = rom[pos]
        pos += 1

        if b == 0xFF:
            # Finish — end of all dialog data
            if current:
                text = " ".join("".join(current).split()).strip()
                messages.append(text)
            break

        if b == 0x7F:
            # EndMessage — save current message
            text = " ".join("".join(current).split()).strip()
            messages.append(text)
            current = []
            continue

        if b == 0x80:
            # Switch to next ROM bank
            addr_idx += 1
            if addr_idx < len(_DIALOG_ROM_ADDRS):
                pos = _snes_to_rom(_DIALOG_ROM_ADDRS[addr_idx]) + offset
            else:
                break
            continue

        if b <= 0x5E:
            # Alphabet character lookup
            current.append(_DIALOG_ALPHABET[b])
            continue

        if 0x67 <= b <= 0x7E:
            # Command byte
            cmd_idx = b - 0x67
            cmd_len = _DIALOG_CMD_LENGTHS[cmd_idx]

            # Accessibility substitutions
            if cmd_idx < len(_DIALOG_CMD_NAMES):
                name = _DIALOG_CMD_NAMES[cmd_idx]
                if name == "Name":
                    current.append("Link")
                elif name in ("1", "2", "3", "Scroll"):
                    current.append(" ")

            # Skip parameter byte if command is 2 bytes
            if cmd_len == 2 and pos < len(rom):
                pos += 1
            continue

        if b >= 0x88:
            # Dictionary lookup
            dict_idx = b - 0x88
            if dict_idx < len(_DIALOG_DICTIONARY):
                current.append(_DIALOG_DICTIONARY[dict_idx])
            continue

        # Bytes 0x5F-0x66 and 0x81-0x87 are unused; skip.

    return messages
