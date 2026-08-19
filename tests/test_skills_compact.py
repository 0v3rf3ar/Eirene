"""Skills discovery and history compaction."""

from __future__ import annotations

import pytest

from eirene.core import paths, skills
from eirene.core.compact import compact
from eirene.core.config import Config
from eirene.core.errors import ProviderError
from eirene.core.session import Message, Session
from eirene.providers.base import Done, TextDelta


def write_skill(name: str, body: str) -> None:
    (paths.skills_dir() / f"{name}.md").write_text(body, encoding="utf-8")


def test_discover_reads_title_and_summary():
    write_skill("deploy", "# Deploying\nPush with rsync over ssh.\n")
    found = skills.discover()
    assert len(found) == 1
    assert found[0].name == "deploy"
    assert found[0].title == "Deploying"
    assert found[0].summary == "Push with rsync over ssh."


def test_discover_falls_back_to_the_filename():
    write_skill("bare", "just text, no heading")
    assert skills.discover()[0].title == "bare"


def test_non_markdown_is_ignored():
    (paths.skills_dir() / "notes.txt").write_text("nope", encoding="utf-8")
    assert skills.discover() == []


def test_missing_skills_dir_is_fine(monkeypatch, tmp_path):
    monkeypatch.setenv(paths.ENV_HOME, str(tmp_path / "nothing"))
    assert skills.discover() == []


def test_enabled_block_joins_bodies():
    write_skill("a", "# A\nfirst")
    write_skill("b", "# B\nsecond")
    found = skills.discover()
    block = skills.enabled_block(found)
    assert "first" in block and "second" in block


def test_disabled_skills_are_left_out():
    write_skill("a", "# A\nfirst")
    write_skill("b", "# B\nsecond")
    found = skills.discover()
    found[1].enabled = False
    block = skills.enabled_block(found)
    assert "first" in block and "second" not in block


def test_no_skills_means_no_block():
    assert skills.enabled_block([]) == ""


def test_config_drives_the_enabled_flag():
    write_skill("a", "# A\nx")
    config = Config.load()
    config.set_skill("a", False)
    found = skills.apply_config(skills.discover(), config)
    assert found[0].enabled is False


def test_oversized_skill_is_truncated():
    write_skill("big", "# Big\n" + "x" * (skills.MAX_SKILL_BYTES + 5000))
    body = skills.load(skills.discover()[0])
    assert "skill truncated" in body


def test_unreadable_skill_is_skipped(monkeypatch):
    write_skill("a", "# A\nx")
    skill = skills.discover()[0]
    skill.path.unlink()
    assert skills.load(skill) == ""


class Summariser:
    """Provider stub that returns a fixed summary."""

    supports_tools = True

    def __init__(self, text="the user wanted a build script; it exists now"):
        self.text = text
        self.systems = []

    async def stream(self, messages, model, *, system="", tools=None, max_tokens=8192):
        self.systems.append(system)
        yield TextDelta(self.text)
        yield Done("stop")


async def test_compact_shrinks_and_keeps_the_summary(workdir):
    session = Session.create(workdir)
    for index in range(12):
        session.add_user("please do a fairly long thing " * 20)
        session.add_assistant("here is a fairly long answer " * 20)

    before, after, summary = await compact(session, Summariser(), "m")
    assert after < before
    assert "build script" in summary
    assert session.messages[0]["role"] == "user"
    assert "Summary of the conversation" in session.messages[0]["content"]


async def test_compact_survives_a_reload(workdir):
    session = Session.create(workdir)
    session.add_user("a" * 400)
    session.add_assistant("b" * 400)
    session.add_user("c" * 400)
    await compact(session, Summariser(), "m")
    session.close()

    resumed = Session.resume(session.id)
    assert "Summary of the conversation" in resumed.messages[0]["content"]
    resumed.close()


async def test_compact_never_orphans_a_tool_result(workdir):
    session = Session.create(workdir)
    session.add_user("go")
    session.add_assistant("", [{"id": "c1", "name": "list_dir", "arguments": {}}])
    session.add_tool_result("c1", "list_dir", "a.txt")
    session.add_assistant("done")
    await compact(session, Summariser(), "m")
    roles = [m["role"] for m in session.messages]
    assert "tool" not in roles or roles.index("tool") > roles.index("assistant")
    for index, role in enumerate(roles):
        if role == "tool":
            assert session.messages[index - 1].get("tool_calls")


