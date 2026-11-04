"""Windows Task Scheduler."""

from __future__ import annotations

from ..core.subprocesses import external_environment

import subprocess

from ..core.errors import SchedulerError
from .base import Backend, Schedule, Task, quoted_command

DAY_CODES = {0: "MON", 1: "TUE", 2: "WED", 3: "THU", 4: "FRI", 5: "SAT", 6: "SUN"}


class SchtasksBackend(Backend):
    """Drives schtasks.exe."""

    name = "schtasks"
    supports_signed_out = True

    def validate(self, schedule: Schedule) -> None:
        if schedule.kind == "interval":
            interval_argv(schedule.minutes)

    def warnings(self, task: Task | None = None) -> list[str]:
        if task is not None and task.run_signed_out:
            return []
        # schtasks registers "interactive only" tasks: nothing fires while signed out.
        return ["Windows runs this only while you are signed in; runs that fall while "
                "signed out are skipped"]

    def signed_out_mode(self) -> tuple[str, str]:
        from .windows_rights import batch_logon_allowed, elevated
        if batch_logon_allowed() is False:
            return "", ("this Windows account lacks the 'log on as a batch job' right, so "
                        "Windows would accept a signed-out routine and never start it; "
                        "an administrator can grant the right")
        # Windows only lets an elevated process register a no-password (S4U) task,
        # even for administrators; ask it directly with a disabled throwaway task.
        if elevated():
            try:
                _run(s4u_check_argv(), what="powershell")
                return "s4u", ""
            except SchedulerError:
                pass
        return "password", ""

    def verify_password(self, password: str) -> str:
        # Registration alone proves little: Windows accepts a password task for an
        # account without the batch right and then never starts it. Run one for real.
        try:
            result = _run(password_check_argv(), what="powershell", secret=password)
        except SchedulerError as exc:
            message = exc.user_message()
            if "password is incorrect" in message.lower() or "logon failure" in message.lower():
                return "Windows did not accept that password"
            return message
        code = _last_result(result.stdout)
        if code == 0:
            return ""
        if code == NOT_YET_RUN:
            return ("Windows accepted the password but would not start a signed-out run "
                    "(this account lacks the 'log on as a batch job' right)")
        if code == LOGON_FAILURE:
            return "Windows did not accept that password"
        return f"a signed-out test run failed (Windows result 0x{(code or 0) & 0xFFFFFFFF:08X})"

    def install(self, task: Task, password: str | None = None) -> str:
        logon = task.signed_out_logon or "s4u"
        if task.run_signed_out:
            if logon == "password" and not password:
                raise SchedulerError("a Windows password is needed to run while signed out")
            if logon == "s4u":
                mode, problem = self.signed_out_mode()
                if mode != "s4u":
                    raise SchedulerError("cannot run while signed out without a password: "
                                         + (problem or "run Eirene as administrator, or "
                                            "choose the password option"))
        _run(create_argv(task))
        if task.run_signed_out:
            try:
                if logon == "password":
                    _run(password_logon_argv(task), what="powershell", secret=password)
                else:
                    _run(signed_out_argv(task), what="powershell")
            except SchedulerError as exc:
                self.remove(task)
                raise SchedulerError("Windows would not let this routine run while signed "
                                     f"out: {exc.user_message()}") from exc
            return f"installed task {task_name(task)} (runs signed in or out)"
        return f"installed task {task_name(task)}"

    def remove(self, task: Task) -> str:
        result = _run(["schtasks", "/Delete", "/TN", task_name(task), "/F"], check=False)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[:200]
            if "cannot find" in detail.lower():
                return "nothing to remove"
            raise SchedulerError(f"schtasks failed: {detail}")
        return f"removed task {task_name(task)}"

    def set_enabled(self, task: Task, enabled: bool) -> str:
        # /Change with only /ENABLE or /DISABLE keeps the stored logon (S4U/password).
        _run(["schtasks", "/Change", "/TN", task_name(task),
              "/ENABLE" if enabled else "/DISABLE"])
        return f"{'enabled' if enabled else 'disabled'} task {task_name(task)}"

    def run_now(self, task: Task) -> str:
        _run(["schtasks", "/Run", "/TN", task_name(task)])
        return f"started task {task_name(task)}"

    def status(self, task: Task) -> str:
        result = _run(["schtasks", "/Query", "/TN", task_name(task), "/FO", "LIST"],
                      check=False)
        if result.returncode != 0:
            return "not installed"
        for line in (result.stdout or "").splitlines():
            if line.lower().startswith("status:"):
                return line.split(":", 1)[1].strip().lower()
        return "installed"

    def password_changed_at(self) -> float | None:
        # A stale stored password makes Windows skip the run silently: "Last Result"
        # keeps the previous value and the failure goes to a log that is off by default.
        from .windows_rights import password_changed_at
        return password_changed_at()


def task_name(task: Task) -> str:
    return f"Eirene-{task.id}"


def create_argv(task: Task) -> list[str]:
    """Build the schtasks /Create command."""
    schedule = task.schedule
    argv = ["schtasks", "/Create", "/TN", task_name(task),
            "/TR", quoted_command(task), "/F", "/RL", "LIMITED"]
    clock = f"{schedule.hour:02d}:{schedule.minute:02d}"
    if schedule.kind == "interval":
        argv += interval_argv(schedule.minutes)
    elif schedule.kind == "hourly":
        # Without a start time the hours count from the moment of creation.
        argv += ["/SC", "HOURLY", "/ST", "00:00"]
    elif schedule.kind == "boot":
        argv += ["/SC", "ONLOGON"]
    elif schedule.kind == "weekly":
        argv += ["/SC", "WEEKLY", "/D", DAY_CODES[schedule.weekday], "/ST", clock]
    else:
        argv += ["/SC", "DAILY", "/ST", clock]
    return argv


