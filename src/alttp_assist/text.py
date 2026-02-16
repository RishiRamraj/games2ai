"""Dialog text loading from text dump files."""

from __future__ import annotations

import re


_CONTROL_CODE_RE = re.compile(r'\*[0-9A-Za-z]+')
_GRAPHIC_RE = re.compile(r'\|[^|]*\|')


def _clean_dialog_text(raw: str) -> str:
    """Strip ALttP control codes for screen reader output."""
    lines: list[str] = []
    for line in raw.split('\n'):
        line = line.strip()
        if not line:
            continue
        # Remove *XX control codes and |graphic| insertions
        line = _CONTROL_CODE_RE.sub('', line)
        line = _GRAPHIC_RE.sub('', line)
        # Skip Hylian glyph-only lines
        if all(c in '\u2020\u00a7\u00bb ' for c in line):
            continue
        # Remove leading telepathy/fortune/menu prefix (single char C/B/A)
        if len(line) > 1 and line[0] in 'CBA' and line[1].isupper():
            line = line[1:]
        line = line.strip()
        if line:
            lines.append(line)
    return ' '.join(lines)


def load_text_dump(path: str) -> list[str]:
    """Parse a text dump file into an ordered list of dialog messages."""
    try:
        with open(path) as f:
            content = f.read()
    except FileNotFoundError:
        return []

    # Skip header -- actual text starts after "The Text Dump" heading
    marker = "The Text Dump"
    idx = content.find(marker)
    if idx >= 0:
        rest = content[idx:]
        nl = rest.find('\n\n')
        content = rest[nl:] if nl >= 0 else rest

    # Split on blank lines to separate individual messages
    raw_messages = re.split(r'\n\s*\n', content.strip())

    messages: list[str] = []
    for raw in raw_messages:
        cleaned = _clean_dialog_text(raw)
        if cleaned:
            messages.append(cleaned)
    return messages
