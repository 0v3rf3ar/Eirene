"""ChatGPT subscription access through the supported Codex app-server."""

from __future__ import annotations

import asyncio
import json
import shutil
from collections import deque
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable

from .. import __version__
from ..core.errors import AuthError, ConnectionFailed, ProviderError
from ..core.subprocesses import executable_argv
from ..tools import activity
from .base import (Done, Event, PlanUpdate, Provider, ProviderTool, TextDelta,
                   ThinkingDelta, Usage)

ApprovalFn = Callable[[str, str, str, str], Awaitable[str]]
ChoiceFn = Callable[[str, list[str]], Awaitable[str | None]]


class CodexSubscription(Provider):
    """Codex-owned agent turns authenticated by a ChatGPT subscription."""

    name = "chatgpt-subscription"
    protocol = "codex-app-server"
    supports_tools = False  # Codex owns its tools; Eirene must not run them twice.
    owns_context = True

    def __init__(self, *, timeout: float = 300.0, binary: str = "codex") -> None:
        super().__init__(None, "", timeout=timeout)
        self.binary = binary
        self.root = Path.cwd()
        self.mode = "manual"
        self.approve: ApprovalFn | None = None
        self.choose: ChoiceFn | None = None
        self._rpc: _AppServer | None = None
        self._thread_id = ""
        self._turn_id = ""
        self._system_sent = False
        self._commands: dict[str, str] = {}
        self._file_changes: dict[str, list[dict[str, Any]]] = {}
        self._shown: set[str] = set()

    def set_context(self, root: Path, mode: str, approve: ApprovalFn | None = None,
                    choose: ChoiceFn | None = None) -> None:
        if self._thread_id and self.mode != mode:
            # Developer instructions are fixed at thread creation. Recreate the
            # Codex thread so a mode switch cannot retain stale instructions.
            self.reset_thread()
        self.root = root.resolve()
        self.mode = mode
        self.approve = approve
        self.choose = choose

    async def _server(self) -> "_AppServer":
        if self._rpc is None:
            self._rpc = _AppServer(self.binary, self.timeout, self._approve_request)
            await self._rpc.start()
        return self._rpc

    async def account(self, refresh: bool = False) -> dict[str, Any] | None:
        result = await (await self._server()).request(
            "account/read", {"refreshToken": refresh})
        account = result.get("account") if isinstance(result, dict) else None
        return account if isinstance(account, dict) else None

    async def login(self, method: str = "chatgpt") -> dict[str, Any]:
        if method not in ("chatgpt", "chatgptDeviceCode"):
            raise ProviderError(f"unsupported Codex login method '{method}'")
        return await (await self._server()).request(
            "account/login/start", {"type": method})

    async def wait_for_login(self, login_id: str, timeout: float = 300) -> dict[str, Any]:
        server = await self._server()
        while True:
            message = await server.notification(timeout)
            if message.get("method") != "account/login/completed":
                continue
            params = message.get("params") or {}
            if str(params.get("loginId") or "") != login_id:
                continue
            if not params.get("success"):
                raise AuthError(str(params.get("error") or "ChatGPT sign-in failed"))
            account = await self.account(refresh=True)
            if not account:
                raise AuthError("ChatGPT sign-in completed without an account")
            return account

    async def models(self) -> list[str]:
        result = await (await self._server()).request(
            "model/list", {"limit": 100, "includeHidden": False})
        rows = result.get("data", []) if isinstance(result, dict) else []
        names = []
        for row in rows:
            if isinstance(row, dict):
                name = str(row.get("model") or row.get("id") or "").strip()
                if name and name not in names:
                    names.append(name)
        return names

    async def validate(self, model: str = "") -> str:
        account = await self.account(refresh=True)
        if not account or account.get("type") != "chatgpt":
            raise AuthError("not signed in to ChatGPT; complete the Codex login")
        models = await self.models()
        plan = str(account.get("planType") or "subscription")
        return f"ChatGPT {plan}, {len(models)} models available"

    async def stream(self, messages: list[dict], model: str, *, system: str = "",
                     tools: list[dict] | None = None,
                     max_tokens: int = 8192) -> AsyncIterator[Event]:
        server = await self._server()
        if not self._thread_id:
            result = await server.request("thread/start",
                                          self._thread_options(model, system))
            thread = result.get("thread", {}) if isinstance(result, dict) else {}
            self._thread_id = str(thread.get("id") or "")
            if not self._thread_id:
                raise ProviderError("Codex did not return a thread id")

        text = _last_user_text(messages)
        if not self._system_sent:
            history = _prior_history(messages)
            pieces = []
            if history:
                pieces.append("Prior Eirene conversation:\n" + history)
            pieces.append("Current user request:\n" + text)
            text = "\n\n".join(piece for piece in pieces if piece)
            self._system_sent = True

        result = await server.request("turn/start", {
            "threadId": self._thread_id,
            "input": [{"type": "text", "text": text}],
            "model": model,
            "cwd": str(self.root),
            **self._turn_policy(),
        })
        turn = result.get("turn", {}) if isinstance(result, dict) else {}
        self._turn_id = str(turn.get("id") or "")
        usage = Usage()
        try:
            while True:
                message = await server.notification(self.timeout)
                method = str(message.get("method") or "")
                params = message.get("params") or {}
                if params.get("threadId") not in (None, self._thread_id):
                    continue
                if method == "item/agentMessage/delta":
                    yield TextDelta(str(params.get("delta") or ""))
                elif method == "item/reasoning/summaryTextDelta":
                    yield ThinkingDelta(str(params.get("delta") or ""))
                elif method == "thread/tokenUsage/updated":
                    last = (params.get("tokenUsage") or {}).get("last") or {}
                    usage = Usage(int(last.get("inputTokens") or 0),
                                  int(last.get("outputTokens") or 0))
                    yield usage
                elif method == "turn/plan/updated":
                    steps = []
                    for raw in params.get("plan") or []:
                        if not isinstance(raw, dict) or not raw.get("step"):
                            continue
                        status = {"inProgress": "in_progress"}.get(
                            str(raw.get("status") or "pending"),
                            str(raw.get("status") or "pending"))
                        steps.append({"text": str(raw["step"]), "status": status})
                    yield PlanUpdate(steps, str(params.get("explanation") or ""))
                elif method == "item/started":
                    item = params.get("item") or {}
                    item_type = str(item.get("type") or "")
                    if item_type == "fileChange":
                        item_id = str(item.get("id") or "")
                        if item_id:
                            self._file_changes[item_id] = list(item.get("changes") or [])
                    elif item_type == "commandExecution":
                        item_id = str(item.get("id") or "")
                        command = _command_text(item.get("command"))
                        if item_id and command and item_id not in self._commands:
                            self._commands[item_id] = activity.start_provider_command(
                                f"Codex: {command}", self._interrupt_turn)
                    shown = _item_tool(item, self.root)
                    if shown is not None:
                        self._shown.add(shown.id)
                        yield shown
                elif method == "item/fileChange/patchUpdated":
                    item_id = str(params.get("itemId") or "")
                    if item_id:
                        self._file_changes[item_id] = list(params.get("changes") or [])
                elif method in ("item/completed", "item/failed"):
                    item = params.get("item") or {}
                    item_id = str(item.get("id") or params.get("itemId") or "")
                    command_id = self._commands.pop(item_id, "")
                    if command_id:
                        activity.finish_provider_command(command_id)
                    if item_id in self._shown:
                        self._shown.discard(item_id)
                        shown = _item_tool(item, self.root)
                        if shown is not None:
                            shown.result = _item_result(item)
                            shown.finished = True
                            shown.is_error = method == "item/failed"
                            yield shown
                    self._file_changes.pop(item_id, None)
                elif method == "error":
                    error = params.get("error") or {}
                    raise ProviderError(str(error.get("message") or "Codex turn failed"))
                elif method == "turn/completed":
                    completed = params.get("turn") or {}
                    if self._turn_id and completed.get("id") not in (None, self._turn_id):
                        continue
                    status = str(completed.get("status") or "completed")
                    if status == "failed":
                        error = completed.get("error") or {}
                        raise ProviderError(str(error.get("message") or "Codex turn failed"))
                    yield Done("stop" if status == "completed" else status)
                    return
        except asyncio.CancelledError:
            if self._thread_id and self._turn_id:
                try:
                    await server.request("turn/interrupt", {
                        "threadId": self._thread_id, "turnId": self._turn_id})
                except ProviderError:
                    pass
            raise
        finally:
            for command_id in self._commands.values():
                activity.finish_provider_command(command_id)
            self._commands.clear()
            self._file_changes.clear()
            self._shown.clear()
            self._turn_id = ""

    async def _interrupt_turn(self) -> None:
        """Interrupt the Codex turn that owns a displayed command."""
        if self._rpc is not None and self._thread_id and self._turn_id:
            await self._rpc.request("turn/interrupt", {
                "threadId": self._thread_id, "turnId": self._turn_id})

    async def isolated_stream(self, messages: list[dict], model: str, *,
                              system: str = "", tools: list[dict] | None = None,
                              max_tokens: int = 8192) -> AsyncIterator[Event]:
        """Run side questions in a separate read-only Codex conversation."""
        clone = CodexSubscription(timeout=self.timeout, binary=self.binary)
        clone.set_context(self.root, "plan")
        try:
            async for event in clone.stream(messages, model, system=system,
                                            tools=None, max_tokens=max_tokens):
                yield event
        finally:
            await clone.close()

    def reset_thread(self) -> None:
        """Detach from prior context after Eirene clears its session."""
        self._thread_id = ""
        self._turn_id = ""
        self._system_sent = False

    def _thread_options(self, model: str, system: str = "") -> dict[str, Any]:
        policy = self._turn_policy()
        sandbox = policy.pop("sandboxPolicy")
        legacy = "read-only" if sandbox["type"] == "readOnly" else "workspace-write"
        return {"model": model, "cwd": str(self.root), "sandbox": legacy,
                "approvalPolicy": policy["approvalPolicy"],
                "developerInstructions": system or None,
                "serviceName": "eirene"}

    def _turn_policy(self) -> dict[str, Any]:
        if self.mode == "plan":
            return {"approvalPolicy": "never",
                    "sandboxPolicy": {"type": "readOnly"}}
        if self.mode == "auto":
            return {"approvalPolicy": "never", "sandboxPolicy": {
                "type": "workspaceWrite", "writableRoots": [str(self.root)],
                "networkAccess": False}}
        # "on-request" lets Codex write inside the workspace unasked, which is
        # not what Eirene's manual mode promises.
        return {"approvalPolicy": "untrusted", "sandboxPolicy": {
            "type": "workspaceWrite", "writableRoots": [str(self.root)],
            "networkAccess": False}}

    async def _approve_request(self, message: dict[str, Any]) -> dict[str, Any]:
        method = str(message.get("method") or "")
        params = message.get("params") or {}
        if method == "item/tool/requestUserInput":
            answers = {}
            for question in params.get("questions") or []:
                if not isinstance(question, dict):
                    continue
                question_id = str(question.get("id") or "")
                options = [str(option.get("label") or "")
                           for option in question.get("options") or []
                           if isinstance(option, dict) and option.get("label")]
                answer = None
                if self.mode != "auto" and self.choose is not None:
                    answer = await self.choose(str(question.get("question") or ""),
                                               options)
                answers[question_id] = {"answers": [answer] if answer else []}
            return {"answers": answers}
        if self.mode != "manual" or self.approve is None:
            return {"decision": "decline"}
        if method == "item/commandExecution/requestApproval":
            command = params.get("command") or []
            label = " ".join(command) if isinstance(command, list) else str(command)
            answer = await self.approve("run_command", label, "",
                                        str(params.get("reason") or "Codex command"))
        elif method == "item/fileChange/requestApproval":
            item_id = str(params.get("itemId") or "")
            # The server request and its preceding item notification are read by
            # separate tasks. Give the stream consumer a moment to cache the diff.
            for _ in range(50):
                changes = self._file_changes.get(item_id, [])
                if changes:
                    break
                await asyncio.sleep(0.01)
            label, preview = _file_change_preview(changes, self.root)
            answer = await self.approve("native_apply_patch", label, preview,
                                        str(params.get("reason") or "Codex file change"))
        else:
            return {"decision": "decline"}
        return {"decision": {"yes": "accept", "always": "acceptForSession"}.get(
            answer, "decline")}

    async def close(self) -> None:
        if self._rpc is not None:
            await self._rpc.close()
            self._rpc = None


