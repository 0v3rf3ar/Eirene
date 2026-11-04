"""Bundles adapted to Eirene and shipped inside it: catalog, content and installation."""

import json
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from eirene.commands import plugin_commands
from eirene.commands.plugins import run
from eirene.core import paths, plugin_install, plugins, skills
from eirene.core.plugin_catalog import BUNDLES, SHIPPED, source_for

ROOT = Path(__file__).resolve().parent.parent
BUNDLES_DIR = ROOT / "eirene" / "plugins"
ADAPTED = ("arena", "superpowers")
OTHER_HOSTS = re.compile(
    r"claude|codex|gemini|copilot|opencode|hermes|\bmuse\b|antigravity|harness|anthropic|general-purpose"
    r"|haiku|sonnet|\bopus\b|run_in_background|EnterWorktree|native tool|TodoWrite", re.IGNORECASE)
# Eirene's own hook variable and its list of the instruction files it reads.
ALLOWED = re.compile(r"CLAUDE_PLUGIN_ROOT|`CLAUDE\.md`|\.github/copilot-instructions\.md")


def text_files(root):
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "LICENSE" and "__pycache__" not in path.parts:
            try:
                yield path, path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue


def test_catalog_offers_the_new_defaults_and_not_the_removed_ones():
    names = {name for name, _, _ in BUNDLES}
    assert {"arena", "obsidian", "superpowers"} <= names
    assert not names & {"react-best-practices", "react-native-skills", "web-design-guidelines"}
    for name in SHIPPED:
        assert source_for(name) == f"builtin:{name}"
        assert (BUNDLES_DIR / name / "LICENSE").is_file()
    assert "obra/superpowers" not in {source for _, source, _ in BUNDLES}


@pytest.mark.parametrize("name", ADAPTED)
def test_adapted_bundles_do_not_speak_for_other_hosts(name):
    found = [f"{path.relative_to(BUNDLES_DIR)}: {line.strip()[:90]}"
             for path, text in text_files(BUNDLES_DIR / name) for line in text.splitlines()
             if OTHER_HOSTS.search(ALLOWED.sub("", line))]
    assert not found, "\n".join(found)


def test_superpowers_has_no_remote_logo_or_removed_files():
    for path, text in text_files(BUNDLES_DIR / "superpowers"):
        assert "primeradiant.com" not in text, path
        assert "diagnosing-superpowers" not in text, path
        assert "-tools.md" not in text or "eirene-tools.md" in text, path
        assert "Model Selection; an omitted" not in text, path
    assert "SUPERPOWERS_TELEMETRY_DISABLED = true" in (
        BUNDLES_DIR / "superpowers/skills/brainstorming/scripts/server.cjs").read_text()


@pytest.mark.parametrize("name", ("arena", "superpowers", "obsidian"))
def test_relative_links_point_at_files_that_exist(name):
    broken = []
    for path, text in text_files(BUNDLES_DIR / name):
        if path.suffix != ".md":
            continue
        for target in re.findall(r"\]\(([^)#\s]+\.md)\)", text):
            if "://" not in target and not (path.parent / target).exists():
                broken.append(f"{path.relative_to(BUNDLES_DIR)} -> {target}")
    assert not broken, broken


@pytest.mark.parametrize("name, count", [("superpowers", 14), ("arena", 1), ("obsidian", 6)])
def test_installs_offline_with_every_skill_loadable(name, count, config):
    assert plugin_install.install(name) == (name, count)
    plugin = plugins.discover()[0]
    assert plugin.catalog_shortcut == name and plugin.description
    found = skills.discover()
    assert len(found) == count
    assert all(skills.load(item).strip() and item.summary for item in found)
    assert not config.get("plugin_trust", {}).get(name)


@pytest.mark.usefixtures("trusted_plugins")
def test_shipped_commands_are_offered(config):
    plugin_install.install("arena")
    assert "arena" in {command.name for command in plugin_commands.commands(config)}
    assert "$ARGUMENTS" in skills.load(skills.discover()[0])


