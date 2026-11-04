# Web, browser and HTTP

[Documentation](../README.md) / Guides / Web, browser and HTTP

Eirene has three built-in ways to reach the web, and MCP servers can add more.

| You want to | Use | Needs |
| --- | --- | --- |
| Find facts and read public pages | [Web search and fetch](#search-and-read-the-web) | Nothing extra |
| See a page after JavaScript runs, click through it, or take a screenshot | [Built-in browser](#use-the-browser) | A Chromium-based browser |
| Call a specific endpoint | [HTTP requests](#send-an-http-request) | Nothing extra |
| Automate a browser over many steps | [Playwright plugin](../extending/plugins/playwright.md) | Node.js and a browser |
| Use a service with its own login and tools | [MCP server](../extending/mcp.md) | Depends on the server |

## Search and read the web

Ask a specific question, and ask for links if you want to check the answer:

```text
Find the official documentation for this API's pagination behavior and link the relevant section.
```

Search uses DuckDuckGo and returns titles, URLs and snippets, and Eirene then reads the pages it
needs. Web search never asks for approval. Fetching a page follows your
[network permissions](modes-and-permissions.md#the-sandbox). Fetching extracts readable text and
does not run JavaScript, so a page that needs it calls for the browser.

Results can be missing because of rate limits or challenge pages, which does not mean the
information does not exist. Ask for a narrower query, an official page, or give a source you
already know.

### Optional Tavily fallback

If normal search often fails for you, you can add a [Tavily](https://tavily.com) key as a fallback:

```text
/search-api
```

Choose Tavily and enter the key in the hidden prompt. Eirene validates it without spending a search
credit. Tavily is used only when normal search returns nothing usable, and each fallback search can
use a credit. If Tavily reports a rate or credit limit, the fallback pauses and normal search keeps
working.

Run `/search-api` again to keep, replace or remove the key. It is stored as
[`search_api`](../reference/configuration.md#search-api), separately from your providers.

## Use the browser

Eirene looks for Chromium, Chrome or Edge on `PATH` and in the usual install locations. If it cannot
find yours, set `EIRENE_CHROMIUM_PATH` to the executable before launching Eirene.

### Inspect a page

```text
Inspect http://localhost:3000 after JavaScript runs and explain why the empty-state message is missing.
```

This reads the rendered page, up to 120,000 characters.

### Interact with a page

```text
Open http://localhost:3000, enter an invalid email in the signup form, submit it, and report the validation message. Do not create an account.
```

Eirene can navigate, click, type, wait, read the page and run JavaScript, with up to 25 actions in one
batch. Each batch opens a fresh browser profile, which is discarded afterwards, so logins and page
state do not carry over between batches.

Interactions have real effects on the site, so state the limits clearly when a page has forms or a
login. They are not available in Plan mode.

### Take and check a screenshot

```text
Save a 1280 by 800 screenshot of http://localhost:3000 to screenshots/home.png, then check whether the heading overlaps the navigation.
```

Screenshots are saved as PNG files in the workspace. Judging one requires a model with vision.

Eirene can read PNG, JPEG, GIF and WebP images up to 10 MB. The image is sent to your model service.
You can also give the model an image by [attaching it](terminal-interface.md#attach-files).

### Test a local app

Ask Eirene to [start the app as a managed process](running-commands.md#servers-and-watchers), then
inspect the URL it reports. Ctrl+B shows the server's output.

## Send an HTTP request

Eirene can make one explicit request when you ask for it. Give the method and the full URL, and for
a request with a body, the data and content type:

```text
Send a GET request to http://localhost:3000/health and report the status code and response body.
```

```text
POST {"email":"test@example.com"} as JSON to http://localhost:3000/api/validate. Report the response and do not call the production service.
```

- **Methods:** `GET`, `HEAD`, `POST`, `PUT`, `PATCH`, `DELETE`, `OPTIONS`.
- **Target:** an absolute HTTP or HTTPS URL, without a username or password in it.
- **Approval:** subject to your mode and network permissions. Plan mode does not send requests.
- **Limits:** 30 seconds by default, 2 MB downloaded, and 120,000 characters of response text. A
  marker shows when the response was cut. Redirects are followed.

The result begins with the status, final URL and headers, followed by the body.

If a request times out or is interrupted, the service may still have acted on it, so check before
repeating one that creates or changes data.

Responses are saved in your session like other tool output. Avoid pasting credentials into a prompt;
an [MCP server](../extending/mcp.md) can hold them instead.
