"""Durable project-scoped structured plans."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import paths
from .errors import ToolError

STATUSES = {"pending", "in_progress", "completed", "blocked"}
MAX_STEPS = 100


@dataclass
class Step:
    text: str
    status: str = "pending"
    verification: str = ""


@dataclass
class Plan:
    root: str
    objective: str = ""
    steps: list[Step] = field(default_factory=list)
    notes: str = ""
    updated: float = field(default_factory=time.time)

    @property
    def active(self) -> bool:
        return bool(self.objective or self.steps)

    def render(self) -> str:
        if not self.active:
            return "no active plan"
        rows = [f"Objective: {self.objective or '(not set)'}"]
        icons = {"pending": "[ ]", "in_progress": "[>]",
                 "completed": "[x]", "blocked": "[!]"}
        for index, step in enumerate(self.steps, 1):
            row = f"{index}. {icons[step.status]} {step.text}"
            if step.verification:
                row += f" — verify: {step.verification}"
            rows.append(row)
        if self.notes:
            rows.append(f"Notes: {self.notes}")
        return "\n".join(rows)


def load(root: Path) -> Plan:
    root = root.resolve()
    path = _path(root)
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
        return Plan(str(root), str(body.get("objective") or ""),
                    [_step(item) for item in body.get("steps", [])],
                    str(body.get("notes") or ""), float(body.get("updated") or 0))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return Plan(str(root))


def update(root: Path, objective: str, raw_steps: list[dict[str, Any]],
           notes: str = "") -> str:
    if len(raw_steps) > MAX_STEPS:
        raise ToolError(f"a plan may have at most {MAX_STEPS} steps")
    steps = [_step(item) for item in raw_steps]
    in_progress = sum(step.status == "in_progress" for step in steps)
    if in_progress > 1:
        raise ToolError("only one plan step may be in progress")
    plan = Plan(str(root.resolve()), " ".join(objective.split()), steps,
                notes.strip(), time.time())
    if not plan.objective and not plan.steps:
        raise ToolError("plan needs an objective or at least one step")
    _save(root, plan)
    return plan.render()


def set_status(root: Path, index: int, status: str) -> str:
    plan = load(root)
    if not plan.active:
        raise ToolError("no active plan")
    if status not in STATUSES:
        raise ToolError(f"invalid plan status '{status}'")
    if index < 1 or index > len(plan.steps):
        raise ToolError(f"plan step {index} does not exist")
    if status == "in_progress":
        for step in plan.steps:
            if step.status == "in_progress":
                step.status = "pending"
    plan.steps[index - 1].status = status
    plan.updated = time.time()
    _save(root, plan)
    return plan.render()


def clear(root: Path) -> str:
    try:
        _path(root.resolve()).unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise ToolError(f"cannot clear plan: {exc}") from exc
    return "plan cleared"


def _step(raw: Any) -> Step:
    if not isinstance(raw, dict):
        raise ToolError("each plan step must be an object")
    text = " ".join(str(raw.get("text") or raw.get("step") or "").split())
    if not text:
        raise ToolError("plan step text is required")
    status = str(raw.get("status") or "pending")
    if status not in STATUSES:
        raise ToolError(f"invalid plan status '{status}'")
    return Step(text[:500], status, str(raw.get("verification") or "").strip()[:500])


def _path(root: Path) -> Path:
    key = hashlib.sha256(str(root).encode()).hexdigest()[:24]
    return paths.plans_dir() / f"{key}.json"


def _save(root: Path, plan: Plan) -> None:
    path = _path(root.resolve())
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(plan)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".plan-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except OSError as exc:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise ToolError(f"cannot save plan: {exc}") from exc
