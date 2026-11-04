# Python MCP servers with FastMCP

The official Python SDK (`pip install mcp`) includes **FastMCP**, which turns
type-hinted Python functions into MCP tools, with schemas generated from type
hints and Pydantic models. Check the SDK README for the current API:
`https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/main/README.md`.

## At a glance

```python
from mcp.server.fastmcp import FastMCP, Context
from pydantic import BaseModel, ConfigDict, Field

mcp = FastMCP("example_mcp")

@mcp.tool(name="example_get_item", annotations={"readOnlyHint": True, "openWorldHint": True})
async def get_item(item_id: str) -> str:
    """Get one item by ID."""
    ...

if __name__ == "__main__":
    mcp.run()                      # stdio
    # mcp.run(transport="streamable-http")  # remote
```

## Layout

```
example_mcp/
├── pyproject.toml          # dependencies: mcp, httpx, pydantic
├── README.md
├── example_mcp/
│   ├── __init__.py
│   ├── server.py           # FastMCP instance, tools, entry point
│   ├── api.py              # one HTTP client, error mapping
│   └── formatting.py       # Markdown/JSON rendering
└── tests/
    └── smoke.py            # self-check client
```

Name the server `{service}_mcp`. Add a console script so clients can run it with
`uvx example-mcp` or `python -m example_mcp.server`.

## Inputs with Pydantic

A single Pydantic model per tool gives you validation, defaults and the JSON
Schema the model sees. Field descriptions are the model's only documentation for
each argument, so make them concrete.

```python
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ResponseFormat(str, Enum):
    MARKDOWN = "markdown"
    JSON = "json"


class SearchUsers(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(..., min_length=2, max_length=200,
                       description="Text to match against names and emails, e.g. 'marketing'")
    limit: int = Field(20, ge=1, le=100, description="Maximum users to return")
    offset: int = Field(0, ge=0, description="Matches to skip, for pagination")
    response_format: ResponseFormat = Field(ResponseFormat.MARKDOWN,
                                            description="'markdown' for reading, 'json' for structured data")

    @field_validator("query")
    @classmethod
    def no_wildcards(cls, value: str) -> str:
        if value.strip("*") == "":
            raise ValueError("query must contain text, not only wildcards")
        return value
```

Pydantic v2 reminders: `model_config = ConfigDict(...)` instead of `class
Config`; `field_validator` instead of `validator`; `model_dump()` instead of
`dict()`; `extra="forbid"` rejects unknown arguments.

Take the model as the tool's single parameter (`params: SearchUsers`), or use
plain annotated parameters with `Annotated[int, Field(ge=1, le=100)]` for simple
tools.

## The API client

One module-level `httpx.AsyncClient`, one request helper, one error mapper:

```python
import os
import httpx

API_BASE = "https://api.example.com/v1"
API_KEY = os.environ.get("EXAMPLE_API_KEY", "")
client = httpx.AsyncClient(base_url=API_BASE, timeout=30.0,
                           headers={"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"})


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


MESSAGES = {
    401: "The Example API rejected the key. Check EXAMPLE_API_KEY.",
    403: "This key cannot access that resource.",
    404: "Not found. Check the ID; example_search_users lists valid IDs.",
    429: "Rate limited. Wait a minute, then retry with a smaller limit.",
}


async def api_get(path: str, **params) -> dict:
    try:
        response = await client.get(path, params=params)
    except httpx.TimeoutException:
        raise ApiError(0, "The Example API did not answer within 30 seconds; try a narrower query.")
    if response.is_error:
        raise ApiError(response.status_code,
                       MESSAGES.get(response.status_code, f"The Example API returned HTTP {response.status_code}."))
    return response.json()
```

Always use async I/O in tools (`httpx.AsyncClient`, not `requests`): a blocking
call stalls every other request the server is handling.

## Output

