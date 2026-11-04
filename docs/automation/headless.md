# Headless runs

[Documentation](../README.md) / Automation / Headless runs

A headless run performs one task from a shell or script, with no interface. Set up your provider interactively first, because a headless process cannot show a sign-in prompt or ask for approval.

```sh
eirene -C /path/to/project -p "Explain the project structure" --mode plan
```

The answer goes to standard output, while tool activity and errors go to standard error. `-q` hides the activity and keeps errors.

```sh
eirene -p "Summarize the current changes" --mode plan > summary.txt 2> activity.log
```

Each prompt is a new run with its own saved session. There is no way to continue a previous `-p` run.

## Choose a provider and model

```sh
eirene -p "Run the import tests and summarize failures" --provider anthropic --model MODEL_NAME
```

`--provider` selects a connection you have already set up, and defaults to your active provider. It does not accept keys or create connections. The model is chosen from `--model`, the provider's saved model, the active model, then the provider's default. Tasks that touch files or
commands need a tool-capable provider.

## Pipe input

Piped text is added after your prompt in a `<stdin>` block. `-p -` reads the whole prompt from stdin instead.

```sh
git diff | eirene -p "Review this change" --mode plan
eirene -p - < task.md
```

Input is limited to 4 MB, and larger input exits with code `2`. If nothing arrives within three seconds, the run continues without it, so an unused open pipe does not hang. Prompts starting with `/` ignore piped input.

## Modes and approvals

The default mode is Auto. Use `--mode plan` for read-only work. Nobody can answer an approval prompt, so anything that would ask is refused: that includes every change in Manual mode and every attempt to leave the sandbox. The run may finish incomplete as a result. On Windows, tasks needing host access fail in the same way.

Try a task with these constraints before relying on it unattended.

## Tools and access

`--tools` limits what a run may use. Groups are `read`, `edit`, `commands`, `web`, `mcp` and `agents`, separated by commas or spaces, or `all`. `read` is always included, and the default is every tool.

```sh
eirene -p "Find dead code" --tools read
eirene -p "Fix the failing test" --tools "edit, commands"
```

