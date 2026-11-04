# MCP server best practices

## At a glance

| Topic | Rule |
| --- | --- |
| Server name | Python `{service}_mcp` (`slack_mcp`); TypeScript `{service}-mcp-server` (`slack-mcp-server`) |
| Tool name | snake_case, service prefix, verb first: `{service}_{action}_{resource}` (`slack_send_message`) |
| Output | Markdown by default, JSON on request (`response_format`) |
| Lists | Respect `limit`; return `total`, `count`, `offset`, `has_more`, `next_offset`; default 20–50 items |
| Size | Cap responses (about 25,000 characters) by returning fewer items |
| Transport | stdio for local, Streamable HTTP for remote; SSE is deprecated |

## Naming

**Servers.** General, descriptive of the service, easy to guess from the task,
no version numbers: `github_mcp` / `github-mcp-server`, `jira_mcp` /
`jira-mcp-server`.

**Tools.**

1. snake_case: `search_users`, `create_project`, `get_channel_info`.
2. A service prefix, because your server will run beside others:
   `slack_send_message`, not `send_message`.
3. A verb first: get, list, search, create, update, delete.
4. Specific enough not to collide with another server's tools.

## Tool design

- Each description says exactly what the tool does and nothing it does not.
- Keep tools focused: one clear operation each, plus a few workflow tools where
  they save many round trips.
- Set annotations truthfully (see below).
- Tell the model when to use a sibling tool instead ("Use `x_get_user` when you
  already have an ID").

## Response formats

Tools that return data accept `response_format`:

**`markdown`** (usually the default)

- readable text with headings and lists;
- human-readable dates;
- display names with IDs in parentheses: `Ada Lovelace (U123)`;
- no bulky metadata.

**`json`**

- complete, consistently named fields for programmatic use;
- the same data in `structuredContent`, with its JSON text in the text block.

## Pagination

For anything that lists:

- always honour `limit`;
- page with `offset` or a cursor;
- return `has_more`, `next_offset` (or `next_cursor`) and `total` when known;
- never fetch everything into memory;
- default to 20–50 items.

```json
{
  "total": 150,
  "count": 20,
  "offset": 0,
  "items": ["..."],
  "has_more": true,
  "next_offset": 20
}
```

In Markdown, end with how to get more: `More results: call again with offset=20.`

## Response size

Set a character limit (25,000 is a sensible default). When a page would exceed
it, return fewer items rather than truncating text, so `next_offset` still points
at the first item left out and JSON stays valid. Measure the final text, not an
intermediate value.

## Transports

### stdio

For local tools the client starts as a subprocess: simple, no network setup, one
client. **Never write anything but protocol messages to stdout** — log to stderr.

### Streamable HTTP

For remote services and many clients: deployable as a web service, supports
server-to-client notifications. Prefer stateless request/response JSON unless you
need sessions or streaming.

| | stdio | Streamable HTTP |
| --- | --- | --- |
| Where | local | remote |
| Clients | one | many |
| Setup | low | medium |
| Notifications | no | yes |

SSE is the older remote transport and is deprecated; do not start new servers on
it.

## Security

### Authentication

- **OAuth 2.1** for remote servers acting for users: validate every access token,
  and accept only tokens issued for this server (check the audience/resource).
- **API keys:** read them from environment variables, never from code or
  arguments; check they are present at start-up; fail with a clear message.
- Never log tokens or keys.

### Input

- Validate every input with the schema (Zod or Pydantic): types, ranges, lengths.
- Resolve file paths and reject anything outside the allowed root.
- Validate URLs and external identifiers; do not fetch arbitrary URLs for the
  caller unless that is the tool's job.
- Never build shell commands from input; pass argument lists.

### Errors

- Do not leak stack traces or internal details to clients.
- Log security-relevant failures on the server side.
- Clean up resources after failures.

### Local HTTP servers

- Bind to `127.0.0.1`, not `0.0.0.0`.
- Validate `Host` and `Origin` on every request (DNS rebinding protection).

## Annotations

| Annotation | Default | Set to true when the tool… |
| --- | --- | --- |
| `readOnlyHint` | false | changes nothing |
| `destructiveHint` | true | may delete or overwrite data |
| `idempotentHint` | false | can be repeated with the same arguments to no further effect |
| `openWorldHint` | true | talks to an external system |

Annotations are hints. Clients use them for things like auto-approving read-only
tools or confirming destructive ones; they are not a security boundary.

## Errors

MCP has two channels:

- **Tool errors** — a normal result with `isError: true`. The model reads these,
  so say what went wrong and what to try next.
- **Protocol errors** — JSON-RPC errors for malformed requests and the like,
  handled by the client application; the model does not see them.

Report tool failures as tool errors, not protocol errors.

```typescript
try {
  const text = await runQuery(args);
  return { content: [{ type: "text", text }] };
} catch (error) {
  return {
    isError: true,
    content: [{ type: "text", text: `Query failed: ${message(error)}. Narrow it with status="open".` }],
  };
}
```

## Testing

- **Function:** valid and invalid inputs for every tool.
- **Integration:** real calls against a test account where possible.
- **Security:** authentication failures, path and input validation, rate limits.
- **Performance:** timeouts, large results, slow upstreams.
- **Errors:** every failure path returns an actionable message and cleans up.

## Documentation

- Document every tool and what it needs (scopes, permissions, environment
  variables).
- Give working examples for the main features.
- State rate limits and known limits.
- Describe the security model: what the server can reach and on whose behalf.
