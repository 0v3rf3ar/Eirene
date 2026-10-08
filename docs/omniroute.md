# OmniRoute

[Documentation](README.md) / [Plugin catalog](plugin-catalog.md) / OmniRoute

OmniRoute is a separate gateway that routes chat requests to its configured
providers and model combinations. Eirene's adapter makes it available as a chat
connection and can optionally expose gateway management tools through MCP.

## Install the gateway separately

Install and run [OmniRoute](https://github.com/diegosouzapw/OmniRoute) using its
upstream instructions. Configure its providers in the dashboard. Eirene does not
download the gateway, run npm for it, or start it when you install the adapter.

The gateway needs to be running for connection and management requests. A Docker
installation does not by itself put the local `omniroute` CLI on PATH.

## Connect chat

```text
/plugins install omniroute
/connect omniroute
```

Accept `http://localhost:20128/v1` or enter your gateway's base URL ending in `/v1`.
Enter its API key. Leave it empty only when the gateway permits unauthenticated
requests. `EIRENE_OMNIROUTE_API_KEY` can override the saved key.

Select a live provider model, combo, `auto/coding`, or `auto`, as available from
your gateway. Use `/model` to switch. `/connect omniroute!` replaces the saved URL
and key. A stopped gateway or rejected credential fails connection validation.

```text
Eirene -> gateway chat API -> configured routing/combo -> selected upstream model
```

Routing, fallback, caching, and compression are gateway settings. Eirene uses its
Chat Completions API for streaming, reasoning, tool calls, supported images, and
usage. Available capabilities depend on the routed model. Gateway audio, image
generation, embeddings, and other non-chat features use the gateway's own dashboard
or APIs; they do not receive dedicated Eirene commands automatically.

## Enable optional management

```text
/plugins inspect omniroute
/plugins doctor omniroute
/mcp
```

Select `omniroute / gateway` to turn management on. Installation and hook trust do
not enable this server. The separate `omniroute` executable must be on PATH. The
adapter launches `omniroute --mcp` on the next normal turn; Plan mode does not
start it. Codex and Claude Code receive its stdio definition through their native
configuration.

The `/omniroute` entry is a management task command, not the chat-connection command.
It needs the enabled MCP server and a tool-capable provider or native CLI. You can
use management while another provider supplies the conversation model.

```text
/omniroute Check gateway health and remaining provider quotas.
/omniroute List my combos and explain their routing strategies without changing them.
/omniroute Show usage and costs by provider, using the tools available in this gateway version.
```

Management can expose routing, combos, cache/compression, quotas, and other tools
advertised by your installed gateway. State whether you want inspection or changes.
No fixed tool list is guaranteed across gateway versions.

## URL, key, and authorization

By default, the management adapter uses the saved OmniRoute connection URL and
key, including later connection changes and the environment key override. Its MCP
base URL is the gateway root without `/v1`. The plugin declaration does not need
to contain a duplicate key.

Management calls require the appropriate key scopes and, where required by the
gateway, Management Access enabled in its dashboard. Chat authentication succeeding
does not prove that every management operation is authorized.

For a separate management URL or key, explicitly set `OMNIROUTE_BASE_URL` or
`OMNIROUTE_API_KEY` under `mcpServers.gateway.env` in the installed `plugin.json`.
Refresh and reenable the server after changing the declaration. Prefer normal
shared credentials unless you need a separate management identity.

## Gateway data directory

Some gateway tools access SQLite directly. The MCP process must use the running
gateway's actual data directory, including its encryption key; a different local
database cannot manage the remote instance correctly.

The adapter chooses a platform default. For a custom location, set
`EIRENE_OMNIROUTE_DATA_DIR` before launching Eirene and installing the adapter. If
already installed, edit both `DATA_DIR` and the matching `write_paths` in the
server declaration, then run `/plugins refresh omniroute` and enable it through
`/mcp` again. Start the gateway first so its data directory exists.

Full management of a remote gateway needs the MCP process on its host with access
to its actual data. Merely changing the HTTP base URL does not supply that local
database access.

## Access and shutdown

Enabling the management server grants the declared network access and write access
to its gateway data directory. The picker shows those grants. It does not change
Eirene's global network preference. Custom launchers can need additional runtime
read paths; inspect their actual declarations and errors.

Use `/mcp` to disable management, `/plugins` to disable the bundle, or
`/plugins untrust omniroute` to revoke its MCP activation. A gateway started
separately continues running independently of Eirene. See [MCP](mcp.md),
[providers](providers.md), and [permissions](harness.md).

## Configuration locations

Chat settings live in `providers.omniroute` in `config.json`; active selection
uses top-level `provider`/`model`. The management declaration is in
`plugins/omniroute/plugin.json` and its normalized index. Activation uses
`mcp_enabled.omniroute__gateway`. An API key in the provider connection does not
itself enable that server. See [config.json](config-file.md) for credential
precedence and [plugin formats](plugins.md#local-bundle-format) for refresh behavior.

The management data directory is external to Eirene's application data. The
adapter uses `EIRENE_OMNIROUTE_DATA_DIR` when set; otherwise it selects an existing
`~/.omniroute`, then platform config defaults, with `~/.omniroute` as the POSIX
fallback. The database and its encryption material need their own backup. See
[data layout](data-layout.md#backup-transfer-and-recovery) for the distinction.
