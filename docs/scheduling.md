# Scheduled tasks

[Documentation](README.md) / Scheduled tasks

Scheduled tasks run a saved prompt through your operating system's scheduler.
They record the workspace, provider, and model selected when you create them, so
a run can start without the terminal interface being open.

## Create a task

```text
/schedule Summarize changes in this repository since the previous workday.
```

Eirene asks for a short name, a schedule, and confirmation before installing the
scheduler entry. With no prompt argument, it asks what the task should do first.
Task prompts are limited to 4,000 characters. Choose work that can finish without
interactive questions or permission approvals.

```text
prompt -> name -> frequency -> confirmation -> OS scheduler -> saved run
```

The current project directory is recorded. Keep that directory available and
ensure the scheduled environment can find Eirene and required tools.

## Schedule formats

| Input | Meaning |
| --- | --- |
| `every 30m` | Every 30 minutes. |
| `every 2h` | Every two hours. |
| `hourly` | On the hourly schedule. |
| `daily at 09:00` | Each day at the specified local time. |
| `mon at 18:30` | Weekly on the named weekday. |
| `at startup` | User login/startup according to the platform scheduler. |

Clock times use 24-hour notation. Intervals must be at least one minute and no
more than 30 days. Schedule execution, catch-up behavior, and availability while
logged out depend on the OS scheduler.

## Platform backends

| System | Scheduler |
| --- | --- |
| Linux | User systemd services and timers. |
| macOS | launchd. |
| Windows | Task Scheduler through `schtasks`. |

A machine without a usable backend cannot install the task. Linux user timers can
require an available user service manager; use the warnings shown during creation
to assess whether runs will occur when you are logged out.

## Manage tasks

```text
/tasks
```

The list shows IDs, schedules, workspace paths, enabled state, retries, timeouts,
timezone labels, and recent outcomes. Its picker lets you run a task now, toggle
it, show recent history, or remove it. Disabling keeps the saved task; its scheduled
invocations skip work while it remains disabled.

A manual run starts managed background work. Use Ctrl+B to inspect it. To run an
existing task from an external shell:

```sh
eirene --task TASK_ID
```

This uses the task's recorded workspace and settings. It is not a way to create a
new task or change its prompt.

## Advanced run settings

Tasks live in `tasks.json` beneath [Eirene's data directory](configuration.md).
Stop Eirene before editing a saved task and preserve its ID and schedule structure.
The following fields control runtime behavior and are not separate slash commands.

| Field | Default | Meaning |
| --- | --- | --- |
| `enabled` | `true` | Whether invocations perform work. |
| `timeout` | `3600` | Overall seconds per attempt; accepted range 60–86,400. |
| `retries` | `0` | Additional attempts after failure; accepted range 0–10. |
| `retry_delay` | `30` | Seconds between attempts; accepted range 0–3,600. |
| `allow_overlap` | `false` | Whether another run may start while one is active. |
| `env` | `{}` | Extra environment values for the task. |
| `timezone` | `local` | Calendar timezone; explicit timezone scheduling is supported by the Linux backend. |

Changes to calendar timing require reinstalling the scheduler entry; editing the
stored timezone alone does not update an installed OS schedule. macOS and Windows
use their scheduler's local calendar behavior. Do not use the timezone label as
proof that a custom timezone is active there.

Environment overrides cannot replace `EIRENE_HOME`, `PYTHONPATH`, `PYTHONHOME`,
or `LD_PRELOAD`. Saved environment values are stored on disk; avoid putting keys
there when a provider credential store is sufficient.

## Unattended limitations

Runs use headless Auto mode and cannot answer approval or choice prompts. Missing
credentials, command isolation, dependencies, or project directories can fail a
run. A disabled task or overlapping invocation skipped by the default lock can
exit successfully without performing the prompt; inspect history to distinguish
those from completed work.

Retries may repeat actions from a partially completed failed run. Use tasks whose
side effects you understand and check recorded outcomes. See [headless runs](headless.md)
for output and access limits, and [notifications](notifications.md) for failure
notification setup.
