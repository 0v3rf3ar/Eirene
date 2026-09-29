"""Portable skill imports and their activation in Eirene."""

import pytest

from eirene.core import paths, plugins, skills
from eirene.core.config import Config
from eirene.core.plugin_install import github_source, install


def repository(tmp_path):
    root = tmp_path / "ponytail"
    skill = root / "skills" / "ponytail"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: ponytail\ndescription: >\n  Keep code simple.\n"
        "  Reuse existing features.\n---\n# Ponytail\nPrefer built-ins.\n"
    )
    (skill / "reference.txt").write_text("supporting content")
    (root / "LICENSE").write_text("license")
    (root / "plugin.json").write_text('{"hooks":{"before_tool":["unsafe"]}}')
    return root


def test_import_preserves_resources_and_loads_namespaced_skill(tmp_path):
    root = repository(tmp_path)
    assert install(str(root)) == ("ponytail", 1)
    found = skills.apply_config(skills.discover(), Config.load())
    assert len(found) == 1
    assert found[0].name == "ponytail:ponytail"
    assert found[0].summary == "Keep code simple. Reuse existing features."
    assert "Prefer built-ins." in skills.load(found[0])
    installed = paths.plugins_dir() / "ponytail"
    assert (installed / "skills/ponytail/reference.txt").read_text() == "supporting content"
    assert (installed / "LICENSE").exists()
    assert plugins.merged_hooks(Config.load())["before_tool"] == []
    with pytest.raises(ValueError, match="already installed"):
        install(str(root))


def test_plugin_toggle_disables_its_skills(tmp_path):
    install(str(repository(tmp_path)))
    config = Config.load()
    config.set_plugin("ponytail", False)
    assert not skills.apply_config(skills.discover(), config)[0].enabled
    config.set_plugin("ponytail", True)
    assert skills.apply_config(skills.discover(), config)[0].enabled


def test_standard_standalone_skill(tmp_path):
    root = paths.skills_dir() / "simple"
    root.mkdir()
    (root / "SKILL.md").write_text("# Simple\nKeep it simple.")
    assert skills.discover()[0].name == "simple"


def test_rejects_symlinks_without_partial_install(tmp_path):
    root = repository(tmp_path)
    try:
        (root / "escape").symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError, match="symlinks"):
        install(str(root))
    assert not (paths.plugins_dir() / "ponytail").exists()


def test_github_download_uses_fixed_https_url(tmp_path, monkeypatch):
    root = repository(tmp_path)

    def clone(argv, **kwargs):
        import shutil
        from types import SimpleNamespace
        assert argv[-2] == "https://github.com/DietrichGebert/ponytail.git"
        shutil.copytree(root, argv[-1])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("eirene.core.plugin_install.subprocess.run", clone)
    assert install("https://github.com/DietrichGebert/ponytail.git") == ("ponytail", 1)


@pytest.mark.parametrize("source", ["--upload-pack=bad", "https://example.org/a/b", "../.."])
def test_rejects_invalid_sources(source):
    with pytest.raises(ValueError):
        install(source)


async def test_install_command_reloads_skills(tmp_path):
    from types import SimpleNamespace
    from eirene.commands.plugins import run

    messages, reloads = [], []
    app = SimpleNamespace(say=messages.append,
                          agent=SimpleNamespace(reload_skills=lambda: reloads.append(True)))
    await run(app, f"install {repository(tmp_path)}")
    assert reloads == [True]
    assert "installed ponytail: 1 skills" in messages[-1]


@pytest.mark.parametrize("source, expected", [
    ("owner/repo", ("owner", "repo", "", None)),
    ("https://github.com/owner/repo.git/", ("owner", "repo", "", None)),
    ("owner/repo/plugins/design", ("owner", "repo", "plugins/design", None)),
    ("https://github.com/owner/repo/tree/main/plugins/design",
     ("owner", "repo", "plugins/design", "main")),
])
def test_github_bundle_sources(source, expected):
    assert github_source(source) == expected


@pytest.mark.parametrize("source", [
    "owner/repo/../outside", "owner/repo/plugins//design", "owner/repo/.git",
    "owner/repo/tree/--bad/plugins/design", "owner/repo/tree/main",
    "https://github.com/owner/repo/tree/main/%2e%2e/secret",
])
def test_rejects_unsafe_subdirectory_sources(source):
    with pytest.raises(ValueError):
        github_source(source)


@pytest.mark.parametrize("source", [
    "anthropics/claude-plugins-official/plugins/frontend-design",
    "https://github.com/anthropics/claude-plugins-official/tree/main/plugins/frontend-design",
    "frontend-design",
])
def test_install_selected_bundle_preserves_only_its_resources(tmp_path, monkeypatch, source):
    import json
    import shutil
    from types import SimpleNamespace

    root = tmp_path / "marketplace"
    selected = root / "plugins/frontend-design"
    skill = selected / "skills/frontend-design"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Design\nDesign carefully.")
    (skill / "rules.txt").write_text("supporting rules")
    (selected / ".claude-plugin").mkdir()
    (selected / ".claude-plugin/plugin.json").write_text(json.dumps({"name": "frontend-design"}))
    (selected / "LICENSE").write_text("license")
    (root / "unrelated.txt").write_text("other plugins")

    def clone(argv, **kwargs):
        assert argv[-2] == "https://github.com/anthropics/claude-plugins-official.git"
        if "/tree/" in source:
            assert argv[argv.index("--branch") + 1] == "main"
        shutil.copytree(root, argv[-1])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("eirene.core.plugin_install.subprocess.run", clone)
    assert install(source) == ("frontend-design", 1)
    plugin = plugins.discover()[0]
    assert plugin.name == "frontend-design"
    assert (plugin.path / "skills/frontend-design/rules.txt").read_text() == "supporting rules"
    assert (plugin.path / "LICENSE").exists()
    assert not (plugin.path / "unrelated.txt").exists()
    assert skills.discover()[0].name == "frontend-design:frontend-design"


@pytest.mark.parametrize("symlink", [False, True])
def test_missing_or_symlink_bundle_does_not_install(tmp_path, monkeypatch, symlink):
    import shutil
    from types import SimpleNamespace
    root = tmp_path / "marketplace"
    root.mkdir()
    if symlink:
        target = root / "actual"
        target.mkdir()
        try:
            (root / "plugins").symlink_to(target, target_is_directory=True)
        except OSError:
            pytest.skip("symlinks unavailable")
    def clone(argv, **kwargs):
        shutil.copytree(root, argv[-1], symlinks=True)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr("eirene.core.plugin_install.subprocess.run", clone)
    with pytest.raises(ValueError, match="symlinks|not found"):
        install("owner/repo/plugins")
    assert plugins.discover() == []


async def test_browse_lists_catalog_shortcuts():
    from types import SimpleNamespace
    from eirene.commands.plugins import run
    from eirene.core.plugin_catalog import BUNDLES, source_for
    messages = []
    await run(SimpleNamespace(say=messages.append), "browse")
    for name, source, _ in BUNDLES:
        assert f"/plugins install {name}" in messages[0]
        assert source_for(name) == source
