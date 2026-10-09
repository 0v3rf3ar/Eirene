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
option, not a continuation mechanism for `-p`.

## Slash commands and provider discovery

Prompts starting with `/` dispatch slash commands, including installed plugin
commands. Commands such as `/review`, `/model NAME`, `/plugins install SOURCE`,
and `/plugins inspect NAME` reuse the interactive command handlers.

```sh
eirene -p "/review" --json
eirene --list-providers --json
eirene --configured-providers --json
eirene --list-models anthropic --json
eirene -p "/models anthropic"
eirene -p "/model MODEL_NAME"
eirene -p "/connect anthropic"
```

`/providers` lists available providers; `/providers configured` lists saved
connections without exposing credentials. `/connect` without a name lists
providers. `/connect NAME` validates and switches an existing usable connection,
using its saved/default model, or `--model` when `--provider` selects that connection.
It does not start login or ask for credentials. `/model` without a name lists
the active provider's models; `/models PROVIDER` queries a specific provider.
Listing models does not select one or save settings.

Commands that normally show pickers list their choices without selecting a
default. Supply choice keys explicitly with `--choice KEY`, repeated in prompt
order. For non-secret text fields use repeated `--command-input TEXT` arguments.
Missing required text or confirmation choices fail instead of waiting for input.
These arguments apply to slash-command handlers; they do not approve agent tools
or answer questions from the model.

```sh
eirene -p "/agents" --choice plan
eirene -p "/skills" --choice SKILL_NAME
eirene -p "/mcp" --choice SERVER_KEY
```

Interface-only commands such as `/btw`, `/snow`, `/clear`, `/exit`,
`/prompt-suggest`, and `/keybindings` report an error in headless mode.
Session switching/resume and live steering are not exposed.

## JSON results

`--json` writes one final JSON object to stdout for a prompt, slash command,
provider/model query, or scheduled task. Activity and errors remain on stderr.
There are no streamed JSON fragments.

```sh
eirene -p "Explain this project" --json
```

```json
{"input":"Explain this project","output":"This project…","provider":"anthropic","model":"MODEL_NAME","input_tokens":123,"output_tokens":45,"status":"completed","errors":[],"data":null,"exit_code":0}
```

Token counts come from the agent's usage accounting across the turn, including
tool iterations and delegation. Commands without a model request report zero.
`data` contains structured discovery results or listed choice rows. Failures and
timeouts also produce a result, retaining any partial answer. Counts are zero
when no completed turn supplies usage. Scheduled tasks report the final attempt
and add `task_id` and `attempts`; disabled/skipped tasks use status `skipped`.
`--doctor --json` retains its diagnostic schema.

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

## Configuration and lifecycle

A headless process uses the same `EIRENE_HOME` lookup and config normalization as
interactive use. `--provider` selects a connection; it does not accept an API key
or create a new saved connection. Credential environment overrides and keyring
references still apply. The exact selection order is in the
[config reference](config-file.md#provider-selection-and-credentials).

The runner creates a session UUID, persists the prompt and subsequent conversation
as work begins, closes provider/MCP/managed-process resources, and closes the session.
Output redirection is independent of the saved JSONL history. An incomplete
run can still have persisted messages and project edits. Each task attempt is a
new run; resume does not automatically attach `-p` to an earlier context.

Set PATH and `EIRENE_HOME` explicitly in an external automation environment when
its inherited environment differs from your terminal. See [data layout](data-layout.md)
for saved state and [scheduling](scheduling.md#tasksjson-schema) for task records.