```python
import json

CHARACTER_LIMIT = 25_000


def render_users(users: list[dict], total: int, offset: int, fmt: ResponseFormat, query: str) -> str:
    next_offset = offset + len(users)
    page = {"total": total, "count": len(users), "offset": offset, "users": users,
            "has_more": total > next_offset}
    if page["has_more"]:
        page["next_offset"] = next_offset
    if fmt is ResponseFormat.JSON:
        return json.dumps(page, indent=2)
    lines = [f"# Users matching '{query}'", f"Showing {len(users)} of {total}.", ""]
    for user in users:
        lines += [f"## {user['name']} ({user['id']})", f"- Email: {user['email']}", ""]
    if page["has_more"]:
        lines.append(f"More results: call again with offset={next_offset}.")
    return "\n".join(lines)


def fit(users: list[dict], render) -> str:
    """Halve the page until it fits; next_offset then points at the first user left out."""
    text = render(users)
    while len(users) > 1 and len(text) > CHARACTER_LIMIT:
        users = users[: (len(users) + 1) // 2]
        text = render(users)
    return text
```

For always-structured tools, return a Pydantic model or `TypedDict` from the
function: FastMCP then advertises an output schema and sends
`structuredContent` along with a JSON text block.

## Errors

A tool that raises returns an `isError` result whose text is the exception
message, so raise exceptions with messages that tell the model what to do. Do
not include stack traces or secrets.

## Docstrings

FastMCP uses the docstring as the tool description. Write it for the model:

```python
@mcp.tool(name="example_search_users",
          annotations={"title": "Search users", "readOnlyHint": True, "destructiveHint": False,
                       "idempotentHint": True, "openWorldHint": True})
async def search_users(params: SearchUsers) -> str:
    """Search Example users by name or email.

    Returns one page of matches; when more exist the result gives next_offset.
    Use example_get_user instead when you already have a user ID.

    Examples:
      - "who is on the marketing team" -> query="marketing"
      - "look up ada@example.com" -> query="ada@example.com"
    """
    data = await api_get("users/search", q=params.query, limit=params.limit, offset=params.offset)
    if not data["users"]:
        return f"No users match '{params.query}'. Try a shorter or different query."
    return fit(data["users"], lambda users: render_users(
        users, data["total"], params.offset, params.response_format, params.query))
```

## Complete example

```python
#!/usr/bin/env python3
"""MCP server for the Example API. stdio by default; TRANSPORT=http for Streamable HTTP."""

import os
import sys
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

from .api import ApiError, api_get           # the client above
from .formatting import ResponseFormat, fit, render_users

if not os.environ.get("EXAMPLE_API_KEY"):
    print("EXAMPLE_API_KEY is required", file=sys.stderr)
    sys.exit(1)

mcp = FastMCP("example_mcp")


class SearchUsers(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    query: str = Field(..., min_length=2, max_length=200, description="Text to match against names and emails")
    limit: int = Field(20, ge=1, le=100, description="Maximum users to return")
    offset: int = Field(0, ge=0, description="Matches to skip, for pagination")
    response_format: ResponseFormat = Field(ResponseFormat.MARKDOWN, description="'markdown' or 'json'")


class User(BaseModel):
    id: str
    name: str
    email: str
    team: str | None = None
    active: bool = True


@mcp.tool(name="example_search_users",
          annotations={"title": "Search users", "readOnlyHint": True, "destructiveHint": False,
                       "idempotentHint": True, "openWorldHint": True})
async def search_users(params: SearchUsers) -> str:
    """Search Example users by name or email. Paginated; use example_get_user when you have an ID."""
    data = await api_get("users/search", q=params.query, limit=params.limit, offset=params.offset)
    if not data["users"]:
        return f"No users match '{params.query}'. Try a shorter or different query."
    return fit(data["users"], lambda users: render_users(
        users, data["total"], params.offset, params.response_format, params.query))


@mcp.tool(name="example_get_user",
          annotations={"title": "Get user", "readOnlyHint": True, "destructiveHint": False,
                       "idempotentHint": True, "openWorldHint": True})
async def get_user(user_id: Annotated[str, Field(min_length=1, description="User ID, e.g. 'U123456'")]) -> User:
    """Get one Example user by ID. Returns structured data."""
    return User.model_validate(await api_get(f"users/{user_id}"))


def main() -> None:
    if os.environ.get("TRANSPORT") == "http":
        mcp.settings.host = "127.0.0.1"
        mcp.settings.port = int(os.environ.get("PORT", "8000"))
        mcp.run(transport="streamable-http")   # serves /mcp
    else:
        mcp.run()


if __name__ == "__main__":
    main()
```

