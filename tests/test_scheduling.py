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
    assert "WorkingDirectory=-/home/x/project" in unit
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
    # OnBootSec= is in the past at install time and would fire the timer at once.
    assert "OnActiveSec=15min" in unit and "OnBootSec" not in unit


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
    assert "TimeoutStartSec=390" in unit  # one 90s attempt plus the margin
    assert 'Environment="DEMO=a\\"b"' in unit


def test_launchd_plist_is_valid():
    body = plist_body(make(Schedule("daily", hour=8, minute=5)))
    parsed = plistlib.loads(plistlib.dumps(body))
    assert parsed["Label"] == "com.eirene.abc123"
    assert parsed["StartCalendarInterval"] == {"Hour": 8, "Minute": 5}
    assert "--task" in parsed["ProgramArguments"]
    assert "WorkingDirectory" not in parsed


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


def test_runner_command_keeps_the_venv_interpreter(monkeypatch, tmp_path):
    real = tmp_path / "base" / "python3"
    real.parent.mkdir()
    real.write_text("")
    venv = tmp_path / "venv" / "bin" / "python"
    venv.parent.mkdir(parents=True)
    venv.symlink_to(real)
    monkeypatch.setattr(base.sys, "executable", str(venv))
    monkeypatch.delattr(base.sys, "frozen", raising=False)
    assert base.runner_command(make(Schedule("hourly")))[0] == str(venv)


def test_backend_matches_the_platform():
    from eirene.scheduling import backend
    engine = backend()
    assert engine.name in ("systemd", "launchd", "schtasks", "none")


def test_new_ids_are_unique():
    assert len({base.new_id() for _ in range(200)}) == 200


def test_schtasks_long_intervals_use_whole_days():
    from eirene.scheduling.windows_schtasks import SchtasksBackend
    argv = create_argv(make(Schedule("interval", minutes=2 * 1440)))
    assert argv[argv.index("/SC") + 1] == "DAILY" and argv[argv.index("/MO") + 1] == "2"
    argv = create_argv(make(Schedule("interval", minutes=23 * 60)))
    assert argv[argv.index("/SC") + 1] == "MINUTE" and argv[argv.index("/MO") + 1] == "1380"
    with pytest.raises(SchedulerError, match="whole"):
        SchtasksBackend().validate(Schedule("interval", minutes=25 * 60))


def test_schtasks_hourly_is_aligned_to_the_hour():
    argv = create_argv(make(Schedule("hourly")))
    assert argv[argv.index("/ST") + 1] == "00:00"


def test_systemd_timeout_covers_every_attempt():
    task = make(Schedule("hourly"))
    task.timeout, task.retries, task.retry_delay = 600, 2, 60
    assert task.budget == 3 * 600 + 2 * 60
    assert f"TimeoutStartSec={task.budget + base.BUDGET_MARGIN}" in service_unit(task)


@pytest.mark.parametrize("text,expected", [
    ("all", list(base.TOOL_GROUPS)),
    ("", ["read"]),
    ("read only", ["read"]),
    ("edit, commands", ["read", "edit", "commands"]),
    ("shell+web", ["read", "commands", "web"]),
])
def test_tool_lists_are_parsed(text, expected):
    assert base.parse_tools(text) == expected


def test_unknown_tool_group_is_rejected():
    with pytest.raises(SchedulerError, match="unknown tool group"):
        base.parse_tools("edit, everything-else")


def test_access_fields_round_trip_and_old_records_keep_all_tools():
    task = make(Schedule("hourly"))
    task.access, task.tools, task.workspace = "full-access", ["read", "web"], "worktree"
    loaded = Task.from_dict(task.to_dict())
    assert (loaded.access, loaded.tools, loaded.workspace) == ("full-access", ["read", "web"], "worktree")
    legacy = task.to_dict()
    for key in ("access", "tools", "workspace"):
        legacy.pop(key)
    loaded = Task.from_dict(legacy)
    assert (loaded.access, loaded.tools, loaded.workspace) == ("sandboxed", list(base.TOOL_GROUPS), "project")
    legacy.update(access="root", tools=["edit", "bogus"], workspace="elsewhere")
    loaded = Task.from_dict(legacy)
    assert (loaded.access, loaded.tools, loaded.workspace) == ("sandboxed", ["read", "edit"], "project")


def test_find_task_ignores_ambiguous_names():
    first, second = make(Schedule("hourly")), make(Schedule("hourly"))
    second.id = "def456"
    save_tasks([first, second])
    assert base.find_task("nightly-build") is None
    assert base.find_task("def456").id == "def456"


