"""/usage"""

from __future__ import annotations

from rich.text import Text

from ..core.usage import estimate_messages, human_count, human_duration
from ..ui import art
from ..ui.chat import Block
from . import register


@register("usage", "tokens used in this session")
async def run(app, args: str) -> None:
    stats = app.agent.usage
    body = Text()
    body.append(f"{art.icon('info')} session {app.session.id}\n", style="bold")
    rows = [
        ("input tokens", human_count(stats.input_tokens)),
        ("output tokens", human_count(stats.output_tokens)),
        ("total", human_count(stats.total)),
        ("turns", str(len(stats.turns))),
        ("context now", f"~{human_count(estimate_messages(app.session.messages))}"),
        ("open for", human_duration(stats.elapsed)),
    ]
    width = max(len(name) for name, _ in rows)
    for name, value in rows:
        body.append(f"  {name:<{width}}  ", style="dim")
        body.append(f"{value}\n")

    by_model = stats.by_model()
    if len(by_model) > 1 or (by_model and stats.turns):
        body.append("\n  by model\n", style="bold")
        for name, (got_in, got_out) in sorted(by_model.items()):
            body.append(f"  {name}  ", style="dim")
            body.append(f"{human_count(got_in)} in / {human_count(got_out)} out\n")
    if not stats.turns:
        body.append("\n  nothing sent yet\n", style="dim")
    else:
        cost = stats.estimated_cost(app.config.get("model_costs", {}))
        if cost is None:
            body.append("\n  cost unavailable (configure model_costs)\n", style="dim")
        else:
            body.append(f"\n  estimated cost  ${cost:.6f}\n", style="dim")
    await app.push(Block(body))
