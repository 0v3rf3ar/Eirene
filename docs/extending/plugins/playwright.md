# Playwright

[Documentation](../../README.md) / [Plugin catalog](../plugin-catalog.md) / Playwright

This plugin adds browser automation through the Playwright MCP server: navigation, forms, page inspection, screenshots and browser test workflows. For simple rendered-page checks, the [built-in browser](../../guides/web-and-browser.md#use-the-browser) needs no plugin.

## Requirements

- Node.js, with `npx` on `PATH`.
- Browser binaries and the system libraries they need.
- Network access on first start, to download packages.

## Install

```text
/plugins install playwright
/plugins inspect playwright
/plugins doctor playwright
/plugins trust playwright
```

Trusting the plugin starts the server on your next message. Use Manual, Accept or Auto mode with a tool-capable provider, or a supported CLI connection. Plan mode does not start it.

## Run a browser task

```text
/playwright Open http://localhost:3000, test keyboard navigation through the signup form, and report accessibility problems. Do not submit a real account.
/playwright Capture the invoice list at desktop and mobile widths, then inspect the screenshots for clipped controls.
```

The full command name is `/playwright:playwright`. Give the target URL and the expected behavior. The model uses whichever tools the running server offers, so there is no fixed slash command for each browser action.

Inspecting screenshots needs a model with vision. Sign-ins, bot protection and site availability can still prevent a task.

## Install the browser

The server can start before a browser is installed. Its browser installation tool can install supported binaries, under normal approval, but system libraries may need setting up separately. If a task fails, ask for the actual launch error.

The standard launcher allows up to three minutes for startup, to accommodate a first download. `/plugins doctor playwright` checks `node`, `npx`, activation and known startup errors, but does not launch a browser.

## How it is set up

Eirene adapts the standard launcher to `npx -y @playwright/mcp@latest`, with network access declared. Downloads are kept in `plugin-data/playwright/mcp` in the [data directory](../../reference/data-directory.md), through these defaults:

| Variable | Default |
| --- | --- |
| `XDG_CACHE_HOME` | `plugin-data/playwright/mcp` |
| `npm_config_cache` | The same folder |
| `PLAYWRIGHT_BROWSERS_PATH` | Its `browsers/` subfolder |

Values you set in the plugin's declaration take priority. A custom launcher is kept as you wrote it, but does not get these automatic settings and grants.

## Turn it off

Toggle the server off in `/mcp`. Do not count on the server or browser state surviving when you exit Eirene or change permissions.

## Origin

Playwright MCP is made by Microsoft, with thanks. Sources: [catalog bundle](https://github.com/anthropics/claude-plugins-official/tree/main/external_plugins/playwright) and [Playwright MCP](https://github.com/microsoft/playwright-mcp).
