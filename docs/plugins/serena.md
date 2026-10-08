# Serena

[Documentation](../README.md) / [Plugin catalog](../plugin-catalog.md) / Serena

Serena adds language-server-assisted navigation, references, supported symbol
edits, and project memory through MCP. It is useful when textual search alone
cannot distinguish similarly named symbols or reliably trace their usage.

## Prerequisites

Install uv so `uvx` is available, and install Git. First startup needs network
access to fetch Serena and its environment. Language servers or project toolchains
vary by language; follow Serena's requirements for the project you are using.

## Install and enable

```text
/plugins install serena
/plugins inspect serena
/plugins doctor serena
/mcp
```

Enable Serena's server in the picker. Use a normal mode and a tool-capable provider
or native CLI connection. Plan mode does not launch imported MCP servers.

The standard catalog launcher uses Python 3.13 through uv, selects the project
from the current directory, and leaves the web dashboard closed. Python 3.13 is
the selected runtime, not a claim that every Serena release requires it as its
minimum version. Custom launchers are preserved.

Caches, downloaded environments, and Serena runtime data are managed beneath
`plugin-data/serena/mcp` in Eirene's data directory. The first startup allowance is
five minutes; package or language-tool problems can still fail it.

## Work on a project

```text
/serena Find references to InvoiceValidator and explain which call paths depend on its return type. Do not edit.
```

The canonical entry is `/serena:serena`. Eirene asks the model to follow Serena's
initial instructions and onboarding checks where available, then use the tools
advertised by the running server.

Project discovery uses the nearest Git root or Serena project configuration.
A folder without a recognized project may need explicit project activation through
the available Serena tools. Check the active project before a semantic edit.

```text
/serena Rename the internal validation helper and its references, preserving the public API. Run the relevant checks afterward.
```

Supported languages and symbol editing behavior depend on the installed Serena
version and language server. Semantic navigation does not replace project tests,
compilers, or runtime verification.

## Profiles, memory, and limits

Project memory belongs to Serena's own workflow. Eirene's session history and
`/plan` are separate. Do not assume the MCP server automatically reads all parent
conversation context or every project file.

Eirene-managed delegated read-only tasks do not start imported MCP servers; use
Serena in the main normal turn when its tools are needed. Built-in file and
reference search remains available for simpler investigations.

Use `/plugins doctor serena` for launcher/activation checks and inspect the actual
server error for missing language prerequisites. Disable it through `/mcp` when
finished. See [MCP](../mcp.md) and [code navigation](../code-navigation.md).

Sources: [catalog bundle](https://github.com/anthropics/claude-plugins-official/tree/main/external_plugins/serena),
[Serena user guide](https://oraios.github.io/serena/02-usage/020_running.html).

## Adapter environment and project identity

The recognized standard declaration is adapted to include `-p 3.13`,
`--project-from-cwd`, and `--open-web-dashboard false`. Runtime binding supplies
default cache/state environment values:

| Variable | Default beneath `EIRENE_HOME/plugin-data/serena/mcp` |
| --- | --- |
| `XDG_CACHE_HOME` | the MCP directory itself |
| `UV_CACHE_DIR` | the MCP directory itself |
| `UV_PYTHON_INSTALL_DIR` | `python/` |
| `SERENA_HOME` | `serena/` |

Explicit declaration values win over these defaults. The adapter creates the
MCP data directory and adds writable access, plus read access to the resolved
launcher's parent. A custom launcher that does not match the recognized standard
argv is not rewritten automatically.

The working directory is the workspace supplied by Eirene. Serena's own project
activation and memory are separate from Eirene's `projects/` cache and session
UUID. For custom declarations or runtime paths, read
[MCP fields](../config-file.md#standalone-mcp-declarations) and
[plugin import/refresh](../plugins.md#local-bundle-format).
