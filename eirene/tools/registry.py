"""Tool schemas and dispatch."""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..core.errors import SandboxError, ToolError
from . import browser, files, language, shell, processes, patches
from ..core import git as git_ops
from ..core import project as project_ops
from ..core import skills as skill_ops
from ..core import plans as plan_ops
from .sandbox import Sandbox

READ = "read"
WRITE = "write"
EXEC = "exec"
ASK = "ask"

CHAT_OPTION = "__chat__"


@dataclass
class Tool:
    """One callable exposed to the model."""

    name: str
    kind: str
    description: str
    schema: dict[str, Any]
    icon: str = ""


TOOLS: list[Tool] = [
    Tool("read_file", READ, "Check file size and read bounded text with line numbers; use pattern/context, tail, or offset/limit to focus. Oversized lines support byte_offset continuation.", {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path, relative to the sandbox."},
            "offset": {"type": "integer", "description": "First line to read, 0-based."},
            "limit": {"type": "integer", "description": "Max lines to read."},
            "tail": {"type": "boolean", "description": "Read the last limit lines."},
            "pattern": {"type": "string", "description": "Regex to select matching lines (grep-style)."},
            "context": {"type": "integer", "description": "Neighboring lines around matches; default 2."},
            "byte_offset": {"type": "integer", "description": "Continue an oversized physical line at this byte position."},
        },
        "required": ["path"],
    }, ""),
    Tool("read_image", READ,
         "View an image from the sandbox. Use when you support vision and need to inspect pixels.", {
             "type": "object",
             "properties": {
                 "path": {"type": "string", "description": "PNG, JPEG, GIF or WebP path."},
             },
             "required": ["path"],
         }, ""),
    Tool("write_file", WRITE, "Create or overwrite a file.", {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path, relative to the sandbox."},
            "content": {"type": "string", "description": "Full file contents."},
        },
        "required": ["path", "content"],
    }, ""),
    Tool("edit_file", WRITE, "Replace exact text in an existing file.", {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_string": {"type": "string", "description": "Exact text to replace."},
            "new_string": {"type": "string", "description": "Replacement text."},
            "replace_all": {"type": "boolean", "description": "Replace every occurrence."},
        },
        "required": ["path", "old_string", "new_string"],
    }, ""),
    Tool("list_dir", READ, "List the entries of a directory.", {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Defaults to the sandbox root."}},
    }, ""),
    Tool("glob", READ, "Find files by glob pattern, newest first.", {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "e.g. '**/*.py'"},
            "path": {"type": "string", "description": "Directory to search from."},
        },
        "required": ["pattern"],
    }, ""),
    Tool("run_command", EXEC,
         "Run a bounded, non-interactive shell command. Long commands return a managed process id; poll it instead of restarting.", {
             "type": "object",
             "properties": {
                 "command": {"type": "string", "description": "Command line to execute."},
                 "timeout": {"type": "integer",
                             "description": "Total time limit in seconds, including background work. Defaults adapt to the command; maximum 3600."},
                 "stdin": {"type": "string", "description": "Optional exact input text; stdin closes after sending it."},
                 "powershell": {"type": "boolean",
                                "description": "Use PowerShell instead of cmd on Windows."},
                 "pty": {"type": "boolean",
                         "description": "Run with terminal emulation when a command requires a TTY."},
             },
             "required": ["command"],
         }, ""),
    Tool("ask_user", ASK,
         "Ask the user to choose between options. Use this instead of ending "
         "your turn with a question, so they can answer with one key.", {
             "type": "object",
             "properties": {
                 "question": {"type": "string",
                              "description": "What you need decided, in one line."},
                 "options": {
                     "type": "array",
                     "items": {"type": "string"},
                     "description": "Two to five short answers to choose from.",
                 },
             },
             "required": ["question", "options"],
    }, ""),
    Tool("git_status", READ, "Show repository branch and working-tree state.", {
        "type": "object", "properties": {},
    }),
    Tool("git_diff", READ, "Show staged and unstaged Git changes.", {
        "type": "object", "properties": {
            "path": {"type": "string", "description": "Optional repository-relative path."},
        },
    }),
    Tool("git_diff_base", READ, "Show all changes against a Git base revision.", {
        "type": "object", "properties": {"base": {"type": "string"}},
        "required": ["base"],
    }),
    Tool("git_checkpoint", WRITE,
         "Create a recoverable snapshot of all current Git working-tree changes.", {
             "type": "object", "properties": {
                 "label": {"type": "string", "description": "Short reason for the checkpoint."},
             },
         }),
    Tool("git_checkpoints", READ, "List recoverable checkpoints for this repository.", {
        "type": "object", "properties": {},
    }),
    Tool("git_rollback", WRITE, "Restore a prior Eirene Git checkpoint.", {
        "type": "object", "properties": {
            "checkpoint_id": {"type": "string"},
        }, "required": ["checkpoint_id"],
    }),
    Tool("git_commit", WRITE,
         "Commit only explicitly named paths; never stages unrelated changes.", {
             "type": "object", "properties": {
                 "message": {"type": "string"},
                 "paths": {"type": "array", "items": {"type": "string"}},
             }, "required": ["message", "paths"],
         }),
    Tool("git_worktree_create", WRITE,
         "Create an isolated Git worktree inside the repository.", {
             "type": "object", "properties": {
                 "path": {"type": "string"}, "branch": {"type": "string"},
             }, "required": ["path"],
         }),
    Tool("git_worktree_remove", WRITE, "Remove a registered Git worktree.", {
        "type": "object", "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }),
    Tool("start_process", EXEC,
         "Start a long-running process and return a managed process id.", {
             "type": "object", "properties": {
                 "command": {"type": "string"},
                 "pty": {"type": "boolean", "description": "Use terminal emulation."},
                 "auto_stop": {"type": "integer",
                               "description": "Seconds before automatic termination; defaults to 3600."},
             }, "required": ["command"],
         }),
    Tool("poll_process", READ, "Read output and state from a managed process.", {
        "type": "object", "properties": {
            "process_id": {"type": "string"},
            "all_output": {"type": "boolean"},
        }, "required": ["process_id"],
    }),
    Tool("list_processes", READ, "List managed processes and their state.", {
        "type": "object", "properties": {},
    }),
    Tool("stop_process", EXEC, "Stop a managed process and its child processes.", {
        "type": "object", "properties": {
            "process_id": {"type": "string"},
        }, "required": ["process_id"],
    }),
    Tool("project_info", READ,
         "Show detected project languages, manifests, instructions and verification commands.", {
             "type": "object", "properties": {
                 "refresh": {"type": "boolean"},
             },
         }),
    Tool("search_text", READ, "Search project text with a regular expression.", {
        "type": "object", "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string", "description": "Directory to search from."},
            "glob": {"type": "string", "description": "Optional file glob such as '*.py'."},
            "limit": {"type": "integer", "description": "Maximum matches, up to 500."},
        }, "required": ["pattern"],
    }),
    Tool("find_symbol", READ, "Find definitions of an exact code symbol.", {
        "type": "object", "properties": {
            "name": {"type": "string"}, "path": {"type": "string"},
            "limit": {"type": "integer"},
        }, "required": ["name"],
    }),
    Tool("find_references", READ,
         "Find bounded whole-identifier references across source files.", {
             "type": "object", "properties": {
                 "symbol": {"type": "string"},
                 "path": {"type": "string", "description": "File or directory; default '.'."},
                 "limit": {"type": "integer", "description": "Maximum matches, up to 500."},
             }, "required": ["symbol"],
         }),
    Tool("language_diagnostics", READ,
         "Run the installed parser/compiler's fast syntax diagnostics for one source file.", {
             "type": "object", "properties": {
                 "path": {"type": "string"},
                 "timeout": {"type": "integer"},
             }, "required": ["path"],
         }),
    Tool("browser_inspect", EXEC,
         "Render a URL with headless Chromium and return the post-JavaScript DOM. "
         "Use for frontend inspection, browser-only pages, and web research.", {
             "type": "object", "properties": {
                 "url": {"type": "string"},
                 "timeout": {"type": "integer", "description": "Seconds, default 30."},
             }, "required": ["url"],
         }),
    Tool("browser_interact", EXEC,
         "Batch up to 25 actions in one ephemeral headless Chromium page. Supports "
         "navigate, click, type, wait, evaluate JavaScript, DOM, and visible text.", {
             "type": "object", "properties": {
                 "url": {"type": "string"},
                 "actions": {"type": "array", "maxItems": 25, "items": {
                     "type": "object", "properties": {
                         "action": {"type": "string", "enum": [
                             "navigate", "click", "type", "wait", "evaluate", "dom", "text"]},
                         "url": {"type": "string"}, "selector": {"type": "string"},
                         "text": {"type": "string"}, "expression": {"type": "string"},
                         "milliseconds": {"type": "integer"}},
                     "required": ["action"]}},
                 "timeout": {"type": "integer"},
             }, "required": ["url", "actions"],
         }),
    Tool("web_search", READ,
         "Search the web and return a small set of titles, URLs, and snippets. Use "
         "for current or unfamiliar facts; make one precise query.", {
             "type": "object", "properties": {
                 "query": {"type": "string"},
                 "limit": {"type": "integer", "description": "Results, 1-8; default 5."},
             }, "required": ["query"],
         }),
    Tool("web_fetch", READ,
         "Read compact text from one web-search result URL. Fetch only the most "
         "relevant source and cite its URL in the answer.", {
             "type": "object", "properties": {
                 "url": {"type": "string"},
                 "timeout": {"type": "integer", "description": "Seconds, default 20."},
             }, "required": ["url"],
         }),
    Tool("browser_screenshot", WRITE,
         "Render a URL with headless Chromium and save a PNG in the sandbox; call "
         "read_image afterward to visually review it.", {
             "type": "object", "properties": {
                 "url": {"type": "string"}, "path": {"type": "string"},
                 "width": {"type": "integer"}, "height": {"type": "integer"},
                 "timeout": {"type": "integer"},
             }, "required": ["url", "path"],
         }),
    Tool("http_request", EXEC,
         "Send an explicit bounded HTTP request when the user asks to call an endpoint.", {
             "type": "object", "properties": {
                 "method": {"type": "string"}, "url": {"type": "string"},
                 "headers": {"type": "object", "additionalProperties": {"type": "string"}},
                 "body": {"type": "string"}, "timeout": {"type": "integer"},
             }, "required": ["method", "url"],
         }),
    Tool("load_skill", READ,
         "Load one relevant Markdown skill by its catalogue name.", {
             "type": "object", "properties": {"name": {"type": "string"}},
             "required": ["name"],
         }),
    Tool("plan_show", READ, "Show the durable plan for this session.", {
        "type": "object", "properties": {},
    }),
    Tool("plan_update", READ, "Create or replace the durable session plan metadata.", {
        "type": "object", "properties": {
            "objective": {"type": "string"},
            "steps": {"type": "array", "items": {"type": "object", "properties": {
                "text": {"type": "string"},
                "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "blocked"]},
                "verification": {"type": "string"}}, "required": ["text"]}},
            "notes": {"type": "string"},
        }, "required": ["objective", "steps"],
    }),
    Tool("plan_set_status", READ, "Update one durable session plan step's status.", {
        "type": "object", "properties": {
            "index": {"type": "integer"},
            "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "blocked"]},
        }, "required": ["index", "status"],
    }),
    Tool("plan_clear", READ, "Clear the durable session plan metadata.", {
        "type": "object", "properties": {},
    }),
    Tool("apply_patch", WRITE,
         "Atomically validate and apply a unified patch, including multiple files.", {
             "type": "object", "properties": {
                 "patch": {"type": "string"},
             }, "required": ["patch"],
         }),
]

