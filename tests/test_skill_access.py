"""Skills can be found by short name, list their files, and are readable (never writable) in the sandbox."""
from __future__ import annotations

import pytest

from eirene.core import paths, skills
from eirene.core.errors import SandboxError
from eirene.tools import registry
from eirene.tools.sandbox import Sandbox


@pytest.fixture
def installed(config):
    folder = paths.skills_dir() / "bundle" / "report"
    (folder / "scripts").mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\nname: report\ndescription: Write reports.\n---\n\n# Report\nBody.\n")
    (folder / "scripts" / "make.py").write_text("print('hi')\n")
    (folder / "guide.md").write_text("guide\n")
    (paths.skills_dir() / "solo.md").write_text("---\nname: solo\ndescription: A flat skill.\n---\n\nSolo body.\n")
    return folder


def test_short_names_find_a_unique_plugin_skill(installed):
    found = skills.discover()
    assert skills.find(found, "bundle:report").name == "bundle:report"
    assert skills.find(found, "report").name == "bundle:report"
    assert skills.find(found, "solo").name == "solo"
    assert skills.find(found, "missing") is None


def test_short_names_stay_ambiguous_when_two_bundles_share_one(installed):
    other = paths.skills_dir() / "second" / "report"
    other.mkdir(parents=True)
    (other / "SKILL.md").write_text("---\nname: report\ndescription: Another.\n---\n\nOther.\n")
    assert skills.find(skills.discover(), "report") is None


def test_supporting_files_are_listed_for_folder_skills(installed):
    report = skills.find(skills.discover(), "report")
    text = skills.supporting_files(report)
    assert "- guide.md" in text and "- scripts/make.py" in text and "SKILL.md" not in text.split("\n")[1]
    solo = skills.find(skills.discover(), "solo")
    assert skills.supporting_files(solo) == ""


@pytest.mark.asyncio
async def test_load_skill_result_names_the_files(installed, tmp_path):
    result = await registry.execute("load_skill", {"name": "report"}, Sandbox(project(tmp_path)))
    assert "Skill directory:" in result and "Supporting files:" in result and "Body." in result


def test_sandbox_reads_but_never_writes_the_skills_folder(installed, tmp_path):
    box = Sandbox(project(tmp_path))
    script = installed / "scripts" / "make.py"
    assert box.resolve(script) == script.resolve()
    assert box.contains(script, write=False)
    assert not box.contains(script)  # the default is the write check
    with pytest.raises(SandboxError):
        box.check_write_target(script)
    with pytest.raises(SandboxError):
        box.resolve(paths.config_file())  # the rest of Eirene's data stays outside


