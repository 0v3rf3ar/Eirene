"""Markdown skills from ~/.local/share/eirene/skills.

A subfolder without its own SKILL.md is a group: its skills are named
"<folder>:<skill>". Installed plugins put their skills in a group named after
the plugin. A skill or group can add slash commands from a commands/ folder.
"""

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
    group: str = ""

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
    """Read every .md in the skills dir, then each group folder."""
    directory = paths.skills_dir()
    skills = []
    for path in sorted([*directory.glob("*.md"), *directory.glob("*/SKILL.md")]):
        _append_skill(skills, path)
    groups = set()
    for folder in sorted(group_folders()):
        groups.add(folder.name)
        for path in sorted([*folder.glob("*.md"), *folder.glob("*/SKILL.md")]):
            _append_skill(skills, path, prefix=folder.name)
    try:
        # Bundles whose skills have not been copied into a group folder yet.
        from .plugins import discover as discover_plugins
        for plugin in discover_plugins():
            if plugin.name not in groups:
                for path in plugin.skills:
                    _append_skill(skills, path, prefix=plugin.name)
    except (ImportError, OSError):
        pass
    return skills


def group_folders() -> list[Path]:
    """Skill folders that hold other skills rather than being one."""
    directory = paths.skills_dir()
    if not directory.is_dir():
        return []
    return [folder for folder in directory.iterdir()
            if folder.is_dir() and not folder.name.startswith(".")
            and not (folder / "SKILL.md").is_file()]


def group_copy(group: str, path: Path) -> Path:
    """The skills/<group>/ copy of a bundled skill file, when it has one."""
    folder = paths.skills_dir() / group
    copy = (folder / path.parent.name / "SKILL.md" if path.name == "SKILL.md"
            else folder / path.name)
    return copy if copy.is_file() else path


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
    skills.append(Skill(name, path, title, summary, size, group=prefix))


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


def expand_paths(text: str, directory: Path, plugin_root: Path | None = None) -> str:
    """Put real paths in place of the placeholders skills use for their own files.

    A model that has to compose the path itself gets it wrong: skills/<plugin>/<skill>
    repeats a name when the two match, and it drops one.
    """
    for key in ("${SKILL_DIR}", "${CLAUDE_SKILL_DIR}"):
        text = text.replace(key, str(directory))
    for key in ("${CLAUDE_PLUGIN_ROOT}", "${CODEX_PLUGIN_ROOT}", "${PLUGIN_ROOT}"):
        text = text.replace(key, str(plugin_root or directory))
    return text


def _plugin_root(skill: Skill) -> Path | None:
    if not skill.group:
        return None
    from . import plugins
    return next((plugin.path for plugin in plugins.discover() if plugin.name == skill.group), None)


def load(skill: Skill) -> str:
    """Read a skill body, without its header, with its own paths filled in."""
    try:
        text = skill.path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    _, body = split_front_matter(text)
    if "${" in body:
        body = expand_paths(body, skill.path.parent, _plugin_root(skill))
    if len(body) > MAX_SKILL_BYTES:
        body = body[:MAX_SKILL_BYTES] + "\n… skill truncated"
    return body.strip()


UNGROUPED_BUNDLE = "skill"


def standalone_bundles(config) -> list:
    """Enabled skills from the skills folder, packaged so they can add commands like a plugin.

    A skill folder may hold commands/*.md beside its SKILL.md, and a group folder
    may hold commands/ for the whole group. Plugin skills are not included here:
    their plugin already offers them.
    """
    from .plugins import Plugin, discover as discover_plugins
    owned = {plugin.name for plugin in discover_plugins()}
    bundles: dict[str, Plugin] = {}
    for skill in apply_config(discover(), config):
        if skill.group in owned or not skill.enabled:
            continue
        key = skill.group or UNGROUPED_BUNDLE
        root = paths.skills_dir() / skill.group if skill.group else paths.skills_dir()
        bundle = bundles.setdefault(key, Plugin(key, root, standalone=True))
        bundle.skills.append(skill.path)
        if skill.path.name == "SKILL.md":
            bundle.commands.extend(sorted(skill.path.parent.glob("commands/*.md")))
    for name, bundle in bundles.items():
        if name != UNGROUPED_BUNDLE:
            bundle.commands.extend(sorted(bundle.path.glob("commands/*.md")))
    return list(bundles.values())