def signed_out_argv(task: Task) -> list[str]:
    """Switch an installed task to S4U logon: runs without a session, no password stored."""
    script = ("$ErrorActionPreference = 'Stop'; "
              "$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name; "
              "$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType S4U "
              "-RunLevel Limited; "
              f"Set-ScheduledTask -TaskName '{task_name(task)}' -Principal $principal "
              "| Out-Null")
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-Command", script]


def s4u_check_argv() -> list[str]:
    """Register and remove a disabled S4U task to see whether Windows allows one."""
    import uuid
    name = f"Eirene-check-{uuid.uuid4().hex[:8]}"
    script = ("$ErrorActionPreference = 'Stop'; "
              "$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name; "
              "$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType S4U "
              "-RunLevel Limited; "
              "$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c exit'; "
              "$settings = New-ScheduledTaskSettingsSet; $settings.Enabled = $false; "
              f"try {{ Register-ScheduledTask -TaskName '{name}' -Action $action "
              "-Principal $principal -Settings $settings | Out-Null } "
              f"finally {{ Unregister-ScheduledTask -TaskName '{name}' -Confirm:$false "
              "-ErrorAction SilentlyContinue }")
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-Command", script]


NOT_YET_RUN = 0x00041303    # SCHED_S_TASK_HAS_NOT_RUN
LOGON_FAILURE = 0x8007052E  # ERROR_LOGON_FAILURE as an HRESULT

# Read the password from stdin so it never appears on a command line.
_READ_SECRET = ("$secret = [Console]::In.ReadLine(); "
                "$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name; ")


def password_logon_argv(task: Task) -> list[str]:
    """Store the account password with the task so Windows can start it signed out."""
    script = ("$ErrorActionPreference = 'Stop'; " + _READ_SECRET +
              f"Set-ScheduledTask -TaskName '{task_name(task)}' -User $user "
              "-Password $secret | Out-Null")
    return _powershell(script)


def password_check_argv() -> list[str]:
    """Register a throwaway password task, run it once, report its result, delete it."""
    import uuid
    name = f"Eirene-check-{uuid.uuid4().hex[:8]}"
    script = ("$ErrorActionPreference = 'Stop'; " + _READ_SECRET +
              "$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c exit 0'; "
              f"try {{ Register-ScheduledTask -TaskName '{name}' -Action $action -User $user "
              "-Password $secret -RunLevel Limited | Out-Null; "
              f"Start-ScheduledTask -TaskName '{name}'; "
              "$end = (Get-Date).AddSeconds(30); "
              f"do {{ Start-Sleep -Milliseconds 500; $info = Get-ScheduledTaskInfo -TaskName '{name}'; "
              f"$state = (Get-ScheduledTask -TaskName '{name}').State }} "
              "while (($info.LastTaskResult -eq 267011 -or $state -eq 'Running') "
              "-and (Get-Date) -lt $end); "
              "[Console]::Out.WriteLine('RESULT ' + $info.LastTaskResult) } "
              f"finally {{ Unregister-ScheduledTask -TaskName '{name}' -Confirm:$false "
              "-ErrorAction SilentlyContinue }")
    return _powershell(script)


def _powershell(script: str) -> list[str]:
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-Command", script]


def _int(text: str) -> int | None:
    try:
        return int(text, 16) if text.lower().startswith("0x") else int(text)
    except ValueError:
        return None


def _last_result(output: str) -> int | None:
    for line in (output or "").splitlines():
        if line.startswith("RESULT "):
            value = _int(line[7:].strip())
            return None if value is None else value & 0xFFFFFFFF
    return None


def interval_argv(minutes: int) -> list[str]:
    """schtasks caps MINUTE at 1439 and HOURLY at 23, so longer gaps use whole days."""
    if minutes < 1440:
        return ["/SC", "MINUTE", "/MO", str(minutes)]
    if minutes % 1440 == 0:
        return ["/SC", "DAILY", "/MO", str(minutes // 1440)]
    raise SchedulerError("Windows Task Scheduler repeats under 24 hours or in whole "
                         "days; use e.g. 'every 23h', 'every 48h' or 'daily at 09:00'")


def _run(argv: list[str], check: bool = True, what: str = "schtasks",
         secret: str | None = None) -> subprocess.CompletedProcess:
    options = ({"input": secret + "\n"} if secret is not None
               else {"stdin": subprocess.DEVNULL})
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=90,
                                env=external_environment(), **options)
    except FileNotFoundError as exc:
        raise SchedulerError(f"{argv[0]} not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise SchedulerError(f"{what} timed out") from exc
    if check and result.returncode != 0:
        text = (result.stderr or result.stdout or "").strip()
        # PowerShell wraps the message at the console width, then appends position
        # and category lines starting with "At line:"; keep only the message.
        message = text.split("At line:")[0] if "At line:" in text else text
        detail = " ".join(message.split())[:240]
        raise SchedulerError(f"{what} failed: {detail}")
    return result
