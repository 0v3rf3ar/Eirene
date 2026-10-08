# MCP servers

[Documentation](README.md) / MCP servers

An MCP server adds tools from an external program, such as a browser automation
service or a semantic code assistant. A plugin can declare the server, but Eirene
requires you to enable it separately before it starts.

## Enable a server

```text
/plugins install playwright
/plugins inspect playwright
/mcp
```

In the picker, select the server to toggle it on, then select Done. Review its
launcher, network access, and writable paths. The plugin must be enabled first.
Finish or stop the current turn before changing server activation.

The server starts on the next normal agent turn. Plan mode does not launch
imported MCP servers. `/plugins trust` applies to hooks and is not needed merely
to toggle an MCP-only plugin's server.

## Use the tools

```text
/playwright Check the local app's navigation and report broken links.
```

Use the plugin entry command or ask in ordinary language. Eirene discovers the
tools actually advertised by the running version. API providers expose them to a
tool-capable model. Codex and Claude Code receive the enabled stdio declaration
and use their native MCP handling.

Server activation and tool readiness are different. The server may start while a
browser binary, language toolchain, project selection, or service authorization
still needs setup. Do not treat successful discovery as a completed browser test
or proof of remote management access.

## Inspect startup problems

```text
/plugins doctor playwright
/plugins inspect playwright
```

Check PATH, server activation, current mode, provider tool support, and network
access for first-use downloads. Playwright needs Node.js/npx plus browsers and OS
libraries. Serena needs uv/uvx, Git, and language-specific prerequisites. OmniRoute
needs its separate CLI, gateway, and management authorization.

The doctor reports known startup errors for the current agent. A fresh native CLI
connection can expose its own errors rather than Eirene's server-manager history.
See [Playwright](plugins/playwright.md), [Serena](plugins/serena.md), and
[OmniRoute](omniroute.md) for exact setup flows.

## Disable or replace

Open `/mcp` and toggle the server off. The picker closes existing Eirene-managed
stdio processes when applying changes; the selected state takes effect for the
next normal turn. Disabling the bundle also prevents use of its servers.

`/plugins untrust NAME` and `/plugins refresh NAME` disable that plugin's MCP
activation. After changing installed declarations, refresh and manually enable
again. Reverting to `/permissions sandboxed` also stops Eirene-managed servers.
Already completed external actions are not undone.

## Supported connections

The plugin importer supports stdio server launchers with their arguments and
environment. It does not import HTTP/SSE transports or OAuth app connections.
A native CLI may support additional transports outside Eirene, but that does not
make them available through this installer. Use the declared grants and the
[permission guide](harness.md) to understand a server's access.

## Declare a standalone server

A server does not need to belong to a plugin. Close Eirene and merge a declaration
into `mcp_servers` in [config.json](config-file.md#standalone-mcp-declarations):

```json
{
  "mcp_servers": {
    "local-tools": {
      "command": ["/absolute/path/to/server", "--stdio"],
      "env": {"SERVER_SETTING": "value"},
      "network": false,
      "startup_timeout": 60,
      "request_timeout": 30
    }
  }
}
```

Use the executable and flags documented by the server. A direct config entry
uses an argv array including all arguments, rather than the plugin importer's
separate `command` and `args` fields. This is not shell syntax: pipes, shell
variables, and a command-plus-arguments string are not expanded.

Restart Eirene, open `/mcp`, and toggle `local-tools` on. Its activation key is
`mcp_enabled.local-tools`. Imported plugins instead use `PLUGIN__SERVER` keys.
A direct entry takes precedence if it collides with a plugin's public server key.
The picker supports activation; it does not create or edit declarations, and
there is no `/mcp add` command in this implementation.

For all launcher, environment, working-directory and mount fields, see the
[configuration reference](config-file.md#standalone-mcp-declarations).

## Connection sequence and protocol limits

For managed API connections, Eirene launches the process with stdin/stdout pipes
and drains stderr into an 8192-byte diagnostic tail. It sends JSON-RPC
`initialize` with protocol version `2025-03-26`, sends
`notifications/initialized`, then calls `tools/list`. Pagination follows
`nextCursor`; repeated cursors and excessive pagination are rejected.

The managed client uses newline-delimited JSON, one object per stdout line,
with a 4 MiB per-line reader limit. A launcher must send logs to stderr; text
logs on stdout are treated as invalid JSON. The default deadline is 30 seconds
per request. Server-specific deadlines accept 1–600 seconds. Initialization
uses `startup_timeout`; listing and calling use `request_timeout`.

The public tool name is `mcp__SERVER__REMOTE_TOOL`, with unsupported characters
replaced by underscores. Tool descriptions and JSON input schemas come from
the server; a missing schema falls back to an empty object schema. Server
initialization instructions are appended to managed guidance. Each client's
requests are serialized by a lock, rather than multiplexed on its stream.

`tools/call` sends the remote name and argument object. Text content blocks are
joined; other blocks are serialized as JSON text. An `isError` result becomes a
tool error. This client is primarily a tool bridge: it does not implement a
resource browser, prompt picker, sampling, or elicitation. Server `ping` requests
are answered; other server-to-client requests receive method-not-supported.

## Runtime and grant boundaries

The managed server's working directory defaults to the project and cannot leave
it through `cwd`. Executable dependencies can be exposed through read-only
`read_paths`; additional writable state uses `write_paths`. Paths must exist
before launching an isolated process. Network permission is enabled only by the
actual boolean `network: true`, not the string `"true"`.

Process isolation and declared grants control what the server process can access.
They do not authenticate the downstream service or interpret every remote tool's
side effect. Configure service accounts and server-side restrictions separately.
In Plan mode the server is not launched, even if activation is saved.

Codex and Claude Code receive `command`, `args`, `env`, and `cwd` through their
native configuration translation. They own the subprocess handling and sandbox;
Eirene's managed-client timeout/mount fields are not native CLI settings.

For a standalone server there is no owning plugin to inspect with `/plugins doctor NAME`. Inspect its definition and startup error. Process exit errors
include the stderr tail when available. A timeout, invalid JSON, missing mount,
and empty tool list are distinct failures; increasing a deadline does not fix
an incorrect executable or incompatible transport.
