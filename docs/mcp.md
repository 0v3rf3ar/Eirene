# MCP servers

[Documentation](README.md) / MCP servers

An MCP server adds tools from a local program or remote service. Eirene supports
stdio, Streamable HTTP (`type: "http"`), and legacy SSE (`type: "sse"`).

## Guided setup

Open `/mcp` and choose **Add MCP server…**, or run `/mcp add`. Paste the MCP JSON
from a server's documentation, or enter the path to a JSON/JSONC file. There are
no provider-specific setup menus. Eirene resolves missing values, prepares the
runtime, detects authentication, and tests the connection before enabling it.
For multiple servers, one review can connect all of them. **Save disabled**
records declarations without connecting. Esc cancels; failed tests stay disabled.

The importer accepts `mcpServers`, `mcp_servers`, VS Code `servers`/`inputs`,
`mcp.servers`, OpenCode `mcp`, and a bare map. Copied Markdown code fences,
comments, and trailing commas are accepted. Use `/mcp add NAME` for an unnamed
single-server object. Simple `npx mcp-remote URL` declarations use native HTTP/SSE
automatically; unfamiliar proxy flags keep the original command.

`${VAR}`, `${env:VAR}`, `${VAR:-default}`, `${input:id}`, `${workspaceFolder}`,
and `${userHome}` are supported. Missing secrets and documentation placeholders
are requested securely. VS Code promptString and pickString inputs work;
editor-specific command inputs are rejected rather than executed as shell code.

See the [24 sourced JSON examples and compatibility notes](mcp-examples/README.md)
for the integrations reviewed, including Cloudflare, Burp, Google Workspace,
Ahrefs, databases, browser tools, and collaboration services.

Remote authentication options are browser OAuth, bearer token, custom headers,
and no authentication. Remote JSON defaults to automatic OAuth discovery when
no authentication headers are supplied. Header credentials and OAuth tokens are stored privately
under Eirene's data directory, separately from `config.json`. The official MCP
SDK handles discovery, PKCE, state verification, and token refresh. Background
connections never open a browser; if sign-in is needed, use `/mcp login NAME`.
Adding write permissions later may require signing in again with those scopes.
Pre-registered OAuth clients are supported using an `oauth` object with
`client_id`, `client_secret`, `redirect_uri`, and `authorization_params`.
Google's `access_type=offline`/`prompt=consent` can be supplied there. Registered
callbacks must be HTTP localhost callbacks with a port. App registration, tenant
consent, account plans, and database credentials remain service prerequisites.

For local servers, Eirene checks that the executable exists, prepares persistent
npm/uv caches when applicable, and guides you through environment variables,
network access, and additional readable/writable folders. Imports prepare a
persistent server home and package/browser caches, detect Docker sockets and
configuration, and expose existing kubeconfig where needed. These grants are
shown in the connection review. Node.js or uv must
already be installed for commands using npx or uvx. The wizard does not install
system runtimes. **Connect and enable** authorizes launching that local command;
package launchers may download their requested packages.

```text
/mcp add my-server https://example.com/mcp
/mcp import
/mcp import /path/to/mcp.json
/mcp test my-server
/mcp login my-server
/mcp remove my-server
```

`/mcp import` accepts `mcpServers`, `mcp_servers`, or a map of named declarations,
including the usual `command` plus `args` format and HTTP `type` plus `url`.
It reviews connections before saving, and asks before replacing a name.
The **Manage connection…** menu offers testing, authentication, and removal.
Removing a standalone remote server also removes its saved credentials.

## Enable a server

```text
/plugins install playwright
/plugins inspect playwright
/mcp
```

In the picker, select the server to toggle it on, then press Esc. The fixed
footer shows its access details. The plugin must be enabled first.
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
tool-capable model. Codex and Claude Code receive local stdio declarations
directly; remote connections use Eirene's bundled stdio proxy, sharing its saved
login and token refresh without exporting tokens into native configuration.

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

The plugin importer supports stdio, HTTP, and SSE declarations. Remote servers
require a network grant when network isolation is enabled. HTTPS and HTTP
endpoints are supported, including local development and private-network servers.
Use `/mcp login NAME` to configure authentication for an imported remote server.
Use the declared grants and the [permission guide](harness.md) to understand a
server's access. Testing connects and lists tools; it does not call them or
prove that deployment or write permissions have been granted.

## Declare a standalone server

A server does not need to belong to a plugin. Prefer `/mcp add` for guided setup.
For manual configuration, close Eirene and merge a declaration into `mcp_servers`
in [config.json](config-file.md#standalone-mcp-declarations):

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
can use an argv array including all arguments or separate `command` and `args`
fields. This is not shell syntax: pipes, shell
variables, and a command-plus-arguments string are not expanded.

Restart Eirene, open `/mcp`, and toggle `local-tools` on. Its activation key is
`mcp_enabled.local-tools`. Imported plugins instead use `PLUGIN__SERVER` keys.
A direct entry takes precedence if it collides with a plugin's public server key.
The picker supports adding connections, activation, testing, authentication, and
removal. `/mcp add` also accepts a server name and URL.

For all launcher, environment, working-directory and mount fields, see the
[configuration reference](config-file.md#standalone-mcp-declarations).

## Stdio connection sequence and protocol limits

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
actual boolean `network: true`, not the string `"true"`. HTTP/SSE declarations
default to network access because their connection is remote; an explicit
`network: false` remains a block when network isolation is enabled.

For servers added through `/mcp`, Eirene derives the read grants a local
launcher needs each time it starts, and keeps them apart from the `read_paths`
you write yourself:

- A script argument (`.py`, `.js`, `.ts`, `.jar`, and similar) gets its project
  root: the nearest folder with a project marker such as `pyproject.toml`,
  `package.json`, or `.git`, widened to the enclosing Git repository for
  monorepos. Without a marker it gets the script's own folder.
- Folder arguments (for example `uv run --directory /path`), `PYTHONPATH` and
  `NODE_PATH` entries, and a project venv's project are granted too.
- Relative script paths are read from the project, and linked scripts launch
  from their real location so the sandbox can mount them.
- A derived grant is never a filesystem or drive root, a shared top-level
  folder (`/home`, `/Users`, `/Volumes`, `/opt`, `C:\Users`, `C:\Windows`,
  `C:\Program Files`, and similar), your home folder or anything above it, the
  system temp folder or above, a credential store (`~/.ssh`, `~/.gnupg`,
  `~/.aws`, `~/.kube`, `~/.docker`, macOS `~/Library/Keychains`, Windows
  `AppData\Roaming\Microsoft\Credentials`, and others), or Eirene's own data
  outside its plugin and MCP runtime folders. These checks ignore case, as macOS
  and Windows volumes usually do. A grant narrows to the script's folder, then to
  the file alone, rather than widening.
- A file named in the command or environment that sits in one of those places
  is withheld, and the setup confirmation lists it. Add it to `read_paths` to
  share it deliberately.

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