BY_NAME = {tool.name: tool for tool in TOOLS}

for _name in ("run_command", "start_process"):
    BY_NAME[_name].schema["properties"].update({
        "read_paths": {"type": "array", "items": {"type": "string"},
                       "description": "Existing external paths to mount read-only; requires approval."},
        "write_paths": {"type": "array", "items": {"type": "string"},
                        "description": "Existing external directories/files to mount writable; requires approval."},
        "network_access": {"type": "boolean", "description": "Request network access for this command; requires approval."},
    })

_output_tool = Tool("read_output", READ, "Read a saved tool output artifact by ID and byte offset.", {
    "type": "object", "properties": {"artifact_id": {"type": "string"},
    "offset": {"type": "integer"}, "limit": {"type": "integer"}}, "required": ["artifact_id"]})
TOOLS.append(_output_tool)
BY_NAME[_output_tool.name] = _output_tool


BY_NAME["start_process"].schema["properties"]["powershell"] = {
    "type": "boolean", "description": "Use PowerShell instead of cmd on Windows."}


def specs(include_exec: bool = True) -> list[dict[str, Any]]:
    """Schemas in provider-neutral form."""
    return [{"name": t.name, "description": t.description, "parameters": t.schema}
            for t in TOOLS if include_exec or t.kind != EXEC]