The groups are explained under [Tool groups](routines.md#tool-groups). Tools outside the list are not offered to the model. Granting `web` also approves network access for the web tools during that run.

Providers that run their own tools, Claude Code and Codex, cannot honor a narrower list, so a restricted `--tools` fails with a configuration error on them instead of running unrestricted.

`--access sandboxed|full-access` sets the sandbox level for one run and is never saved. See [Full access](../guides/modes-and-permissions.md#full-access) before using it unattended.

### MCP servers and skills

Nobody can approve an MCP tool call during a headless run, so servers start only if you grant them. Naming a server is the approval for its tools.

```sh
eirene -p "Summarize open issues" --mcp github
eirene -p "Check every connected service" --mcp all
```

`--mcp` takes names, `all` (every server enabled in `/mcp`) or `none` (the default). A name that is unknown or not enabled exits with code `3`. Granting a server also adds the `mcp` group to `--tools`. If a remote server's sign-in has expired, the run reports it and continues without those tools. Run
`/mcp login NAME` interactively to fix that.

Skills enabled in `/skills` are offered as usual. `--skills` overrides this for one run with names, `all` or `none`. A named skill is offered even if it is off in `/skills`, and an unknown name exits with code `3`.

```sh
eirene -p "Write the release notes" --skills release-notes
```

## Limits

| Flag | Effect |
| --- | --- |
| `--timeout SECONDS` | Stops the whole run, with exit code `124`. The default is 3600. |
| `--max-steps N` | Stops after N tool rounds, with exit code `6`. A provider's own lower limit still applies. |
| `--max-tokens N` | Stops once input plus output tokens, including subagents, reach N, with exit code `6`. It is checked after each model reply, so one reply can go past the limit. Pending tool calls are not run. |

Individual commands keep [their own time limits](../guides/running-commands.md#timeouts). Processes the run started are stopped when it ends.

## JSON output

`--json` writes one object to standard output when the run ends:

```sh
eirene -p "Explain this project" --json
```

```json
{"input":"Explain this project","output":"This project…","provider":"anthropic","model":"MODEL_NAME","session":"SESSION_UUID","input_tokens":123,"output_tokens":45,"cost_usd":null,"duration_seconds":8.4,"status":"completed","error_kind":null,"errors":[],"tool_calls":[{"name":"read_file","label":"README.md","is_error":false,"seconds":0.01}],"tool_call_count":1,"files_edited":[],"data":null,"exit_code":0}
```

| Field | Meaning |
| --- | --- |
| `session` | The saved session's ID. |
| `input_tokens`, `output_tokens` | Totals for the whole turn, including tool rounds and subagents. Zero if no turn completed. |
| `cost_usd` | An estimate from [`model_costs`](../guides/context-and-usage.md#estimate-cost), or `null` if a model used has no rate. |
| `duration_seconds` | Wall-clock time. |
| `status` | `completed`, `failed`, `incomplete`, `timeout` or `interrupted`. |
| `error_kind` | `null`, or the first failure's class: `config`, `auth`, `network`, `provider`, `tool`, `incomplete`, `timeout`, `interrupted` or `failed`. |
| `tool_calls`, `tool_call_count` | The first 200 tool calls, and the total. |
| `files_edited` | Files changed by file tools. Changes made by shell commands are not listed. |
| `data` | Structured results from discovery commands or listed choices. |

Failed and timed-out runs still produce an object, with any partial answer. [Routines](routines.md) add `task_id` and `attempts`, and use status `skipped` when a run is skipped.

### Streaming

`--stream-json` writes one JSON object per line as the run goes, and ends with a `result` line holding the same object as `--json`. The two flags cannot be combined. Tool activity moves into the stream, and errors go to standard error as well.

```sh
eirene -p "Run the tests" --stream-json | jq -c 'select(.type == "tool_start")'
```

| `type` | Fields |
| --- | --- |
| `start` | `session`, `cwd`, `provider`, `model`, `mode`, `tools`, `mcp`, `skills` |
| `text` | `text`, a fragment of the answer |
| `tool_start` | `id`, `name`, `label`, `kind` |
| `tool_end` | `id`, `name`, `label`, `is_error`, `seconds`, `result` (first 2,000 characters) |
| `notice` | `text` |
| `plan` | `steps`, `explanation` |
| `error` | `text`, `kind` |
| `turn_done` | `status`, `seconds`, `input_tokens`, `output_tokens` |
| `result` | The final result object |

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success. Some routine skip conditions also use `0`. |
| `1` | The run failed: a provider rejected the request, a slash command failed, or an unexpected error occurred. |
| `2` | Invalid argument or workspace, oversized piped input, an empty prompt, or starting the interface without a terminal. |
| `3` | Not configured: no provider or model, an unknown provider or model, a missing key or base URL, or a `--tools` list the provider cannot enforce. |
| `4` | The provider rejected the credentials. |
| `5` | Network or availability: unreachable host, rate limit, or a server error after retries. |
| `6` | Incomplete: stopped by `--max-steps`, `--max-tokens`, the configured step limit, or a model that got stuck. |
| `124` | The overall timeout was reached. |
| `130` | Interrupted with Ctrl+C. |

## Slash commands

A prompt starting with `/` runs a slash command without starting a model turn, unless the command needs one, as `/review` and plugin commands do.

```sh
eirene -p "/review" --json
eirene -p "/plugins install superpowers"
eirene -p "/model MODEL_NAME"
eirene -p "/connect anthropic"
```

`/connect NAME` validates and switches to an existing connection, but it does not sign in or ask for credentials.

Commands that normally show a picker list their choices instead. Supply a choice with `--choice KEY` and non-secret text with `--command-input TEXT`, repeating them in the order the command asks. Anything required and missing fails instead of waiting. These flags answer slash commands only: they cannot approve tools or
answer questions from the model.

```sh
eirene -p "/agents" --choice plan
eirene -p "/skills" --choice skill:SKILL_NAME
eirene -p "/skills" --choice group:FOLDER --choice all:off
eirene -p "/mcp" --choice SERVER_KEY
```

Interface-only commands such as `/btw`, `/clear`, `/exit`, `/prompt-suggest`, `/keybindings` and `/config` report an error.

## Discover providers and models

```sh
eirene --list-providers --json
eirene --configured-providers --json
eirene --list-models anthropic --json
```

Inside `-p`, `/providers`, `/providers configured` and `/models PROVIDER` do the same. Listing never changes your settings or shows credentials.

## In scripts and CI

- The first run needs an interactive setup, or a [`config.json`](../reference/configuration.md) and environment key prepared in advance. `EIRENE_<PROVIDER>_API_KEY` is the simplest way to supply a key.
- Set `PATH` and `EIRENE_HOME` explicitly if the automation's environment differs from your terminal's.
- An incomplete run can still have saved messages and edited files. Check the exit code and the working tree.

For recurring work, see [Routines](routines.md). All flags are listed in the [command reference](../reference/commands.md#launch-options).
