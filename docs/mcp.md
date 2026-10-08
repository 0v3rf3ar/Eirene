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
