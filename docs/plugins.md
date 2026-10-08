# Plugin management

[Documentation](README.md) / Plugins

Plugins bundle reusable guidance, task commands, specialist profiles, and optional
executable integrations. Start with one workflow you need, inspect its imported
capabilities, and activate only the executable parts you intend to use.

## Find and install

```text
/plugins browse
/plugins install superpowers
/plugins inspect superpowers
```

The catalog currently has [14 named shortcuts](plugin-catalog.md). GitHub installs
require Git on PATH and network access. The installer downloads and imports the
bundle without running its repository installer. It preserves supporting files
and licenses and rejects symlink-containing bundles.

Other supported source forms are:

```text
/plugins install owner/repository
/plugins install owner/repository/path/to/plugin
/plugins install https://github.com/owner/repository/tree/main/path/to/plugin
/plugins install /absolute/path/to/local-plugin
```

These illustrate source formats; replace the owner, repository, and path with a
real bundle. A GitHub tree URL must include a branch or tag and plugin directory;
branch names with slashes are not supported by that form. Private repositories
need working Git authentication, since Eirene does not open a credential prompt
for the clone.

If a bundle is already installed, its files are preserved and installation reports
that it exists. Installation does not overwrite it or fetch an upgrade in place.

## Understand activation

```text
install bundle
    |
    +-- written skills and commands -> available when enabled
    +-- hooks -> inspect -> /plugins trust NAME
    `-- external MCP tools -> inspect -> /mcp -> enable each server