def test_arena_runs_from_where_it_is_installed_with_eirene_defaults(tmp_path):
    plugin_install.install("arena")
    script = paths.skills_dir() / "arena/arena/bracket.py"
    plan = subprocess.run([sys.executable, str(script), "plan"], capture_output=True, text=True, cwd=tmp_path)
    assert plan.returncode == 0, plan.stderr
    assert "16 agents, 4 rounds, waves of 8" in plan.stdout and "91" in plan.stdout
    (tmp_path / "task.md").write_text("Say hello.")
    subprocess.run([sys.executable, str(script), "init", "--seed", "1", "--task-file", "task.md"],
                   check=True, capture_output=True, cwd=tmp_path)
    jobs = subprocess.run([sys.executable, str(script), "prompts", "spawn"], check=True,
                          capture_output=True, text=True, cwd=tmp_path).stdout
    assert "delegate_tasks" in jobs and "read_only false" in jobs and "Agent call" not in jobs
    briefs = list((tmp_path / ".arena").rglob("*.md"))
    assert any("competitor" in path.read_text() for path in briefs)


@pytest.mark.skipif(not shutil.which("bash"), reason="the hook needs bash")
async def test_superpowers_startup_hook_runs_and_teaches_eirene_tools(config, box):
    from eirene.core.plugin_runtime import PluginRuntime
    plugin_install.install("superpowers")
    config.set("plugin_trust", {"superpowers": True})
    config.set("execution_isolation", "none")
    runtime = PluginRuntime("bundled-bootstrap")
    await runtime.submit("Review the project", box, config)
    block = runtime.block(config)
    assert "You have superpowers" in block and "load_skill" in block and "eirene-tools.md" in block


def test_install_restores_executable_bits_packaging_can_drop(tmp_path, monkeypatch):
    if sys.platform == "win32":
        pytest.skip("no executable bit")
    source = tmp_path / "bundles"
    shutil.copytree(BUNDLES_DIR / "superpowers", source / "superpowers")
    for path in source.rglob("*"):
        if path.is_file():
            path.chmod(0o644)
    monkeypatch.setattr(plugin_install, "bundled_skills", lambda name="": source / name)
    plugin_install.install("superpowers")
    root = paths.plugins_dir() / "superpowers"
    assert (root / "hooks/run-hook.cmd").stat().st_mode & stat.S_IXUSR
    assert (paths.skills_dir() / "superpowers/brainstorming/scripts/start-server.sh").stat().st_mode & stat.S_IXUSR
    assert not (root / "hooks/hooks.json").stat().st_mode & stat.S_IXUSR


def _github_copy(tmp_path, shortcut):
    """What a catalog install from GitHub left behind, before this bundle shipped."""
    upstream = tmp_path / "superpowers"
    (upstream / "skills/old").mkdir(parents=True)
    (upstream / "skills/old/SKILL.md").write_text("Use the Skill tool.")
    plugin_install.install(str(upstream))
    index = paths.plugins_dir() / "superpowers/.eirene-plugin.json"
    body = json.loads(index.read_text())
    del body["install_source"]
    if shortcut:
        body["catalog_shortcut"] = shortcut
    index.write_text(json.dumps(body))


def _eirene_repository(monkeypatch, change=None):
    """Stand in for cloning Eirene: its plugins folder, optionally changed. Returns the URLs used."""
    urls = []

    def clone(url, destination, **_):
        urls.append(url)
        shutil.copytree(BUNDLES_DIR, destination / "eirene/plugins")
        if change:
            change(destination / "eirene/plugins")

    monkeypatch.setattr(plugin_install, "clone", clone)
    return urls


def _changed_skill(plugins_folder):
    (plugins_folder / "superpowers/skills/brainstorming/NEW.md").write_text("from the repository")