def harmless(name: str, args: dict[str, Any]) -> bool:
    """True when a call cannot change anything."""
    if name == "ask_user":
        return True
    if name in {"web_search", "web_fetch"}:
        # They are read-only and valid in plan mode, but manual mode should still
        # disclose that a query or URL is about to leave the machine.
        return False
    if name == "run_command":
        return shell.is_safe(str(args.get("command", "")))
    return kind_of(name) == READ


def kind_of(name: str) -> str:
    tool = BY_NAME.get(name)
    return tool.kind if tool else EXEC


def validate_arguments(name: str, arguments: dict) -> None:
    """Reject malformed model calls before previews, permissions or execution."""
    tool = BY_NAME.get(name)
    if tool is None:
        raise ToolError(f"unknown tool '{name}'")
    if not isinstance(arguments, dict):
        raise ToolError("arguments must be an object")
    for key in tool.schema.get("required", []):
        if key not in arguments:
            raise ToolError(f"{name}: {key} is required")
    types = {"string": str, "integer": int, "number": (int, float),
             "boolean": bool, "array": list, "object": dict}
    for key, value in arguments.items():
        schema = tool.schema.get("properties", {}).get(key, {})
        expected = schema.get("type")
        if expected in types and (not isinstance(value, types[expected]) or
                                  (expected in {"integer", "number"} and isinstance(value, bool))):
            raise ToolError(f"{name}: {key} must be {expected}")
        if expected in {"integer", "number"} and not math.isfinite(value):
            raise ToolError(f"{name}: {key} must be finite")
        item_type = schema.get("items", {}).get("type")
        if expected == "array" and item_type in types and any(not isinstance(item, types[item_type]) for item in value):
            raise ToolError(f"{name}: {key} must contain {item_type} values")


