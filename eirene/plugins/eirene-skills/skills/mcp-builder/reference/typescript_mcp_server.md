# TypeScript MCP servers

This guide uses **SDK v2** (`@modelcontextprotocol/server`), the current stable
release. A section at the end covers projects still on **v1**
(`@modelcontextprotocol/sdk`) and how to migrate them.

The v2 documentation index is `https://ts.sdk.modelcontextprotocol.io/v2/llms.txt`
(every page is also available as Markdown at its `.md` URL). The SDK repository's
`examples/` folder has runnable servers for every feature.

## Install

```bash
npm install @modelcontextprotocol/server zod
npm install @modelcontextprotocol/express @modelcontextprotocol/node express   # only for Streamable HTTP
npm install -D @modelcontextprotocol/client typescript tsx @types/node @types/express
```

Node.js 20 or newer. Zod **4.2 or newer**, imported as `import * as z from
"zod/v4"` — v2 does not accept Zod 3, and Zod 4.0–4.1 schemas fail to type-check
in `registerTool`.

## Smallest server

```typescript
#!/usr/bin/env node
import { McpServer } from "@modelcontextprotocol/server";
import { serveStdio } from "@modelcontextprotocol/server/stdio";
import * as z from "zod/v4";

function createServer(): McpServer {
  const server = new McpServer({ name: "notes-mcp-server", version: "1.0.0" });
  server.registerTool(
    "notes_echo",
    {
      title: "Echo",
      description: "Return the text you send. Useful to check the server is reachable.",
      inputSchema: z.object({ text: z.string().max(1000).describe("Text to echo back") }),
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async ({ text }) => ({ content: [{ type: "text", text }] }),
  );
  return server;
}

serveStdio(createServer);
console.error("notes-mcp-server ready on stdio"); // stdout belongs to the protocol
```

## Layout

```
{service}-mcp-server/
├── package.json
├── tsconfig.json
├── README.md
├── src/
│   ├── index.ts        # createServer() and transport selection
│   ├── api.ts          # upstream client and error messages
│   ├── format.ts       # Markdown/JSON rendering, size limit
│   └── tools/          # registerXxxTools(server) per area
├── scripts/
│   └── smoke.ts        # self-check client
└── dist/               # build output; entry point dist/index.js
```

### package.json

```json
{
  "name": "{service}-mcp-server",
  "version": "1.0.0",
  "type": "module",
  "bin": { "{service}-mcp-server": "dist/index.js" },
  "files": ["dist"],
  "scripts": {
    "build": "tsc",
    "start": "node dist/index.js",
    "dev": "tsx watch src/index.ts",
    "smoke": "tsx scripts/smoke.ts"
  },
  "engines": { "node": ">=20.3" },
  "dependencies": {
    "@modelcontextprotocol/express": "^2.0.2",
    "@modelcontextprotocol/node": "^2.1.1",
    "@modelcontextprotocol/server": "^2.3.1",
    "express": "^5.1.0",
    "zod": "^4.2.0"
  },
  "devDependencies": {
    "@modelcontextprotocol/client": "^2.3.1",
    "@types/express": "^5.0.0",
    "@types/node": "^24.0.0",
    "tsx": "^4.19.2",
    "typescript": "^5.9.3"
  }
}
```

A stdio-only server can drop `express`, `@types/express` and the two adapter
packages. The `bin` entry and the `#!/usr/bin/env node` line let clients start it
with `npx -y {service}-mcp-server`.

### tsconfig.json

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "Node16",
    "moduleResolution": "Node16",
    "lib": ["ES2022"],
    "outDir": "dist",
    "rootDir": "src",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "declaration": true,
    "sourceMap": true
  },
  "include": ["src/**/*"]
}
```

## The server factory

Write `createServer()` to build a **new** `McpServer` with everything registered
on it. The transports call it; you do not:

- `serveStdio(createServer)` calls it once for the connection;
- `createMcpHandler(createServer)` calls it **once per HTTP request**, so the HTTP
  server keeps no state between requests and scales out as is.

Rules:

- Register tools, resources and prompts inside the factory, never on a shared
  instance.
- Return a fresh instance every time. A shared one passes one-at-a-time manual
  tests, then fails concurrent requests with `-32603 Internal server error`.
- Keep it cheap: create API clients, pools and configuration once at module scope
  and close over them.
- Behind `createMcpHandler`, the factory receives the request context, so
  `createMcpHandler(({ authInfo }) => ...)` can build an instance per caller.

## Calling the upstream API

One helper at module scope that every tool uses. Node 20 has `fetch`.

```typescript
// src/api.ts
const BASE = "https://api.example.com/v1";
const KEY = process.env.EXAMPLE_API_KEY;

