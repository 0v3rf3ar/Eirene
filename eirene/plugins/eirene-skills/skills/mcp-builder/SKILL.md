---
name: mcp-builder
description: Build high-quality MCP (Model Context Protocol) servers that let language models use an external service through well-designed tools — in Python (FastMCP) or TypeScript (MCP SDK) — then test and evaluate them. Use when creating an MCP server for an API or service, or improving an existing one.
---

# Building MCP servers

An MCP server exposes an external service to a model as tools. Its quality is
measured by one thing: how well a model, using only those tools, can get real
work done.

## Workflow

Four phases: **research and plan**, **implement**, **review and test**, and
**evaluate**.

### Phase 1 — research and plan

#### 1.1 What good MCP design looks like

**Coverage versus workflows.** Balance broad coverage of the API's endpoints
with a few higher-level workflow tools. Workflow tools are convenient for common
tasks; broad coverage lets an agent combine operations it was not designed for.
Clients differ — some do well chaining simple tools, others prefer workflows —
so when unsure, favour broad coverage.

**Names that can be found.** Clear, descriptive, consistently prefixed names
(`github_create_issue`, `github_list_repos`) help a model pick the right tool.
Start with a verb.

**Context is scarce.** Keep descriptions tight, return focused data, and let
callers filter and paginate. A tool that dumps everything wastes the model's
context.

**Errors that say what to do.** An error message should point to the fix:
"Rate limit exceeded; wait 60 seconds" or "No such user; use
`example_search_users` to find IDs".

#### 1.2 The protocol

Read the specification as needed. Start from the site map,
`https://modelcontextprotocol.io/sitemap.xml`, then fetch pages with a `.md`
suffix for Markdown (for example
`https://modelcontextprotocol.io/specification/draft.md`). The parts that matter
most: the architecture overview, transports (stdio and Streamable HTTP), and the
definitions of tools, resources and prompts.

#### 1.3 The SDK

**Recommended stack:**

- **Language:** TypeScript has the most complete SDK and runs in the most host
  environments; models also write it well thanks to static types and linting.
  Python with FastMCP is an equally good choice when the team or the service's
  client libraries are in Python.
- **Transport:** stdio for a local server that a client launches; Streamable HTTP
  with stateless JSON responses for a remote server (simpler to scale than
  sessions and streams).

Load the guides you need:

- `reference/mcp_best_practices.md` — naming, response formats, pagination,
  transports, security, annotations, errors. **Read this first.**
- `reference/typescript_mcp_server.md` — TypeScript with SDK v2
  (`@modelcontextprotocol/server`), plus what changes for v1 projects.
- `reference/python_mcp_server.md` — Python with FastMCP and Pydantic.

**TypeScript has two SDK major versions.** Choose before writing code:

- **v2** (`@modelcontextprotocol/server`) is the current stable release. Use it
  for new servers.
- **v1** (`@modelcontextprotocol/sdk`) gets only bug and security fixes. Use it
  only when the project's `package.json` already depends on it.

If the project already uses v1, say once, briefly, that v2 is the current
release, that v1 only gets fixes, and that
`npx @modelcontextprotocol/codemod@latest v1-to-v2 .` migrates it. Then carry
on with v1 unless asked to migrate. Never mix the two in one project.

For the latest SDK details, fetch the READMEs:

- TypeScript v2: `https://raw.githubusercontent.com/modelcontextprotocol/typescript-sdk/main/README.md`
  (full index: `https://ts.sdk.modelcontextprotocol.io/v2/llms.txt`)
- TypeScript v1: `https://raw.githubusercontent.com/modelcontextprotocol/typescript-sdk/v1.x/README.md`
- Python: `https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/main/README.md`

#### 1.4 Plan

**Learn the API.** Read the service's documentation for its main endpoints,
authentication and data model. Search the web and fetch pages as needed.

