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
| Session-start, prompt-submit, and stop hooks | Trusted hooks run under the configured execution policy. |
| Stdio MCP servers | Explicit server activation for API or native CLI connections. |
| HTTP/SSE MCP and OAuth/app connectors | Not imported by this bundle installer. |
| Native status lines, LSP declarations, output styles, and other hook events | Not emulated; inspection reports compatibility limits. |

For a plugin's full workflow and requirements, use its individual guide from the
[catalog](plugin-catalog.md).