export class ApiError extends Error {
  constructor(readonly status: number) {
    super(messageFor(status));
  }
}

function messageFor(status: number): string {
  switch (status) {
    case 401: return "The Example API rejected the key. Check EXAMPLE_API_KEY.";
    case 403: return "This key cannot access that resource.";
    case 404: return "Not found. Check the ID; example_search_users lists valid IDs.";
    case 429: return "Rate limited. Wait a minute before retrying.";
    default: return `The Example API returned HTTP ${status}.`;
  }
}

export async function apiGet<T>(path: string, params: Record<string, string | number>,
                                signal: AbortSignal): Promise<T> {
  const url = new URL(`${BASE}/${path}`);
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, String(v));
  let response: Response;
  try {
    response = await fetch(url, {
      headers: { Authorization: `Bearer ${KEY}`, Accept: "application/json" },
      // cancelled when the client cancels the call, or after 30 s
      signal: AbortSignal.any([signal, AbortSignal.timeout(30_000)]),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "TimeoutError") {
      throw new Error("The Example API did not answer within 30 seconds; narrow the query and retry.");
    }
    throw error;
  }
  if (!response.ok) throw new ApiError(response.status);
  return (await response.json()) as T;
}
```

Tool handlers pass `ctx.mcpReq.signal`, so a cancelled call also cancels the
upstream request. Anything a tool handler throws becomes an `isError: true`
result whose text is the error's `message` — which is why the messages say how
to recover.

## Designing tools

### Names and descriptions

- snake_case, verb first, service prefix: `slack_send_message`,
  `github_create_issue`.
- The `description` is all the model has. Say what the tool does, what it
  returns, when to use a sibling instead, and give an example request or two.
  JSDoc comments are not sent.
- Give each tool a `title`, `description`, `inputSchema` (if it takes arguments)
  and `annotations`.

### Annotations

| Set `true` when the tool… | Annotation |
| --- | --- |
| changes nothing | `readOnlyHint` |
| may delete or overwrite | `destructiveHint` |
| can repeat with no further effect | `idempotentHint` |
| talks to an external system | `openWorldHint` |

They are hints for clients (auto-approve, confirm); they do not change how the
SDK runs the tool.

### Input schemas

`inputSchema` is a Zod object: `z.object({...})`, or `z.strictObject({...})` to
reject unknown arguments. From it the SDK derives the JSON Schema clients see,
validates arguments before your handler runs, and types the handler.

```typescript
enum ResponseFormat { MARKDOWN = "markdown", JSON = "json" }

const SearchInput = z.strictObject({
  query: z.string().min(2).max(200).describe("Text to match against names and emails"),
  limit: z.number().int().min(1).max(100).default(20).describe("Maximum users to return"),
  offset: z.number().int().min(0).default(0).describe("Matches to skip, for pagination"),
  response_format: z.enum(ResponseFormat).default(ResponseFormat.MARKDOWN)
    .describe("'markdown' for reading, 'json' for structured data"),
});
```

- `.describe()` becomes the field's `description` — the model's only
  documentation for it.
- Fields with `.default()` are optional for callers and always set in the handler.
- Invalid arguments never reach the handler; the caller gets an `isError` result
  explaining what failed.
- Zod 4 differences: `z.strictObject()` instead of `.strict()`, `z.enum(TsEnum)`
  instead of `z.nativeEnum`, `z.email()` / `z.url()` / `z.uuid()` instead of
  `z.string().email()`.

### Output

Let the caller choose with `response_format`:

- **Markdown** (default): readable, human dates, names with IDs in parentheses.
- **JSON**: complete data; put it in `structuredContent` and its
  `JSON.stringify` in the text block (the spec asks for both).

Declare `outputSchema` only on tools whose output is always JSON. With one, every
successful result must include matching `structuredContent`, and the advertised
schema forbids extra fields — so build the value from the schema
(`UserSchema.parse(raw)`), which also validates upstream data.

### Pagination and size

```typescript
const CHARACTER_LIMIT = 25_000;

