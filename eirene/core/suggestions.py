"""Reject obvious assistant replies before they become user input drafts."""
from __future__ import annotations

import re

_ASSISTANT_VOICE = re.compile(
    r"^(?:would you like me to|do you want me to|let me\b|"
    r"how (?:can|may) i (?:help|assist)|"
    r"i(?:['’]m| am) (?:happy|here|ready) to (?:help|assist)|"
    r"i (?:can|will|would be happy to) (?:help|assist)|"
    r"i (?:need|require) (?:more |some |additional )?(?:details|information|context))"
    r"|\bso (?:that )?i can (?:help|assist|give you|provide you)\b"
    r"|\bwhich (?:specific )?(?:project|file|repository|codebase) "
    r"(?:you(?: are|['’]re)? )?(?:are )?referring to\b",
    re.IGNORECASE,
)


def is_assistant_reply(text: str) -> bool:
    """A narrow guard, not a semantic guarantee; ordinary user questions pass."""
    return bool(_ASSISTANT_VOICE.search(text))