async def test_update_reads_a_shipped_plugin_from_eirenes_repository(config, monkeypatch):
    from tests.test_marketplace import fake_app
    urls = _eirene_repository(monkeypatch, _changed_skill)
    plugin_install.install("superpowers")
    assert urls == []  # installing stays offline
    config.set("plugin_trust", {"superpowers": True})
    app = fake_app(config)
    await run(app, "update superpowers")
    assert urls == ["https://github.com/0v3rf3ar/Eirene.git"]
    assert "updated superpowers" in app.said[-1]
    assert (paths.plugins_dir() / "superpowers/skills/brainstorming/NEW.md").is_file()
    assert (paths.skills_dir() / "superpowers/brainstorming/NEW.md").is_file()
    assert not config.get("plugin_trust").get("superpowers")


async def test_update_keeps_trust_when_the_repository_copy_is_the_same(config, monkeypatch):
    from tests.test_marketplace import fake_app
    _eirene_repository(monkeypatch)
    plugin_install.install("superpowers")
    config.set("plugin_trust", {"superpowers": True})
    app = fake_app(config)
    await run(app, "update superpowers")
    assert app.said[-1] == "superpowers is already up to date"
    assert config.get("plugin_trust").get("superpowers")


async def test_update_restores_executable_bits_from_the_repository(config, monkeypatch):
    if sys.platform == "win32":
        pytest.skip("no executable bit")
    from tests.test_marketplace import fake_app

    def without_bits(plugins_folder):
        _changed_skill(plugins_folder)
        for path in plugins_folder.rglob("*"):
            if path.is_file():
                path.chmod(0o644)

    _eirene_repository(monkeypatch, without_bits)
    plugin_install.install("superpowers")
    await run(fake_app(config), "update superpowers")
    assert (paths.plugins_dir() / "superpowers/hooks/run-hook.cmd").stat().st_mode & stat.S_IXUSR


@pytest.mark.parametrize("change", [lambda folder: shutil.rmtree(folder / "superpowers"), None])
async def test_failed_repository_update_keeps_the_installed_copy(config, monkeypatch, change):
    from tests.test_marketplace import fake_app
    _eirene_repository(monkeypatch, change)
    plugin_install.install("superpowers")
    if change is None:
        def offline(*_, **__):
            raise ValueError("could not download repository")
        monkeypatch.setattr(plugin_install, "clone", offline)
    config.set("plugin_trust", {"superpowers": True})
    app = fake_app(config)
    await run(app, "update superpowers")
    assert "superpowers: update failed" in app.said[-1]
    assert (paths.plugins_dir() / "superpowers/skills/brainstorming/SKILL.md").is_file()
    assert config.get("plugin_trust").get("superpowers")


async def test_refresh_does_not_undo_a_repository_update(config, monkeypatch):
    from tests.test_marketplace import fake_app
    _eirene_repository(monkeypatch, _changed_skill)
    plugin_install.install("superpowers")
    app = fake_app(config)
    await run(app, "update superpowers")
    await run(app, "refresh superpowers")
    assert (paths.plugins_dir() / "superpowers/skills/brainstorming/NEW.md").is_file()


async def test_update_moves_a_github_install_to_the_shipped_copy(tmp_path, config, monkeypatch):
    from tests.test_marketplace import fake_app
    _eirene_repository(monkeypatch)
    _github_copy(tmp_path, "superpowers")
    config.set("plugin_trust", {"superpowers": True})
    app = fake_app(config)
    await run(app, "update superpowers")
    assert "updated superpowers: 14 skills" in app.said[-1]
    assert (paths.skills_dir() / "superpowers/brainstorming/SKILL.md").is_file()
    assert not (paths.skills_dir() / "superpowers/old").exists()
    assert not config.get("plugin_trust").get("superpowers")


async def test_refresh_leaves_a_users_own_plugin_of_the_same_name(tmp_path, config):
    from tests.test_marketplace import fake_app
    _github_copy(tmp_path, "")
    await run(fake_app(config), "refresh superpowers")
    assert (paths.plugins_dir() / "superpowers/skills/old/SKILL.md").is_file()
    assert not (paths.plugins_dir() / "superpowers/skills/brainstorming").exists()