function page<T>(items: T[], total: number, offset: number) {
  const next = offset + items.length;
  return { total, count: items.length, offset, items, has_more: total > next,
           ...(total > next ? { next_offset: next } : {}) };
}

// Return fewer items rather than cutting text; next_offset then points at the first one left out.
function fit<T>(items: T[], render: (items: T[]) => string): { items: T[]; text: string } {
  let kept = items;
  let text = render(kept);
  while (kept.length > 1 && text.length > CHARACTER_LIMIT) {
    kept = kept.slice(0, Math.ceil(kept.length / 2));
    text = render(kept);
  }
  return { items: kept, text };
}
```

End Markdown pages with how to continue: `More results: call again with
offset=20.`

### Errors

- **Tool errors** (`isError: true` results) are read by the model: return one or
  throw from the handler.
- **Protocol errors** go to the client application. Resource and prompt callbacks
  have no `isError` channel, so they throw `ProtocolError`.

## Complete example

Two tools, both transports. `example_search_users` shows pagination, the size
limit and both formats; `example_get_user` shows an `outputSchema`.

```typescript
#!/usr/bin/env node
/** MCP server for the Example API: stdio by default, Streamable HTTP when TRANSPORT=http. */
import { createMcpExpressApp } from "@modelcontextprotocol/express";
import { toNodeHandler } from "@modelcontextprotocol/node";
import { createMcpHandler, McpServer } from "@modelcontextprotocol/server";
import { serveStdio } from "@modelcontextprotocol/server/stdio";
import * as z from "zod/v4";
import { apiGet } from "./api.js";

if (!process.env.EXAMPLE_API_KEY) {
  console.error("EXAMPLE_API_KEY is required");
  process.exit(1);
}

const CHARACTER_LIMIT = 25_000;
enum ResponseFormat { MARKDOWN = "markdown", JSON = "json" }

const User = z.object({
  id: z.string(),
  name: z.string(),
  email: z.string(),
  team: z.string().optional(),
  active: z.boolean(),
});
type User = z.infer<typeof User>;
const UserPage = z.object({ users: z.array(User), total: z.number() });

const userMarkdown = (u: User) =>
  [`## ${u.name} (${u.id})`, `- Email: ${u.email}`, ...(u.team ? [`- Team: ${u.team}`] : []),
   ...(u.active ? [] : ["- Inactive"])].join("\n");

const readOnly = { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: true };