SUPPORT_LISTED = 60
SCRIPT_SUFFIXES = {".py", ".sh", ".js", ".cjs", ".mjs", ".ts", ".ps1", ".rb"}


def find(items: list[Skill], wanted: str) -> Skill | None:
    """A skill by exact id, or by its short name when exactly one plugin skill has it."""
    exact = next((item for item in items if item.name == wanted), None)
    if exact is not None or not wanted or ":" in wanted:
        return exact
    matches = [item for item in items if item.name.rsplit(":", 1)[-1] == wanted]
    return matches[0] if len(matches) == 1 else None


def supporting_files(skill: Skill) -> str:
    """How to reach the files next to a skill's SKILL.md, for the load_skill result.

    Plugin skills are read with load_plugin_resource, whose path is relative to the
    plugin folder; spell that path out so the model does not have to guess it.
    """
    folder = skill.path.parent
    if skill.path.name != "SKILL.md" or not folder.is_dir():
        return ""
    files = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")
                   if p.is_file() and p.name != "SKILL.md" and "__pycache__" not in p.parts)
    if not files:
        return ""
    prefix = ""
    if ":" in skill.name:
        from . import plugins
        bundle, _, _ = skill.name.partition(":")
        plugin = next((item for item in plugins.discover() if item.name == bundle), None)
        source = next((path for path in (plugin.skills if plugin else []) if path.parent.name == folder.name), None)
        if plugin is not None and source is not None:
            try:
                prefix = source.parent.relative_to(plugin.path).as_posix() + "/"
            except ValueError:
                prefix = ""
    shown = files[:SUPPORT_LISTED]
    example = next((name for name in shown if name.endswith(".md")), shown[0])
    more = f"\n… and {len(files) - len(shown)} more" if len(files) > len(shown) else ""
    if prefix:
        how = (f"Read them with load_plugin_resource(plugin=\"{bundle}\", path=\"{prefix}<file>\"), "
               f"for example path=\"{prefix}{example}\".")
    else:
        how = "They are in the skill directory above."
    script = next((name for name in files if Path(name).suffix in SCRIPT_SUFFIXES), "")
    if script:
        how += (" Scripts are not in the workspace: run them by full path, for example "
                f"\"{folder / script}\", and give full paths for any workspace files they take.")
    return "Supporting files:\n" + "\n".join(f"- {name}" for name in shown) + more + f"\n{how}\n\n"


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


_LEGACY_EXAMPLES = {
    "python-project.md": "636d81ec966512172a1968150b6311ac85f4728eebc0ae6c81c0105d527d6088",
    "systemd-service.md": "926136e946b8b221bed386e27683a224b2d6b2281c6fcb73f5828c77b3a5af46",
}


def remove_seeded_examples() -> int:
    """Remove only unchanged copies left by the former first-run installer."""
    target = paths.skills_dir()
    marker = target / SEED_MARKER
    try:
        if marker.read_text(encoding="utf-8").strip() != "examples copied once; delete to get them again":
            return 0
    except (OSError, UnicodeError):
        return 0
    removed = 0
    for name, digest in _LEGACY_EXAMPLES.items():
        path = target / name
        try:
            if not path.is_symlink() and hashlib.sha256(path.read_text(encoding="utf-8").encode()).hexdigest() == digest:
                path.unlink()
                removed += 1
        except (OSError, UnicodeError):
            continue
    return removed


def group_on(name: str, config, installed: set[str] | None = None) -> bool:
    """Whether a skill's group allows it. A plugin's skills need its trust; your own do not."""
    if ":" not in name:
        return True
    if installed is None:
        from .plugins import discover as discover_plugins
        installed = {plugin.name for plugin in discover_plugins()}
    group = name.split(":", 1)[0]
    return config.plugin_active(group) if group in installed else config.plugin_enabled(group)


def apply_config(skills: list[Skill], config) -> list[Skill]:
    """Set enabled flags from saved config."""
    from .plugins import discover as discover_plugins
    installed = {plugin.name for plugin in discover_plugins()}
    for skill in skills:
        skill.enabled = config.skill_enabled(skill.name, True) and group_on(skill.name, config, installed)
    return skills
