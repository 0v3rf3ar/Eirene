"""Config and session persistence."""

from __future__ import annotations

import json
import os

import pytest

from eirene.core import paths
from eirene.core.config import CONFIG_VERSION, Config
from eirene.core.errors import SessionError
from eirene.core.session import Session, list_sessions, read_records, replay


def test_defaults_when_missing():
    config = Config.load()
    assert config.mode == "manual"
    assert config.provider is None
    assert config.data["providers"] == {}


def test_save_and_reload():
    config = Config.load()
    config.provider = "anthropic"
    config.set_provider("anthropic", api_key="sk-ant-test", model="claude-x")
    config.save()
    again = Config.load()
    assert again.provider == "anthropic"
    assert again.api_key("anthropic") == "sk-ant-test"
    assert again.provider_config("anthropic")["model"] == "claude-x"


@pytest.mark.skipif(os.name == "nt", reason="posix permissions")
def test_config_is_private():
    config = Config.load()
    config.save()
    assert paths.config_file().stat().st_mode & 0o077 == 0


def test_corrupt_config_is_quarantined():
    paths.config_file().write_text("{not json", encoding="utf-8")
    config = Config.load()
    assert config.mode == "manual"
    assert paths.config_file().with_suffix(".json.bak").exists()


def test_non_dict_config_recovers():
    paths.config_file().write_text("[1,2,3]", encoding="utf-8")
    assert Config.load().mode == "manual"


def test_empty_config_recovers():
    paths.config_file().write_text("", encoding="utf-8")
    assert Config.load().provider is None


def test_bad_mode_is_normalised():
    paths.config_file().write_text(json.dumps({"mode": "chaos"}), encoding="utf-8")
    assert Config.load().mode == "manual"


def test_old_config_is_migrated_and_new_values_are_validated():
    paths.config_file().write_text(json.dumps({
        "version": 1, "shell_timeout": "bad", "max_tokens": 1,
        "log_level": "noisy", "log_backups": 999,
    }), encoding="utf-8")
    config = Config.load()
    assert config.data["version"] == CONFIG_VERSION
    assert config.get("shell_timeout") == 120
    assert config.get("max_tokens") == 512
    assert config.get("log_level") == "INFO"
    assert config.get("log_backups") == 20


def test_execution_isolation_is_validated():
    paths.config_file().write_text(json.dumps({
        "execution_isolation": "bubblewrap", "isolate_network": True,
    }), encoding="utf-8")
    config = Config.load()
    assert config.get("execution_isolation") == "auto"
    assert config.get("isolate_network") is True
    paths.config_file().write_text(json.dumps({"execution_isolation": "magic"}),
                                   encoding="utf-8")
    assert Config.load().get("execution_isolation") == "auto"


def test_env_key_wins(monkeypatch):
    config = Config.load()
    config.set_provider("chatgpt", api_key="stored")
    monkeypatch.setenv("EIRENE_CHATGPT_API_KEY", "from-env")
    assert config.api_key("chatgpt") == "from-env"


def test_forget_provider():
    config = Config.load()
    config.set_provider("kimi", api_key="k")
    assert config.forget_provider("kimi")
    assert not config.forget_provider("kimi")


def test_skill_toggles():
    config = Config.load()
    assert config.skill_enabled("deploy") is True
    config.set_skill("deploy", False)
    assert config.skill_enabled("deploy") is False


def test_session_writes_jsonl(workdir):
    session = Session.create(workdir)
    session.add_user("hello")
    session.add_assistant("hi", [{"id": "1", "name": "read_file",
                                  "arguments": {"path": "a"}}])
    session.add_tool_result("1", "read_file", "contents")
    session.close()

    records = list(read_records(session.path))
    assert records[0]["t"] == "meta"
    assert records[0]["sandbox"] == str(workdir)
    assert [r["t"] for r in records[1:]] == ["user", "assistant", "tool_result"]


def test_session_replay_round_trip(workdir):
    session = Session.create(workdir)
    session.add_user("q")
    session.add_assistant("a")
    session.close()
    rebuilt = replay(list(read_records(session.path)))
    assert [m["role"] for m in rebuilt] == ["user", "assistant"]