```

Installed bundles are enabled by default unless a saved preference disables them.
Use `/plugins` to toggle the bundle and `/skills` for individual skills. Changes
apply on the next turn. Turning a bundle off removes its guidance and commands;
it also prevents its executable integrations from being active.

Hooks and MCP have separate controls. `/plugins trust NAME` approves hooks after
showing compatibility and execution details. It does not enable MCP. `/mcp`
requires a separate choice for each server, even if hooks are trusted.

## Use commands

```text
/feature-dev Add a CSV export for filtered invoices.
/pr-review-toolkit:review-pr tests errors
```

A plugin command loads written instructions into a normal agent turn. It can use
files, commands, questions, and external tools according to the selected provider
and permission policy. It does not automatically execute every workflow in the
bundle or bypass approval.

Namespaced commands use `/installed-name:command`. A short `/command` alias appears
only when unambiguous and not reserved by a built-in. Use namespaced commands in
saved instructions for predictability. `/help` and slash completion show the
currently available commands.

Arguments are inserted as literal task text. Embedded upstream shell snippets
are performed through ordinary tools when needed, rather than executed simply
because a Markdown command was expanded.

The `anthropic-skills` shortcut installs the upstream bundle under the name
`skills`. Use `/skills:docx`, for example; the built-in `/skills` remains the skill
picker. Catalog shortcuts can be used for inspection and management of the bundles
installed through them.

## Diagnose, revoke, and refresh

```text
/plugins doctor
/plugins doctor playwright
/plugins untrust ponytail
/plugins refresh superpowers
```

Doctor checks activation, executable prerequisites, provider limitations, and
known startup errors without running plugin code. It cannot prove that a browser,
remote account, or every language server works.

Untrust revokes hook trust and disables the plugin's MCP servers. Refresh rebuilds
the imported index from files already installed and also revokes these executable
grants. Reinspect afterward, then trust hooks or enable MCP again if appropriate.
Finish or stop the current turn before changing executable plugin settings.

Refresh is not an updater. To replace a bundle, disable it, stop Eirene, back up
and move its installed directory out of `plugins/`, then install the desired
source again. Review any restored configuration and reapprove executable parts.
There is no `/plugins remove` or `/plugins update` command. For removal, disable
the bundle and remove its directory yourself while Eirene is closed; keep a backup
if you need its files or state.

## Provider compatibility

Written workflows are adapted to Eirene's selected provider. API specialist work
uses the same provider and model instead of imposing upstream Claude model names.
Codex and Claude Code receive guidance and enabled stdio MCP definitions through
their own interfaces.

This does not make every connection equally capable. A text-only provider cannot
run tools. Vision requires a suitable model. Dependencies such as Node.js, Git,
browsers, document renderers, and language servers must be available separately.
See [specialists](specialists.md) and [MCP](mcp.md).

| Imported capability | User-visible support |
| --- | --- |
| Markdown skills and commands | Guidance and task commands, with supporting resources retained. |
| Specialist agent profiles | Profile commands and independent task passes where supported. |
| Session-start and prompt-submit hooks | Trusted synchronous command hooks run under the configured execution policy. |
| Stdio MCP servers | Explicit server activation for API or native CLI connections. |
| HTTP/SSE MCP and OAuth/app connectors | Not imported by this bundle installer. |
| Native status lines, LSP declarations, output styles, and other hook events | Not emulated; inspection reports compatibility limits. |

For a plugin's full workflow and requirements, use its individual guide from the
[catalog](plugin-catalog.md).

## Local bundle format

The importer recognizes manifests in this order:
`.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`,
`.agent-plugin/plugin.json`, `.github/plugin/plugin.json`, then `plugin.json`.
Without a manifest it can discover conventional directories and MCP files.
The name must match `[A-Za-z0-9][A-Za-z0-9_.-]*`.

A small local source bundle can have:

```text
local-tools/
├── plugin.json
├── skills/
│   └── inspect-service/SKILL.md
├── commands/
│   └── inspect.md
├── agents/
│   └── reviewer.md
└── .mcp.json
```

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

Install with `/plugins install /absolute/path/to/local-tools`. This copies the
source, including support files; it does not link live edits back to your source
directory. The importer writes `.eirene-plugin.json` with normalized lists and
combined MCP argv. Discovery prefers that generated index over `plugin.json`.
`/plugins refresh local-tools` rebuilds the index from the **installed** source
files and revokes executable grants. It does not recopy your original directory.

`skills`, `commands`, and `agents` accept a path or list of paths relative to the
bundle. Conventional paths are discovered in addition to those declarations.
Command and agent directories are searched for Markdown. Skill discovery uses
`SKILL.md`, flat files in `skills/`, and explicitly declared files. Paths escaping
the bundle are rejected; symlink-containing imports are rejected even if their
target is inside the repository. There must be at least one imported capability.

MCP declarations can be inline under `mcpServers`/`mcp_servers`, or a relative
JSON filename. Default filenames are `.mcp.json`, then `mcp.json`. The importer
accepts string or array `command` plus array `args` and combines them. Definitions
without a stdio command produce a compatibility warning and are skipped. For
runtime fields, see the [configuration reference](config-file.md#standalone-mcp-declarations).

`${CLAUDE_PLUGIN_ROOT}`, `${CODEX_PLUGIN_ROOT}`, and `${PLUGIN_ROOT}` in imported
server definitions expand to the installed bundle directory. They do not make
arbitrary environment-variable interpolation available. Imported server names
are `PLUGIN__SERVER`; tools are discovered when the server is activated.

## Imported lifecycle hooks

The portable importer accepts synchronous command hooks for `SessionStart` and
`UserPromptSubmit`, typically in `hooks/hooks.json`. Other events and async hooks
are reported as unsupported. Hook matcher strings are validated as regular
expressions. A hook timeout defaults to 30 seconds and is bounded to 1–120.

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

An imported bundle must be enabled and trusted for lifecycle execution. Plan
mode skips it. The runtime runs startup once per runtime activation, then prompt
submission before normal turns. It applies the startup matcher to `startup`;
this is not an implementation of every upstream host's matcher/event semantics.

stdin contains JSON with `session_id`, `cwd`, `hook_event_name`, `source`, and
`prompt`. Environment includes plugin-root variables, `PLUGIN_DATA`,
`CLAUDE_PLUGIN_DATA`, `XDG_CONFIG_HOME`, and `EIRENE_SESSION_ID`. Per-session and
persistent settings directories are writable; the installed bundle is read-only
under isolation. See [data layout](data-layout.md).

Plain stdout becomes model context. JSON stdout can supply `additionalContext`
or `hookSpecificOutput.additionalContext`, plus `systemMessage` for a notice.
`continue: false` or `decision: "block"` raises a blocking error. Nonzero exit
also fails the hook. Hook execution is distinct from reading a Markdown command.
Top-level config `before_tool`/`after_tool` hooks use a different schema; see
[tool hooks](config-file.md#tool-hooks).

## Command adaptation

Imported Markdown is interpreted as instructions for the selected provider.
Front matter is parsed by a small key/value parser, not a complete YAML engine.
Arguments are inserted as literal task text; upstream `!` shell snippets are
converted to normal tool work, not executed at expansion time. Reserved built-in
commands win over aliases. Explicit namespaced commands remain available when
short names collide.

Native-only host features are not recreated just because a manifest declares
them. Inspector warnings report unsupported hook events, LSP declarations, and
output styles. Repository installation downloads files but does not execute
install scripts. See [skills](skills.md) for guidance loading and
[specialists](specialists.md) for independent contexts.