class _AppServer:
    """Minimal concurrent JSONL client for `codex app-server`."""

    def __init__(self, binary: str, timeout: float,
                 approve: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]) -> None:
        self.binary = binary
        self.timeout = timeout
        self.approve = approve
        self.process: asyncio.subprocess.Process | None = None
        self.pending: dict[int, asyncio.Future] = {}
        self.notifications: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._next_id = 0
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._stderr: deque[str] = deque(maxlen=20)
        self._write_lock = asyncio.Lock()

    async def start(self) -> None:
        if self.process is not None:
            return
        executable = shutil.which(self.binary)
        if not executable:
            raise ConnectionFailed("Codex CLI", "install `codex` and put it on PATH")
        try:
            self.process = await asyncio.create_subprocess_exec(
                *executable_argv(executable, "app-server", "--listen", "stdio://"),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE)
        except OSError as exc:
            raise ConnectionFailed("Codex app-server", str(exc)) from exc
        self._reader_task = asyncio.create_task(self._read())
        self._stderr_task = asyncio.create_task(self._read_stderr())
        await self.request("initialize", {"clientInfo": {
            "name": "eirene", "title": "Eirene", "version": __version__}})
        await self._send({"method": "initialized", "params": {}})

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self.process is None:
            raise ConnectionFailed("Codex app-server", "not running")
        self._next_id += 1
        request_id = self._next_id
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        await self._send({"method": method, "id": request_id, "params": params})
        try:
            result = await asyncio.wait_for(future, self.timeout)
        except asyncio.TimeoutError as exc:
            self.pending.pop(request_id, None)
            raise ProviderError(f"Codex timed out during {method}", retryable=True) from exc
        return result if isinstance(result, dict) else {}

    async def notification(self, timeout: float) -> dict[str, Any]:
        try:
            return await asyncio.wait_for(self.notifications.get(), timeout)
        except asyncio.TimeoutError as exc:
            raise ProviderError("Codex stopped sending events", retryable=True) from exc

    async def _send(self, message: dict[str, Any]) -> None:
        process = self.process
        if process is None or process.stdin is None:
            raise ConnectionFailed("Codex app-server", "stdin closed")
        data = (json.dumps(message, separators=(",", ":")) + "\n").encode()
        async with self._write_lock:
            process.stdin.write(data)
            await process.stdin.drain()

    async def _read(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        # Command completion items can contain the full aggregated output in a
        # single JSONL record. StreamReader.readline() enforces asyncio's 64 KiB
        # line limit and kills this task when a noisy command crosses it, leaving
        # the turn waiting for notifications that nobody is reading. Drain fixed
        # size chunks and frame the JSONL records ourselves instead.
        buffer = bytearray()
        reader_error = ""
        try:
            while chunk := await self.process.stdout.read(64 * 1024):
                buffer.extend(chunk)
                while (newline := buffer.find(b"\n")) >= 0:
                    self._handle_line(bytes(buffer[:newline]))
                    del buffer[:newline + 1]
            if buffer:
                self._handle_line(bytes(buffer))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            reader_error = f"protocol reader failed: {exc}"
        detail = (reader_error or "".join(self._stderr).strip()[-500:]
                  or "process exited")
        error = ConnectionFailed("Codex app-server", detail)
        await self.notifications.put({"method": "error", "params": {
            "error": {"message": error.user_message()}}})
        for future in self.pending.values():
            if not future.done():
                future.set_exception(error)
        self.pending.clear()

    def _handle_line(self, line: bytes) -> None:
        """Dispatch one app-server JSONL record without imposing a line limit."""
        if not line.strip():
            return
        try:
            message = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        if not isinstance(message, dict):
            return
        request_id = message.get("id")
        if request_id is not None and "method" not in message:
            future = self.pending.pop(request_id, None)
            if future is None or future.done():
                return
            if message.get("error"):
                error = message["error"]
                future.set_exception(ProviderError(
                    str(error.get("message") if isinstance(error, dict) else error)))
            else:
                future.set_result(message.get("result") or {})
        elif request_id is not None and message.get("method"):
            asyncio.create_task(self._answer_server_request(message))
        else:
            self.notifications.put_nowait(message)

    async def _answer_server_request(self, message: dict[str, Any]) -> None:
        try:
            result = await self.approve(message)
        except Exception:  # noqa: BLE001
            result = {"decision": "decline"}
        await self._send({"id": message["id"], "result": result})

    async def _read_stderr(self) -> None:
        assert self.process is not None and self.process.stderr is not None
        while line := await self.process.stderr.readline():
            self._stderr.append(line.decode(errors="replace"))

    async def close(self) -> None:
        process, self.process = self.process, None
        if process is None:
            return
        if process.stdin:
            process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), 2)
        except asyncio.TimeoutError:
            process.terminate()
            await process.wait()
        for task in (self._reader_task, self._stderr_task):
            if task and not task.done():
                task.cancel()


