"""Permission policy."""

from __future__ import annotations

import pytest

from eirene.core.modes import ALLOW, ASK, BLOCK, Mode, decide, next_mode, parse
from eirene.tools.registry import EXEC, READ, WRITE

TABLE = [
    (Mode.AUTO, READ, ALLOW), (Mode.AUTO, WRITE, ALLOW), (Mode.AUTO, EXEC, ALLOW),
    (Mode.MANUAL, READ, ASK), (Mode.MANUAL, WRITE, ASK), (Mode.MANUAL, EXEC, ASK),
    (Mode.PLAN, READ, ALLOW), (Mode.PLAN, WRITE, BLOCK), (Mode.PLAN, EXEC, BLOCK),
]


@pytest.mark.parametrize("mode,kind,expected", TABLE)
def test_policy_table(mode, kind, expected):
    verdict, _ = decide(mode, kind)
    assert verdict == expected


def test_manual_escape_asks():
    verdict, reason = decide(Mode.MANUAL, READ, "outside the sandbox")
    assert verdict == ASK
    assert reason == "outside the sandbox"


def test_auto_escape_asks_rather_than_giving_up():
    verdict, reason = decide(Mode.AUTO, READ, "outside the sandbox")
    assert verdict == ASK
    assert reason == "outside the sandbox"


def test_plan_requests_approval_for_external_reads():
    verdict, reason = decide(Mode.PLAN, READ, "outside the sandbox")
    assert verdict == ASK
    assert reason == "outside the sandbox"


def test_plan_reason_explains_itself():
    _, reason = decide(Mode.PLAN, WRITE)
    assert "plan mode" in reason


def test_cycle_visits_every_mode():
    seen = [Mode.MANUAL]
    for _ in range(2):
        seen.append(next_mode(seen[-1]))
    assert set(seen) == set(Mode)
    assert next_mode(seen[-1]) == Mode.MANUAL


@pytest.mark.parametrize("text,expected", [
    ("auto", Mode.AUTO), ("a", Mode.AUTO), ("plan", Mode.PLAN),
    ("p", Mode.PLAN), ("manual", Mode.MANUAL), ("", Mode.MANUAL),
    (None, Mode.MANUAL), ("nonsense", Mode.MANUAL),
])
def test_parse(text, expected):
    assert parse(text) == expected


def test_each_mode_describes_itself():
    for mode in Mode:
        assert mode.blurb
        assert mode.icon
        assert mode.label.endswith("mode")


def test_read_only_commands_need_no_approval():
    from eirene.tools import registry as tools

    assert tools.harmless("run_command", {"command": "ls -la"}) is True
    assert tools.harmless("run_command", {"command": "git status"}) is True
    assert tools.harmless("run_command", {"command": "rm -rf x"}) is False
    assert tools.harmless("run_command", {"command": "python x.py"}) is False


def test_reading_files_needs_no_approval():
    from eirene.tools import registry as tools

    assert tools.harmless("read_file", {"path": "a"}) is True
    assert tools.harmless("list_dir", {"path": "."}) is True
    assert tools.harmless("write_file", {"path": "a", "content": "x"}) is False
    assert tools.harmless("edit_file", {"path": "a"}) is False
    assert tools.kind_of("web_search") == READ
    assert tools.harmless("web_search", {"query": "news"}) is False