def test_session_round_trip_preserves_change_presentation(workdir):
    session = Session.create(workdir)
    session.add_user("update it")
    preview = "--- hello.py\n+++ hello.py\n@@ -1 +1 @@\n-old\n+new"
    session.add_assistant("", [{
        "id": "c1", "name": "edit_file", "arguments": {"path": "hello.py"},
        "label": "hello.py", "preview": preview, "action": "Update",
    }])
    session.add_tool_result("c1", "edit_file", "updated hello.py", seconds=1.25)
    session.close()

    rebuilt = replay(list(read_records(session.path)))
    call = rebuilt[1]["tool_calls"][0]
    assert call["preview"] == preview
    assert call["label"] == "hello.py" and call["action"] == "Update"
    assert rebuilt[2]["seconds"] == 1.25


def test_truncated_last_line_is_skipped(workdir):
    session = Session.create(workdir)
    session.add_user("one")
    session.close()
    with open(session.path, "a", encoding="utf-8") as handle:
        handle.write('{"t": "user", "content": "trun')
    records = list(read_records(session.path))
    assert [r["t"] for r in records] == ["meta", "user"]


def test_blank_lines_ignored(workdir):
    session = Session.create(workdir)
    session.add_user("one")
    session.close()
    with open(session.path, "a", encoding="utf-8") as handle:
        handle.write("\n\n\n")
    assert len(list(read_records(session.path))) == 2


def test_resume_restores_history(workdir):
    session = Session.create(workdir)
    session.add_user("first")
    session.add_assistant("second")
    session.close()

    resumed = Session.resume(session.id)
    assert resumed.sandbox == workdir
    assert [m["content"] for m in resumed.messages] == ["first", "second"]
    resumed.close()


def test_resume_missing_session():
    with pytest.raises(SessionError):
        Session.resume("does-not-exist")


def test_compact_replaces_history(workdir):
    session = Session.create(workdir)
    session.add_user("a")
    session.add_assistant("b")
    from eirene.core.session import Message
    session.replace_history([Message.user("summary")], "the summary")
    session.close()
    rebuilt = replay(list(read_records(session.path)))
    assert [m["content"] for m in rebuilt] == ["summary"]


def test_visual_replay_keeps_history_before_compaction(workdir):
    session = Session.create(workdir)
    session.add_user("original question")
    session.add_assistant("original answer")
    from eirene.core.session import Message
    session.replace_history([Message.user("summary")], "the summary")
    session.add_user("later question")
    session.close()
    records = list(read_records(session.path))

    model_history = replay(records)
    visual_history = replay(records, apply_compaction=False)
    assert [m["content"] for m in model_history] == ["summary", "later question"]
    assert [m["content"] for m in visual_history] == [
        "original question", "original answer", "later question"]


def test_list_sessions(workdir):
    session = Session.create(workdir)
    session.add_user("x")
    session.close()
    listed = list_sessions()
    assert listed[0]["id"] == session.id
    assert listed[0]["turns"] == 1


def test_nothing_is_written_before_the_first_input(workdir):
    session = Session.create(workdir)
    assert not session.path.exists()
    assert session.saved is False
    session.add_note("guard", reason="ignored")
    assert not session.path.exists()
    session.close()
    assert not session.path.exists()


def test_the_first_input_creates_the_file(workdir):
    session = Session.create(workdir)
    session.add_user("hello")
    assert session.path.exists()
    assert session.saved is True
    session.close()


def test_clear_destroys_the_log(workdir):
    session = Session.create(workdir)
    session.add_user("hello")
    session.add_assistant("hi")
    session.clear()
    assert not session.path.exists()
    assert session.messages == []
    session.close()
    assert not session.path.exists()


def test_writing_after_a_clear_starts_a_fresh_log(workdir):
    session = Session.create(workdir)
    session.add_user("first")
    session.clear()
    session.add_user("second")
    session.close()
    records = list(read_records(session.path))
    assert [r.get("content") for r in records if r["t"] == "user"] == ["second"]


