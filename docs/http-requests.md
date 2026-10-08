# HTTP requests

[Documentation](README.md) / HTTP requests

Eirene can make an explicit, bounded HTTP request when you ask it to call an
endpoint. Use this for a local health check, an API behavior check, or another
request whose method, target, and expected effect you understand.

## Describe the request

```text
Send a GET request to http://localhost:3000/health and report the status code and response body.
```

Specify the method and full URL. For a request with a body, include the intended
data and content type, or point to a workspace file containing that data. State
whether you are using a local test service or a remote environment.

Supported methods are `GET`, `HEAD`, `POST`, `PUT`, `PATCH`, `DELETE`, and
`OPTIONS`. The target must be an absolute HTTP or HTTPS URL without embedded
username/password credentials.

```text
POST {"email":"test@example.com"} as JSON to the local validation endpoint at http://localhost:3000/api/validate. Report the response and do not call the production service.
```

HTTP requests are execution actions, subject to the selected mode and network
permissions. Plan mode does not send them. Manual mode can prompt for approval;
Auto mode still needs permission for access outside its boundary.

## Understand the result

A response can establish the outcome of that request, not every behavior of the
service. Inspect the status, body, and any error. Responses and downloads are
bounded, so a displayed excerpt may not contain the entire result.

A timeout or interrupted request does not prove that the remote service took no
action. Check the service state before repeating a request that creates or changes
data. Do not paste credentials into an ordinary conversation when a configured
integration can supply them instead.

## Choose the right tool

Use [web research](web-search.md) for finding sources and reading public pages.
Use [browser work](browser.md) when JavaScript, page interaction, or screenshots
are needed. Use [MCP](mcp.md) for an installed service integration with its own
tools and authorization, such as [OmniRoute management](omniroute.md).

## Response bounds and redirect behavior

The built-in request helper defaults to 30 seconds, sends the supplied body as
encoded text, and converts header keys/values to strings. It follows HTTP
redirects. The result starts with JSON metadata containing status, final URL,
and response headers, followed by decoded body text.

Downloads are bounded to 2000000 bytes and displayed response text to 120000
characters. A truncation marker indicates partial content; a status code alone
does not mean the full response was retained. This helper does not parse an
application schema or retry a mutating operation as a transaction.

This deadline is separate from provider `request_timeout` and MCP deadlines in
[config.json](config-file.md#numeric-limits). HTTP helper output enters ordinary
tool results and session storage; see [session formats](sessions.md#event-log-format).
