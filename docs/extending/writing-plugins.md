# Writing plugins

[Documentation](../README.md) / Extending Eirene / Writing plugins

A plugin is a folder. If you only need guidance, a [skill](skills.md) is simpler. Write a plugin when you want to package several skills, commands, specialist profiles, hooks or MCP servers together.

## Layout

```text
local-tools/
├── plugin.json
├── skills/
│   └── inspect-service/SKILL.md
├── commands/
│   └── inspect.md
├── agents/
│   └── reviewer.md
├── hooks/
│   └── hooks.json
└── .mcp.json
```

A plugin must contain at least one of these capabilities.

## The manifest

Eirene looks for a manifest in this order: `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`, `.agent-plugin/plugin.json`, `.github/plugin/plugin.json`, `plugin.json`. Plugins written for those other tools can therefore often be used
as they are. Without a manifest, Eirene discovers the conventional folders and MCP files.

```json
{
  "name": "local-tools",
  "description": "Instructions and tools for inspecting a local service",
  "skills": ["skills"],
  "commands": ["commands"],
  "agents": ["agents"],
  "mcpServers": ".mcp.json"
}
```

- `name` must match `[A-Za-z0-9][A-Za-z0-9_.-]*`.
- `skills`, `commands` and `agents` take a path or a list of paths relative to the plugin. Conventional folders are found in addition to these.
- Paths that leave the plugin folder are rejected. Plugins containing symlinks are rejected, even if the link stays inside.

## Install and iterate

```text
/plugins install /absolute/path/to/local-tools
/plugins trust local-tools
```

Installing copies the folder, so later edits to your source folder have no effect. To pick up source changes, run `/plugins update local-tools`. If you edit the installed copy under `plugins/local-tools/`, run
`/plugins refresh local-tools`. Refresh always removes trust, and update removes it when something changed, so trust the plugin again afterwards.

Eirene writes its index of the plugin to `.eirene-plugin.json`. This file is generated, so edit the source files rather than this one.

## Commands

Each Markdown file in `commands/` becomes a slash command named after the file.

```markdown
---
description: Inspect a running service
argument-hint: "[service name]"
---

Check the health of $ARGUMENTS and report anything unusual.
```

`$ARGUMENTS` is replaced by what the user typed, as literal text. Shell snippets using `!` in other tools' command formats are not executed when the command expands. The model carries out that work with its normal tools, under the usual approvals.

Front matter is read by a small key/value parser, not a full YAML parser. Built-in command names always take priority. If two plugins share a short name, the long form `/plugin:command` remains available.

## Specialist profiles

Each Markdown file in `agents/` becomes a [specialist profile](../guides/subagents.md#specialist-profiles), listed by `/agents list`, with the command `/plugin:agent-NAME`. A profile supplies instructions, and cannot choose a credential or model tier.

## MCP servers

Declare servers inline under `mcpServers` or `mcp_servers`, or in a relative JSON file. The default files are `.mcp.json`, then `mcp.json`.

```json
{
  "mcpServers": {
    "service": {
      "command": "/absolute/path/to/server",
      "args": ["--stdio"],
      "network": true
    }
  }
}
```

`${CLAUDE_PLUGIN_ROOT}`, `${CODEX_PLUGIN_ROOT}` and `${PLUGIN_ROOT}` expand to the installed plugin's folder. Other environment variables are not expanded in plugin declarations. The server's public name is `PLUGIN__SERVER`. See [MCP server fields](../reference/configuration.md#mcp-server-fields).

## Hooks

Eirene runs synchronous command hooks for two events, `SessionStart` and `UserPromptSubmit`, usually declared in `hooks/hooks.json`. Other events and async hooks are reported as unsupported.

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup",
        "hooks": [{"type": "command", "command": "node \"${PLUGIN_ROOT}/hooks/start.js\"", "timeout": 30}]
      }
    ]
  }
}
```

A plugin must be enabled and trusted for hooks to run, and Plan mode skips them. `SessionStart` runs once when the plugin's runtime starts, and `UserPromptSubmit` runs before each normal turn. The matcher must be a valid regular expression, and `SessionStart` matches against `startup`. The timeout defaults to 30 seconds, and can be from 1 to 120.

**Input.** The hook receives JSON on stdin with `session_id`, `cwd`, `hook_event_name`, `source` and `prompt`. Its environment includes the plugin root variables, `PLUGIN_DATA`, `CLAUDE_PLUGIN_DATA`, `XDG_CONFIG_HOME` and `EIRENE_SESSION_ID`. Under isolation, the plugin folder is read-only, and the session and persistent settings folders are writable.

**Output.**

| Hook output | Effect |
| --- | --- |
| Plain text on stdout | Added to the model's context. |
| JSON with `additionalContext` or `hookSpecificOutput.additionalContext` | Added to the model's context. |
| JSON with `systemMessage` | Shown as a notice. |
| JSON with `continue: false` or `decision: "block"` | Raises a blocking error. |
| A non-zero exit code | The hook fails. |

These hooks are separate from the [`before_tool` and `after_tool` hooks](../reference/configuration.md#tool-hooks) in `config.json`, which use a different format.

## What is not supported

Eirene does not recreate features specific to other hosts: status lines, LSP declarations, output styles, and other hook events are all skipped. `/plugins inspect` lists anything it skipped.

## Share your plugin

Any Git repository works: others can run `/plugins install owner/repository`. To list several plugins, publish a [marketplace](plugins.md#marketplaces).
