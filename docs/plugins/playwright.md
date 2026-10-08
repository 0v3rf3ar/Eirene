# Playwright

[Documentation](../README.md) / [Plugin catalog](../plugin-catalog.md) / Playwright

Playwright adds browser automation through a separately launched MCP server. Use
it for navigation, form behavior, page inspection, screenshots, and browser test
workflows supported by the server's installed version.

## Prerequisites

Install Node.js with `npx` available on PATH. Browser binaries and required OS
libraries must also be present. The first server startup can download npm packages
and browser setup can need additional network access.

## Install and enable

```text
/plugins install playwright
/plugins inspect playwright
/plugins doctor playwright
/mcp
```

Select the Playwright server in `/mcp` to enable it. Hook trust is not a substitute
for this choice. Use Manual or Auto mode and a tool-capable provider, or a supported
native CLI connection; Plan mode does not start the server.

Eirene adapts the catalog's standard launcher to
`npx -y @playwright/mcp@latest`, with network access declared for server startup.
Its managed npm/browser cache is under `plugin-data/playwright/mcp` in the data
directory. Custom launchers are preserved rather than replaced automatically.

## Run a browser task

```text
/playwright Open http://localhost:3000, test keyboard navigation through the signup form, and report accessibility problems. Do not submit a real account.
```

The canonical entry is `/playwright:playwright`. Give the target URL and expected
behavior. The model uses the tools discovered from the actual running server;
there is no fixed slash command for every browser operation.

```text
/playwright Capture the invoice list at desktop and mobile widths, then inspect the screenshots for clipped controls.
```

Screenshot inspection needs an image-capable model. Authentication, bot protection,
site availability, and permission restrictions can still prevent a task.

## Browser installation and startup

The server may initialize before a browser binary is installed. Its browser
installation tool can install supported binaries under normal approval, but OS
libraries may require separate host setup. Ask for the actual startup or launch
error rather than assuming the server is fully ready.

The catalog launcher allows up to three minutes for startup, which can matter on
a first download. Use `/plugins doctor playwright` to check `node`, `npx`, activation,
and known startup errors. It does not launch a browser or exercise a full page test.

## Shutdown and alternatives

Toggle the server off in `/mcp` to disable it. Server and browser state should not
be assumed to survive Eirene exit, a configuration restart, or a permission change.
For simple rendered-page checks without an MCP plugin, use the
[built-in browser helpers](../browser.md).

Sources: [catalog bundle](https://github.com/anthropics/claude-plugins-official/tree/main/external_plugins/playwright),
[Playwright MCP](https://github.com/microsoft/playwright-mcp).
