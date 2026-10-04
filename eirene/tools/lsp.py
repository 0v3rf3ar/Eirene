"""Bounded, read-only LSP queries using the application's execution sandbox.

Each query owns one server process, opens the current on-disk document, and tears
down the process tree. No stale indexes or unsynchronized document cache survive
an edit. Servers are optional; nothing is installed or fetched automatically.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from ..core.errors import ToolError
from ..core.subprocesses import executable_argv
from . import files, isolation as runtime, language, shell
from .sandbox import Sandbox

MAX_MESSAGE = 4 * 1024 * 1024
LANGUAGES = {
    ".py": "python", ".js": "javascript", ".jsx": "javascriptreact",
    ".ts": "typescript", ".tsx": "typescriptreact", ".rs": "rust", ".go": "go",
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp",
    ".sh": "shellscript", ".bash": "shellscript",
    ".html": "html", ".htm": "html",
    ".css": "css", ".scss": "scss", ".less": "less",
    ".json": "json", ".jsonc": "jsonc",
    ".yaml": "yaml", ".yml": "yaml", ".lua": "lua",
}
COMMANDS = {
    "python": [["pyright-langserver", "--stdio"], ["pylsp"]],
    "typescript": [["typescript-language-server", "--stdio"]],
    "javascript": [["typescript-language-server", "--stdio"]],
    "rust": [["rust-analyzer"]], "go": [["gopls"]],
    "c": [["clangd", "--background-index=false"]],
    "cpp": [["clangd", "--background-index=false"]],
    "shellscript": [["bash-language-server", "start"]],
    "html": [["vscode-html-language-server", "--stdio"]],
    "css": [["vscode-css-language-server", "--stdio"]],
    "scss": [["vscode-css-language-server", "--stdio"]],
    "less": [["vscode-css-language-server", "--stdio"]],
    "json": [["vscode-json-language-server", "--stdio"]],
    "jsonc": [["vscode-json-language-server", "--stdio"]],
    "yaml": [["yaml-language-server", "--stdio"]],
    "lua": [["lua-language-server"]],
}


def server_for(path: Path, definitions: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    language_id = LANGUAGES.get(path.suffix.lower(), "")
    base = language_id.removesuffix("react")
    definition = definitions.get(language_id, definitions.get(base))
    if definition is False:
        return None
    if definition is not None:
        if not isinstance(definition, dict):
            raise ToolError(f"language_servers.{base} must be an object or false")
        command = definition.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
            raise ToolError(f"language_servers.{base}.command must be a nonempty argv array")
        return language_id or str(definition.get("language_id", "plaintext")), definition
    for argv in COMMANDS.get(base, []):
        executable = shutil.which(argv[0])
        if executable:
            return language_id, {"command": [executable, *argv[1:]]}
    return None


class Client:
    """Sequential Content-Length JSON-RPC transport with bounded notifications."""

    def __init__(self, process: asyncio.subprocess.Process, root: Path) -> None:
        self.process = process
        self.root = root
        self.next_id = 0
        self.diagnostics: dict[str, list[dict[str, Any]]] = {}
        self.configuration: dict[str, Any] = {}

    async def send(self, message: dict[str, Any]) -> None:
        payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
        if len(payload) > MAX_MESSAGE:
            raise ToolError("language-server request exceeds the message limit")
        if self.process.stdin is None:
            raise ToolError("language-server stdin is closed")
        self.process.stdin.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload)
        await self.process.stdin.drain()

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        await self.send({"jsonrpc": "2.0", "method": method, "params": params})

    async def receive(self) -> dict[str, Any]:
        stream = self.process.stdout
        if stream is None:
            raise ToolError("language-server stdout is closed")
        header = await stream.readuntil(b"\r\n\r\n")
        if len(header) > 8192:
            raise ToolError("language-server header exceeds the limit")
        length = None
        for line in header.decode("ascii").split("\r\n"):
            key, separator, value = line.partition(":")
            if separator and key.lower() == "content-length":
                length = int(value.strip())
        if length is None or not 0 < length <= MAX_MESSAGE:
            raise ToolError("invalid language-server message length")
        message = json.loads(await stream.readexactly(length))
        if not isinstance(message, dict):
            raise ToolError("invalid language-server response")
        return message

    async def handle(self, message: dict[str, Any]) -> None:
        method, params = message.get("method"), message.get("params", {})
        if not isinstance(params, dict):
            raise ToolError("language server sent invalid notification parameters")
        if "id" in message:
            result: Any = None
            if method == "workspace/configuration":
                result = [self.configuration.get(item.get("section", ""), {})
                          for item in params.get("items", [])]
            elif method == "workspace/workspaceFolders":
                result = [{"uri": self.root.as_uri(), "name": self.root.name}]
            elif method not in {"window/workDoneProgress/create", "client/registerCapability", "client/unregisterCapability"}:
                await self.send({"jsonrpc": "2.0", "id": message["id"],
                                 "error": {"code": -32601, "message": "read-only client does not support this request"}})
                return
            await self.send({"jsonrpc": "2.0", "id": message["id"], "result": result})
        elif method == "textDocument/publishDiagnostics" and isinstance(params.get("uri"), str):
            # Keep only the opened document, set by the caller before didOpen.
            if params["uri"] in self.diagnostics:
                self.diagnostics[params["uri"]] = params.get("diagnostics", [])[:500]

    async def request(self, method: str, params: dict[str, Any]) -> Any:
        self.next_id += 1
        request_id = self.next_id
        await self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        while True:
            message = await self.receive()
            if message.get("id") == request_id and "method" not in message:
                if "error" in message:
                    raise ToolError(f"language server rejected {method}: {message['error']}")
                return message.get("result")
            await self.handle(message)


async def _drain(stream: asyncio.StreamReader | None) -> None:
    if stream:
        while await stream.read(8192):
            pass


def _position(text: str, line: int, column: int) -> dict[str, int]:
    rows = text.split("\n")
    if line < 1 or line > len(rows) or column < 1 or column > len(rows[line - 1]) + 1:
        raise ToolError("line/column is outside the source document (both are 1-based)")
    prefix = rows[line - 1][:column - 1]
    return {"line": line - 1, "character": len(prefix.encode("utf-16-le")) // 2}


def _locations(result: Any, box: Sandbox, limit: int) -> str:
    items = result if isinstance(result, list) else [result] if isinstance(result, dict) else []
    rows = []
    for item in items[:500]:
        if not isinstance(item, dict):
            raise ToolError("language server returned an invalid location")
        uri = urlparse(item.get("uri", item.get("targetUri", "")))
        if uri.scheme != "file" or uri.netloc not in {"", "localhost"}:
            continue
        decoded = unquote(uri.path)
        if os.name == "nt" and decoded.startswith("/"):
            decoded = decoded[1:]
        path = Path(decoded).resolve()
        if not box.contains(str(path)):
            continue
        location_range = item.get("range", item.get("targetSelectionRange", {}))
        if not isinstance(location_range, dict):
            raise ToolError("language server returned an invalid location range")
        span = location_range.get("start", {})
        rows.append(f"{box.relative(path)}:{int(span.get('line', 0)) + 1}:{int(span.get('character', 0)) + 1}")
        if len(rows) >= limit:
            break
    body = "\n".join(rows) or "no semantic locations found within approved paths"
    if len(items) > limit:
        body += "\n[Partial result: location limit reached; narrow the query.]"
    return body


def _format(action: str, result: Any, box: Sandbox, limit: int) -> str:
    if action in {"definition", "references"}:
        return _locations(result, box, limit)
    if action == "hover":
        contents = result.get("contents", "") if isinstance(result, dict) else ""
        items = contents if isinstance(contents, list) else [contents]
        return "\n".join(str(item.get("value", "")) if isinstance(item, dict) else str(item)
                         for item in items)[:16000] or "no semantic hover information"
    items = result.get("items", []) if isinstance(result, dict) else result or []
    rows = []
    for item in items[:limit]:
        start = item.get("range", {}).get("start", {})
        rows.append(f"{int(start.get('line', 0)) + 1}:{int(start.get('character', 0)) + 1} "
                    f"severity={item.get('severity', '?')} {str(item.get('message', ''))[:1000]}")
    body = "\n".join(rows) or "no language-server diagnostics"
    if len(items) > limit:
        body += "\n[Partial result: diagnostic limit reached.]"
    return body


async def query(box: Sandbox, path: str, action: str, *, line: int = 1, column: int = 1,
                limit: int = 100, timeout: float = 30, definitions: dict[str, Any] | None = None,
                isolation: str = "none", isolate_network: bool = True, read_only: bool = True) -> str:
    if action not in {"definition", "references", "hover", "diagnostics"}:
        raise ToolError("action must be definition, references, hover, or diagnostics")
    target = box.resolve(path)
    if not target.is_file() or target.stat().st_size > 1024 * 1024:
        raise ToolError("semantic navigation requires a source file no larger than 1 MB")
    text = target.read_text(encoding="utf-8")
    position = _position(text, line, column)
    limit = max(1, min(int(limit), 500))
    selected = server_for(target, definitions or {})
    if selected is None:
        if action == "diagnostics":
            return "No language server installed; compiler/parser fallback:\n" + await language.diagnostics(
                box, path, timeout, isolation=isolation, isolate_network=isolate_network, read_only=read_only)
        if action in {"definition", "references"}:
            import re
            row = text.split("\n")[line - 1]
            symbol = next((match.group() for match in re.finditer(r"[A-Za-z_$][\w$]*", row)
                           if match.start() <= column - 1 < match.end()), None)
            if symbol:
                lexical_result = (files.find_symbol(box, symbol, ".", limit) if action == "definition"
                          else await asyncio.to_thread(language.references, box, symbol, ".", limit))
                return "No language server installed; lexical fallback (name matches, not semantic identity):\n" + lexical_result
        return "No language server installed; configure language_servers or use targeted search_text."
    language_id, definition = selected
    argv = executable_argv(*definition["command"])
    extra_env = definition.get("env", {})
    env = runtime.environment(extra_env)
    if isolation != "none":
        read_paths = list(definition.get("read_paths", []))
        if target != box.root and box.root not in target.parents:
            read_paths.append(str(target))  # box.resolve already checked this call's approval.
        argv = runtime.command(shlex.join(argv), box.root, backend=isolation,
                               network=False, read_paths=read_paths, read_only=read_only)
    elif read_only:
        raise ToolError("language-server execution needs a sandbox to enforce read-only access")
    process: asyncio.subprocess.Process | None = None
    stderr_task: asyncio.Task[None] | None = None
    try:
        async with asyncio.timeout(max(1, min(timeout, 120))):
            process = await asyncio.create_subprocess_exec(
                *argv, cwd=str(box.root), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, **shell._spawn_kwargs())
            stderr_task = asyncio.create_task(_drain(process.stderr))
            client = Client(process, box.root)
            client.configuration = definition.get("configuration", {})
            initialized = await client.request("initialize", {
                "processId": None, "rootUri": box.root.as_uri(),
                "workspaceFolders": [{"uri": box.root.as_uri(), "name": box.root.name}],
                "capabilities": {"general": {"positionEncodings": ["utf-16"]},
                                 "workspace": {"configuration": True},
                                 "textDocument": {"diagnostic": {}}},
                "initializationOptions": definition.get("initialization_options"),
            })
            capabilities = initialized.get("capabilities", {})
            if capabilities.get("positionEncoding", "utf-16") != "utf-16":
                raise ToolError("language server selected an unsupported position encoding")
            await client.notify("initialized", {})
            if client.configuration:
                await client.notify("workspace/didChangeConfiguration", {"settings": client.configuration})
            uri = target.as_uri()
            client.diagnostics[uri] = []
            await client.notify("textDocument/didOpen", {"textDocument": {
                "uri": uri, "languageId": language_id, "version": 1, "text": text}})
            params: dict[str, Any] = {"textDocument": {"uri": uri}, "position": position}
            if action == "references":
                params["context"] = {"includeDeclaration": True}
            if action == "diagnostics":
                if capabilities.get("diagnosticProvider"):
                    result = await client.request("textDocument/diagnostic", {"textDocument": {"uri": uri}})
                else:
                    # Wait for an explicit publication; no response is never reported as success.
                    while True:
                        message = await client.receive()
                        await client.handle(message)
                        if message.get("method") == "textDocument/publishDiagnostics" and message.get("params", {}).get("uri") == uri:
                            result = client.diagnostics[uri]
                            break
            else:
                capability = {"definition": "definitionProvider", "references": "referencesProvider", "hover": "hoverProvider"}[action]
                if not capabilities.get(capability):
                    raise ToolError(f"language server does not support {action}; use targeted text search")
                result = await client.request(f"textDocument/{action}", params)
            return f"LSP {action} ({language_id}; locations use 1-based UTF-16 columns):\n" + _format(action, result, box, limit)
    except (OSError, ValueError, TypeError, KeyError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError) as exc:
        raise ToolError(f"language-server query failed ({type(exc).__name__}): {exc}; use targeted search or project checks") from exc
    finally:
        if process:
            await shell._kill_tree(process)
        if stderr_task:
            stderr_task.cancel()
            await asyncio.gather(stderr_task, return_exceptions=True)
