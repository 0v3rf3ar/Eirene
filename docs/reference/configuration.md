# Configuration

[Documentation](../README.md) / Reference / Configuration

Slash commands handle most settings, validating your choices and saving them for you. This page describes the underlying file, `config.json`, for settings without a command and for anyone who prefers to edit by hand.

**On this page:** [Edit the file](#edit-the-file) · [How the file is loaded](#how-the-file-is-loaded) · [Defaults](#defaults) · [Providers](#providers) · [Credentials](#credentials) · [Modes and access](#modes-and-access) · [Interface](#interface) · [Numeric limits](#numeric-limits) · [Context and costs](#context-limits-and-costs) · [Skills and plugins](#skills-and-plugins) · [MCP servers](#mcp-servers) · [Tool hooks](#tool-hooks) · [Search API](#search-api) · [Environment variables](#environment-variables)

## Edit the file

The file is `~/.local/share/eirene/config.json` on every system. On Windows, `~` is your user folder. Setting `EIRENE_HOME` before launch moves it, along with the rest of the [data directory](data-directory.md):

```sh
EIRENE_HOME=/absolute/path/to/eirene-data eirene
```

```powershell
$env:EIRENE_HOME = 'C:\Users\you\eirene-data'
eirene
```

There is no `--config` option and no per-project configuration. Separate `EIRENE_HOME` directories have separate preferences and history, but share your system keyring entries and external CLI logins.

The easiest way to edit it is `/config`, which opens the file in your `editor` setting, then nvim, vim or the system default. After a terminal editor closes, Eirene reloads the file, or reports a JSON error and keeps its current settings.

Otherwise, close Eirene first, because it holds settings in memory and a later save would overwrite your edit. Back up the file and merge the fields you need. Examples on this page are fragments to merge, unless they say otherwise: replacing the whole file with a fragment discards everything else.

The file is UTF-8 JSON, with double quotes, lowercase `true`, `false` and `null`, and no comments or trailing commas. Windows paths need escaped backslashes (`"C:\\Tools\\java.exe"`) or forward slashes. Use real JSON booleans, because the string `"false"` can count as enabled.

## How the file is loaded

1. A missing or empty file loads as an empty object.
2. If the JSON is invalid, or the top level is not an object, Eirene copies the file to `config.json.bak` and uses defaults. The next save replaces the original, so [recover it promptly](../help/troubleshooting.md#settings-reset-to-defaults).
3. Older versions are migrated in memory, and written out at the next save.
4. Your top-level values replace the defaults. Nested objects replace the default as a whole and are not merged.
5. Selected types and ranges are corrected, as described in the tables below.

A permissions error while reading stops with an error instead of using defaults. The object fields `providers`, `skills`, `plugins`, `hooks`, `mcp_servers`, `mcp_enabled`, `model_context_limits`, `model_costs` and `search_api` are reset to empty if they are not objects. Unknown top-level keys are kept but do nothing. Not every nested field is checked on load, so a bad value can fail later, when it is used.

Saves are atomic. On Linux and macOS, the file is mode `0600` and its folder `0700`.

`version` is the file's schema version, currently `5`, and does not select a program release. Lowering it re-runs migrations, which can change your settings.

## Defaults

A new configuration has these values:

```json
{
  "version": 5,
  "provider": null,
  "model": null,
  "mode": "manual",
  "theme": "default",
  "seasonal_effects": true,
  "providers": {},
  "trusted_workspaces": [],
  "skills": {},
  "shell_timeout": 120,
  "max_iterations": 0,
  "max_output_bytes": 200000,
  "max_attachment_bytes": 20000000,
  "request_timeout": 300,
  "retry_attempts": 12,
  "notifications": false,
  "max_tokens": 16384,
  "context_warning": 0,
  "log_level": "INFO",
  "log_max_bytes": 2000000,
  "log_backups": 3,
  "execution_isolation": "auto",
  "permissions": "sandboxed",
  "prompt_suggest": false,
  "recap": true,
  "fast_mode": false,
  "isolate_network": true,
  "plugins": {},
  "hooks": {},
  "mcp_servers": {},
  "mcp_enabled": {},
  "auto_compact": true,
  "model_context_limits": {},
  "model_costs": {},
  "reduce_motion": false,
  "companion": false,
  "accessible_icons": false,
  "mouse": "auto",
  "credential_store": "file",
  "search_api": {},
  "check_updates": true,
  "editor": ""
}
```

## Providers

| Field | Type | Meaning |
| --- | --- | --- |
| `provider` | string or null | The active provider's canonical key, set by `/connect`. |
| `model` | string or null | The active model, set by `/model`. |
| `providers` | object | Saved connections, by canonical key. |

Use canonical keys from the [provider list](../providers/README.md#choose-a-connection). Aliases such as `codex` work only in commands.

Each entry in `providers` can contain:

| Field | Type | Meaning |
| --- | --- | --- |
| `api_key` | string | The key, stored in this file. |
| `api_key_ref` | `"keyring"` | Look the key up in the system keyring instead. |
| `base_url` | string | An API root that overrides the built-in one. |
| `model` | string | The remembered model for this provider. |
| `think` | boolean | [Thinking](../providers/thinking.md#local-models) for `ollama-local` and `llamacpp`. Defaults to true. |
| `reasoning_efforts` | object | [Per-model level](../providers/thinking.md#deepseek-and-chatgpt-plan) for DeepSeek or ChatGPT plan. DeepSeek accepts `default`, `none`, `low`, `high` and `max`. |
| `context_limit` | integer | [Context limit](../guides/context-and-usage.md#set-context-limits) for all models on this provider. |
| `model_context_limits` | object | Context limits for exact models on this provider. |

```json
{
  "provider": "ollama-local",
  "model": "your-downloaded-model",
  "providers": {
    "ollama-local": {
      "base_url": "http://localhost:11434",
      "model": "your-downloaded-model",
      "think": false
    },
    "custom-openai": {
      "base_url": "http://127.0.0.1:8080/v1",
      "api_key": "REPLACE_WITH_ENDPOINT_KEY",
      "model": "your-served-model"
    }
  }
}
```

## Credentials

By default, `credential_store` is `"file"`, so API keys are saved in `config.json`. Do not share that file. Set it to `"keyring"` to save new provider and search keys in your system's credential store, which needs a working keyring service. `eirene --doctor --json` reports whether one is available.

Eirene looks for a provider's key in this order:

1. A non-empty environment variable, `EIRENE_<PROVIDER>_API_KEY`, using the canonical name in uppercase, such as `EIRENE_ANTHROPIC_API_KEY`. A hyphen in the name stays a hyphen, so set such names with your platform's environment tools. This does not apply to the Codex and Claude Code CLIs, or to the search API.
2. The keyring, if `api_key_ref` is `"keyring"`. A missing keyring value does not fall back to the file.
3. `api_key` in the file.

Changing `credential_store` does not move existing keys. Enter them again with `/connect PROVIDER!` or `/search-api`.

The keyring service name is `eirene`, with provider keys as usernames and `search:tavily` for Tavily. Credentials for ChatGPT plan and MCP servers are stored in private files in the [data directory](data-directory.md).

## Modes and access

| Field | Default | Meaning |
| --- | --- | --- |
| `mode` | `"manual"` | `manual`, `accept`, `auto` or `plan`. Invalid values become `manual`. Headless runs default to Auto. |
| `permissions` | `"sandboxed"` | Always `sandboxed` on load. [Full access](../guides/modes-and-permissions.md#full-access) lasts only for the current process. |
| `execution_isolation` | `"auto"` | Always `auto`, which selects your platform's sandbox. |
| `isolate_network` | `true` | Restrict network access in the sandbox. MCP servers can declare their own grant. |
| `trusted_workspaces` | `[]` | Paths you have [trusted](../guides/sessions.md#workspace-trust). |

## Interface

| Field | Default | Meaning |
| --- | --- | --- |
| `theme` | `"default"` | [Theme name](../guides/appearance.md#themes). |
| `mouse` | `"auto"` | `"eirene"` or `"auto"`: Eirene handles the mouse, including over SSH. `"terminal"`: selection, copying and link clicks are left to your terminal. F4 switches for the session. |
| `reduce_motion` | `false` | [Reduce motion](../guides/appearance.md#reduce-motion). |
| `companion` | `false` | The [companion](../guides/appearance.md#companion). |
| `accessible_icons` | `false` | [Simpler icons](../guides/appearance.md#accessible-icons). |
| `seasonal_effects` | `true` | [December snowfall](../guides/appearance.md#december-snowfall). |
| `notifications` | `false` | [Desktop notifications](../guides/notifications.md). |
| `prompt_suggest` | `false` | [Follow-up suggestions](../guides/prompt-suggestions.md), using extra model requests. |
| `recap` | `true` | [Session recaps](../guides/context-and-usage.md#recaps), using extra model requests. |
| `fast_mode` | `false` | [Fast mode](../providers/fast-mode.md). |
| `check_updates` | `true` | [Startup update checks](../getting-started/updating.md#turn-off-update-checks). |
| `editor` | `""` | The editor `/config` opens. |

## Numeric limits

Values are converted to integers and limited to the range shown. A value that cannot be converted uses the default. Timeouts for providers, MCP, commands and headless runs are all separate, so raising one does not raise the others.

| Field | Default | Range | Meaning |
| --- | --- | --- | --- |
| `shell_timeout` | 120 | 1 to 86,400 | Seconds for [commands without a more specific limit](../guides/running-commands.md#timeouts) and for tool hooks. |
| `max_iterations` | 0 | 0 to 10,000 | Model and tool rounds per turn. 0 means no configured limit, though local profiles and subagents have their own. |
| `max_output_bytes` | 200,000 | 1,024 to 100,000,000 | Command output kept at the execution layer. Saved output has its own 20 MB limit. |
| `max_attachment_bytes` | 20,000,000 | 1 to 1,000,000,000 | Maximum size of each [attached file](../guides/terminal-interface.md#attach-files). |
| `request_timeout` | 300 | 1 to 86,400 | Seconds for provider requests. Both Ollama connections and `llamacpp` use at least 600. |
| `retry_attempts` | 12 | 1 to 100 | Total attempts per eligible provider call. |
| `max_tokens` | 16,384 | 512 to 393,216 | Output tokens requested per response. Most providers are capped at 200,000. DeepSeek uses its model's limit. Not honored by ChatGPT plan. |
| `context_warning` | 0 | 0 to 10,000,000 | 0 budgets from the model's size. A positive value makes compaction start earlier. |
| `log_max_bytes` | 2,000,000 | 10,000 to 100,000,000 | Size at which the runtime log rotates. |
| `log_backups` | 3 | 0 to 20 | Rotated logs kept. |

`log_level` is `INFO` by default, and can be `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL`. Other values become `INFO`.

## Context limits and costs

| Field | Default | Meaning |
| --- | --- | --- |
| `auto_compact` | `true` | Compact before the limit is reached. When false, compaction still happens when a request would not otherwise fit. |
| `model_context_limits` | `{}` | Exact model ID to token limit, on any provider. |
| `model_costs` | `{}` | Exact model ID to `input_per_million` and `output_per_million`, in US dollars. |

[Context and usage](../guides/context-and-usage.md#set-context-limits) explains the order of precedence and has examples. An oversized `max_tokens` can leave no room for input, because Eirene reserves it plus an overhead of 2,048 tokens (256 on local profiles) before fitting the conversation.

In `model_costs`, a used model with no entry makes the estimate unavailable, while an omitted rate inside an entry counts as zero.

## Skills and plugins

| Field | Shape | Behavior |
| --- | --- | --- |
| `skills` | skill ID to boolean | Missing means enabled. IDs are the filename stem, the folder name, or `folder:skill` and `plugin:skill`. |
| `plugins` | plugin name to boolean | Missing means enabled, though the plugin also needs trust. |
| `plugin_trust` | plugin name to boolean | Only `true` lets a plugin work. Missing means off. Added by commands. |
| `mcp_enabled` | server ID to boolean | For a server you added, only `true` turns it on. For a trusted plugin's server, only `false` turns it off. |

```json
{
  "skills": {"concise-reviews": true, "superpowers:brainstorming": false},
  "plugins": {"superpowers": true},
  "plugin_trust": {"superpowers": true},
  "mcp_enabled": {"example": false, "playwright__playwright": false}
}
```

Prefer `/skills`, `/plugins` and `/mcp`. Plugin servers are named `PLUGIN__SERVER`, and an entry in `mcp_servers` with the same name takes precedence.

## MCP servers

`mcp_servers` maps names to server definitions. [`/mcp add`](../extending/mcp.md#add-a-server) is usually easier than writing them by hand.

```json
{
  "mcp_servers": {
    "example": {
      "command": ["/absolute/path/to/server", "--stdio"],
      "env": {"EXAMPLE_SETTING": "value"},
      "cwd": ".",
      "network": false,
      "read_paths": ["/absolute/path/to/runtime"],
      "write_paths": ["/absolute/path/to/existing/cache"],
      "startup_timeout": 60,
      "request_timeout": 30
    }
  }
}
```

### MCP server fields

| Field | Default | Meaning |
| --- | --- | --- |
| `type` | inferred | `stdio`, `http` or `sse`. A `url` without a type means HTTP. |
| `command` | required for stdio | An array of the executable and its arguments. A string is one executable name, not parsed shell text. Separate `command` and `args` also work. |
| `url` | required for remote | The HTTP or HTTPS endpoint. |
| `auth` | `auto` without headers | `auto` discovers OAuth during setup, `oauth` requires browser sign-in, and `none` uses only configured headers. |
| `headers` | `{}` | HTTP headers. The setup wizard stores credentials privately, outside this file. |
| `scope` | discovered | OAuth scopes to request. |
| `client_metadata_url` | unset | HTTPS client metadata document, for servers that support it. |
| `oauth` | `{}` | Registered client settings: `client_id`, `client_secret`, `redirect_uri`, `scope`, `token_endpoint_auth_method` and `authorization_params`. |
| `auto_setup` | `false` | Prepare caches and runtime access again on each connection, as guided imports do. |
| `env` | `{}` | Environment values. Not interpolated by a shell. |
| `cwd` | workspace | A path inside the workspace. |
| `network` | false for stdio, true for remote | Network access. Must be a JSON boolean. |
| `read_paths`, `write_paths` | `[]` | Extra host paths exposed to the sandbox. They must exist. `~` is expanded, and `/` is refused. |
| `startup_timeout` | 30 | Seconds for initialization, from 1 to 600. Other values use 30. |
| `request_timeout` | 30 | Seconds for other requests, from 1 to 600. Other values use 30. |

Use literal absolute paths for executables: variables, `~`, quotes, redirects and pipes are not expanded in `command`. A runtime outside system folders may need its whole install folder in `read_paths`.

Codex and Claude Code receive only `command`, `args`, `env` and `cwd`.

## Tool hooks

`hooks` runs shell commands around each tool call. These are different from [plugin hooks](../extending/writing-plugins.md#hooks).

```json
{
  "hooks": {
    "before_tool": ["python scripts/check_workspace.py"],
    "after_tool": ["python scripts/record_tool.py"]
  }
}
```

Hooks run under the current sandbox, with `shell_timeout` as their limit and output capped at 50,000 bytes. Their environment includes `EIRENE_HOOK_EVENT`, `EIRENE_TOOL_NAME` and `EIRENE_TOOL_FAILED` (`"1"` or `"0"`). A failing hook raises a tool error. Having any hook turns off parallel reads, so the order stays predictable.

These commands run without a trust prompt, so add only commands you understand.

## Search API

`search_api` is empty by default. It configures the [Tavily fallback](../guides/web-and-browser.md#optional-tavily-fallback), and `/search-api` writes it for you.

```json
{
  "search_api": {
    "provider": "tavily",
    "api_key_ref": "keyring"
  }
}
```

Use `api_key` instead of `api_key_ref` for file storage.

## Environment variables

| Variable | Purpose |
| --- | --- |
| `EIRENE_HOME` | The [data directory](data-directory.md). |
| `EIRENE_<PROVIDER>_API_KEY` | Override a provider's [saved key](#credentials). |
| `EIRENE_CHROMIUM_PATH` | The browser executable for the [built-in browser](../guides/web-and-browser.md#use-the-browser). |
| `EIRENE_REDUCE_MOTION` | [Reduce motion](../guides/appearance.md#reduce-motion) when set to any non-empty value. |
| `EIRENE_NO_UPDATE_CHECK` | Skip startup update checks when set. |
| `EIRENE_OMNIROUTE_DATA_DIR` | The [gateway data directory](../providers/omniroute.md#gateway-data-directory). |
| `NO_COLOR` | Disable color. |

The installer has [its own variables](../getting-started/installation.md#installer-options).