function createServer(): McpServer {
  const server = new McpServer({ name: "example-mcp-server", version: "1.0.0" });

  server.registerTool(
    "example_search_users",
    {
      title: "Search users",
      description: `Search Example users by name or email.

Returns one page of matches; when more exist the result gives next_offset.
Use example_get_user instead when you already have an ID.

Examples:
  - "who is on the marketing team" -> query="marketing"
  - "look up ada@example.com" -> query="ada@example.com"`,
      inputSchema: z.strictObject({
        query: z.string().min(2).max(200).describe("Text to match against names and emails"),
        limit: z.number().int().min(1).max(100).default(20).describe("Maximum users to return"),
        offset: z.number().int().min(0).default(0).describe("Matches to skip, for pagination"),
        response_format: z.enum(ResponseFormat).default(ResponseFormat.MARKDOWN)
          .describe("'markdown' for reading, 'json' for structured data"),
      }),
      annotations: readOnly,
    },
    async ({ query, limit, offset, response_format }, ctx) => {
      const data = UserPage.parse(
        await apiGet<unknown>("users/search", { q: query, limit, offset }, ctx.mcpReq.signal));
      if (data.users.length === 0) {
        return { content: [{ type: "text", text: `No users match '${query}'. Try a shorter or different query.` }] };
      }
      const build = (users: User[]) => {
        const next = offset + users.length;
        const more = data.total > next;
        const result = { total: data.total, count: users.length, offset, users, has_more: more,
                         ...(more ? { next_offset: next } : {}) };
        const text = response_format === ResponseFormat.JSON
          ? JSON.stringify(result, null, 2)
          : [`# Users matching '${query}'`, `Showing ${users.length} of ${data.total}.`, "",
             users.map(userMarkdown).join("\n\n"),
             ...(more ? ["", `More results: call again with offset=${next}.`] : [])].join("\n");
        return { result, text };
      };
      let users = data.users;
      let built = build(users);
      while (users.length > 1 && built.text.length > CHARACTER_LIMIT) {
        users = users.slice(0, Math.ceil(users.length / 2));
        built = build(users);
      }
      return response_format === ResponseFormat.JSON
        ? { content: [{ type: "text", text: built.text }], structuredContent: built.result }
        : { content: [{ type: "text", text: built.text }] };
    },
  );

  server.registerTool(
    "example_get_user",
    {
      title: "Get user",
      description: "Get one Example user by ID. Use example_search_users to find IDs.",
      inputSchema: z.strictObject({ user_id: z.string().min(1).describe("User ID, e.g. 'U123456'") }),
      outputSchema: User,
      annotations: readOnly,
    },
    async ({ user_id }, ctx) => {
      const user = User.parse(await apiGet<unknown>(`users/${encodeURIComponent(user_id)}`, {}, ctx.mcpReq.signal));
      return { content: [{ type: "text", text: JSON.stringify(user, null, 2) }], structuredContent: user };
    },
  );

  return server;
}

if (process.env.TRANSPORT === "http") {
  const handler = createMcpHandler(createServer);
  const app = createMcpExpressApp(); // JSON body parsing plus Host/Origin checks on localhost
  const node = toNodeHandler(handler);
  app.all("/mcp", (req, res) => void node(req, res, req.body));
  const port = Number(process.env.PORT ?? 3000);
  app.listen(port, "127.0.0.1", () => console.error(`listening on http://127.0.0.1:${port}/mcp`));
} else {
  serveStdio(createServer);
  console.error("example-mcp-server ready on stdio");
}
```

## Serving

### stdio

`serveStdio(createServer)` reads requests from stdin and writes responses to
stdout. A single `console.log` corrupts the stream — log with `console.error`.

### Streamable HTTP

`createMcpHandler(createServer)` returns a web-standard handler;
`toNodeHandler` adapts it to Express (Hono and Fastify adapters exist too).

- It serves current and older protocol revisions from the same factory, without
  sessions.
- `createMcpExpressApp()` validates `Host` and `Origin` on localhost binds, which
  blocks DNS rebinding. When binding every interface, name the hosts:
  `createMcpExpressApp({ host: "0.0.0.0", allowedHosts: ["mcp.example.com"] })`.
- On Workers, Deno or Bun, `export default handler` is the whole mount; add Host
  and Origin checks in front.

### Authentication

The handler checks no tokens. For anything reachable beyond localhost, put bearer
auth in front of the route:

```typescript
import { createMcpExpressApp, requireBearerAuth, type OAuthTokenVerifier } from "@modelcontextprotocol/express";
import { OAuthError, OAuthErrorCode, type AuthInfo } from "@modelcontextprotocol/server";

const resource = new URL("https://mcp.example.com/mcp");
const verifier: OAuthTokenVerifier = {
  async verifyAccessToken(token): Promise<AuthInfo> {
    const claims = await verifyWithYourAuthServer(token); // JWT check or introspection
    if (!claims) throw new OAuthError(OAuthErrorCode.InvalidToken, "Unknown or expired token");
    return { token, clientId: claims.clientId, scopes: claims.scopes,
             expiresAt: claims.exp,           // required: tokens without expiry are refused
             resource: new URL(claims.aud) }; // compared with expectedResource
  },
};
const app = createMcpExpressApp({ host: "0.0.0.0", allowedHosts: ["mcp.example.com"] });
app.all("/mcp", requireBearerAuth({ verifier, requiredScopes: ["mcp"], expectedResource: resource }),
        (req, res) => void node(req, res, req.body));
