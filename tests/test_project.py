"""Project discovery, caching, instructions, and targeted search."""

from __future__ import annotations

import pytest

from eirene.core import paths, project
from eirene.core.errors import ToolError
from eirene.tools.files import search_text
from eirene.tools.files import find_symbol


def test_python_project_profile(workdir):
    (workdir / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (workdir / "AGENTS.md").write_text("Always run the tests.\n", encoding="utf-8")
    (workdir / "app.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
    profile = project.discover(workdir)
    assert profile.frameworks == ["Python"]
    assert "Python" in profile.languages
    assert profile.instructions == ["AGENTS.md"]
    assert "Always run the tests" in profile.prompt_block()
    assert "python -m pytest" in profile.commands


def test_profile_is_cached_and_invalidated(workdir):
    manifest = workdir / "package.json"
    manifest.write_text("{}", encoding="utf-8")
    first = project.discover(workdir)
    caches = list(paths.projects_dir().glob("*.json"))
    assert len(caches) == 1
    assert project.discover(workdir).frameworks == first.frameworks
    manifest.write_text('{"scripts":{"test":"node test.js"}}\n', encoding="utf-8")
    assert project.discover(workdir).frameworks == ["Node.js"]


def test_search_text_is_bounded_and_skips_dependencies(workdir, box):
    (workdir / "src").mkdir()
    (workdir / "src" / "a.py").write_text("needle one\nneedle two\n", encoding="utf-8")
    (workdir / "node_modules").mkdir()
    (workdir / "node_modules" / "hidden.py").write_text("needle hidden\n",
                                                           encoding="utf-8")
    result = search_text(box, "needle", ".", "**/*.py", 1)
    assert "src/a.py:1" in result
    assert "hidden" not in result
    assert "stopped after 1" in result


def test_search_text_reports_bad_regex(box):
    with pytest.raises(ToolError, match="bad regular expression"):
        search_text(box, "[", ".")


def test_profile_cache_never_contains_unrelated_file_contents(workdir):
    (workdir / "secret.txt").write_text("do-not-cache-this", encoding="utf-8")
    project.discover(workdir)
    cache = next(paths.projects_dir().glob("*.json"))
    assert "do-not-cache-this" not in cache.read_text(encoding="utf-8")


def test_find_symbol_locates_definitions(workdir, box):
    (workdir / "code.py").write_text("def target():\n    pass\n", encoding="utf-8")
    (workdir / "mention.py").write_text("target()\n", encoding="utf-8")
    result = find_symbol(box, "target")
    assert "code.py:1" in result
    assert "mention.py" not in result