## More FastMCP features

### Context

Add a `ctx: Context` parameter to get logging, progress, and access to the
session; it is injected and does not appear in the tool's schema.

```python
@mcp.tool()
async def export_report(report_id: str, ctx: Context) -> str:
    """Export a report; reports progress while it runs."""
    await ctx.info(f"exporting {report_id}")
    for step in range(1, 5):
        await ctx.report_progress(step, 4)
        ...
    return "done"
```

Context can also ask the user for input mid-call (elicitation) and request a
completion from the client's model (sampling) when the client supports them;
see the SDK README.

### Resources and prompts

```python
@mcp.resource("example://teams")
async def teams() -> str:
    """Every team in the workspace, as JSON."""
    return json.dumps(await api_get("teams"))


@mcp.resource("example://users/{user_id}")
async def user_profile(user_id: str) -> str:
    return json.dumps(await api_get(f"users/{user_id}"))


@mcp.prompt()
def team_report(team: str) -> str:
    return f"Use example_search_users to find everyone on the {team} team, then summarise it in a table."
```

Resources are read-only data the client attaches as context; prompts are
templates a user invokes; tools are what the model calls.

### Shared state with a lifespan

Open connections once and close them on shutdown:

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(server):
    db = await connect()
    try:
        yield {"db": db}
    finally:
        await db.close()

mcp = FastMCP("example_mcp", lifespan=lifespan)
# in a tool: ctx.request_context.lifespan_context["db"]
```

## Self-check client

Start the server as a client would, call its tools, and fail loudly:

```python
# tests/smoke.py — run with: python tests/smoke.py
import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    # sys.executable: the same interpreter (and installed packages) as this script
    server = StdioServerParameters(command=sys.executable, args=["-m", "example_mcp.server"],
                                   env={**os.environ})
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            names = sorted(tool.name for tool in (await session.list_tools()).tools)
            assert names == ["example_get_user", "example_search_users"], names
            result = await session.call_tool("example_search_users",
                                             {"params": {"query": "ada", "limit": 5, "response_format": "json"}})
            assert not result.isError, result.content
            bad = await session.call_tool("example_search_users", {"params": {"query": "a"}})
            assert bad.isError, "a one-character query should be rejected"
    print("smoke test passed")


asyncio.run(main())
```

For interactive exploration: `npx @modelcontextprotocol/inspector python -m
example_mcp.server`.

## Checklist

### Design
- [ ] Tools cover real workflows, not only thin endpoint wrappers
- [ ] snake_case names with the service prefix
- [ ] Docstrings say what the tool does, what it returns, and when to use another tool
- [ ] Truthful annotations on every tool
- [ ] Pydantic models with constraints and descriptions; `extra="forbid"`
- [ ] Pagination with `limit`/`offset` and `next_offset`
- [ ] Responses capped by returning fewer items
- [ ] Errors say how to recover

### Implementation
- [ ] One async HTTP client with timeouts; no blocking calls in tools
- [ ] Secrets from environment variables, checked at start-up
- [ ] Nothing printed to stdout in stdio mode (use `print(..., file=sys.stderr)` or logging)
- [ ] HTTP mode binds to 127.0.0.1 unless deliberately exposed, with authentication when it is

### Verification
- [ ] `python -m py_compile` passes for every module
- [ ] The self-check client passes
- [ ] The evaluation harness runs and the results are acceptable