def describe(name: str, args: dict[str, Any], box: Sandbox) -> str:
    """One-line human summary of a call."""
    if name == "run_command":
        return str(args.get("command", "")).strip() or "(empty)"
    if name == "web_search":
        return str(args.get("query", "")).strip() or "(empty search)"
    if name in {"web_fetch", "browser_inspect", "browser_interact"}:
        return str(args.get("url", "")).strip() or "(empty URL)"
    if name == "browser_screenshot":
        url = str(args.get("url", "")).strip() or "(empty URL)"
        path = str(args.get("path", "")).strip() or "(no path)"
        return f"{url} → {path}"
    if name == "http_request":
        method = str(args.get("method", "GET")).strip().upper() or "GET"
        url = str(args.get("url", "")).strip() or "(empty URL)"
        return f"{method} {url}"
    path = str(args.get("path", "") or args.get("pattern", ""))
    if name == "glob":
        where = args.get("path") or "."
        return f"{args.get('pattern', '')} in {where}"
    if not path:
        return name
    try:
        return box.relative(box.resolve(path))
    except SandboxError:
        return path


async def execute(name: str, args: dict[str, Any], box: Sandbox, *,
                  timeout: float | None = None, max_bytes: int = 200_000,
                  on_output: Callable[[str], None] | None = None,
                  isolation: str = "none", isolate_network: bool = False,
                  plan_scope: str | None = None, read_only: bool = False) -> str:
    with git_ops.execution_policy(backend=isolation, network=not isolate_network,
                                  read_only=read_only):
        return await _execute(name, args, box, timeout=timeout, max_bytes=max_bytes,
                              on_output=on_output, isolation=isolation,
                              isolate_network=isolate_network, plan_scope=plan_scope,
                              read_only=read_only)


