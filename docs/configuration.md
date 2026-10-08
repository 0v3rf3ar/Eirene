# Configuration and data

[Documentation](README.md) / Configuration

Use slash commands for everyday settings. They validate choices and save changes
without requiring you to edit configuration manually. For settings without an
interactive control, edit `config.json` while Eirene is closed and keep it valid
JSON.

## Data directory

The default data directory is `~/.local/eirene` on every platform. On Windows,
`~` means your user home directory. `EIRENE_HOME` chooses a different directory
when set before launch.

| Location beneath the data directory | Contents |
| --- | --- |
| `config.json` | Providers, models, saved preferences, skill and plugin activation. |
| `sessions/` | Saved conversations. |
| `outputs/` | Bounded saved command output. |
| `skills/` | Your Markdown skills. |
| `plugins/` | Installed bundles. |
| `plugin-data/` | Plugin state, caches, and downloaded runtime data. |
| `plans/` | Saved session plans. |
| `projects/` | Project-related metadata. |
| `tasks.json` | Saved scheduled tasks. |
| `task-runs/` | Scheduled run history. |
| `task-locks/` | Coordination for scheduled runs. |
| `logs/eirene.jsonl` | Rotating runtime log. |

The executable's installation directory is separate from the data directory.
Changing `EIRENE_INSTALL_DIR` does not move sessions. For a backup, close Eirene
and copy its data directory; include the project itself separately. OS credential
store entries and external CLI logins are not contained in that copy.

## Credentials

The default `credential_store` is `file`: saved API keys are in configuration.
Set it to `keyring` to use a supported OS credential backend for newly saved
provider and search keys. A functioning keyring service is required. Changing
the setting does not automatically migrate old file-stored keys; reconnect or
replace those keys through their setup prompts and review the saved configuration.

Provider keys can be overridden by `EIRENE_<PROVIDER>_API_KEY`, using the canonical
provider name in uppercase. For example, `EIRENE_ANTHROPIC_API_KEY` and
`EIRENE_OMNIROUTE_API_KEY` override saved keys for those connections. Names that
contain a hyphen retain it in the environment variable; use your platform's
environment tools to set such names. This lookup does not authenticate native
Codex or Claude Code CLIs.

`eirene --doctor --json` reports credential-store availability and whether a key
is present without printing its value. Do not share the configuration file itself
without removing credentials.

## Everyday settings

| Setting | Default | Control or purpose |
| --- | --- | --- |
| `provider`, `model` | Not selected | `/connect` and `/model`. |
| `mode` | `manual` | `/agents`; applies to interactive sessions. |
| `theme` | `default` | `/theme`; see [appearance](appearance.md). |
| `notifications` | `false` | `/notification`; see [notifications](notifications.md). |
| `prompt_suggest` | `false` | `/prompt-suggest`; extra model requests. |
| `reduce_motion` | `false` | Static activity markers; also `--reduce-motion`. |
| `accessible_icons` | `false` | Accessible icon presentation. |
| `check_updates` | `true` | Startup update checks; `/update check` remains available. |
| `auto_compact` | `true` | Automatic context summaries for managed conversations. |
| `isolate_network` | `true` | Require approval for network access under sandboxed permissions. |

`permissions` is always saved as `sandboxed`. `/permissions full-access` is an
explicit current-process choice, not a persistent configuration default.
`execution_isolation` is normalized to automatic platform behavior; `/sandbox`
shows its status and does not select a container or image.

## Model limits and usage estimates

| Setting | Default | Meaning |
| --- | --- | --- |
| `max_tokens` | `16384` | Requested response token budget, subject to provider support. |
| `context_warning` | `60000` | Context warning/compaction budget input; actual model limits also matter. |
| `model_context_limits` | `{}` | Explicit context limits by model identifier. |
| `model_costs` | `{}` | Input/output USD per million token rates by model identifier. |
| `request_timeout` | `300` | Provider request timeout in seconds; both Ollama connections use at least 600 seconds. |
| `retry_attempts` | `12` | Retry attempts for eligible transient API failures, range 1–100. |
| `max_iterations` | `0` | Agent iteration limit; zero means no configured cap. |

For example, merge these fields into the existing configuration rather than
replacing it:

```json
{
  "reduce_motion": true,
  "model_context_limits": {"your-model-id": 32768},
  "model_costs": {
    "your-model-id": {"input_per_million": 1.25, "output_per_million": 5.00}
  }
}
```

The price values are examples. Match your actual model identifier and pricing.
A configured context number does not extend the model's real context window.
See [context and usage](context-and-usage.md).

## Commands and logging

| Setting | Default | Meaning |
| --- | --- | --- |
| `shell_timeout` | `120` | Shell fallback timeout in seconds; command classification can choose a different deadline. |
| `max_output_bytes` | `200000` | Output preview budget. |
| `log_level` | `INFO` | Runtime log verbosity: DEBUG, INFO, WARNING, ERROR, or CRITICAL. |
| `log_max_bytes` | `2000000` | Size threshold for log rotation. |
| `log_backups` | `3` | Number of rotated logs retained. |

Use [process controls](processes.md) for ongoing commands. Logs can contain task
and error details; review them before sharing. There is no general `/config`
command.

## Environment variables

| Variable | Purpose |
| --- | --- |
| `EIRENE_HOME` | Application data directory. |
| `EIRENE_<PROVIDER>_API_KEY` | Override a provider API key. |
| `EIRENE_CHROMIUM_PATH` | Explicit executable for built-in browser helpers. |
| `EIRENE_REDUCE_MOTION` | Enable reduced motion when set. |
| `EIRENE_NO_UPDATE_CHECK` | Skip startup update checks when set. |
| `EIRENE_OMNIROUTE_DATA_DIR` | Gateway data directory for the OmniRoute management adapter; set before installing it. |
| `NO_COLOR` | Disable colored output. |

For installer-only variables, see [installation](installation.md). For plugin
execution grants, use `/plugins`, `/plugins trust`, and `/mcp` rather than editing
activation fields by guesswork. Scheduled-task environment fields are described
in [scheduling](scheduling.md).

## Full schema and storage references

The [config.json reference](config-file.md) lists every built-in field, accepted
numeric ranges, nested provider/credential objects, activation maps, tool hooks,
and standalone MCP declarations. It also explains default overlay, migration,
malformed-file recovery, atomic saves, and which settings are normalized rather
than honored as written.

Use [data layout and source structure](data-layout.md) to distinguish executable,
workspace, and application data paths, identify session/output/plan files, and
plan a backup or transfer. For a server that is not a plugin, follow
[standalone MCP configuration](mcp.md#declare-a-standalone-server).
