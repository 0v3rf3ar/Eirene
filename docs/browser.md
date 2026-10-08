# Browser and image work

[Documentation](README.md) / Browser and image work

Eirene can inspect rendered pages, perform bounded browser interactions, save
screenshots, and let a vision-capable model inspect image files. These features
help with frontend behavior and layout verification.

## Built-in browser inspection

Install a Chromium-based browser such as Chromium, Chrome, or Edge. Eirene checks
PATH and common installation locations. If it cannot find your browser, set
`EIRENE_CHROMIUM_PATH` to its executable before launching Eirene.

```text
Inspect http://localhost:3000 after JavaScript runs and explain why the empty-state message is missing.
```

Browser inspection reads the rendered DOM, rather than just the initial HTML.
Use ordinary [web research](web-search.md) when the page's text or documentation
is sufficient.

## Interact with a page

```text
Open http://localhost:3000, enter an invalid email in the signup form, submit it, and report the validation message. Do not create an account.
```

Built-in interactions can navigate, click, type, wait, inspect text or DOM, and
run page JavaScript. A single interaction batch uses one temporary browser page,
with at most 25 actions. Separate calls use fresh browser profiles; do not assume
a login or page state persists between them.

Browser interactions require a normal mode and the applicable network or command
permissions. They can have real effects on the visited application. State the
scope of a test clearly, particularly for submissions or authenticated services.

## Save and inspect a screenshot

```text
Save a 1280 by 800 screenshot of http://localhost:3000 to screenshots/home.png, then check whether the heading overlaps the navigation.
```

The built-in screenshot output is a PNG file in the workspace. Viewing it requires
an image-capable model connection. Image reads support PNG, JPEG, GIF, and WebP;
a text-only model cannot assess pixels. Point to a file in the workspace rather
than assuming pasted image clipboard data is an attachment.

## Use Playwright MCP

The [Playwright plugin](plugins/playwright.md) adds a fuller browser automation
workflow through an external MCP server. Install the plugin, satisfy its Node.js
and browser prerequisites, and enable the server with `/mcp`. Its tools and
browser lifecycle differ from the built-in temporary-page helpers.

A server can initialize while its browser binary is still missing. Complete the
browser installation and any OS dependency setup before treating it as ready for
a full test. Use `/plugins doctor playwright` for launcher and activation checks.

## Local servers

Ask Eirene to start the app as a managed process, then inspect its reported URL.
Do not guess that a server started successfully or assume its default port was
available. Ctrl+B lets you check output and stop it. See [running commands](processes.md)
for service lifetime and temporary host-access grants.

## Implementation limits and image encoding

Built-in rendered inspection uses a discovered Chromium executable and a fresh
temporary profile. Interaction uses the Chrome DevTools Protocol and can require
the optional Python `websockets` dependency in a source installation. The core
package declaration does not make every optional browser dependency available.
The process is terminated and temporary profile discarded after the call.

Rendered DOM is bounded to 120000 characters; interaction result text is bounded
separately. File image reads identify PNG/JPEG/GIF/WebP by MIME type, reject files
larger than 10000000 bytes, and base64-encode the image for the provider. The image
bytes are sent to the selected model service when vision is used; a local path
is not just a text-only reference. The managed MCP bridge serializes non-text
blocks, so it does not guarantee native image rendering for every MCP result.

Browser executable overrides are environment values set before launch, rather
than a `config.json` browser-path field. See [configuration](configuration.md#environment-variables),
[data layout](data-layout.md), and [Playwright adapter caches](plugins/playwright.md).
