"""Bounded project discovery and reusable repository context."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import paths

INSTRUCTION_FILES = ("AGENTS.md", "EIRENE.md", ".eirene.md", "CLAUDE.md",
                     ".github/copilot-instructions.md")
MANIFESTS = {
    "pyproject.toml": ("Python", ["python -m pytest", "python -m ruff check ."]),
    "requirements.txt": ("Python", ["python -m pytest"]),
    "package.json": ("Node.js", ["npm test", "npm run lint", "npm run build"]),
    "Cargo.toml": ("Rust", ["cargo test", "cargo clippy"]),
    "go.mod": ("Go", ["go test ./...", "go vet ./..."]),
    "pom.xml": ("Java/Maven", ["mvn test"]),
    "build.gradle": ("Java/Gradle", ["./gradlew test"]),
    "build.gradle.kts": ("Kotlin/Gradle", ["./gradlew test"]),
    "Gemfile": ("Ruby", ["bundle exec rspec"]),
    "composer.json": ("PHP", ["composer test"]),
    "Makefile": ("Make", ["make test"]),
}
EXTENSIONS = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".rs": "Rust",
    ".go": "Go", ".java": "Java", ".kt": "Kotlin", ".rb": "Ruby",
    ".php": "PHP", ".cs": "C#", ".c": "C", ".h": "C/C++",
    ".cpp": "C++", ".swift": "Swift", ".sh": "Shell", ".md": "Markdown",
}
SKIP = {".git", ".venv", "venv", "node_modules", "dist", "build", "target",
        ".pytest_cache", "__pycache__", ".next", ".idea"}
MAX_FILES = 10_000
MAX_INSTRUCTION_CHARS = 16_000


@dataclass
class ProjectProfile:
    root: str
    name: str
    frameworks: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    manifests: list[str] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    file_count: int = 0
    instruction_text: str = ""

    def prompt_block(self) -> str:
        rows = ["Project profile:", f"- name: {self.name}"]
        if self.frameworks:
            rows.append("- detected: " + ", ".join(self.frameworks))
        if self.languages:
            rows.append("- languages: " + ", ".join(self.languages))
        if self.manifests:
            rows.append("- manifests: " + ", ".join(self.manifests))
        if self.commands:
            rows.append("- likely verification: " + "; ".join(self.commands))
        if self.instructions:
            rows.append("- instruction files: " + ", ".join(self.instructions))
        if self.instruction_text:
            rows.extend(["", "Project instructions:", self.instruction_text])
        return "\n".join(rows)


def discover(root: Path, *, refresh: bool = False) -> ProjectProfile:
    root = root.resolve()
    signature = _signature(root)
    cache = paths.projects_dir() / (_key(root) + ".json")
    if not refresh:
        loaded = _load(cache, signature)
        if loaded:
            return loaded
    profile = _scan(root)
    _save(cache, signature, profile)
    return profile


def describe(root: Path, *, refresh: bool = False) -> str:
    profile = discover(root, refresh=refresh)
    return profile.prompt_block()


def _scan(root: Path) -> ProjectProfile:
    manifests = []
    frameworks = []
    commands = []
    for name, (framework, suggested) in MANIFESTS.items():
        if (root / name).is_file():
            manifests.append(name)
            frameworks.append(framework)
            commands.extend(suggested)
    if (root / "package.json").is_file():
        try:
            scripts = json.loads((root / "package.json").read_text()).get("scripts", {})
            if not isinstance(scripts, dict):
                scripts = {}
            commands = [c for c in commands if c not in MANIFESTS["package.json"][1]]
            manager = "pnpm" if (root / "pnpm-lock.yaml").exists() else "yarn" if (root / "yarn.lock").exists() else "bun" if any((root / n).exists() for n in ("bun.lock", "bun.lockb")) else "npm"
            commands.extend(f"{manager} run {name}" for name in ("test", "lint", "typecheck", "build") if name in scripts)
        except (OSError, ValueError, AttributeError):
            pass
    instructions = [name for name in INSTRUCTION_FILES if (root / name).is_file()]
    instruction_parts = []
    remaining = MAX_INSTRUCTION_CHARS
    for name in instructions:
        try:
            body = (root / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        chunk = body[:remaining]
        instruction_parts.append(f"## {name}\n{chunk}")
        remaining -= len(chunk)
        if remaining <= 0:
            break
    language_names = {"Python": "Python", "Node.js": "JavaScript", "Rust": "Rust", "Go": "Go", "Java/Maven": "Java", "Java/Gradle": "Java", "Kotlin/Gradle": "Kotlin", "Ruby": "Ruby", "PHP": "PHP"}
    languages = list(dict.fromkeys(language_names[f] for f in frameworks if f in language_names))
    file_count = 0  # Native inventory is loaded on demand by project_info.
    return ProjectProfile(str(root), root.name or str(root),
                          list(dict.fromkeys(frameworks)), languages, manifests,
                          instructions, list(dict.fromkeys(commands)), file_count,
                          "\n\n".join(instruction_parts))


def _signature(root: Path) -> str:
    facts = [("profile_version", "native-commands-v1")]
    for name in (*MANIFESTS, *INSTRUCTION_FILES, "pnpm-lock.yaml", "yarn.lock", "bun.lock", "bun.lockb"):
        path = root / name
        try:
            facts.append((name, path.stat().st_mtime_ns, path.stat().st_size))
        except OSError:
            facts.append((name, 0, 0))
    return hashlib.sha256(repr(facts).encode()).hexdigest()


def _key(root: Path) -> str:
    return hashlib.sha256(str(root).encode()).hexdigest()[:24]


def _load(cache: Path, signature: str) -> ProjectProfile | None:
    try:
        body = json.loads(cache.read_text(encoding="utf-8"))
        if body.get("signature") != signature:
            return None
        return ProjectProfile(**body["profile"])
    except (OSError, KeyError, TypeError, ValueError):
        return None


def _save(cache: Path, signature: str, profile: ProjectProfile) -> None:
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"signature": signature, "profile": asdict(profile)},
                                    indent=2, ensure_ascii=False), encoding="utf-8")
        if os.name != "nt":
            cache.chmod(0o600)
    except OSError:
        pass


def scoped_instructions(root: Path, target: Path) -> str:
    """Return nested instructions, outer to inner, for one path."""
    root, target = root.resolve(), target.resolve()
    if target != root and root not in target.parents:
        return ""
    directory = target if target.is_dir() else target.parent
    parents = []
    while directory != root:
        parents.append(directory)
        directory = directory.parent
    rows = []
    for parent in reversed(parents):
        for name in ("AGENTS.md", "EIRENE.md", "CLAUDE.md"):
            file = parent / name
            if file.is_file() and root in file.resolve().parents:
                with file.open(encoding="utf-8", errors="replace") as handle:
                    rows.append(f"Instructions scoped to {parent.relative_to(root)}/ ({name}):\n" + handle.read(MAX_INSTRUCTION_CHARS))
    return "\n\n".join(rows)