async def _execute(name: str, args: dict[str, Any], box: Sandbox, *,
                  timeout=None, max_bytes=200_000, on_output=None, isolation="none",
                  isolate_network=False, plan_scope=None, read_only=False) -> str:
    """Run a tool call and return its text result."""
    if name not in BY_NAME:
        raise ToolError(f"unknown tool '{name}'")
    if not isinstance(args, dict):
        raise ToolError("arguments must be an object")

    if name == "ask_user":
        return str(args.get("question", "")).strip() or "a question"
    if name == "read_output":
        from ..core import artifacts
        try:
            return artifacts.read(_text(args, "artifact_id"), int(args.get("offset", 0)),
                                  int(args.get("limit", 50000)))
        except (ValueError, OSError) as exc:
            raise ToolError(f"cannot read output: {exc}") from exc

    if name == "run_command":
        command = str(args.get("command", "")).strip()
        if not command:
            raise ToolError("command is empty")
        result = await shell.run(command, box.root,
                                 timeout=_number(args.get("timeout"), shell.command_timeout(command, timeout)),
                                 max_bytes=max_bytes, on_output=on_output,
                                 input_text=args.get("stdin"), yield_after=10,
                                 stall=0,
                                 powershell=bool(args.get("powershell")),
                                 pty=bool(args.get("pty")), isolation=isolation,
                                 isolate_network=isolate_network and not args.get("network_access", False),
                                 read_paths=args.get("read_paths", []), write_paths=args.get("write_paths", []),
                                 read_only=read_only)
        if result.refused:
            raise ToolError(result.refused)
        if not result.ok:
            raise ToolError(result.summary())
        return result.summary()

    if name == "start_process":
        return await processes.start(_text(args, "command"), box.root,
                                     powershell=bool(args.get("powershell")),
                                     pty=bool(args.get("pty")), isolation=isolation,
                                     isolate_network=isolate_network and not args.get("network_access", False),
                                     read_paths=args.get("read_paths", []), write_paths=args.get("write_paths", []),
                                     auto_stop=float(_number(args.get("auto_stop"), 0) or 0))
    if name == "poll_process":
        return await processes.poll(_text(args, "process_id"),
                                    all_output=bool(args.get("all_output")))
    if name == "list_processes":
        return processes.listing()
    if name == "stop_process":
        return await processes.stop(_text(args, "process_id"))
    if name == "project_info":
        return project_ops.describe(box.root, refresh=bool(args.get("refresh")))
    if name == "search_text":
        return files.search_text(box, _text(args, "pattern"),
                                 str(args.get("path") or "."),
                                 str(args.get("glob") or ""),
                                 int(_number(args.get("limit"), 100) or 100))
    if name == "find_symbol":
        return files.find_symbol(box, _text(args, "name"),
                                 str(args.get("path") or "."),
                                 int(_number(args.get("limit"), 100) or 100))
    if name == "find_references":
        return language.references(box, _text(args, "symbol"),
                                   str(args.get("path") or "."),
                                   int(_number(args.get("limit"), 100) or 100))
    if name == "language_diagnostics":
        return await language.diagnostics(
            box, _text(args, "path"),
            float(_number(args.get("timeout"), 30) or 30),
            isolation=isolation, isolate_network=isolate_network,
            read_only=read_only)
    if name == "browser_inspect":
        if isolate_network:
            raise ToolError("browser access is disabled by isolate_network")
        return await browser.inspect(_text(args, "url"),
                                     timeout=float(_number(args.get("timeout"), 30) or 30))
    if name == "browser_interact":
        if isolate_network:
            raise ToolError("browser access is disabled by isolate_network")
        actions = args.get("actions")
        if not isinstance(actions, list):
            raise ToolError("actions must be an array")
        return await browser.interact(
            _text(args, "url"), actions,
            timeout=float(_number(args.get("timeout"), 30) or 30))
    if name == "web_search":
        if isolate_network:
            raise ToolError("web search is disabled by isolate_network")
        return await browser.search(
            _text(args, "query"), limit=int(_number(args.get("limit"), 5) or 5))
    if name == "web_fetch":
        if isolate_network:
            raise ToolError("web access is disabled by isolate_network")
        return await browser.fetch_text(
            _text(args, "url"),
            timeout=float(_number(args.get("timeout"), 20) or 20))
    if name == "browser_screenshot":
        if isolate_network:
            raise ToolError("browser access is disabled by isolate_network")
        return await browser.screenshot(
            box, _text(args, "url"), _text(args, "path"),
            width=int(_number(args.get("width"), 1440) or 1440),
            height=int(_number(args.get("height"), 900) or 900),
            timeout=float(_number(args.get("timeout"), 30) or 30))
    if name == "http_request":
        if isolate_network:
            raise ToolError("HTTP access is disabled by isolate_network")
        raw_headers = args.get("headers") or {}
        if not isinstance(raw_headers, dict):
            raise ToolError("headers must be an object")
        return await browser.request(
            _text(args, "method"), _text(args, "url"), headers=raw_headers,
            body=str(args.get("body") or ""),
            timeout=float(_number(args.get("timeout"), 30) or 30))
    if name == "load_skill":
        wanted = _text(args, "name")
        skill = next((item for item in skill_ops.discover() if item.name == wanted), None)
        if skill is None:
            raise ToolError(f"no skill '{wanted}'")
        body = skill_ops.load(skill)
        return f"# Skill: {skill.title}\n{body}" if body else "skill is empty"
    if name == "plan_show":
        return plan_ops.load(box.root, plan_scope).render()
    if name == "plan_update":
        raw_steps = args.get("steps")
        if not isinstance(raw_steps, list):
            raise ToolError("steps must be an array")
        return plan_ops.update(box.root, str(args.get("objective") or ""), raw_steps,
                               str(args.get("notes") or ""), plan_scope)
    if name == "plan_set_status":
        return plan_ops.set_status(box.root, int(_number(args.get("index"), 0) or 0),
                                   _text(args, "status"), plan_scope)
    if name == "plan_clear":
        return plan_ops.clear(box.root, plan_scope)
    if name == "apply_patch":
        return patches.apply(box, _text(args, "patch"))

    if name.startswith("git_"):
        repo = git_ops.repository(box.root)
        if repo and repo != box.root:
            raise ToolError("Git repository extends outside workspace; use an approved shell mount of the repository root")
    if name == "git_status":
        return git_ops.status(box.root)
    if name == "git_diff":
        return git_ops.diff(box.root, str(args.get("path") or ""))
    if name == "git_diff_base":
        return git_ops.diff_against(box.root, _text(args, "base"))
    if name == "git_checkpoint":
        checkpoint_id = git_ops.checkpoint(box.root, str(args.get("label") or ""))
        return f"created checkpoint {checkpoint_id}"
    if name == "git_checkpoints":
        return git_ops.list_checkpoints(box.root)
    if name == "git_rollback":
        return git_ops.rollback(box.root, _text(args, "checkpoint_id"))
    if name == "git_commit":
        raw_paths = args.get("paths")
        if not isinstance(raw_paths, list):
            raise ToolError("paths must be an array")
        return git_ops.commit(box.root, _text(args, "message"),
                              [str(path) for path in raw_paths])
    if name == "git_worktree_create":
        return git_ops.create_worktree(box.root, _text(args, "path"),
                                       str(args.get("branch") or ""))
    if name == "git_worktree_remove":
        return git_ops.remove_worktree(box.root, _text(args, "path"))

    return _run_file_tool(name, args, box, max_chars=min(24000, max_bytes))


