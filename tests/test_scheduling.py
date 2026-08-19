"""Schedule parsing and generated unit files."""

from __future__ import annotations

import plistlib

import pytest

from eirene.core.errors import SchedulerError
from eirene.scheduling import base
from eirene.scheduling.base import Schedule, Task, load_tasks, parse_schedule, save_tasks
from eirene.scheduling.linux_systemd import on_calendar, service_unit, timer_unit
from eirene.scheduling.macos_launchd import plist_body
from eirene.scheduling.windows_schtasks import create_argv


def make(schedule: Schedule, cwd="/home/x/project") -> Task:
    return Task(id="abc123", name="nightly-build", prompt="run the test suite",
                cwd=cwd, schedule=schedule, provider="anthropic", model="claude-x")


@pytest.mark.parametrize("text,expected", [
    ("every 30m", Schedule("interval", minutes=30)),
    ("every 2h", Schedule("interval", minutes=120)),
    ("every 45 minutes", Schedule("interval", minutes=45)),
    ("hourly", Schedule("hourly")),
    ("daily at 09:00", Schedule("daily", hour=9, minute=0)),
    ("at 07:15", Schedule("daily", hour=7, minute=15)),
    ("daily", Schedule("daily", hour=9, minute=0)),
    ("mon at 18:30", Schedule("weekly", hour=18, minute=30, weekday=0)),
    ("every friday at 06:00", Schedule("weekly", hour=6, minute=0, weekday=4)),
    ("at startup", Schedule("boot")),
])
def test_schedule_parsing(text, expected):
    assert parse_schedule(text) == expected


@pytest.mark.parametrize("text", ["", "sometimes", "every 0m", "at 25:00",
                                  "at 10:99", "every 100000m", "daily at noon"])
def test_bad_schedules_rejected(text):
    with pytest.raises(SchedulerError):
        parse_schedule(text)


def test_schedules_describe_themselves():
    assert parse_schedule("every 2h").describe() == "every 2h"
    assert parse_schedule("mon at 18:30").describe() == "every mon at 18:30"
    assert parse_schedule("at startup").describe() == "at startup"


def test_systemd_service_unit():
    unit = service_unit(make(Schedule("daily", hour=3, minute=30)))
    assert "Type=oneshot" in unit
    assert "WorkingDirectory=/home/x/project" in unit
    assert "--task abc123" in unit
    assert "WantedBy=default.target" in unit


def test_systemd_calendar_timer():
    unit = timer_unit(make(Schedule("daily", hour=3, minute=30)))
    assert "OnCalendar=*-*-* 03:30:00" in unit
    assert "Persistent=true" in unit
    assert "Unit=eirene-abc123.service" in unit


def test_systemd_interval_timer():
    unit = timer_unit(make(Schedule("interval", minutes=15)))
    assert "OnUnitActiveSec=15min" in unit
    assert "OnBootSec=5min" in unit


def test_systemd_boot_timer():
    assert "OnBootSec=2min" in timer_unit(make(Schedule("boot")))


def test_systemd_weekly_calendar():
    task = make(Schedule("weekly", hour=18, minute=30, weekday=4))
    assert on_calendar(task) == "Fri *-*-* 18:30:00"


def test_systemd_hourly_calendar():
    assert on_calendar(make(Schedule("hourly"))) == "hourly"


def test_systemd_calendar_supports_an_explicit_timezone():
    task = make(Schedule("daily", hour=9, minute=30))
    task.timezone = "Asia/Tehran"
    assert on_calendar(task).endswith("Asia/Tehran")


def test_systemd_service_uses_task_timeout_and_environment():
    task = make(Schedule("hourly"))
    task.timeout = 90
    task.env = {"DEMO": 'a"b'}
    unit = service_unit(task)
    assert "TimeoutStartSec=90" in unit
    assert 'Environment="DEMO=a\\"b"' in unit


def test_launchd_plist_is_valid():
    body = plist_body(make(Schedule("daily", hour=8, minute=5)))
    parsed = plistlib.loads(plistlib.dumps(body))
    assert parsed["Label"] == "com.eirene.abc123"
    assert parsed["StartCalendarInterval"] == {"Hour": 8, "Minute": 5}
    assert "--task" in parsed["ProgramArguments"]
    assert parsed["WorkingDirectory"] == "/home/x/project"


def test_launchd_interval():
    body = plist_body(make(Schedule("interval", minutes=20)))
    assert body["StartInterval"] == 1200


def test_launchd_weekday_conversion():
    body = plist_body(make(Schedule("weekly", hour=6, minute=0, weekday=6)))
    assert body["StartCalendarInterval"]["Weekday"] == 1
    monday = plist_body(make(Schedule("weekly", hour=6, minute=0, weekday=0)))
    assert monday["StartCalendarInterval"]["Weekday"] == 2


def test_launchd_boot_runs_at_load():
    assert plist_body(make(Schedule("boot")))["RunAtLoad"] is True


def test_schtasks_daily():
    argv = create_argv(make(Schedule("daily", hour=22, minute=0)))
    assert "/SC" in argv and argv[argv.index("/SC") + 1] == "DAILY"
    assert argv[argv.index("/ST") + 1] == "22:00"
    assert argv[argv.index("/TN") + 1] == "Eirene-abc123"


def test_schtasks_interval():
    argv = create_argv(make(Schedule("interval", minutes=10)))
    assert argv[argv.index("/SC") + 1] == "MINUTE"
    assert argv[argv.index("/MO") + 1] == "10"


def test_schtasks_weekly():
    argv = create_argv(make(Schedule("weekly", hour=9, minute=0, weekday=2)))
    assert argv[argv.index("/D") + 1] == "WED"


def test_schtasks_boot():
    argv = create_argv(make(Schedule("boot")))
    assert argv[argv.index("/SC") + 1] == "ONLOGON"


def test_tasks_round_trip():
    task = make(Schedule("interval", minutes=5))
    save_tasks([task])
    loaded = load_tasks()
    assert len(loaded) == 1
    assert loaded[0].id == task.id
    assert loaded[0].schedule == task.schedule
    assert loaded[0].prompt == task.prompt


def test_corrupt_tasks_file_recovers():
    from eirene.core import paths
    paths.tasks_file().write_text("{{{", encoding="utf-8")
    assert load_tasks() == []


def test_damaged_task_entries_are_skipped():
    from eirene.core import paths
    paths.tasks_file().write_text('[{"id": ""}, "junk", {"id": "ok"}]', encoding="utf-8")
    assert [t.id for t in load_tasks()] == ["ok"]


def test_find_task_by_id_or_name():
    task = make(Schedule("hourly"))
    save_tasks([task])
    assert base.find_task("abc123").name == "nightly-build"
    assert base.find_task("nightly-build").id == "abc123"
    assert base.find_task("missing") is None


def test_runner_command_points_at_this_interpreter():
    argv = base.runner_command(make(Schedule("hourly")))
    assert argv[-2:] == ["--task", "abc123"]


def test_backend_matches_the_platform():
    from eirene.scheduling import backend
    engine = backend()
    assert engine.name in ("systemd", "launchd", "schtasks", "none")


def test_new_ids_are_unique():
    assert len({base.new_id() for _ in range(200)}) == 200
