"""Marketplaces, the /plugin command forms, the tabbed menu, and commands added by skills."""

import asyncio
import json
import re
from types import SimpleNamespace

import pytest

from eirene.commands import plugin_commands
from eirene.commands.plugins import run
from eirene.commands.skills import run as skills_run
from eirene.core import marketplace, paths, plugin_install, plugin_stats, plugins, skills
from eirene.core.config import Config


def skill(root, name, text="# Title\nBody."):
    folder = root / "skills" / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(text)
    return folder


def catalog(root, entries, name="shelf", **extra):
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (root / ".claude-plugin/marketplace.json").write_text(
        json.dumps({"name": name, "owner": {"name": "x"}, "plugins": entries, **extra}))
    return root


def fake_app(config, choices=()):
    """Records what the command says and answers prompts from a list."""
    said = []
    answers = list(choices)

    async def ask_choice(title, options, **kwargs):
        return answers.pop(0) if answers else None

    async def ask_tabs(title, tabs, tab=0, selected=""):
        app.shown.append((tab, tabs))
        return tab, answers.pop(0) if answers else None

    app = SimpleNamespace(config=config, turn=None, say=lambda text, *a: said.append(str(text)),
                          said=said, shown=[], ask_choice=ask_choice, ask_tabs=ask_tabs,
                          _save_config=lambda: None, agent=SimpleNamespace(reload_skills=lambda: None))
    return app


@pytest.fixture
def config():
    return Config.load()


def test_repository_that_is_both_catalog_and_plugin(tmp_path, config):
    # The layout of kepano/obsidian-skills: source "./" and a plugin.json naming the bundle.
    root = catalog(tmp_path / "obsidian-skills", [
        {"name": "obsidian", "source": "./", "description": "Vault files"}], name="obsidian-skills")
    skill(root, "obsidian-cli")
    (root / ".claude-plugin/plugin.json").write_text('{"name": "obsidian", "description": "Vault files"}')
    assert marketplace.add(str(root)).plugins[0]["name"] == "obsidian"
    assert plugin_install.install("obsidian@obsidian-skills") == ("obsidian", 1)
    plugin = plugins.discover()[0]
    assert (plugin.name, plugin.marketplace) == ("obsidian", "obsidian-skills")
    assert [s.name for s in skills.discover()] == ["obsidian:obsidian-cli"]


def test_entry_selects_only_its_skills_and_refresh_keeps_the_selection(tmp_path, config):
    # The layout of anthropics/skills: several entries share one folder.
    root = catalog(tmp_path / "repo", [
        {"name": "docs", "source": "./", "strict": False, "skills": ["./skills/pdf"]},
        {"name": "art", "source": "./", "strict": False, "skills": ["./skills/canvas"]}])
    skill(root, "pdf")
    skill(root, "canvas")
    marketplace.add(str(root))
    assert plugin_install.install("docs@shelf") == ("docs", 1)
    assert [s.name for s in skills.discover()] == ["docs:pdf"]


async def test_refresh_keeps_marketplace_selection(tmp_path, config):
    root = catalog(tmp_path / "repo", [{"name": "docs", "source": "./", "skills": ["./skills/pdf"]}])
    skill(root, "pdf")
    skill(root, "canvas")
    marketplace.add(str(root))
    plugin_install.install("docs@shelf")
    await run(fake_app(config), "refresh docs")
    plugin = plugins.discover()[0]
    assert [p.parent.name for p in plugin.skills] == ["pdf"]
    assert plugin.marketplace == "shelf"


def test_relative_source_cannot_leave_the_catalog(tmp_path):
    outside = tmp_path / "outside"
    skill(outside, "secret")
    root = catalog(tmp_path / "repo", [{"name": "evil", "source": "../outside"}])
    marketplace.add(str(root))
    with pytest.raises(ValueError, match="leaves"):
        plugin_install.install("evil@shelf")
    assert not plugins.discover()


