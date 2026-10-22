"""Terminal-safe text shared by tool output and display paths."""
from __future__ import annotations

import re
import unicodedata

_SEQUENCES = re.compile(
    r"(?:\x1b\]|\x9d)[^\x07\x1b]*(?:\x07|\x1b\\|$)"
    r"|\x1b[PX^_].*?(?:\x1b\\|$)"
    r"|(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]"
    r"|\x1b[@-_]", re.DOTALL)


_TEXT_ICONS = {
    "⏸": "Ⅱ", "⏹": "■", "⚡": "↯", "⚠": "!", "⚙": "⌘",
    "☑": "≡", "☷": "≡", "↗": "→", "🌐": "ᯤ",
}


def terminal_icon(glyph: str) -> str:
    """Use ordinary text glyphs, without depending on terminal emoji fonts."""
    glyph = glyph.replace("\ufe0e", "").replace("\ufe0f", "")
    return "".join(_TEXT_ICONS.get(char, char) for char in glyph)


def safe_text(text: str, *, tabs: bool = True) -> str:
    """Strip terminal commands, binary controls, surrogates and bidi controls."""
    text = _SEQUENCES.sub("", str(text or ""))
    allowed = "\n\t" if tabs else "\n"
    return "".join(char for char in text if char in allowed or
                   unicodedata.category(char) not in {"Cc", "Cs"} and
                   char not in "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")