ITEM_TOOLS = {"commandExecution": ("Bash", "exec"), "fileChange": ("Edit", "write"),
              "mcpToolCall": ("MCP", "exec"), "webSearch": ("WebSearch", "read"),
              "fileRead": ("Read", "read")}


def _item_tool(item: dict[str, Any], root: Path) -> ProviderTool | None:
    """Turn a Codex work item into something the transcript can show."""
    named = ITEM_TOOLS.get(str(item.get("type") or ""))
    item_id = str(item.get("id") or "")
    if named is None or not item_id:
        return None
    name, kind = named
    label = _command_text(item.get("command")) or str(
        item.get("query") or item.get("tool") or "")
    preview = ""
    if not label:
        changes = [change for change in item.get("changes") or []
                   if isinstance(change, dict)]
        label, preview = _file_change_preview(changes, root)
    return ProviderTool(item_id, name, label[:120] or name, kind, preview=preview)


def _relative(path: str, root: Path) -> str:
    try:
        return str(Path(path).relative_to(root))
    except ValueError:
        return path


def _item_result(item: dict[str, Any]) -> str:
    for key in ("output", "result", "summary", "status"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value[:400]
    return ""


def _command_text(raw: Any) -> str:
    if isinstance(raw, list):
        return " ".join(str(part) for part in raw).strip()
    return str(raw or "").strip()


def _file_change_preview(changes: list[dict[str, Any]], root: Path) -> tuple[str, str]:
    """Combine Codex app-server file-change records into a visible diff."""
    paths, diffs = [], []
    for change in changes:
        if not isinstance(change, dict):
            continue
        raw_path = str(change.get("path") or "workspace files")
        try:
            path = str(Path(raw_path).resolve().relative_to(root.resolve()))
        except (OSError, ValueError):
            path = raw_path
        paths.append(path)
        diff = str(change.get("diff") or change.get("unified_diff") or "")
        if diff:
            diffs.append(diff)
    label = paths[0] if len(paths) == 1 else (
        f"{len(paths)} files" if paths else "workspace files")
    return label, "\n".join(diffs)


def _last_user_text(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def _prior_history(messages: list[dict], limit: int = 24_000) -> str:
    rows = []
    seen_latest = False
    for message in reversed(messages):
        role = str(message.get("role") or "")
        if role == "user" and not seen_latest:
            seen_latest = True
            continue
        if role not in ("user", "assistant"):
            continue
        content = str(message.get("content") or "").strip()
        if content:
            rows.append(f"{role}: {content}")
    return "\n\n".join(reversed(rows))[-limit:]
