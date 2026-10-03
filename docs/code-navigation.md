# Semantic code navigation

Eirene's native providers expose `code_navigation` with four actions:
`definition`, `references`, `hover`, and `diagnostics`. Definitions and references
use a source position instead of a symbol name, so a language server can distinguish
unrelated identifiers with the same spelling. The agent discovers relevant paths,
reads focused ranges, inspects symbol relationships, edits, and verifies with
diagnostics and project tests. Subscription providers retain their own tools.

Example tool arguments:

```json
{"path": "src/main.py", "action": "references", "line": 12, "column": 5}
```

Input lines and columns are 1-based; input columns count Unicode characters.
The client converts them to LSP's UTF-16 positions. Returned semantic locations
use 1-based UTF-16 columns. `limit` defaults to 100 and is capped at 500. Queries
default to 30 seconds and are capped at 120. Source files are limited to 1 MB;
protocol messages are limited to 4 MB.

## Servers

Eirene checks host PATH for these installed servers:

| Language | Command |
| --- | --- |
| Python | `pyright-langserver --stdio`, then `pylsp` |
| JavaScript / TypeScript / JSX / TSX | `typescript-language-server --stdio` |
| Rust | `rust-analyzer` |
| Go | `gopls` |
| C / C++ | `clangd --background-index=false` |

Custom definitions go in `~/.local/eirene/config.json` (or the directory selected
by `EIRENE_HOME`). Commands must be argv arrays, not shell command strings:

```json
{
  "language_servers": {
    "python": {
      "command": ["/path/to/venv/bin/pylsp"],
      "read_paths": ["/path/to/venv"],
      "initialization_options": {},
      "configuration": {
        "pylsp": {"plugins": {"pycodestyle": {"enabled": false}}}
      }
    },
    "rust": false
  }
}
```

`false` disables discovery for that language. `env` can supply explicit server
environment variables. Configuration is trusted local configuration, like MCP
server configuration; inspect executable paths and grants before adding them.
There are no automatic downloads, package installations, network grants, or
server-requested workspace edits. A server installed outside sandbox-readable
runtime directories needs an explicit `read_paths` grant.

## Execution and fallbacks

Each query starts a server in the existing command sandbox, opens the current
on-disk document, performs the request, and stops the process tree. Linux and
macOS queries use read-only workspace access with networking disabled. Windows
requires native execution approval and blocks these queries in plan mode.
Servers may need writable caches or dependencies that this restricted environment
does not provide; use project checks when the server cannot operate there.

Servers receive initialization/configuration requests but cannot request edits.
Locations outside approved paths are omitted. Diagnostics support both pull
responses and explicit push publications; a missing response times out rather
than being reported as a clean document. Queries do not keep a persistent index,
so large projects may take longer to initialize.

Without a server, definitions and references use labeled lexical matches. Those
matches are discovery leads, not evidence that all callers have been found.
Hover has no fabricated text fallback. Compiler/parser diagnostics remain
available through `language_diagnostics`; run the project's own tests/type checker
for acceptance. Existing `find_symbol`, `find_references`, and `search_text`
remain available for targeted text discovery.

The transport follows the [Language Server Protocol specification](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/).
