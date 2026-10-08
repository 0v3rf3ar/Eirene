# Headless runs

[Documentation](README.md) / Headless runs

Use a headless run for one task from a shell, script, or external automation.
Configure a provider interactively first. A headless process cannot open the
credential picker or ask you to approve an action.

## Run one task

```sh
eirene -C /path/to/project -p "Explain the project structure" --mode plan
```

Choose a tool-capable provider when the task needs files or commands. Provider
and model overrides select an already usable connection:

```sh
eirene -C /path/to/project -p "Run the import tests and summarize failures" --provider anthropic --model MODEL_NAME --mode auto
```

The active configured provider is used when `--provider` is absent. Model choice
uses your explicit override, then the selected provider's saved model, then other
configured/default choices. API credentials still need to be available.

## Mode and approval limits

The headless default is Auto. Use `--mode plan` for inspection. Manual mode can
block actions because no approval callback is available. Workspace actions allowed
by Auto can proceed within the platform boundary; operations requiring an escape
or a user choice cannot receive approval and may leave the run incomplete.

On native Windows, arbitrary commands need approval, so unattended command tasks
fail closed. A full-access choice from an interactive process does not carry into
a new headless process. Do not assume an interactive task can run unattended until
you have checked its permission and environment requirements.

## Output and saved history

The answer is written to standard output. Tool activity and errors go to standard
error. Redirect them separately when saving a result:

```sh
eirene -p "Summarize the current changes" --mode plan > summary.txt 2> activity.log
```

Each prompt is a new run and saves a session. `--resume` is an interactive-session
option, not a continuation mechanism for `-p`. A headless prompt is ordinary task
text; `-p "/plugins install ..."` does not dispatch an interactive slash command.
Install and configure plugins in the interface beforehand, then describe the
workflow you want in the prompt.

`--json` applies to `--doctor` only. It does not wrap the agent's answer in a
machine-readable result format.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Completed successfully; some scheduled-task skip conditions also use `0`. |
| `1` | Configuration/provider failure, failed task, or incomplete run. |
| `2` | Invalid argument or workspace, or interactive launch without a terminal. |
| `124` | Headless overall timeout. |
| `130` | Interrupted with Ctrl+C. |

An ordinary headless prompt has a one-hour overall timeout. There is no public
launch flag to change that prompt timeout. Individual commands have their own
deadlines. Scheduled tasks support a stored per-run timeout.

Managed processes are stopped when the headless run ends. Use
[scheduled tasks](scheduling.md) for recurring work and [command reference](commands.md)
for the complete launch options.