**Choose the tools.** List the endpoints to cover, most common operations first.
Note which are read-only and which change or delete data.

### Phase 2 — implement

#### 2.1 Project layout

Follow the layout in the language guide.

#### 2.2 Shared pieces first

- one API client with authentication, timeouts and cancellation;
- error helpers that turn HTTP failures into actionable messages;
- response formatting (Markdown and JSON);
- pagination helpers and a response size limit.

#### 2.3 Tools

For every tool:

**Input schema** — Zod (TypeScript) or Pydantic (Python), with constraints and a
clear description (and an example) on every field.

**Output** — offer `response_format` (`markdown` or `json`). Declare an
`outputSchema` where the output is always structured, and return
`structuredContent` alongside the text.

**Description** — what it does, what it returns, when to use a sibling tool
instead, and one or two example requests.

**Implementation** — async I/O, actionable errors, pagination where results can
be long, a cap on response size.

**Annotations** — `readOnlyHint`, `destructiveHint`, `idempotentHint`,
`openWorldHint`, set truthfully.

### Phase 3 — review and test

#### 3.1 Review

- no duplicated logic (one API client, one error mapper, one formatter);
- consistent error handling;
- complete types;
- descriptions that match what the tools actually do.

#### 3.2 Build and test

**TypeScript:** `npm run build`, then the self-check client from the guide
(`npm run smoke`). For manual poking, `npx @modelcontextprotocol/inspector node
dist/index.js`.

**Python:** `python -m py_compile server.py`, then the self-check client from the
guide. The inspector works too: `npx @modelcontextprotocol/inspector python
server.py`.

**In Eirene:** add the server with `/mcp add`, enable it in `/mcp`, and try it in
a session. A stdio server must never write to stdout except protocol messages.

### Phase 4 — evaluate

Once it works, measure whether a model can actually use it. Read
`reference/evaluation.md` for the full method.

#### 4.1 Why

An evaluation asks: given only these tools, can a model answer realistic, hard
questions correctly?

#### 4.2 Ten questions

1. **Inspect the tools** — names, schemas, descriptions.
2. **Explore the data** with read-only calls.
3. **Write ten** complex, realistic questions.
4. **Answer each yourself** with the tools, to confirm the answer.

#### 4.3 Each question must be

- **independent** of the others;
- **read-only** — no writes needed;
- **complex** — many tool calls and real exploration;
- **realistic** — something a person would want;
- **verifiable** — one answer, checkable by string comparison;
- **stable** — the answer will not change over time.

#### 4.4 Format

```xml
<evaluation>
  <qa_pair>
    <question>Among the projects archived in 2023, which one had the most open issues when it was archived? Give its name.</question>
    <answer>atlas-legacy</answer>
  </qa_pair>
  <!-- nine more -->
</evaluation>
```

#### 4.5 Run it

`scripts/evaluation.py` runs every question through `eirene -p` with only the
server under test granted (`--mcp NAME`), then reports accuracy, tool calls,
time, tokens and the model's feedback on the tools:

```bash
python scripts/evaluation.py questions.xml --server example -o report.md
```

See `reference/evaluation.md` for the options and how to read the report.

## Reference files

Load these as you need them:

- **Protocol:** start at `https://modelcontextprotocol.io/sitemap.xml`; fetch
  pages with `.md`.
- `reference/mcp_best_practices.md` — naming, formats, pagination, transports,
  security and error handling. Load first.
- `reference/typescript_mcp_server.md` — project setup, server factory, Zod 4
  schemas, output formats, pagination, errors, a complete example serving stdio
  and Streamable HTTP, bearer auth, resources and prompts, a self-check client,
  v1 differences and migration, and a checklist.
- `reference/python_mcp_server.md` — FastMCP setup, Pydantic models, tool
  registration, a complete example, context features, resources, a self-check
  client and a checklist.
- `reference/evaluation.md` — writing questions, verifying answers, the XML
  format, and running the harness.