def test_schtasks_warns_that_runs_need_a_signed_in_user():
    from eirene.scheduling.windows_schtasks import SchtasksBackend
    assert any("signed in" in note for note in SchtasksBackend().warnings())


def test_signed_out_fields_round_trip_and_default_off():
    task = make(Schedule("hourly"))
    loaded = Task.from_dict(task.to_dict())
    assert loaded.run_signed_out is False and loaded.signed_out_logon == ""
    task.run_signed_out, task.signed_out_logon = True, "password"
    loaded = Task.from_dict(task.to_dict())
    assert loaded.run_signed_out is True and loaded.signed_out_logon == "password"
    body = task.to_dict(); body["signed_out_logon"] = "kerberos"
    assert Task.from_dict(body).signed_out_logon == ""


class _Result:
    def __init__(self, code=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = code, out, err


class _Windows:
    """Record schtasks/powershell calls and answer them from a script."""

    def __init__(self, monkeypatch, *, rights=None, elevated=False, answer=None):
        from eirene.scheduling import windows_rights, windows_schtasks as win
        self.win, self.calls = win, []
        self.answer = answer or (lambda argv, stdin: _Result())
        monkeypatch.setattr(windows_rights, "batch_logon_allowed", lambda: rights)
        monkeypatch.setattr(windows_rights, "elevated", lambda: elevated)
        monkeypatch.setattr(win.subprocess, "run", self.run)

    def run(self, argv, **kw):
        stdin = kw.get("input")
        self.calls.append((argv, stdin))
        return self.answer(argv, stdin)

    @property
    def backend(self):
        return self.win.SchtasksBackend()


def test_elevated_session_uses_s4u_without_a_password(monkeypatch):
    fake = _Windows(monkeypatch, elevated=True)
    assert fake.backend.signed_out_mode() == ("s4u", "")
    script = fake.calls[0][0][-1]
    assert "-LogonType S4U" in script and "Enabled = $false" in script
    assert "Unregister-ScheduledTask" in script and '"' not in script


def test_normal_session_falls_back_to_the_password(monkeypatch):
    fake = _Windows(monkeypatch, elevated=False)
    assert fake.backend.signed_out_mode() == ("password", "")
    assert fake.calls == []  # no S4U attempt: Windows refuses it without elevation


def test_elevated_session_whose_s4u_is_refused_uses_the_password(monkeypatch):
    fake = _Windows(monkeypatch, elevated=True,
                    answer=lambda argv, stdin: _Result(1, err="Access is denied."))
    assert fake.backend.signed_out_mode() == ("password", "")


def test_known_missing_batch_right_offers_nothing(monkeypatch):
    fake = _Windows(monkeypatch, rights=False, elevated=True)
    mode, problem = fake.backend.signed_out_mode()
    assert mode == "" and "batch job" in problem and fake.calls == []


@pytest.mark.parametrize("answer,expected", [
    (_Result(0, out="RESULT 0\n"), ""),
    (_Result(0, out="RESULT 267011\n"), "batch job"),
    (_Result(0, out="RESULT -2147023570\n"), "did not accept that password"),
    (_Result(1, err="Register-ScheduledTask : The user name or\npassword is incorrect.\nAt line:1"),
     "did not accept that password"),
    (_Result(0, out="RESULT 1\n"), "0x00000001"),
])
def test_password_is_checked_with_a_real_test_run(monkeypatch, answer, expected):
    fake = _Windows(monkeypatch, answer=lambda argv, stdin: answer)
    problem = fake.backend.verify_password("hunter2")
    assert (expected in problem) if expected else problem == ""
    argv, stdin = fake.calls[0]
    assert stdin == "hunter2\n" and "hunter2" not in " ".join(argv)
    assert "Start-ScheduledTask" in argv[-1] and "Unregister-ScheduledTask" in argv[-1]


def test_password_install_hands_the_password_over_stdin(monkeypatch):
    fake = _Windows(monkeypatch)
    task = make(Schedule("daily", hour=9, minute=0))
    task.run_signed_out, task.signed_out_logon = True, "password"
    assert "signed in or out" in fake.backend.install(task, "hunter2")
    assert fake.calls[0][0][:2] == ["schtasks", "/Create"]
    argv, stdin = fake.calls[1]
    assert stdin == "hunter2\n" and "hunter2" not in " ".join(argv)
    assert "-Password $secret" in argv[-1] and "'Eirene-abc123'" in argv[-1]
    assert all("hunter2" not in " ".join(call[0]) for call in fake.calls)


def test_password_install_needs_the_password(monkeypatch):
    fake = _Windows(monkeypatch)
    task = make(Schedule("hourly"))
    task.run_signed_out, task.signed_out_logon = True, "password"
    with pytest.raises(SchedulerError, match="password is needed"):
        fake.backend.install(task)
    assert fake.calls == []


def test_s4u_install_switches_the_logon(monkeypatch):
    fake = _Windows(monkeypatch, elevated=True)
    task = make(Schedule("daily", hour=9, minute=0))
    task.run_signed_out, task.signed_out_logon = True, "s4u"
    assert "signed in or out" in fake.backend.install(task)
    scripts = [call[0][-1] for call in fake.calls if call[0][0] == "powershell.exe"]
    assert any("Set-ScheduledTask -TaskName 'Eirene-abc123' -Principal" in s for s in scripts)
    assert fake.backend.warnings(task) == []


def test_s4u_install_refuses_without_elevation(monkeypatch):
    fake = _Windows(monkeypatch, elevated=False)
    task = make(Schedule("hourly"))
    task.run_signed_out, task.signed_out_logon = True, "s4u"
    with pytest.raises(SchedulerError, match="without a password"):
        fake.backend.install(task)
    assert fake.calls == []


def test_signed_out_refusal_rolls_back(monkeypatch):
    def answer(argv, stdin):
        if argv[0] == "powershell.exe":
            return _Result(1, err="Set-ScheduledTask : Access is denied.\nAt line:1 char:112\n"
                                  "    + CategoryInfo : PermissionDenied")
        return _Result()
    fake = _Windows(monkeypatch, answer=answer)
    task = make(Schedule("hourly"))
    task.run_signed_out, task.signed_out_logon = True, "password"
    with pytest.raises(SchedulerError) as caught:
        fake.backend.install(task, "hunter2")
    assert "Access is denied." in caught.value.user_message()
    assert "CategoryInfo" not in caught.value.user_message()
    assert fake.calls[-1][0][:2] == ["schtasks", "/Delete"]


def _at(text):
    import datetime as dt
    return dt.datetime.strptime(text, "%Y-%m-%d %H:%M").timestamp()


@pytest.mark.parametrize("schedule,now,expected", [
    (Schedule("daily", hour=9, minute=0), "2026-11-04 10:00", "2026-11-04 09:00"),
    (Schedule("daily", hour=9, minute=0), "2026-11-04 08:00", "2026-11-03 09:00"),
    (Schedule("weekly", hour=18, minute=30, weekday=0), "2026-11-10 10:00", "2026-11-09 18:30"),
    (Schedule("hourly"), "2026-11-04 10:42", "2026-11-04 10:00"),
    (Schedule("interval", minutes=30), "2026-11-03 01:10", "2026-11-03 01:00"),
])
def test_last_due_finds_the_latest_scheduled_moment(schedule, now, expected):
    created = _at("2026-11-03 00:00")
    assert schedule.last_due(_at(now), created) == _at(expected)


def test_last_due_ignores_moments_before_creation_and_boot():
    created = _at("2026-11-03 12:00")
    assert Schedule("daily", hour=9, minute=0).last_due(_at("2026-11-03 13:00"), created) is None
    assert Schedule("boot").last_due(_at("2026-11-05 13:00"), created) is None


def test_rights_checks_are_inert_off_windows(monkeypatch):
    from eirene.scheduling import windows_rights
    monkeypatch.setattr(windows_rights.sys, "platform", "linux")
    assert windows_rights.batch_logon_allowed() is None
    assert windows_rights.elevated() is False


def test_private_dirs_are_owner_only_on_posix(tmp_path):
    import os
    from eirene.core.private_dirs import make_private_dir
    target = tmp_path / "a" / "b"
    make_private_dir(target, parents=True)
    make_private_dir(target)  # idempotent
    if os.name != "nt":
        assert target.stat().st_mode & 0o777 == 0o700


def test_locked_temp_folder_falls_back_to_a_sibling(tmp_path, monkeypatch):
    from eirene.core import paths
    real = paths._private
    locked = tmp_path / "locked"

    def private(path):
        if path == locked:
            raise PermissionError(13, "Access is denied", str(path))
        return real(path)

    monkeypatch.setattr(paths, "_private", private)
    assert paths._private_or_sibling(locked) == (tmp_path / "locked-u").resolve()


class _Systemd:
    def __init__(self, monkeypatch, tmp_path):
        from eirene.scheduling import linux_systemd as sd
        self.sd, self.calls = sd, []
        monkeypatch.setattr(sd, "UNIT_DIR", tmp_path)
        monkeypatch.setattr(sd.subprocess, "run", self.run)

    def run(self, argv, **kw):
        self.calls.append(argv)
        return _Result(out="enabled\n" if "is-enabled" in argv else "inactive\n")


def test_systemd_startup_routine_is_enabled_not_started(monkeypatch, tmp_path):
    fake = _Systemd(monkeypatch, tmp_path)
    task = make(Schedule("boot"))
    fake.sd.SystemdBackend().install(task)
    assert ["systemctl", "--user", "enable", "eirene-abc123.timer"] in fake.calls
    assert not any("--now" in argv for argv in fake.calls)
    assert fake.sd.SystemdBackend().status(task) == "waits for the next startup"


def test_systemd_pause_resume_and_run_now(monkeypatch, tmp_path):
    fake = _Systemd(monkeypatch, tmp_path)
    engine, task = fake.sd.SystemdBackend(), make(Schedule("hourly"))
    engine.set_enabled(task, False)
    engine.set_enabled(task, True)
    engine.run_now(task)
    assert fake.calls == [
        ["systemctl", "--user", "disable", "--now", "eirene-abc123.timer"],
        ["systemctl", "--user", "enable", "--now", "eirene-abc123.timer"],
        ["systemctl", "--user", "start", "--no-block", "eirene-abc123.service"],
    ]


def test_launchd_startup_routine_waits_for_login(monkeypatch, tmp_path):
    from eirene.scheduling import macos_launchd as ld
    calls = []
    monkeypatch.setattr(ld, "AGENT_DIR", tmp_path)
    monkeypatch.setattr(ld.os, "getuid", lambda: 501, raising=False)
    monkeypatch.setattr(ld.subprocess, "run",
                        lambda argv, **kw: calls.append(argv) or _Result())
    ld.LaunchdBackend().install(make(Schedule("boot")))
    assert not any("bootstrap" in argv for argv in calls)
    calls.clear()
    ld.LaunchdBackend().set_enabled(make(Schedule("daily")), False)
    assert calls[0] == ["launchctl", "disable", "gui/501/com.eirene.abc123"]
    assert calls[1][:2] == ["launchctl", "bootout"]


def test_windows_pause_and_run_now(monkeypatch):
    fake = _Windows(monkeypatch)
    task = make(Schedule("daily"))
    fake.backend.set_enabled(task, False)
    fake.backend.run_now(task)
    assert fake.calls[0][0] == ["schtasks", "/Change", "/TN", "Eirene-abc123", "/DISABLE"]
    assert fake.calls[1][0] == ["schtasks", "/Run", "/TN", "Eirene-abc123"]


def test_removing_history_deletes_kept_copies(workdir):
    from eirene.core import paths
    from eirene.scheduling import worktree
    from eirene.scheduling.history import remove_history
    kept = paths.task_worktrees_dir() / "abc123" / "20261103-090000-1"
    (kept / ".git" / "objects").mkdir(parents=True)
    (kept / ".git" / "objects" / "pack").write_text("x")
    (kept / ".git" / "objects" / "pack").chmod(0o444)
    assert worktree.kept("abc123") == [kept]
    remove_history("abc123")
    assert not (paths.task_worktrees_dir() / "abc123").exists()


def test_systemd_status_while_running_and_idle(monkeypatch, tmp_path):
    from eirene.scheduling import linux_systemd as sd
    service = {"state": "activating"}

    def run(argv, **kw):
        if argv[2] == "is-active":
            return _Result(out=("active" if argv[3].endswith(".timer")
                                else service["state"]) + "\n")
        return _Result(out="- - Tue 2026-11-03 15:53:57 +0330 2min ago eirene-abc123.timer "
                           "eirene-abc123.service\n")

    monkeypatch.setattr(sd.subprocess, "run", run)
    task = make(Schedule("interval", minutes=2))
    assert sd.SystemdBackend().status(task) == "running now"
    service["state"] = "inactive"
    assert sd.SystemdBackend().status(task) == "active"


def test_a_running_copy_is_not_kept_or_discarded(workdir):
    from eirene.core import paths
    from eirene.scheduling import worktree
    from eirene.scheduling.history import lock_for, record
    done = paths.task_worktrees_dir() / "abc123" / "run-1"
    live = paths.task_worktrees_dir() / "abc123" / "run-2"
    done.mkdir(parents=True)
    live.mkdir()
    record("abc123", "started", run="run-1")
    record("abc123", "finished", run="run-1")
    record("abc123", "started", run="run-2")
    lock = lock_for("abc123")
    assert lock.acquire()
    try:
        assert worktree.kept("abc123") == [done]
        assert worktree.remove_kept("abc123") == 1
        assert live.exists() and not done.exists()
    finally:
        lock.release()
    assert worktree.kept("abc123") == [live]  # lock gone: the run ended abnormally