```

`expectedResource` rejects tokens issued for other services. Verified `AuthInfo`
reaches the factory (`createMcpHandler(({ authInfo }) => ...)`) and handlers
(`ctx.http?.authInfo`, undefined on stdio). OAuth discovery metadata and per-tool
scopes are covered in the SDK's `oauth` and `scoped-tools` examples.

## Resources and prompts

Resources are read-only data at a URI that the client attaches as context.
Prompts are templates a user invokes. Tools are what the model calls.

```typescript
import { completable, ProtocolError, ProtocolErrorCode, ResourceNotFoundError,
         ResourceTemplate } from "@modelcontextprotocol/server";

server.registerResource(
  "example-teams", "example://teams",
  { title: "Teams", description: "Every team", mimeType: "application/json" },
  async (uri, ctx) => ({ contents: [{ uri: uri.href, mimeType: "application/json",
    text: JSON.stringify(await apiGet<unknown>("teams", {}, ctx.mcpReq.signal)) }] }),
);

server.registerResource(
  "example-user", new ResourceTemplate("example://users/{userId}", { list: undefined }),
  { title: "User profile", mimeType: "application/json" },
  async (uri, { userId }, ctx) => {
    if (!/^U\d+$/.test(String(userId))) {
      throw new ProtocolError(ProtocolErrorCode.InvalidParams, `User IDs look like U123, got "${userId}"`);
    }
    const user = await apiGet<unknown>(`users/${userId}`, {}, ctx.mcpReq.signal).catch((error: unknown) => {
      if (error instanceof ApiError && error.status === 404) throw new ResourceNotFoundError(uri.href);
      throw error;
    });
    return { contents: [{ uri: uri.href, mimeType: "application/json", text: JSON.stringify(user) }] };
  },
);

const TEAMS = ["engineering", "marketing", "sales"];
server.registerPrompt(
  "example_team_report",
  { title: "Team report", description: "Summarise who is on a team",
    argsSchema: z.object({ team: completable(z.string().describe("Team name"),
                                             (value) => TEAMS.filter((t) => t.startsWith(value))) }) },
  async ({ team }) => ({ messages: [{ role: "user", content: { type: "text",
    text: `Use example_search_users to find everyone on the ${team} team and summarise it in a table.` } }] }),
);
```

- Give a template a `list` callback returning `{ resources: [...] }` to list its
  instances; `{ list: undefined }` keeps them readable but unlisted.
- If a template variable becomes a file path, resolve it with `realpath` and
  reject anything outside your root.

## Notifications

`registerTool` / `registerResource` / `registerPrompt` return handles whose
`enable()`, `disable()`, `update()` and `remove()` send the matching
`list_changed` notification. Behind `createMcpHandler` each request has its own
instance, so notify through the handler instead: `handler.notify.toolsChanged()`.
Notify only when capabilities really change.

## Self-check client

Run after every change, with `npm run build`:

```typescript
// scripts/smoke.ts — npm run build && npm run smoke
import { strict as assert } from "node:assert";
import { Client } from "@modelcontextprotocol/client";
import { getDefaultEnvironment, StdioClientTransport } from "@modelcontextprotocol/client/stdio";

const client = new Client({ name: "smoke", version: "1.0.0" });
await client.connect(new StdioClientTransport({
  command: "node",
  args: ["dist/index.js"],
  // the child gets only a minimal environment; pass the server's own settings
  env: { ...getDefaultEnvironment(), EXAMPLE_API_KEY: process.env.EXAMPLE_API_KEY ?? "" },
}));

const { tools } = await client.listTools();
assert.deepEqual(tools.map((t) => t.name).sort(), ["example_get_user", "example_search_users"]);

const search = await client.callTool({ name: "example_search_users",
                                       arguments: { query: "ada", limit: 5, response_format: "json" } });
assert.ok(!search.isError, JSON.stringify(search.content));

const invalid = await client.callTool({ name: "example_search_users", arguments: { query: "a" } });
assert.equal(invalid.isError, true, "a one-character query should be rejected");