async def test_compact_refuses_an_empty_conversation(workdir):
    session = Session.create(workdir)
    with pytest.raises(ProviderError):
        await compact(session, Summariser(), "m")


async def test_compact_refuses_an_empty_summary(workdir):
    session = Session.create(workdir)
    session.add_user("a")
    session.add_assistant("b")
    session.add_user("c")
    with pytest.raises(ProviderError):
        await compact(session, Summariser(""), "m")


async def test_compact_uses_its_own_prompt(workdir):
    session = Session.create(workdir)
    session.add_user("a")
    session.add_assistant("b")
    session.add_user("c")
    provider = Summariser()
    await compact(session, provider, "m")
    assert "Summarise this conversation" in provider.systems[0]


def test_front_matter_gives_a_name_and_description(eirene_home):
    from eirene.core import paths, skills as skills_mod

    (paths.skills_dir() / "deploy.md").write_text(
        "---\nname: Deploy to production\n"
        "description: Ship the built artefact and check it came up.\n---\n\n"
        "Run the deploy script, then curl the health endpoint.\n",
        encoding="utf-8")
    found = skills_mod.discover()
    assert [s.name for s in found] == ["deploy"]
    assert found[0].title == "Deploy to production"
    assert found[0].description == "Ship the built artefact and check it came up."


def test_the_header_is_not_sent_to_the_model(eirene_home):
    from eirene.core import paths, skills as skills_mod

    (paths.skills_dir() / "one.md").write_text(
        "---\nname: One\ndescription: A thing.\n---\n\nThe body only.\n",
        encoding="utf-8")
    skill = skills_mod.discover()[0]
    assert skills_mod.load(skill) == "The body only."
    block = skills_mod.enabled_block([skill])
    assert "# Skill: One" in block
    assert "Use when: A thing." in block
    assert "---" not in block


def test_a_skill_without_front_matter_still_works(eirene_home):
    from eirene.core import paths, skills as skills_mod

    (paths.skills_dir() / "plain.md").write_text(
        "# Plain skill\n\nDo the plain thing.\n", encoding="utf-8")
    skill = skills_mod.discover()[0]
    assert skill.title == "Plain skill"
    assert skill.description == "Do the plain thing."
    assert "Do the plain thing." in skills_mod.load(skill)


def test_a_broken_header_is_treated_as_body(eirene_home):
    from eirene.core import paths, skills as skills_mod

    (paths.skills_dir() / "odd.md").write_text(
        "---\nname: never closed\n\nstill going\n", encoding="utf-8")
    skill = skills_mod.discover()[0]
    assert "never closed" in skills_mod.load(skill)


def test_the_examples_ship_with_the_source():
    from eirene.core import skills as skills_mod

    found = sorted(skills_mod.examples_dir().glob("*.md"))
    assert len(found) >= 2
    for path in found:
        fields, body = skills_mod.split_front_matter(
            path.read_text(encoding="utf-8"))
        assert fields.get("name"), f"{path.name} needs a name"
        assert fields.get("description"), f"{path.name} needs a description"
        assert body.strip(), f"{path.name} needs a body"


def test_the_examples_are_copied_once(eirene_home):
    from eirene.core import paths, skills as skills_mod

    assert skills_mod.seed() >= 2
    names = {p.name for p in paths.skills_dir().glob("*.md")}
    assert "systemd-service.md" in names
    assert "python-project.md" in names

    assert skills_mod.seed() == 0, "the examples arrive once, not every run"
    for path in paths.skills_dir().glob("*.md"):
        path.unlink()
    assert skills_mod.seed() == 0, "deleted skills stay deleted"


def test_the_shipped_examples_describe_themselves(eirene_home):
    from eirene.core import skills as skills_mod

    skills_mod.seed()
    found = {s.name: s for s in skills_mod.discover()}
    assert "systemd" in found["systemd-service"].description.lower()
    assert found["python-project"].description
    assert all(s.title and s.description for s in found.values())
