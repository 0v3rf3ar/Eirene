# Serena

[Documentation](../../README.md) / [Plugin catalog](../plugin-catalog.md) / Serena

Serena adds language-server navigation, references, symbol edits and project memory through MCP. It helps when text search cannot distinguish similarly named symbols or reliably trace their use. For simpler investigations, the [built-in search](../../guides/working-with-code.md) is enough.

## Requirements

- `uv`, so that `uvx` is available, and Git.
- Network access on first start, to fetch Serena and its environment.
- Language servers or toolchains, depending on your language. Serena's documentation lists them.

## Install

```text
/plugins install serena
/plugins inspect serena
/plugins doctor serena
/plugins trust serena
```

Trusting the plugin starts the server on your next message. Use a normal mode with a tool-capable provider or a CLI connection. Plan mode does not start it. The first start can take up to five minutes.

## Use it

```text
/serena Find references to InvoiceValidator and explain which call paths depend on its return type. Do not edit.
/serena Rename the internal validation helper and its references, preserving the public API. Run the relevant checks afterward.
```

The full command name is `/serena:serena`. Eirene asks the model to follow Serena's initial instructions and onboarding, then use the tools the running server offers.

Serena finds your project from the nearest Git root or its own project configuration. A folder without either may need activating through Serena's tools, so check which project is active before a symbol edit.

Supported languages and edit behavior depend on your Serena version and language server. Your project's tests and compilers are still needed to verify changes.

## Limits

- Read-only [subagents](../../guides/subagents.md) do not start MCP servers, so use Serena in the main conversation.
- Serena's project memory is separate from Eirene's sessions and plans.
- The server does not automatically see your conversation or every project file.
- For missing language prerequisites, read the server's actual error. `/plugins doctor serena` covers only the launcher and activation.

## How it is set up

The standard launcher uses Python 3.13 through `uv`, selects the project from the current directory, and leaves the web dashboard closed (`-p 3.13 --project-from-cwd --open-web-dashboard false`). Downloads and state are kept in `plugin-data/serena/mcp` in the [data directory](../../reference/data-directory.md):

| Variable | Default within that folder |
| --- | --- |
| `XDG_CACHE_HOME`, `UV_CACHE_DIR` | The folder itself |
| `UV_PYTHON_INSTALL_DIR` | `python/` |
| `SERENA_HOME` | `serena/` |

Values in the plugin's declaration take priority. A custom launcher is kept as written, without these settings and grants.

## Origin

Serena is made by Oraios, with thanks. Sources: [catalog bundle](https://github.com/anthropics/claude-plugins-official/tree/main/external_plugins/serena) and [Serena's user guide](https://oraios.github.io/serena/02-usage/020_running.html).