await client.close();
console.error("smoke test passed");
```

For HTTP servers, start one (`TRANSPORT=http npm start`) and connect with
`new StreamableHTTPClientTransport(new URL("http://127.0.0.1:3000/mcp"))`. For
manual exploration: `npx @modelcontextprotocol/inspector node dist/index.js`.

## More features

The SDK repository's examples cover: progress, logging and cancellation
(`streaming`); asking the user mid-call (`elicitation`); resource subscriptions
(`subscriptions`); OAuth login (`oauth`) and client credentials
(`oauth-client-credentials`); per-tool scopes (`scoped-tools`); web-standard
runtimes (`hono`, `bearer-auth-web`); sessionful HTTP (`standalone-get`,
`sse-polling`); and a server using every feature (`todos-server`).

## Projects on SDK v1

Most published examples show v1. Translate them for v2, or stay on v1 if the
project already uses it:

| v1 (`@modelcontextprotocol/sdk`) | v2 |
| --- | --- |
| `@modelcontextprotocol/sdk/server/mcp.js` | `@modelcontextprotocol/server` |
| `@modelcontextprotocol/sdk/server/stdio.js` | `@modelcontextprotocol/server/stdio` |
| `zod` 3, `import { z } from "zod"` | `zod` ≥ 4.2, `import * as z from "zod/v4"` |
| `inputSchema: { q: z.string() }` (raw shape) | `inputSchema: z.object({ q: z.string() })` |
| `server.tool()`, `.resource()`, `.prompt()` | `registerTool`, `registerResource`, `registerPrompt` |
| `new StdioServerTransport()` + `server.connect()` | `serveStdio(createServer)` |
| per-request `StreamableHTTPServerTransport` + `express.json()` | `createMcpHandler` + `createMcpExpressApp` + `toNodeHandler` |
| `extra.signal`, `extra.authInfo` | `ctx.mcpReq.signal`, `ctx.http?.authInfo` |
| `McpError`, `ErrorCode` | `ProtocolError`, `ProtocolErrorCode` |
| Node 18+ | Node 20+ |

On v1, the same design rules apply: `registerTool` exists there too (with a raw
Zod 3 shape as `inputSchema`), and for HTTP you create a new
`StreamableHTTPServerTransport` per request with `sessionIdGenerator: undefined`
for stateless operation. Read the v1 README
(`https://raw.githubusercontent.com/modelcontextprotocol/typescript-sdk/v1.x/README.md`)
for exact signatures.

To migrate:

```bash
npx @modelcontextprotocol/codemod@latest v1-to-v2 .
grep -rn '@mcp-codemod-error' .   # places the codemod could not rewrite safely
npx tsc --noEmit
```

Then make sure `zod` is ≥ 4.2 and run the tests. Full guide:
`https://ts.sdk.modelcontextprotocol.io/v2/migration/upgrade-to-v2.md`.

## Checklist

### Design
- [ ] Tools cover workflows, not only endpoint wrappers
- [ ] snake_case names with the service prefix
- [ ] `title`, a description that says when to use it, and truthful `annotations` on every tool
- [ ] Zod object schemas with constraints and `.describe()`; `z.strictObject` where unknown arguments should fail
- [ ] Pagination with `limit`/`offset` and `next_offset`
- [ ] Responses under `CHARACTER_LIMIT` by returning fewer items
- [ ] `structuredContent` paired with its JSON text; `outputSchema` only on always-JSON tools
- [ ] Error messages say how to recover

### Implementation
- [ ] `createServer()` returns a new server each call; shared clients at module scope
- [ ] Upstream calls pass `ctx.mcpReq.signal` and have a timeout
- [ ] Strict TypeScript, no `any`; upstream data validated before it becomes `structuredContent`
- [ ] Nothing written to stdout in stdio mode
- [ ] HTTP keeps Host/Origin validation, plus bearer auth when exposed beyond localhost

### Project
- [ ] Depends on `@modelcontextprotocol/server` (not `/sdk`) and `zod` ≥ 4.2; no `zod/v3` imports
- [ ] `bin` points at `dist/index.js`; `src/index.ts` starts with `#!/usr/bin/env node`

### Verification
- [ ] `npm run build` is clean
- [ ] The self-check passes against the built server
- [ ] The evaluation harness results are acceptable
