"""Shared helpers for the skill-creator scripts."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

FRONT = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.S)


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Simple YAML front matter: key: value, quoted values, and > or | blocks."""
    match = FRONT.match(text)
    if not match:
        return {}, text
    data: dict[str, str] = {}
    lines = match.group(1).splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        found = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        index += 1
        if not found:
            continue
        key, value = found.group(1), found.group(2).strip()
        if value in (">", "|", ">-", "|-", ">+", "|+"):
            block = []
            while index < len(lines) and (lines[index].startswith((" ", "\t")) or not lines[index].strip()):
                block.append(lines[index].strip())
                index += 1
            value = (" " if value.startswith(">") else "\n").join(b for b in block if b or value.startswith("|"))
        else:
            while index < len(lines) and lines[index].startswith((" ", "\t")) and lines[index].strip():
                value += " " + lines[index].strip()
                index += 1
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
        data[key] = value.strip()
    return data, text[match.end():]


def read_skill(path: str | Path) -> tuple[dict[str, str], str, Path]:
    """(frontmatter, body, SKILL.md path) for a skill folder or SKILL.md file."""
    path = Path(path)
    skill_md = path / "SKILL.md" if path.is_dir() else path
    if not skill_md.exists():
        raise SystemExit(f"no SKILL.md at {skill_md}")
    meta, body = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
    return meta, body, skill_md


def with_description(text: str, description: str) -> str:
    """SKILL.md text with its description replaced (written as a folded block)."""
    match = FRONT.match(text)
    if not match:
        raise SystemExit("SKILL.md has no front matter")
    lines = match.group(1).splitlines()
    out, index, replaced = [], 0, False
    while index < len(lines):
        line = lines[index]
        index += 1
        if re.match(r"^description:", line):
            while index < len(lines) and lines[index].startswith((" ", "\t")):
                index += 1
            out.append("description: >")
            words, current = description.split(), "  "
            for word in words:
                if len(current) + len(word) > 80 and current.strip():
                    out.append(current.rstrip())
                    current = "  "
                current += word + " "
            if current.strip():
                out.append(current.rstrip())
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"description: {description}")
    return "---\n" + "\n".join(out) + "\n---\n" + text[match.end():]


def eirene_command(executable: str = "eirene") -> list[str]:
    return [executable]


def run_stream(command: list[str], *, timeout: float, cwd: str | Path | None = None,
               env: dict | None = None, on_event=None) -> tuple[list[dict], int, str]:
    """Run an eirene --stream-json command; return (events, exit code, stderr tail).

    on_event(event) may return True to stop the run early.
    """
    process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace")
    events: list[dict] = []
    import threading

    stderr_lines: list[str] = []
    reader = threading.Thread(target=lambda: stderr_lines.extend(process.stderr), daemon=True)
    reader.start()
    timer = threading.Timer(timeout, process.kill)
    timer.start()
    stopped = False
    try:
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            events.append(event)
            if on_event and on_event(event):
                stopped = True
                process.kill()
                break
    finally:
        timer.cancel()
        process.wait()
        reader.join(timeout=2)
    code = 0 if stopped else process.returncode
    return events, code, "".join(stderr_lines)[-2000:]


def result_of(events: list[dict]) -> dict:
    for event in reversed(events):
        if event.get("type") == "result":
            return event.get("result") or event
    return {}


def private_home(skill_folder: Path | None = None, skill_name: str | None = None) -> Path:
    """A throwaway EIRENE_HOME that shares the real configuration and plugins.

    The skills folder links every real skill except skill_name, and holds a copy
    of skill_folder in its place. Sessions written during tests stay out of the
    real history. Delete it with shutil.rmtree when done.
    """
    real = Path(os.environ.get("EIRENE_HOME") or Path.home() / ".local" / "share" / "eirene").expanduser()
    home = Path(tempfile.mkdtemp(prefix="eirene-skilltest-"))
    os.chmod(home, 0o700)
    if (real / "config.json").exists():
        shutil.copyfile(real / "config.json", home / "config.json")
        os.chmod(home / "config.json", 0o600)
    for name in ("plugins", "plugin-data"):
        if (real / name).exists():
            try:
                (home / name).symlink_to(real / name, target_is_directory=True)
            except OSError:
                shutil.copytree(real / name, home / name, symlinks=True)
    skills = home / "skills"
    skills.mkdir()
    def link(entry: Path, target: Path) -> None:
        try:
            target.symlink_to(entry, target_is_directory=entry.is_dir())
        except OSError:
            (shutil.copytree if entry.is_dir() else shutil.copyfile)(entry, target)

    same = {skill_name, f"{skill_name}.md"} if skill_name else set()
    if (real / "skills").exists():
        for entry in (real / "skills").iterdir():
            if entry.name in same:
                continue
            # A folder of skills (such as an installed plugin's) that holds another copy
            # of this skill: link everything in it except that copy, so the two do not compete.
            if entry.is_dir() and not (entry / "SKILL.md").exists() and any((entry / n).exists() for n in same):
                (skills / entry.name).mkdir()
                for child in entry.iterdir():
                    if child.name not in same:
                        link(child, skills / entry.name / child.name)
                continue
            link(entry, skills / entry.name)
    if skill_folder is not None:
        shutil.copytree(skill_folder, skills / (skill_name or skill_folder.name),
                        ignore=shutil.ignore_patterns("*-workspace", "__pycache__", ".git", "node_modules"))
    return home
