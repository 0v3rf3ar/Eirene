"""/usage"""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text

from ..core.usage import estimate_messages, human_count, human_duration
from ..ui import art, theme
from ..ui.progress import progress_bar
from . import register


BAR_WIDTH = 24
MIN_INNER_WIDTH = 54


def _styles(app) -> dict[str, str]:
    """Return dashboard colours with enough contrast on the active surface."""
    accent = theme.accents(app.theme)
    if accent is None:
        return {
            "frame": "dim",
            "muted": "dim",
            "heading": "bold",
            "value": "bold",
        }
    return {
        "frame": accent.rule,
        "muted": accent.detail,
        "heading": f"bold {accent.marker}",
        "value": f"bold {accent.on_surface}",
    }


def _token_bar(input_tokens: int, output_tokens: int,
               width: int = BAR_WIDTH) -> tuple[Text, str]:
    """Return a compact visual split of input and output tokens."""
    total = input_tokens + output_tokens
    ratio = input_tokens / total if total else 0
    split = (f"{ratio:.0%} in · {output_tokens / total:.0%} out"
             if total else "0% in · 0% out")
    return progress_bar(ratio, width), split


def _content_width(session_id: str, model_rows: list[str]) -> int:
    longest = max(
        [cell_len(f"session {session_id}"), cell_len("  nothing sent yet"),
         cell_len(f"  {'input':<16}{human_count(0):>8}   "
                  f"{'output':<16}{human_count(0):>8}"),
         *(cell_len(row) for row in model_rows)],
        default=0,
    )
    return max(MIN_INNER_WIDTH, longest + 2)


def _append_rule(body: Text, width: int, styles: dict[str, str],
                 left: str = "├", right: str = "┤") -> None:
    body.append(f"{left}{'─' * width}{right}\n", style=styles["frame"])


def _append_box_line(body: Text, content: Text | str, width: int,
                     styles: dict[str, str], style: str = "") -> None:
    line = content if isinstance(content, Text) else Text(content, style=style)
    body.append("│ ", style=styles["frame"])
    body.append_text(line)
    body.append(" " * max(width - 2 - line.cell_len, 0))
    body.append(" │\n", style=styles["frame"])


@register("usage", "tokens used in this session")
async def run(app, args: str) -> None:
    stats = app.agent.usage
    by_model = stats.by_model()
    model_rows = [
        f"  {name}  {human_count(got_in)} in · {human_count(got_out)} out"
        for name, (got_in, got_out) in sorted(by_model.items())
    ]
    width = _content_width(str(app.session.id), model_rows)
    bar, split = _token_bar(stats.input_tokens, stats.output_tokens, width - 2)
    styles = _styles(app)
    body = Text()
    body.append(f"╭─ {art.icon('tokens')} usage ", style=styles["heading"])
    body.append("─" * max(width - 10, 1), style=styles["frame"])
    body.append("╮\n", style=styles["frame"])

    session = Text()
    session.append(f"{art.icon('info')} session ", style=styles["heading"])
    session.append(str(app.session.id), style=styles["value"])
    _append_box_line(body, session, width, styles)
    _append_rule(body, width, styles)

    body.append("│ ", style=styles["frame"])
    body.append("TOKENS", style=styles["heading"])
    body.append(" " * max(width - 8, 0))
    body.append(" │\n", style=styles["frame"])
    metric_rows = [
        (f"{art.icon('tokens')} input", human_count(stats.input_tokens),
         f"{art.icon('up')} output", human_count(stats.output_tokens)),
        ("total", human_count(stats.total), "turns", str(len(stats.turns))),
        ("context now", f"~{human_count(estimate_messages(app.session.messages))}",
         "open for", human_duration(stats.elapsed)),
    ]
    for left_name, left_value, right_name, right_value in metric_rows:
        line = Text("  ")
        line.append(f"{left_name:<16}", style=styles["muted"])
        line.append(f"{left_value:>8}", style=styles["value"])
        line.append("   ")
        line.append(f"{right_name:<16}", style=styles["muted"])
        line.append(f"{right_value:>8}", style=styles["value"])
        _append_box_line(body, line, width, styles)

    label = Text(split.center(width - 2), style=styles["muted"])
    _append_box_line(body, label, width, styles)
    _append_box_line(body, bar, width, styles)

    if model_rows:
        _append_rule(body, width, styles)
        body.append("│ ", style=styles["frame"])
        body.append("MODELS", style=styles["heading"])
        body.append(" " * max(width - 8, 0))
        body.append(" │\n", style=styles["frame"])
        for row in model_rows:
            _append_box_line(body, row, width, styles, styles["muted"])

    _append_rule(body, width, styles)
    if not stats.turns:
        empty = Text(f"{art.icon('clock')} nothing sent yet", style=styles["muted"])
        _append_box_line(body, empty, width, styles)
    else:
        cost = stats.estimated_cost(app.config.get("model_costs", {}))
        if cost is None:
            cost_line = Text("  cost unavailable ", style=styles["muted"])
            cost_line.append("(configure model_costs)",
                             style=f"italic {styles['muted']}")
        else:
            cost_line = Text("  estimated cost  ", style=styles["muted"])
            cost_line.append(f"${cost:.6f}", style=styles["value"])
        _append_box_line(body, cost_line, width, styles)
    body.append(f"╰{'─' * width}╯", style=styles["frame"])
    app.aside.show_content(body)