def _run_file_tool(name: str, args: dict[str, Any], box: Sandbox, *, max_chars: int = 24000) -> str:
    if name == "read_file":
        scoped = project_ops.scoped_instructions(box.root, box.resolve(_text(args, "path")))
        allowance = max(0, max_chars - len(scoped) - (2 if scoped else 0))
        body = files.read_file(box, _text(args, "path"),
                               int(_number(args.get("offset"), 0) or 0),
                               int(_number(args.get("limit"), 0) or 0),
                               max_chars=allowance, tail=bool(args.get("tail")),
                               pattern=str(args.get("pattern") or ""),
                               context=int(_number(args.get("context"), 2)),
                               byte_offset=args.get("byte_offset"))
        return body + ("\n\n" + scoped if scoped else "")
    if name == "read_image":
        from ..core.attachments import prepare_image
        prepare_image(box, _text(args, "path"))
        return f"loaded {box.relative(box.resolve(_text(args, 'path')))} for vision"
    if name == "write_file":
        content = args.get("content")
        if content is None:
            raise ToolError("content is required")
        return files.write_file(box, _text(args, "path"), str(content))
    if name == "edit_file":
        return files.edit_file(box, _text(args, "path"), str(args.get("old_string", "")),
                               str(args.get("new_string", "")),
                               bool(args.get("replace_all")))
    if name == "list_dir":
        return files.list_dir(box, str(args.get("path") or "."))
    if name == "glob":
        return files.glob_files(box, _text(args, "pattern"), str(args.get("path") or "."))
    raise ToolError(f"unknown tool '{name}'")


