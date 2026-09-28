"""Shared thin-line bars with balanced margins."""
from rich.text import Text


def progress_bar(progress: float, width: int, margin: int = 3) -> Text:
    width = max(1, width)
    margin = min(max(0, margin), (width - 1) // 2)
    progress = min(1.0, max(0.0, progress))
    bar_width = width - margin * 2
    filled = int(bar_width * progress)
    tip = 0 < progress < 1 and filled < bar_width
    body = Text(" " * margin, no_wrap=True, overflow="crop")
    body.append("━" * filled, style="#dbe7f3")
    if tip:
        body.append("╸", style="#92a9c0")
    body.append("━" * (bar_width - filled - tip), style="#303844")
    body.append(" " * margin)
    return body
