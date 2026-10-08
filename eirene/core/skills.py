"""Markdown skills from ~/.local/eirene/skills."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from . import paths

MAX_SKILL_BYTES = 60_000
SEED_MARKER = ".examples"


@dataclass
class Skill:
    """One markdown file the model can load."""

    name: str
    path: Path
    title: str
    summary: str
    size: int
    enabled: bool = True

    @property
    def tokens(self) -> int:
        return max(1, self.size // 4)

    @property
    def description(self) -> str:
        return self.summary


def split_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Pull the --- header off a skill, if it has one."""
    if not text.lstrip().startswith("---"):
        return {}, text
    body = text.lstrip()
    lines = body.splitlines()
    fields: dict[str, str] = {}
    multiline = ""
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() in ("---", "..."):
            return fields, "\n".join(lines[index + 1:]).strip()
        if multiline and (line.startswith((" ", "\t")) or not line.strip()):
            fields[multiline] = (fields[multiline] + " " + line.strip()).strip()
            continue
        multiline = ""
        key, sep, value = line.partition(":")
        if sep and key.strip():
            fields[key.strip().lower()] = value.strip().strip('"\'')
            if value.strip() in (">", "|", ">-", "|-"):
                multiline = key.strip().lower()
                fields[multiline] = ""
    return {}, text


def discover() -> list[Skill]:
    """Read every .md in the skills dir."""
    directory = paths.skills_dir()
    skills = []
    for path in sorted([*directory.glob("*.md"), *directory.glob("*/SKILL.md")]):
        _append_skill(skills, path)
    try:
        from .plugins import discover as discover_plugins
        for plugin in discover_plugins():
            for path in plugin.skills:
                _append_skill(skills, path, prefix=plugin.name)
    except (ImportError, OSError):
        pass
    return skills


def _append_skill(skills: list[Skill], path: Path, prefix: str = "") -> None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        size = path.stat().st_size
    except OSError:
        return
    fields, body = split_front_matter(text)
    head = body[:1000]
    title = fields.get("name") or _title(head, path.stem)
    summary = fields.get("description") or _summary(head)
    slug = path.parent.name if path.name == "SKILL.md" else path.stem
    name = f"{prefix}:{slug}" if prefix else slug
    skills.append(Skill(name, path, title, summary, size))


def _title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or fallback
    return fallback


def _summary(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "---", "```")):
            continue
        return stripped[:200]
    return ""


def load(skill: Skill) -> str:
    """Read a skill body, without its header."""
    try:
        text = skill.path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    _, body = split_front_matter(text)
    if len(body) > MAX_SKILL_BYTES:
        body = body[:MAX_SKILL_BYTES] + "\n… skill truncated"
    return body.strip()


def enabled_block(skills: list[Skill]) -> str:
    """Concatenate enabled skills for the prompt."""
    parts = []
    for skill in skills:
        if not skill.enabled:
            continue
        body = load(skill)
        if body:
            head = f"# Skill: {skill.title}"
            if skill.summary:
                head += f"\nUse when: {skill.summary}"
            parts.append(f"{head}\n{body}")
    if not parts:
        return ""
    return "Loaded skills:\n\n" + "\n\n".join(parts)


def catalog_block(skills: list[Skill]) -> str:
    """Small routing catalogue; bodies are loaded only when relevant."""
    rows = []
    for skill in skills:
        if not skill.enabled:
            continue
        detail = f": {skill.summary}" if skill.summary else ""
        rows.append(f"- {skill.name} ({skill.title}){detail}")
    if not rows:
        return ""
    return ("Available skills (call load_skill before using one):\n" +
            "\n".join(rows))


SKILL_BUDGET = 24_000


def inline_block(skills: list[Skill], budget: int = SKILL_BUDGET) -> str:
    """Whole skills for an agent that cannot call load_skill itself."""
    parts, spent, deferred = [], 0, []
    for skill in skills:
        if not skill.enabled:
            continue
        body = load(skill).strip()
        if not body:
            continue
        if spent + len(body) > budget:
            deferred.append(f"- {skill.name}: {skill.summary} — read {skill.path}")
            continue
        spent += len(body)
        parts.append(f"## Skill: {skill.name} ({skill.title})\n"
                     f"Skill directory: {skill.path.parent}\n{body}")
    if deferred:
        parts.append("Additional enabled skills: read the SKILL.md at the given path before using one.\n" + "\n".join(deferred))
    if not parts:
        return ""
    return ("The user has enabled these Eirene skills. Follow one when the work "
            "matches it.\n\n" + "\n\n".join(parts))


def examples_dir() -> Path:
    """Where the shipped example skills live."""
    import sys
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", ".")) / "skills"
    return Path(__file__).resolve().parents[2] / "skills"


def remove_seeded_examples() -> int:
    """Remove only unchanged copies left by the former first-run installer."""
    target = paths.skills_dir()
    marker = target / SEED_MARKER
    try:
        if marker.read_text(encoding="utf-8").strip() != "examples copied once; delete to get them again":
            return 0
    except (OSError, UnicodeError):
        return 0
    original = {
        "python-project.md": "636d81ec966512172a1968150b6311ac85f4728eebc0ae6c81c0105d527d6088",
        "systemd-service.md": "926136e946b8b221bed386e27683a224b2d6b2281c6fcb73f5828c77b3a5af46",
    }
    removed = 0
    for name, digest in original.items():
        path = target / name
        try:
            if not path.is_symlink() and hashlib.sha256(path.read_text(encoding="utf-8").encode()).hexdigest() == digest:
                path.unlink()
                removed += 1
        except (OSError, UnicodeError):
            continue
    return removed


def apply_config(skills: list[Skill], config) -> list[Skill]:
    """Set enabled flags from saved config."""
    for skill in skills:
        skill.enabled = config.skill_enabled(skill.name, True)
        if ":" in skill.name:
            skill.enabled = skill.enabled and config.plugin_enabled(skill.name.split(":", 1)[0])
    return skills
