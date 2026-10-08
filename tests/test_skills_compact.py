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


def test_old_seeded_examples_are_removed_without_touching_custom_skills():
    target = paths.skills_dir()
    (target / skills.SEED_MARKER).write_text("examples copied once; delete to get them again\n")
    for path in skills.examples_dir().glob("*.md"):
        (target / path.name).write_text(path.read_text())
    (target / "custom.md").write_text("# Custom\nUser instructions")
    assert skills.remove_seeded_examples() == 2
    assert {skill.name for skill in skills.discover()} == {"custom"}
    assert skills.remove_seeded_examples() == 0


def test_edited_or_manually_added_examples_are_preserved():
    target = paths.skills_dir()
    source = skills.examples_dir() / "python-project.md"
    copied = target / source.name
    copied.write_text(source.read_text())
    assert skills.remove_seeded_examples() == 0
    (target / skills.SEED_MARKER).write_text("examples copied once; delete to get them again\n")
    copied.write_text(copied.read_text() + "\nMy custom rule")
    assert skills.remove_seeded_examples() == 0
    assert "My custom rule" in copied.read_text()


async def test_local_compaction_bounds_summary_requests_and_preserves_latest(workdir):
    from eirene.core.usage import estimate_messages
    session = Session.create(workdir)
    for _ in range(30):
        session.add_user("obsolete detail " * 200)
        session.add_assistant("completed " * 100)
    session.add_user("Continue the original task; preserve the database.")

    class BoundedSummariser(Summariser):
        calls = 0
        async def stream(self, messages, model, **kwargs):
            self.calls += 1
            assert estimate_messages(messages) + kwargs["max_tokens"] < 4096
            async for event in super().stream(messages, model, **kwargs):
                yield event

    provider = BoundedSummariser()
    before, after, _ = await compact(session, provider, "m", target_tokens=700, context_tokens=4096)
    assert provider.calls > 1
    assert after <= 700 < before
    assert session.messages[-1]["content"] == "Continue the original task; preserve the database."
    session.close()


async def test_compaction_keeps_observed_edits_even_when_summary_omits_them(workdir):
    session = Session.create(workdir)
    session.add_user("Fix the bug, then test it")
    session.add_assistant("", [{"id": "edit", "name": "edit_file", "arguments": {"path": "app.py"}}])
    session.add_tool_result("edit", "edit_file", "replaced one occurrence", artifact_id="a" * 32)
    for _ in range(8):
        session.add_assistant("old chatter " * 100)
    session.add_user("Continue with the tests")
    await compact(session, Summariser("Pending: tests"), "m", target_tokens=700, context_tokens=4096)
    memory = session.messages[1]["content"]
    assert "edit_file app.py" in memory and "replaced one occurrence" in memory
    assert "Do not repeat" in memory
    session.close()
    resumed = Session.resume(session.id)
    await compact(resumed, Summariser("Pending: tests"), "m", target_tokens=700, context_tokens=4096)
    assert "edit_file app.py" in resumed.messages[1]["content"]
    resumed.close()


async def test_automatic_compaction_falls_back_without_losing_latest_request(workdir):
    session = Session.create(workdir)
    for _ in range(10):
        session.add_user("old request " * 100)
        session.add_assistant("old answer " * 100)
    session.add_user("Preserve the database; finish the tests")
    _, after, _ = await compact(session, Summariser(""), "m", target_tokens=700,
                                context_tokens=4096, automatic=True)
    assert after <= 700
    assert session.messages[-1]["content"] == "Preserve the database; finish the tests"
    session.close()


def test_execution_memory_handles_rejected_arguments_and_tiny_limits():
    from eirene.core.tool_memory import execution_memory, shorten
    history = [Message.assistant("", [{"id": "bad", "name": "read_file", "arguments": ["bad"]}]),
               Message.tool("bad", "read_file", "arguments must be an object", True)]
    assert "FAILED" in execution_memory(history)
    for limit in (0, 1, 5, 20):
        assert len(shorten("long content " * 20, limit)) <= limit
