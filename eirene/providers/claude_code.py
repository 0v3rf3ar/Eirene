"""Claude subscription access through Claude Code's supported headless mode."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections import deque
from pathlib import Path
from typing import Any, AsyncIterator

from ..core.errors import (AuthError, ConnectionFailed, EireneError,
                           ProviderError)
from .base import ConnectionStatus
from ..core.subprocesses import executable_argv
from ..tools import activity
from .base import (Done, Event, PlanUpdate, Provider, ProviderTool, TextDelta,
                   ThinkingDelta, Usage)
from .permission_proxy import (APPROVE_TOOL, ASK_TOOL, SERVER,
                               PermissionBroker, describe_change)


class ClaudeCode(Provider):
    """Run agent turns through the authenticated Claude Code executable."""

    name = "claude-code"
    protocol = "claude-code-cli"
    supports_tools = False  # Claude Code owns its tools and permission policy.
    owns_context = True

    def __init__(self, *, timeout: float = 300.0, binary: str = "claude") -> None:
        super().__init__(None, "", timeout=timeout)
        self.binary = binary
        self.root = Path.cwd()
        self.mode = "manual"
        self._session_id = ""
        self._process: asyncio.subprocess.Process | None = None
        self._commands: dict[str, str] = {}
        self._running: dict[str, tuple[str, str]] = {}
        self._interrupted = False
        self.approve = None
        self.choose = None

    def set_context(self, root: Path, mode: str, approve=None, choose=None) -> None:
        resolved = root.resolve()
        if self._session_id and (self.mode != mode or self.root != resolved):
            self.reset_thread()
        self.root = resolved
        self.mode = mode
        self.approve = approve
        self.choose = choose

    def _executable(self) -> str:
        executable = shutil.which(self.binary)
        if not executable:
            raise ConnectionFailed("Claude Code", "install `claude` and put it on PATH")
        return executable

    async def account(self) -> dict[str, Any] | None:
        process = await asyncio.create_subprocess_exec(
            *executable_argv(self._executable(), "auth", "status", "--json"),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(self.root))
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), 20)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise ProviderError("Claude Code authentication check timed out") from exc
        if process.returncode:
            detail = stderr.decode(errors="replace").strip()
            if "not logged" in detail.lower() or "auth" in detail.lower():
                return None
            raise ConnectionFailed("Claude Code", detail or "authentication check failed")
        try:
            status = json.loads(stdout)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderError("Claude Code returned an invalid authentication status") from exc
        if not status.get("loggedIn"):
            return None
        return status

    async def models(self) -> list[str]:
        # Claude Code officially supports stable aliases; availability is plan-specific.
        return ["sonnet", "opus", "haiku"]

    async def validate(self, model: str = "") -> str:
        account = await self.account()
        if not account:
            raise AuthError("not signed in; run `claude auth login`, then use /connect again")
        method = str(account.get("authMethod") or account.get("subscriptionType") or
                     "Claude account")
        return f"authenticated through {method}"

    async def stream(self, messages: list[dict], model: str, *, system: str = "",
                     tools: list[dict] | None = None,
                     max_tokens: int = 8192) -> AsyncIterator[Event]:
        self._interrupted = False
        prompt = _last_user_text(messages)
        first = not self._session_id
        if first:
            history = _prior_history(messages)
            if history:
                prompt = f"Prior Eirene conversation:\n{history}\n\nCurrent user request:\n{prompt}"

        native_windows = os.name == "nt"
        if native_windows and self.mode != "plan":
            reason = "Claude Code on native Windows has no kernel sandbox; this turn may run commands with your user account's filesystem and network access"
            if self.approve is None or await self.approve("native_execution", "Claude Code on Windows", "", reason) not in ("yes", "always"):
                raise ProviderError("Native Windows Claude Code execution needs approval; use WSL2 for sandboxed execution")
        gate = self.mode != "plan" and self.approve is not None
        asking = self.choose is not None
        broker = None
        args = ["-p", prompt, "--output-format", "stream-json",
                "--verbose", "--include-partial-messages", "--model", model,
                "--permission-mode", self._permission_mode(),
                "--settings", json.dumps({"sandbox": {"enabled": not native_windows,
                    "allowUnsandboxedCommands": native_windows, "failIfUnavailable": not native_windows}}),
                "--append-system-prompt", _system_prompt(system, asking)]
        if native_windows and self.mode == "plan":
            args.extend(["--disallowedTools", "Bash,PowerShell,Write,Edit,NotebookEdit"])
        if gate or asking:
            broker = PermissionBroker(self.root, self.approve if gate else None,
                                      self.choose if asking else None,
                                      "deny" if self.mode == "plan" else "allow")
            await broker.start()
            command, permission_args, environment = broker.command()
            server: dict[str, Any] = {"type": "stdio", "command": command,
                                      "args": permission_args}
            if environment:
                server["env"] = environment
            config = {"mcpServers": {SERVER: server}}
            args.extend(["--mcp-config", json.dumps(config),
                         "--permission-prompt-tool", APPROVE_TOOL])
        if self._session_id:
            args.extend(["--resume", self._session_id])

        try:
            self._process = await asyncio.create_subprocess_exec(
                *executable_argv(self._executable(), *args), cwd=str(self.root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE)
        except OSError as exc:
            if broker is not None:
                await broker.close()
            raise ConnectionFailed("Claude Code", str(exc)) from exc
        process = self._process
        assert process.stdout is not None and process.stderr is not None
        stderr: deque[str] = deque(maxlen=30)

        async def drain_stderr() -> None:
            while line := await process.stderr.readline():
                stderr.append(line.decode(errors="replace"))

        stderr_task = asyncio.create_task(drain_stderr())
        saw_partial_text = False
        completed = False
        try:
            while True:
                try:
                    line = await asyncio.wait_for(process.stdout.readline(), self.timeout)
                except asyncio.TimeoutError as exc:
                    process.terminate()
                    raise ProviderError("Claude Code stopped sending events; turn outcome is unknown, inspect before continuing",
                                        retryable=False) from exc
                if not line:
                    break
                try:
                    event = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                session_id = str(event.get("session_id") or "")
                if session_id:
                    self._session_id = session_id
                kind = str(event.get("type") or "")
                if kind == "system" and event.get("subtype") == "api_retry":
                    attempt = event.get("attempt", "?")
                    delay_ms = event.get("retry_delay_ms", 0)
                    try:
                        delay = max(0, float(delay_ms)) / 1000
                    except (TypeError, ValueError):
                        delay = 0
                    yield ConnectionStatus(f"Claude Code reconnecting: attempt {attempt}, retry in {delay:.0f}s")
                elif kind == "stream_event":
                    delta = (event.get("event") or {}).get("delta") or {}
                    delta_type = str(delta.get("type") or "")
                    if delta_type == "text_delta":
                        saw_partial_text = True
                        yield TextDelta(str(delta.get("text") or ""))
                    elif delta_type in ("thinking_delta", "signature_delta"):
                        text = str(delta.get("thinking") or "")
                        if text:
                            yield ThinkingDelta(text)
                elif kind == "assistant":
                    message = event.get("message") or {}
                    for block in message.get("content") or []:
                        if not isinstance(block, dict):
                            continue
                        command = _command_from_tool(block)
                        tool_id = str(block.get("id") or "")
                        if command and tool_id and tool_id not in self._commands:
                            self._commands[tool_id] = activity.start_provider_command(
                                f"Claude Code: {command}", self._interrupt_turn)
                        if block.get("type") == "text" and not saw_partial_text:
                            yield TextDelta(str(block.get("text") or ""))
                        plan = _plan_from_tool(block)
                        if plan is not None:
                            yield plan
                        elif block.get("type") == "tool_use" and tool_id:
                            name = str(block.get("name") or "tool")
                            if name.startswith(f"mcp__{SERVER}__"):
                                continue  # Eirene's own bridge, not the model's work
                            label = _tool_label(name, block.get("input"), self.root)
                            self._running[tool_id] = (name, label)
                            # Read the file before the tool rewrites it.
                            yield ProviderTool(tool_id, name, label, _tool_kind(name),
                                               preview=_change_preview(
                                                   name, block.get("input"), self.root))
                    raw_usage = message.get("usage") or {}
                    if raw_usage:
                        yield Usage(int(raw_usage.get("input_tokens") or 0),
                                    int(raw_usage.get("output_tokens") or 0))
                elif kind == "user":
                    message = event.get("message") or {}
                    for block in message.get("content") or []:
                        if not isinstance(block, dict) or block.get("type") != "tool_result":
                            continue
                        tool_id = str(block.get("tool_use_id") or "")
                        command_id = self._commands.pop(tool_id, "")
                        if command_id:
                            activity.finish_provider_command(command_id)
                        name, label = self._running.pop(tool_id, ("", ""))
                        if name:
                            yield ProviderTool(tool_id, name, label, _tool_kind(name),
                                               _result_text(block.get("content")),
                                               True, bool(block.get("is_error")))
                elif kind == "result":
                    if event.get("is_error"):
                        raise ProviderError(str(event.get("result") or
                                                "Claude Code turn failed"))
                    completed = True
                    yield Done(str(event.get("subtype") or "stop"))
                    return
            await process.wait()
            if not completed:
                if self._interrupted:
                    yield Done("interrupted")
                    return
                detail = "".join(stderr).strip()[-800:]
                raise ProviderError(detail or
                                    f"Claude Code exited with status {process.returncode}")
        except asyncio.CancelledError:
            if process.returncode is None:
                process.terminate()
            raise
        finally:
            if process.returncode is None:
                process.terminate()
            await process.wait()
            if not stderr_task.done():
                stderr_task.cancel()
            for command_id in self._commands.values():
                activity.finish_provider_command(command_id)
            self._commands.clear()
            self._running.clear()
            self._process = None
            if broker is not None:
                await broker.close()

    async def _interrupt_turn(self) -> None:
        """Stop the Claude Code turn that owns a displayed command."""
        if self._process is not None and self._process.returncode is None:
            self._interrupted = True
            self._process.terminate()

    async def isolated_stream(self, messages: list[dict], model: str, *,
                              system: str = "", tools: list[dict] | None = None,
                              max_tokens: int = 8192) -> AsyncIterator[Event]:
        clone = ClaudeCode(timeout=self.timeout, binary=self.binary)
        clone.set_context(self.root, "plan")
        async for event in clone.stream(messages, model, system=system,
                                        tools=None, max_tokens=max_tokens):
            yield event

    def _permission_mode(self) -> str:
        return {"plan": "plan", "auto": "auto"}.get(self.mode, "manual")

    def reset_thread(self) -> None:
        self._session_id = ""

    async def close(self) -> None:
        if self._process is not None and self._process.returncode is None:
            self._process.terminate()
            await self._process.wait()
        self._process = None


ASK_GUIDANCE = (
    "When you need the user to decide something, call the "
    f"{ASK_TOOL} tool with two to five short options instead of "
    "ending your turn with a question. Their answer comes back as the tool result.")


def _system_prompt(system: str, asking: bool) -> str:
    if not asking:
        return system
    return f"{system}\n\n{ASK_GUIDANCE}" if system.strip() else ASK_GUIDANCE


READ_TOOLS = ("Read", "Grep", "Glob", "WebFetch", "WebSearch", "NotebookRead",
              "Task", "ToolSearch", "TaskOutput", "ListAgents")
WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
LABEL_KEYS = ("file_path", "path", "command", "pattern", "query", "url",
              "description", "prompt", "name")
RESULT_LIMIT = 20_000_000


CHANGE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")


def _change_preview(name: str, raw: Any, root: Path) -> str:
    """The diff a file-writing tool is about to apply, or empty."""
    if name not in CHANGE_TOOLS or not isinstance(raw, dict):
        return ""
    try:
        return describe_change(name, raw, root)[2]
    except (EireneError, OSError, ValueError):
        return ""


def _tool_kind(name: str) -> str:
    if name in WRITE_TOOLS:
        return "write"
    return "read" if name in READ_TOOLS else "exec"


def _tool_label(name: str, raw: Any, root: Path) -> str:
    """The one detail worth showing beside a Claude Code tool."""
    if not isinstance(raw, dict):
        return name
    for key in LABEL_KEYS:
        value = raw.get(key)
        if not value or not isinstance(value, str):
            continue
        text = " ".join(value.split())
        if key in ("file_path", "path"):
            try:
                text = str(Path(text).relative_to(root))
            except ValueError:
                pass
        return text[:10000 if key == "command" else 120]
    return name


def _result_text(content: Any) -> str:
    """Flatten a tool result into something a card can show."""
    if isinstance(content, str):
        return content[:RESULT_LIMIT]
    if isinstance(content, list):
        parts = [str(block.get("text") or "") for block in content
                 if isinstance(block, dict) and block.get("type") == "text"]
        return "\n".join(part for part in parts if part)[:RESULT_LIMIT]
    return ""


def _command_from_tool(block: dict[str, Any]) -> str:
    if block.get("type") != "tool_use" or block.get("name") not in (
            "Bash", "Shell", "run_command"):
        return ""
    raw = block.get("input") or {}
    if not isinstance(raw, dict):
        return ""
    return str(raw.get("command") or raw.get("cmd") or "").strip()


def _plan_from_tool(block: dict[str, Any]) -> PlanUpdate | None:
    if block.get("type") != "tool_use" or block.get("name") not in (
            "TodoWrite", "TaskCreate", "TaskUpdate"):
        return None
    raw = block.get("input") or {}
    todos = raw.get("todos") if isinstance(raw, dict) else None
    if not isinstance(todos, list):
        return None
    steps = []
    for todo in todos:
        if not isinstance(todo, dict):
            continue
        text = str(todo.get("content") or todo.get("subject") or "").strip()
        if text:
            status = str(todo.get("status") or "pending").replace("in_progress",
                                                                    "in_progress")
            steps.append({"text": text, "status": status})
    return PlanUpdate(steps) if steps else None


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