def _text(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if value is None or str(value).strip() == "":
        raise ToolError(f"{key} is required")
    return str(value)


def _number(value: Any, fallback: float | None) -> float | None:
    try:
        if value is None:
            return fallback
        return float(value)
    except (TypeError, ValueError):
        return fallback


def touched_path(name: str, args: dict[str, Any]) -> str | None:
    """Path a call would modify, if any."""
    if name in ("write_file", "edit_file", "browser_screenshot"):
        value = args.get("path")
        return str(value) if value else None
    return None


def escape_paths(name: str, args: dict[str, Any]) -> list[str]:
    """Paths a call needs outside the root, mirroring sandbox_escape."""
    if name in ("run_command", "start_process"):
        return [str(p) for key in ("read_paths", "write_paths") for p in args.get(key, [])]
    if name == "apply_patch":
        return [patches._name(c.new if c.new != "/dev/null" else c.old)
                for c in patches.parse(str(args.get("patch", "")))]
    value = args.get("path")
    return [str(value)] if value else []


def preview(name: str, args: dict[str, Any], box: Sandbox) -> str:
    """Diff or command preview for approval."""
    if name == "write_file":
        try:
            return files.diff_preview(box, str(args.get("path", "")),
                                      str(args.get("content", "")))
        except Exception:
            return ""
    if name == "edit_file":
        try:
            return files.edit_preview(box, str(args.get("path", "")),
                                      str(args.get("old_string", "")),
                                      str(args.get("new_string", "")),
                                      bool(args.get("replace_all")))
        except Exception:  # noqa: BLE001
            return ""
    if name == "run_command":
        return str(args.get("command", ""))
    if name == "apply_patch":
        patch = str(args.get("patch", ""))
        return patch[:200_000] + ("\n… patch preview truncated" if len(patch) > 200_000 else "")
    return ""


def sandbox_escape(name: str, args: dict[str, Any], box: Sandbox) -> str:
    """Reason a call leaves the sandbox, or empty."""
    if name in ("run_command", "start_process"):
        for key in ("read_paths", "write_paths"):
            if not isinstance(args.get(key, []), list) or any(not isinstance(p, str) for p in args.get(key, [])):
                raise ToolError(f"{key} must be an array of paths")
        requests = []
        if args.get("read_paths"):
            requests.append("read mounts: " + ", ".join(args["read_paths"]))
        if args.get("write_paths"):
            requests.append("write mounts: " + ", ".join(args["write_paths"]))
        if args.get("network_access"):
            requests.append("network access")
        if requests:
            return "requesting " + "; ".join(requests)
    if name == "apply_patch":
        outside = [p for p in escape_paths(name, args) if not box.contains(p)]
        if outside:
            return "patch outside workspace: " + ", ".join(outside)
    for key in ("path",):
        value = args.get(key)
        if value and not box.contains(str(value)):
            return f"{value} is outside {box.root}"
    if name in ("run_command", "start_process"):
        return _command_escape(str(args.get("command", "")), box)
    return ""


DANGEROUS = ("rm -rf /", "rm -fr /", ":(){", "mkfs", "dd if=", "> /dev/sd",
             "shutdown", "reboot", "format c:", "del /f /s /q c:\\")

MUTATING = {"rm", "rmdir", "mv", "cp", "chmod", "chown", "chgrp", "ln", "dd", "tee",
            "truncate", "install", "mkdir", "touch", "shred", "sed", "systemctl",
            "launchctl", "schtasks", "apt", "apt-get", "dnf", "yum", "pacman",
            "brew", "npm", "pip", "pip3", "cargo", "go", "make", "git"}


def _command_escape(command: str, box: Sandbox) -> str:
    lowered = command.lower()
    for pattern in DANGEROUS:
        if pattern in lowered:
            return f"contains '{pattern.strip()}'"
    if "$(" in command or "`" in command:
        return "uses indirect shell command expansion that cannot be preflighted"
    if "\n" in command or "\r" in command:
        return "contains multiple shell lines that require explicit approval"
    tokens = command.replace(">>", " > ").replace(">", " > ").split()
    verbs = {Path(t.strip("'\"")).name for t in tokens}
    mutating = bool(verbs & MUTATING)
    for index, token in enumerate(tokens):
        stripped = token.strip("'\"")
        if not stripped.startswith("/") or stripped.startswith("//"):
            continue
        redirect = index > 0 and tokens[index - 1] == ">"
        if not (mutating or redirect):
            continue
        if not box.contains(stripped):
            return f"touches {stripped}, outside {box.root}"
    return ""