def project(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir(exist_ok=True)
    return folder


def test_escape_checks_allow_reading_skill_files_only(installed, tmp_path):
    box = Sandbox(project(tmp_path))
    guide = str(installed / "guide.md")
    assert registry.sandbox_escape("read_file", {"path": guide}, box) == ""
    assert registry.sandbox_escape("write_file", {"path": guide, "content": "x"}, box)
    assert registry.sandbox_escape("edit_file", {"path": guide, "old_string": "a", "new_string": "b"}, box)
    assert registry.sandbox_escape("run_command", {"command": "ls", "cwd": str(installed)}, box)


def test_commands_that_use_skill_scripts_get_a_read_only_mount(installed):
    root = str(paths.skills_dir().resolve())
    assert registry.skill_mounts(f"python3 {installed / 'scripts' / 'make.py'} --help") == [root]
    assert registry.skill_mounts("python3 make.py") == []


def test_bubblewrap_mounts_the_skills_folder_read_only(installed, tmp_path, monkeypatch):
    from eirene.tools import isolation
    monkeypatch.setattr(isolation.shutil, "which", lambda name: "/usr/bin/bwrap")
    monkeypatch.setattr(isolation.sys, "platform", "linux")
    root = paths.skills_dir().resolve()
    argv = isolation.command("true", project(tmp_path), backend="bubblewrap", read_paths=[str(root)])
    index = argv.index(str(root))
    assert argv[index - 1] == "--ro-bind" and argv[index + 1] == str(root)


async def finished(command, box):
    """Run a sandboxed command and wait for it, even when it becomes a managed process."""
    import re
    result = await registry.execute("run_command", {"command": command}, box, isolation="bubblewrap")
    found = re.search(r"managed process (\w+)", result)
    if found:
        result = await registry.execute("poll_process", {"process_id": found.group(1), "wait": True}, box)
    return result


@pytest.mark.asyncio
@pytest.mark.skipif(not (__import__("sys").platform == "linux" and __import__("shutil").which("bwrap")),
                    reason="needs Linux bubblewrap")
async def test_sandboxed_command_reads_a_skill_file_and_cannot_change_it(installed, tmp_path):
    guide = installed / "guide.md"
    box = Sandbox(project(tmp_path))
    try:
        result = await finished(f"cat {guide}", box)
    except Exception as exc:  # bubblewrap present but unusable here (e.g. no user namespaces)
        pytest.skip(f"bubblewrap unavailable: {exc}")
    assert "guide" in result
    try:
        await finished(f"touch {installed / 'new.txt'}", box)
    except Exception:
        pass  # a failed command is the expected outcome
    assert not (installed / "new.txt").exists()
    assert guide.read_text() == "guide\n"


def _bundle_with_script():
    root = paths.plugins_dir() / "tools"
    (root / "skills/run/scripts").mkdir(parents=True)
    (root / "bin").mkdir()
    (root / "bin/shared.py").write_text("print('shared')\n")
    (root / "skills/run/scripts/go.py").write_text("print('go')\n")
    (root / "skills/run/SKILL.md").write_text(
        "---\nname: run\ndescription: Run.\n---\n"
        'python3 "${SKILL_DIR}/scripts/go.py" and "${CLAUDE_SKILL_DIR}/x" and "${CLAUDE_PLUGIN_ROOT}/bin/shared.py"\n')
    (root / "plugin.json").write_text('{"name": "tools"}')
    return root


def test_skill_placeholders_become_real_paths(config):
    from eirene.core.plugin_install import install
    source = _bundle_with_script()
    import shutil
    moved = source.parent.parent / "source-tools"
    shutil.move(str(source), str(moved))
    install(str(moved))
    skill = skills.discover()[0]
    body = skills.load(skill)
    folder = paths.skills_dir() / "tools/run"
    assert f'"{folder}/scripts/go.py"' in body and f'"{folder}/x"' in body
    assert f'"{paths.plugins_dir() / "tools"}/bin/shared.py"' in body
    assert "${" not in body


def test_load_skill_says_to_run_scripts_by_full_path(config):
    from eirene.core.plugin_install import install
    source = _bundle_with_script()
    import shutil
    moved = source.parent.parent / "source-tools"
    shutil.move(str(source), str(moved))
    install(str(moved))
    text = skills.supporting_files(skills.discover()[0])
    assert "run them by full path" in text
    assert str(paths.skills_dir() / "tools/run/scripts/go.py") in text


def test_plain_guidance_gets_no_script_advice(installed):
    (installed / "scripts" / "make.py").unlink()
    (installed / "scripts").rmdir()
    assert "full path" not in skills.supporting_files(skills.find(skills.discover(), "bundle:report"))


@pytest.mark.parametrize("written", ["{root}/x.py", "~/{relative}/x.py", "$HOME/{relative}/x.py", "${{HOME}}/{relative}/x.py"])
def test_sandbox_mounts_the_skills_folder_however_it_is_written(monkeypatch, tmp_path, written):
    from pathlib import Path
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv(paths.ENV_HOME, str(tmp_path / "data"))
    root = paths.skills_dir()
    root.mkdir(parents=True)
    relative = root.resolve().relative_to(tmp_path.resolve()).as_posix()
    command = "python3 " + written.format(root=root.resolve(), relative=relative)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path.resolve()))
    assert str(root.resolve()) in registry.skill_mounts(command)


def test_installed_plugin_scripts_are_readable_but_not_writable(config, box):
    root = paths.plugins_dir() / "tools"
    root.mkdir(parents=True)
    (root / "run.py").write_text("x")
    assert str(root.parent.resolve()) in [str(p) for p in paths.readable_roots()]
    assert box.readable((root / "run.py").resolve())
    assert str(paths.plugins_dir().resolve()) in registry.skill_mounts(f"python3 {root / 'run.py'}")
    with pytest.raises(SandboxError):
        box.resolve(root / "run.py", write=True)


async def test_a_quick_skill_script_returns_its_result_the_first_time(config, box):
    import sys
    script = paths.skills_dir() / "tool.py"
    script.write_text("print('hello from the skill')")
    result = await registry.execute("run_command", {"command": f'"{sys.executable}" "{script}"'}, box, config=config)
    assert "hello from the skill" in str(result) and "Still running" not in str(result)