def test_a_closed_session_stays_closed(workdir):
    session = Session.create(workdir)
    session.close()
    session.add_user("late")
    assert not session.path.exists()


def test_list_sessions_filters_by_directory(workdir, tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()
    mine = Session.create(workdir)
    mine.add_user("x")
    mine.close()
    theirs = Session.create(other)
    theirs.add_user("y")
    theirs.close()

    listed = list_sessions(sandbox=workdir)
    assert [info["id"] for info in listed] == [mine.id]
    assert [info["id"] for info in list_sessions(sandbox=other)] == [theirs.id]


def test_the_name_starts_from_the_first_input(workdir):
    from eirene.core.session import name_from

    session = Session.create(workdir)
    assert session.name == ""
    session.add_user("fix the ollama provider")
    session.add_user("and the tests")
    assert session.name == "Fix the ollama provider"
    session.close()
    meta = next(r for r in read_records(session.path) if r["t"] == "meta")
    assert meta["name"] == "Fix the ollama provider"
    assert name_from("") == "untitled"


def test_the_placeholder_drops_filler_openers():
    from eirene.core.session import name_from

    assert name_from("can you write a html workout plan for me") == "Write a html workout plan for…"
    assert name_from("please fix the build") == "Fix the build"
    assert name_from("hey eirene, deploy it") == "Deploy it"
    assert name_from("i want you to add tests") == "Add tests"


def test_a_model_title_replaces_the_placeholder(workdir):
    session = Session.create(workdir)
    session.add_user("can you write a html workout plan for me")
    placeholder = session.name
    session.rename("Futuristic weekly workout planner")
    assert session.name == "Futuristic weekly workout planner"
    assert session.name != placeholder
    session.close()
    records = list(read_records(session.path))
    assert records[-1]["t"] == "rename"
    assert Session.resume(session.id).name == "Futuristic weekly workout planner"


def test_renaming_to_nothing_is_ignored(workdir):
    session = Session.create(workdir)
    session.add_user("first task")
    before = session.name
    session.rename("")
    session.rename("   ")
    assert session.name == before
    session.close()


def test_a_model_title_is_tidied():
    from eirene.core.session import clean_title

    assert clean_title('"Weekly workout plan"') == "Weekly workout plan"
    assert clean_title("Title: fix the parser") == "Fix the parser"
    assert clean_title("weekly plan.") == "Weekly plan"
    assert clean_title("<think>hmm</think> Deploy script") == "Deploy script"


def test_a_rambling_title_is_refused():
    from eirene.core.session import clean_title

    assert clean_title("Sure! Here is a title for you: " + "word " * 20,
                       "fallback") == "fallback"
    assert clean_title("", "fallback") == "fallback"
    assert clean_title("   ") == ""


def test_a_long_first_input_is_shortened():
    from eirene.core.session import NAME_LIMIT, name_from

    name = name_from("elephant " * 40)
    assert len(name) <= NAME_LIMIT + 1
    assert name.endswith("…")


def test_the_name_ignores_folded_pastes():
    from eirene.core.session import name_from

    assert name_from("review this [pasted 40 lines]") == "Review this"
    assert name_from("[pasted 40 lines]") == "untitled"


def test_newlines_collapse_in_the_name():
    from eirene.core.session import name_from

    assert name_from("first line\nsecond line") == "First line second line"


def test_resume_restores_the_name(workdir):
    session = Session.create(workdir)
    session.add_user("deploy the thing")
    session.close()
    resumed = Session.resume(session.id)
    assert resumed.name == "Deploy the thing"
    resumed.close()


def test_clearing_forgets_the_name(workdir):
    session = Session.create(workdir)
    session.add_user("first topic")
    session.clear()
    assert session.name == ""
    session.add_user("second topic")
    assert session.name == "Second topic"
    session.close()


def test_list_sessions_carries_the_name(workdir):
    session = Session.create(workdir)
    session.add_user("write the readme")
    session.close()
    assert list_sessions()[0]["name"] == "Write the readme"
