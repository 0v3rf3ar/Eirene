# config.json reference

[Documentation](README.md) / [Configuration](configuration.md) / config.json

This page describes the file read by `eirene.core.config.Config`, including
normalization and the nested objects consumed by the runtime. Examples describe
this repository's implementation; they are not provider pricing or availability
claims. For the files surrounding this configuration, see [data layout](data-layout.md).

## Contents

- [Locate and edit](#locate-and-edit-the-file)
- [Loading, defaults, and saves](#loading-defaults-and-saves)
- [Complete defaults](#complete-default-file)
- [Providers and credentials](#provider-selection-and-credentials)
- [Modes, access, and interface](#modes-access-and-interface)
- [Numeric limits](#numeric-limits)
- [Context and costs](#context-limits-and-cost-rates)
- [Skills and plugin activation](#skill-and-plugin-maps)
- [Standalone MCP fields](#standalone-mcp-declarations)
- [Tool hooks](#tool-hooks)
- [Search API](#search-api)

## Locate and edit the file

The path is `~/.local/eirene/config.json` on Linux, macOS, and Windows. Windows
uses the user's home directory rather than `%LOCALAPPDATA%` for application data.
Setting `EIRENE_HOME` before launch changes the directory containing the file:

```sh
EIRENE_HOME=/absolute/path/to/eirene-data eirene -C /absolute/path/to/project
```

```powershell
$env:EIRENE_HOME = 'C:\Users\you\eirene-data'
eirene -C 'C:\Users\you\Projects\example'
```

There is no public `--config` option, project-local config overlay, or `/config`
editor. `-C` selects the workspace, not the configuration directory. Separate
`EIRENE_HOME` directories give separate saved preferences and histories. They do
not isolate external CLI logins or OS keyring identities.

Close Eirene before manual edits: its live configuration is held in memory and
later saves can overwrite a file edited underneath it. Back up `config.json`,
merge the fields you need, and restart. An example object on this page is a
fragment to merge unless explicitly identified as a complete default file.
Replacing the whole file with a fragment discards settings not in that fragment.

Use UTF-8 JSON, with double-quoted keys and strings, lowercase `true`, `false`,
and `null`, and no comments or trailing commas. Windows paths need escaped
backslashes (`"C:\\Tools\\java.exe"`) or forward slashes (`"C:/Tools/java.exe"`).
`null`, an empty string, and an omitted key are different values. Use native
JSON booleans; `"false"` is a nonempty string and can evaluate as enabled.

A source installation with Python can check syntax without launching Eirene:

```sh
python -m json.tool /absolute/path/to/config.json
```

This checks JSON syntax only. It does not validate credentials, executable paths,
model identifiers, or every nested Eirene field.

## Loading, defaults, and saves

1. A missing or whitespace-only file loads as an empty object.
2. Invalid JSON or a top-level value other than an object causes a best-effort
   copy to `config.json.bak`, then defaults are used. The original is not moved.
   The next save can replace it; preserve both files before recovery.
3. Old versions are migrated in memory, then built-in defaults are copied and
   top-level saved keys are overlaid. Nested objects are not recursively merged.
4. Selected types and ranges are normalized. The resulting schema version is `3`.
5. A save writes indented JSON to a temporary `.config-*.tmp` file beside the
   destination, flushes and syncs it, then replaces the destination atomically.
   On POSIX, the saved config is mode `0600` and its parent is tightened to `0700`.

A read permission error raises a configuration error rather than loading defaults.
Migration does not rewrite the file until a save occurs. Version 1/2 migrations
restore automatic isolation, network isolation, and automatic compaction defaults.
Setting `version` to an older number can therefore change those values on load.
Do not use this field to select a program release.

Unknown top-level keys are retained but do not create features. Not every nested
object is validated during loading; an invalid nested field can fail when used.
The object fields `providers`, `skills`, `plugins`, `hooks`, `mcp_servers`,
`mcp_enabled`, `model_context_limits`, `model_costs`, and `search_api` are reset to
empty objects if their top-level value is not an object.

## Complete default file

These are the defaults for a new configuration at schema version 3. Runtime
choices, platform behavior, and provider-specific limits can narrow them.

```json
{
  "version": 3,
  "provider": null,
  "model": null,
  "mode": "manual",
  "theme": "default",
  "providers": {},
  "skills": {},
  "shell_timeout": 120,
  "max_iterations": 0,
  "max_output_bytes": 200000,
  "request_timeout": 300,
  "retry_attempts": 12,
  "notifications": false,
  "max_tokens": 16384,
  "context_warning": 60000,
  "log_level": "INFO",
  "log_max_bytes": 2000000,
  "log_backups": 3,
  "execution_isolation": "auto",
  "permissions": "sandboxed",
  "prompt_suggest": false,
  "isolate_network": true,
  "plugins": {},
  "hooks": {},
  "mcp_servers": {},
  "mcp_enabled": {},
  "auto_compact": true,
  "model_context_limits": {},
  "model_costs": {},
  "reduce_motion": false,
  "accessible_icons": false,
  "credential_store": "file",
  "search_api": {},
  "check_updates": true
}
```

## Provider selection and credentials

| Field | Type | Interpretation |
| --- | --- | --- |
| `provider` | string or null | Active canonical provider key, such as `anthropic` or `ollama-local`; `/connect` sets it. |
| `model` | string or null | Active model identifier; `/model` sets it. |
| `providers` | object | Saved connection entries indexed by canonical provider key. |
| `credential_store` | `"file"` or `"keyring"` | Destination for newly saved provider and search keys. Invalid values normalize to `"file"`; case is normalized. |

A provider entry can contain:

| Nested field | Type | Meaning |
| --- | --- | --- |
| `api_key` | string | File-stored credential. Empty keys are treated as absent. |
| `api_key_ref` | `"keyring"` | Look up the credential in the OS keyring instead of `api_key`. |
| `base_url` | string | API root overriding the provider's built-in default. |
| `model` | string | Remembered model for this provider, used when switching connections and in headless selection. |
| `think` | boolean | Local Ollama thinking preference; defaults to true when absent. |

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

Use canonical keys in the file. Command aliases such as `codex` and `openai` are
resolved by commands; they are not additional provider entries. Endpoints and
supported protocols are listed in [providers](providers.md).

For provider `NAME`, a nonempty `EIRENE_<NAME_IN_UPPERCASE>_API_KEY` wins over the
saved credential. Next, `api_key_ref: "keyring"` selects keyring lookup; otherwise
`api_key` is used. A missing keyring value does not fall back to the file key.
Hyphens in provider names remain hyphens in the environment variable name.

The keyring service is `eirene`. Provider usernames are their canonical keys;
Tavily uses `search:tavily`. `EIRENE_HOME` is not part of these usernames, so two
data directories share keyring identities for the same provider. External Codex
and Claude Code logins are managed by those CLIs instead.

Changing `credential_store` does not migrate keys already stored. Reenter them
through `/connect PROVIDER!` or `/search-api` to save using the new destination.
A keyring reference needs a functioning backend on every machine using the file.

Headless provider selection uses `--provider`, then the active provider. Model
selection uses `--model`, the chosen provider's saved model, the active top-level
model, then the provider's bundled default. API root selection uses an explicit
connection override, saved `base_url`, then the built-in provider root. These
layers are independent: changing one does not replace credentials for another.

## Modes, access, and interface

| Field | Default | Values and effect |
| --- | --- | --- |
| `mode` | `"manual"` | `manual`, `auto`, or `plan`. Invalid values become `manual`. Interactive mode is saved; a headless prompt defaults to Auto. |
| `permissions` | `"sandboxed"` | Always normalized to `sandboxed` on load and written as `sandboxed` on save. Full access is process-local. |
| `execution_isolation` | `"auto"` | Always normalized to `auto`; selects platform behavior. Legacy `container_image` is removed. |
| `isolate_network` | `true` | Restricts network access for sandboxed execution; a manually enabled MCP server can declare its own network grant. |
| `theme` | `"default"` | Saved palette name; available names are in [appearance](appearance.md). |
| `notifications` | `false` | Desktop notifications; `/notification` controls it. |
| `prompt_suggest` | `false` | Additional model requests for follow-up drafts; `/prompt-suggest` controls it. |
| `reduce_motion` | `false` | Static activity markers. `--reduce-motion` or a nonempty `EIRENE_REDUCE_MOTION` also enables it. |
| `accessible_icons` | `false` | Alternative icon presentation. |
| `check_updates` | `true` | Startup release checks. A nonempty `EIRENE_NO_UPDATE_CHECK` skips these checks; `/update check` remains explicit. |

`isolate_network`, `auto_compact`, `reduce_motion`, and `accessible_icons` are
converted with Python boolean truthiness on load. Other boolean preferences are
not all normalized; consistently use JSON booleans. For the actual execution
boundary and temporary host grants, see [permissions](harness.md).

## Numeric limits

All fields below are converted using integer conversion and clamped to the
inclusive range shown. A conversion failure uses the built-in default.

| Field | Default | Range | Unit and consumer |
| --- | --- | --- | --- |
| `shell_timeout` | 120 | 1–86400 | Seconds; fallback command and configured tool-hook deadline. Command classification or an explicit tool timeout can choose another deadline. |
| `max_iterations` | 0 | 0–10000 | Model/tool rounds per managed turn; 0 removes this configured cap. Local model profiles and delegation impose independent limits. |
| `max_output_bytes` | 200000 | 1024–100000000 | Command output budget at the execution layer. Context and UI limits can truncate further. Does not increase artifact capacity. |
| `request_timeout` | 300 | 1–86400 | Provider timeout in seconds. Both local and hosted Ollama use at least 600 seconds in the provider factory. |
| `retry_attempts` | 12 | 1–100 | Total allowed attempts per eligible provider call, including the first attempt. |
| `max_tokens` | 16384 | 512–200000 | Requested output allowance per model response; provider and local-profile limits still apply. |
| `context_warning` | 60000 | 0–10000000 | Estimated token budget input for managed context. Zero currently falls back to 60000 at use sites; it does not disable budgeting. |
| `log_max_bytes` | 2000000 | 10000–100000000 | Runtime log rotation threshold in bytes. |
| `log_backups` | 3 | 0–20 | Rotated runtime logs retained. |

`log_level` defaults to `INFO`. It is uppercased and checked against `DEBUG`,
`INFO`, `WARNING`, `ERROR`, and `CRITICAL`; invalid levels become `INFO`.
Provider timeouts, MCP request timeouts, shell deadlines, and overall headless
run timeouts are separate. Increasing one does not increase the others.

## Context limits and cost rates

`auto_compact` defaults to true. When false, exceeding the managed budget fails
with a request to compact or enable automatic compaction. Native CLI connections
own their context and bypass Eirene's managed budgeting.

`model_context_limits` maps exact model identifiers to positive integer token
limits. It has no wildcard or provider-name matching. Local Ollama preparation
can supply a lower effective limit. Budgeting reserves the output allowance plus
2048 tokens for general API providers, or 256 for local profiles, then accounts
for instructions and tool schemas. An oversized `max_tokens` can leave no room
for input even when the conversation is short.

`model_costs` maps exact recorded model identifiers to rate objects:

```json
{
  "auto_compact": true,
  "model_context_limits": {"your-model-id": 32768},
  "model_costs": {
    "your-model-id": {
      "input_per_million": 1.25,
      "output_per_million": 5.00
    }
  }
}
```

Use nonnegative numeric rates in USD per million tokens. These are illustrative
values. If a used model has no rate object, the estimate is unavailable; an
omitted input/output rate inside an existing object currently counts as zero.
Invalid rate conversion also makes the estimate unavailable. Configuration does
not alter the service's billing or model capacity. See [context](context-and-usage.md).

## Skill and plugin maps

| Field | Shape | Behavior |
| --- | --- | --- |
| `skills` | skill identifier → boolean | Missing preferences default to enabled. Local flat filenames use the stem; directory skills use the directory name; plugin skills use `plugin:skill`. |
| `plugins` | installed plugin name → boolean | Missing preferences default to enabled. Disabling a bundle also prevents its skills, commands, hooks, and servers from being used. |
| `plugin_trust` | installed plugin name → boolean | Hook trust for imported bundles. This map is added by commands rather than included in the default file. |
| `mcp_enabled` | available server identifier → boolean | Only the actual boolean `true` activates a server. Absence means disabled. |

```json
{
  "skills": {"concise-reviews": true, "superpowers:brainstorming": false},
  "plugins": {"superpowers": true},
  "plugin_trust": {"superpowers": false},
  "mcp_enabled": {"example": false, "playwright__playwright": false}
}
```

Use the identifier actually shown by `/mcp`; imported servers are named
`PLUGIN__SERVER`. Direct `mcp_servers` entries retain their keys and take
precedence on a name collision. `/plugins trust` does not activate MCP.
`/plugins refresh` and `/plugins untrust` disable the affected plugin's servers.
Prefer the activation commands when changing execution grants in a live session.

## Standalone MCP declarations

`mcp_servers` maps server names to stdio launch definitions. This is the way to
configure a server without installing a plugin. It declares available servers;
`mcp_enabled` separately records activation.

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

| Server field | Default | Meaning |
| --- | --- | --- |
| `command` | required | Nonempty array of executable plus separate arguments. A string is treated as one executable name, not parsed shell text. |
| `env` | `{}` | Environment overrides; keys and values are converted to strings by the managed client. |
| `cwd` | workspace | Relative path resolved beneath the workspace. A path leaving it is rejected by the managed client. |
| `network` | no grant | Only JSON `true` grants network access to the enabled managed process. |
| `read_paths` | `[]` | Additional host paths exposed read-only to the command sandbox. |
| `write_paths` | `[]` | Additional host paths exposed writable to the command sandbox. |
| `startup_timeout` | 30 | Initialization request deadline in seconds. |
| `request_timeout` | 30 | Other MCP request deadlines in seconds. |

Timeouts accept numbers in 1–600; out-of-range or invalid values use 30, rather
than clamping. `startup_timeout` applies to initialization, not the entire tool
catalog sequence. Each `tools/list` page uses the ordinary request deadline.

Put every argument inside `command` for a direct config entry. Separate `args`
is normalized by the **plugin importer**, not the managed standalone client.
Use literal absolute executable/JAR paths: the launcher does not expand shell
variables, `~`, quotes, redirections, or pipes. An `env` value is not a shell
interpolation template. Plugin-root substitutions apply to plugin declarations,
not arbitrary standalone configuration.

Read/write paths are resolved against the workspace and support `~` expansion
in the isolation layer. They must already exist; `/` cannot be granted as a mount.
A runtime outside system directories can need its entire specific installation
root, not just its launcher file. Sandboxed children have a filtered environment
and private home; outside isolation, the managed client inherits the process
environment then adds `env`. A writable path does not make a host directory the
server's working directory.

Native CLI connections receive translated `command`, `args`, `env`, and `cwd`.
Eirene's additional mounts, network flag, and timeouts are not forwarded as native
CLI configuration fields; each CLI applies its own runtime policy. See [MCP](mcp.md).

## Tool hooks

The top-level `hooks` object supports `before_tool` and `after_tool` arrays of
shell command strings. This differs from a plugin's imported lifecycle hook file:

```json
{
  "hooks": {
    "before_tool": ["python scripts/check_workspace.py"],
    "after_tool": ["python scripts/record_tool.py"]
  }
}
```

These are executable configuration, not Markdown guidance. Commands use the
current isolation/network policy and `shell_timeout`, with output bounded to at
most 50000 bytes at the hook layer. The environment includes `EIRENE_HOOK_EVENT`,
`EIRENE_TOOL_NAME`, and `EIRENE_TOOL_FAILED` (`"1"` or `"0"`). Failure raises a
tool error. Configured hooks do not use the imported plugin trust picker.
Installed plugins can also contribute legacy hooks; imported lifecycle hooks
are documented in [plugins](plugins.md). Hook presence disables the managed
parallel-read optimization so ordering remains explicit.

## Search API

`search_api` is empty by default. The supported fallback is Tavily:

```json
{
  "search_api": {
    "provider": "tavily",
    "api_key_ref": "keyring"
  }
}
```

For file storage, use `api_key` instead of `api_key_ref`. `/search-api` validates
and saves the key. The generic provider environment override does not apply to
this separate lookup. The fallback is used when normal search fails; it does
not change the conversation model. See [web research](web-search.md).

## Implementation references

The schema and migrations are in [`core/config.py`](../eirene/core/config.py),
paths in [`core/paths.py`](../eirene/core/paths.py), provider construction in
[`providers/registry.py`](../eirene/providers/registry.py), and standalone MCP
execution in [`core/mcp.py`](../eirene/core/mcp.py). Refer to these when maintaining
this guide after implementation changes.