def test_symlinked_plugin_source_is_refused(tmp_path):
    root = catalog(tmp_path / "repo", [{"name": "linked", "source": "./link"}])
    skill(root / "real", "one")
    try:
        (root / "link").symlink_to(root / "real", target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    marketplace.add(str(root))
    with pytest.raises(ValueError, match="symlinks"):
        plugin_install.install("linked@shelf")


@pytest.mark.parametrize("address", [
    "ext::sh -c touch%20x", "file:///etc", "http://example.com/a.git", "--upload-pack=x/y",
    "https://user:token@example.com/a.git", "../up"])
def test_unsafe_addresses_are_refused(address):
    with pytest.raises(ValueError):
        marketplace.git_url(address)


def test_remote_entries_clone_the_pinned_commit(tmp_path, monkeypatch):
    calls = []

    def clone(url, destination, *, ref="", sha="", progress=None):
        calls.append((url, ref, sha))
        skill(destination / "plugins/tool", "one")

    monkeypatch.setattr(plugin_install, "clone", clone)
    sha = "a" * 40
    root = catalog(tmp_path / "repo", [
        {"name": "tool", "source": {"source": "git-subdir", "url": "https://example.com/r.git",
                                    "path": "plugins/tool", "ref": "main", "sha": sha}},
        {"name": "npm-thing", "source": {"source": "npm", "package": "x"}},
        {"name": "bad-sha", "source": {"source": "url", "url": "https://example.com/r.git", "sha": "--evil"}}])
    marketplace.add(str(root))
    assert plugin_install.install("tool@shelf") == ("tool", 1)
    assert calls == [("https://example.com/r.git", "main", sha)]
    with pytest.raises(ValueError, match="npm"):
        plugin_install.install("npm-thing@shelf")
    with pytest.raises(ValueError, match="invalid"):
        plugin_install.install("bad-sha@shelf")


def test_github_catalog_add_update_remove(tmp_path, monkeypatch):
    version = {"count": 1}

    def clone(url, destination, *, ref="", sha="", progress=None):
        assert url == "https://github.com/acme/shelf.git"
        (destination / ".git").mkdir(parents=True)
        catalog(destination, [{"name": f"p{i}", "source": "./"} for i in range(version["count"])])

    monkeypatch.setattr(plugin_install, "clone", clone)
    assert len(marketplace.add("acme/shelf").plugins) == 1
    assert not (marketplace.directory() / "shelf/.git").exists()
    with pytest.raises(ValueError, match="already added"):
        marketplace.add("acme/shelf")
    version["count"] = 3
    assert len(marketplace.update("shelf")[0].plugins) == 3
    assert len(marketplace.known()[0].plugins) == 3
    marketplace.remove("shelf")
    assert marketplace.known() == []
    assert not (marketplace.directory() / "shelf").exists()


def test_removing_a_local_catalog_keeps_its_folder(tmp_path):
    root = catalog(tmp_path / "repo", [])
    marketplace.add(str(root))
    marketplace.remove("shelf")
    assert root.is_dir()


def test_bare_name_needs_to_be_unambiguous(tmp_path):
    for name in ("one", "two"):
        root = catalog(tmp_path / name, [{"name": "tool", "source": "./"}], name=name)
        skill(root, "s")
        marketplace.add(str(root))
    with pytest.raises(ValueError, match="several"):
        plugin_install.install("tool")
    assert plugin_install.install("tool@two") == ("tool", 1)


async def test_typed_commands_match_claude_code(tmp_path, config):
    root = catalog(tmp_path / "repo", [{"name": "tool", "source": "./", "description": "A tool"}])
    skill(root, "one")
    app = fake_app(config)
    await run(app, f"marketplace add {root}")
    assert "/plugin install tool@shelf" in app.said[-1]
    await run(app, "marketplace list")
    assert "shelf (1 plugin)" in app.said[-1]
    await run(app, "install tool@shelf")
    assert "installed tool" in app.said[-1]
    await run(app, "disable tool@shelf")
    assert not config.plugin_enabled("tool")
    await run(app, "enable tool")
    assert config.plugin_enabled("tool")
    await run(app, "list")
    assert app.said[-1] == "tool@shelf: untrusted"
    await run(app, "marketplace update shelf")
    assert "updated shelf" in app.said[-1]
    await run(app, "marketplace remove shelf")
    assert plugins.discover()[0].name == "tool"
    await run(app, "marketplace add")
    assert "usage" in app.said[-1]
    await run(app, "marketplace add acme/missing/too/deep")
    assert "failed" in app.said[-1]


async def test_uninstall_confirms_and_clears_activation(tmp_path, config):
    root = tmp_path / "tool"
    skill(root, "one")
    plugin_install.install(str(root))
    config.set("plugin_trust", {"tool": True, "other": True})
    config.set_skill("tool:one", False)
    await run(fake_app(config, ["no"]), "uninstall tool")
    assert plugins.discover()
    await run(fake_app(config, ["yes"]), "uninstall tool")
    assert not plugins.discover()
    assert not (paths.skills_dir() / "tool").exists()
    assert config.get("plugin_trust") == {"other": True}
    assert config.get("skills") == {}


async def test_uninstall_leaves_a_users_own_skills_folder(tmp_path, config):
    root = tmp_path / "hooks-only"
    (root / "commands").mkdir(parents=True)
    (root / "commands/go.md").write_text("Go")
    plugin_install.install(str(root))
    mine = paths.skills_dir() / "hooks-only" / "note.md"
    mine.parent.mkdir(parents=True)
    mine.write_text("mine")
    await run(fake_app(config, ["yes"]), "uninstall hooks-only")
    assert mine.exists()


async def test_menu_has_three_tabs_and_remembers_the_tab(tmp_path, config):
    root = catalog(tmp_path / "repo", [{"name": "tool", "source": "./", "description": "A tool"}])
    skill(root, "one")
    marketplace.add(str(root))
    app = fake_app(config, ["install:tool@shelf"])
    await run(app, "")
    tab, tabs = app.shown[0]
    assert [tab[0] for tab in tabs] == ["Installed", "Marketplace", "Stats"]
    assert tabs[0][1] == []
    keys = [row[0] for row in tabs[1][1]]
    assert keys[:2] == ["market-add:", "market:shelf"]
    assert "install:tool@shelf" in keys and "install:ponytail" in keys
    assert "installed tool" in app.said[-1]
    # The next menu shows it installed, in every tab.
    _, after = app.shown[1]
    assert [row[0] for row in after[0][1]] == ["installed:tool"]
    assert "installed:tool" in [row[0] for row in after[1][1]]
    assert "installed:tool" in [row[0] for row in after[2][1]]


def test_stats_table_lines_up_under_its_header(tmp_path, config):
    root = tmp_path / "tool"
    skill(root, "one")
    (root / "commands").mkdir()
    (root / "commands/go.md").write_text("Go")
    plugin_install.install(str(root))
    header, rows = plugin_stats.table(config)
    assert header[0][0].startswith("Active: 0/1 plugins · 0/1 skills · 0/0 MCP")
    config.set("plugin_trust", {"tool": True})
    header, rows = plugin_stats.table(config)
    assert header[0][0].startswith("Active: 1/1 plugins · 1/1 skills · 0/0 MCP")
    columns, row = header[-1][1], rows[0]
    assert row[0] == "installed:tool"
    assert len(row[2]) == len(columns)
    assert row[2].split() == ["1", "1", "–", "–", row[2].split()[4], "on"]
    # Every value ends exactly where its column title does.
    ends = lambda text: [match.end() for match in re.finditer(r"\S+", text)]
    assert ends(columns) == ends(row[2])
    config.set_plugin("tool", False)
    assert plugin_stats.table(config)[0][0][0].startswith("Active: 0/1 plugins")
    assert plugin_stats.table(config)[1][0][2].endswith("off")


async def test_picker_header_is_pinned_and_tabs_keep_their_height():
    from textual.app import App
    from eirene.ui.picker import Picker

    class Host(App):
        def compose(self):
            yield Picker(right_hint=True)

    host = Host()
    async with host.run_test(size=(80, 24)) as pilot:
        picker = host.query_one(Picker)
        rows = [(f"r{i}", f"row {i}", "", "detail") for i in range(15)]
        tabs = [("A", [("a", "only", "", "detail")]), ("B", rows, [("Totals", ""), ("", ""), ("Name", "Count")])]
        task = asyncio.create_task(picker.choose("T", [], tabs=tabs))
        await pilot.pause()
        first = picker.render().plain.splitlines()
        assert first[2] == "" and first[3].strip() == "→ only"  # A gap under the tabs.
        await pilot.press("tab", *["down"] * 12)
        second = picker.render().plain.splitlines()
        assert second[2] == "" and second[3].strip() == "Totals" and "Count" in second[5]
        assert len(first) == len(second)
        await pilot.press("escape")
        assert await task is None


def _names(config):
    return {c.name: c for c in plugin_commands.commands(config)}


def test_a_users_skill_adds_commands(config):
    folder = skill(paths.home(), "tidy", "---\ndescription: Tidy things\n---\nTidy.")
    (folder / "commands").mkdir()
    (folder / "commands/sweep.md").write_text("---\ndescription: Sweep\n---\nSweep $ARGUMENTS.")
    (paths.skills_dir() / "flat.md").write_text("# Flat\nFlat.")
    names = _names(config)
    assert names["tidy"].summary == "Tidy things"
    assert names["sweep"].summary == "Sweep"
    assert "flat" in names
    assert names["skill:tidy"].hidden
    config.set_skill("tidy", False)
    names = _names(config)
    assert "tidy" not in names and "sweep" not in names
    assert "flat" in names


def test_skill_folder_group_adds_commands(config):
    group = paths.skills_dir() / "writing"
    (group / "tone").mkdir(parents=True)
    (group / "tone/SKILL.md").write_text("# Tone\nBe plain.")
    (group / "commands").mkdir()
    (group / "commands/draft.md").write_text("Draft it.")
    names = _names(config)
    assert {"tone", "draft", "writing:tone", "writing:draft"} <= set(names)
    assert not any(name == "writing" for name in names)


def test_skill_cannot_replace_a_builtin_or_opt_out_of_rules(config):
    from eirene.commands import _load
    _load()
    skill(paths.home(), "help", "# Help\nMine.")
    skill(paths.home(), "quiet", "---\nuser-invocable: false\n---\nHidden.")
    names = _names(config)
    assert "help" not in names and "skill:help" in names and not names["skill:help"].hidden
    assert "quiet" not in names and "skill:quiet" not in names


@pytest.mark.usefixtures("trusted_plugins")
def test_plugin_skill_commands_are_imported_and_follow_the_skill(tmp_path, config):
    root = tmp_path / "bundle"
    folder = skill(root, "one")
    (folder / "commands").mkdir()
    (folder / "commands/launch.md").write_text("Launch.")
    plugin_install.install(str(root))
    assert "launch" in _names(config)
    config.set_skill("bundle:one", False)
    assert "launch" not in _names(config)


async def test_skills_add_installs_through_the_plugin_path(tmp_path, config):
    root = catalog(tmp_path / "repo", [{"name": "tool", "source": "./"}])
    skill(root, "one")
    marketplace.add(str(root))
    app = fake_app(config)
    await skills_run(app, "add tool@shelf")
    assert "installed tool" in app.said[-1]
    assert skills.discover()[0].name == "tool:one"
    from eirene.core.errors import CommandError
    with pytest.raises(CommandError, match="usage"):
        await skills_run(app, "add")


async def test_picker_tabs_move_with_tab_and_keep_focus():
    from textual.app import App
    from eirene.ui.picker import Picker

    class Host(App):
        def compose(self):
            yield Picker(right_hint=True)

    host = Host()
    async with host.run_test(size=(80, 24)) as pilot:
        picker = host.query_one(Picker)
        tabs = [("A", [("a1", "first", ""), ("a2", "second", "")]), ("B", []), ("C", [("c1", "third", "")])]
        task = asyncio.create_task(picker.choose("T", [], tabs=tabs))
        await pilot.pause()
        await pilot.press("down", "tab")
        assert (picker.tab, picker.index) == (1, 0)
        await pilot.press("enter")  # An empty tab has nothing to choose.
        assert picker.waiting
        await pilot.press("tab")
        assert picker.tab == 2
        await pilot.press("tab", "shift+tab", "right", "t", "h")
        assert (picker.tab, picker.filter) == (0, "th")
        await pilot.press("left")
        assert (picker.tab, picker.filter) == (2, "")
        await pilot.press("enter")
        assert await task == "c1"


async def test_app_tab_keys_change_tabs_not_the_permission_mode(tmp_path, box):
    from eirene.app import Eirene
    from eirene.ui.composer import Prompt

    app = Eirene(box.root)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        mode = app.agent.mode
        await app.on_prompt_sent(Prompt.Sent("/plugins"))
        await pilot.pause()
        assert app.picker.waiting and app.picker.tab == 0
        await pilot.press("tab")
        assert app.picker.tab == 1
        assert app.picker.has_focus
        await pilot.press("shift+tab")
        assert app.picker.tab == 0
        assert app.agent.mode is mode
        await pilot.press("escape")
        await app.command
        assert not app.picker.waiting
        await pilot.press("shift+tab")
        assert app.agent.mode is not mode


def source_plugin(tmp_path, name="tool"):
    root = tmp_path / name
    skill(root, "one", "---\ndescription: First\n---\nv1")
    (root / "plugin.json").write_text(json.dumps({"name": name}))
    plugin_install.install(str(root))
    return root


async def test_update_replaces_files_and_keeps_preferences(tmp_path, config):
    root = source_plugin(tmp_path)
    config.set_skill("tool:one", False)
    (root / "skills/one/SKILL.md").write_text("---\ndescription: First\n---\nv2")
    skill(root, "two")
    app = fake_app(config)
    await run(app, "update tool")
    assert "updated tool: 2 skills" in app.said[-1]
    assert (paths.skills_dir() / "tool/one/SKILL.md").read_text().endswith("v2")
    assert (paths.skills_dir() / "tool/two/SKILL.md").is_file()
    assert (paths.plugins_dir() / "tool/skills/two/SKILL.md").is_file()
    assert config.skill_enabled("tool:one") is False
    assert "saved a copy" not in app.said[-1]  # Nothing was edited.


async def test_update_with_no_change_keeps_approvals_and_edits(tmp_path, config):
    source_plugin(tmp_path)
    config.set("plugin_trust", {"tool": True})
    edited = paths.skills_dir() / "tool/one/SKILL.md"
    edited.write_text("my edit")
    app = fake_app(config)
    await run(app, "update tool")
    assert "already up to date" in app.said[-1]
    assert config.get("plugin_trust") == {"tool": True}
    assert edited.read_text() == "my edit"


async def test_changed_code_needs_trust_again(tmp_path, config):
    root = source_plugin(tmp_path)
    config.set("plugin_trust", {"tool": True, "other": True})
    (root / "helper.js").write_text("changed, while the hook command text stays the same")
    app = fake_app(config)
    await run(app, "update tool")
    assert config.get("plugin_trust") == {"other": True}
    assert "whole plugin is off until you trust it again" in app.said[-1]


async def test_update_backs_up_edited_skills(tmp_path, config):
    root = source_plugin(tmp_path)
    (paths.skills_dir() / "tool/one/SKILL.md").write_text("my edit")
    (root / "skills/one/SKILL.md").write_text("v2")
    app = fake_app(config)
    await run(app, "update tool")
    backups = list((paths.home() / "plugin-data/tool").glob("skills-backup-*"))
    assert len(backups) == 1 and (backups[0] / "one/SKILL.md").read_text() == "my edit"
    assert str(backups[0]) in app.said[-1]


async def test_failed_update_leaves_the_plugin_working(tmp_path, config, monkeypatch):
    root = source_plugin(tmp_path)
    (root / "skills/one/SKILL.md").write_text("v2")
    def broken(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(plugin_install, "export_skills", broken)
    app = fake_app(config)
    await run(app, "update tool")
    assert "update failed: disk full" in app.said[-1]
    assert (paths.skills_dir() / "tool/one/SKILL.md").read_text().endswith("v1")
    assert (paths.plugins_dir() / "tool/skills/one/SKILL.md").read_text().endswith("v1")
    assert plugins.discover()[0].name == "tool"


async def test_update_refreshes_the_catalog_and_keeps_the_installed_name(tmp_path, config):
    root = catalog(tmp_path / "repo", [{"name": "tool", "source": "./a"}])
    skill(root / "a", "one")
    marketplace.add(str(root))
    plugin_install.install("tool@shelf")
    # The catalog moves the plugin, and upstream renames it.
    skill(root / "b", "one", "moved")
    (root / "b/plugin.json").write_text('{"name": "renamed"}')
    catalog(root, [{"name": "tool", "source": "./b"}])
    app = fake_app(config)
    await run(app, "update tool@shelf")
    assert "updated tool" in app.said[-1]
    plugin = plugins.discover()[0]
    assert (plugin.name, plugin.marketplace) == ("tool", "shelf")
    assert skills.load(skills.discover()[0]) == "moved"


async def test_update_all_reports_each_and_explains_untracked_installs(tmp_path, config):
    source_plugin(tmp_path)
    source_plugin(tmp_path, "older")
    index = paths.plugins_dir() / "older/.eirene-plugin.json"
    body = json.loads(index.read_text())
    del body["install_source"]
    index.write_text(json.dumps(body))
    app = fake_app(config)
    await run(app, "update")
    assert any("older: update failed" in line and "uninstall" in line for line in app.said)
    assert "tool is already up to date" in app.said


async def test_refresh_keeps_the_update_origin(tmp_path, config):
    root = source_plugin(tmp_path)
    await run(fake_app(config), "refresh tool")
    (root / "skills/one/SKILL.md").write_text("v2")
    app = fake_app(config)
    await run(app, "update tool")
    assert "updated tool" in app.said[-1]


async def test_retired_catalog_shortcut_explains_how_to_move_on(tmp_path, config):
    source_plugin(tmp_path)
    index = paths.plugins_dir() / "tool/.eirene-plugin.json"
    body = json.loads(index.read_text())
    del body["install_source"]
    body["catalog_shortcut"] = "retired-bundle"
    index.write_text(json.dumps(body))
    app = fake_app(config)
    await run(app, "update tool")
    assert "before updates were tracked" in app.said[-1]


async def test_added_marketplace_plugins_are_visible_without_scrolling(tmp_path, config):
    root = catalog(tmp_path / "repo", [{"name": "tool", "source": "./"}])
    skill(root, "one")
    marketplace.add(str(root))
    app = fake_app(config)
    await run(app, "")
    keys = [row[0] for row in app.shown[0][1][1][1]]
    assert keys[:3] == ["market-add:", "market:shelf", "install:tool@shelf"]


async def test_opening_a_marketplace_offers_its_plugins(tmp_path, config):
    root = catalog(tmp_path / "repo", [{"name": "tool", "source": "./"}])
    skill(root, "one")
    marketplace.add(str(root))
    menus = []
    app = fake_app(config, ["market:shelf"])
    async def choose(title, options, **kwargs):
        menus.append([row[0] for row in options])
        return "install:tool@shelf" if len(menus) == 1 else None
    app.ask_choice = choose
    await run(app, "")
    assert menus[0] == ["install:tool@shelf", "update", "remove"]
    assert plugins.discover()[0].name == "tool"


async def test_interface_shows_a_bar_that_moves_and_then_goes_away(tmp_path, monkeypatch, workdir):
    from eirene.app import Eirene
    from eirene.commands import dispatch
    from eirene.ui.install_progress import InstallProgress

    seen = []
    release = asyncio.Event()

    def clone(url, destination, *, ref="", sha="", progress=None):
        progress("Receiving objects", .5)
        loop.call_soon_threadsafe(release.set)
        gate.wait(5)
        catalog(destination, [{"name": "tool", "source": "./"}])

    monkeypatch.setattr(plugin_install, "clone", clone)
    import threading
    gate = threading.Event()
    loop = asyncio.get_running_loop()
    app = Eirene(workdir)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        task = asyncio.create_task(dispatch(app, "/plugin marketplace add acme/shelf"))
        await asyncio.wait_for(release.wait(), 5)
        await pilot.pause()
        bar = app.query_one(InstallProgress)
        seen.append(bar._text().plain)
        gate.set()
        await task
        await pilot.pause()
        assert not app.query(InstallProgress)
    assert "Adding marketplace acme/shelf" in seen[0] and "Receiving objects" in seen[0]
    assert " 47%" in seen[0]


def test_bar_never_moves_backward():
    from eirene.ui.install_progress import InstallProgress
    bar = InstallProgress("Adding")
    bar.update = lambda *a: None
    bar.advance("Receiving objects", .6)
    bar.advance("Resolving deltas", .2)
    assert (bar.percent, bar.stage) == (60, "Resolving deltas")
