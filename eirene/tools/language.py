"""Portable language diagnostics and bounded reference discovery."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import shlex
from pathlib import Path

from ..core.errors import ToolError
from .sandbox import Sandbox

MAX_OUTPUT = 80_000


async def diagnostics(box: Sandbox, path: str, timeout: float = 30, *,
                      isolation: str = "none", isolate_network: bool = True,
                      read_only: bool = False) -> str:
    target = box.resolve(path)
    if not target.is_file():
        raise ToolError(f"not a file: {path}")
    suffix = target.suffix.lower()
    if suffix == ".json":
        try:
            json.loads(target.read_text(encoding="utf-8"))
            return "no JSON syntax errors"
        except (OSError, json.JSONDecodeError) as exc:
            return str(exc)
    command = _diagnostic_command(target, suffix)
    if suffix == ".rs" and (box.root / "Cargo.toml").is_file() and shutil.which("cargo"):
        command = [shutil.which("cargo"), "check", "--offline", "--message-format=short",
                   "--target-dir", "/tmp/eirene-cargo-target"]
    if suffix == ".go" and (box.root / "go.mod").is_file() and shutil.which("go"):
        command = [shutil.which("go"), "test", "-run", "^$", "./..."]
    if suffix in {".ts", ".tsx"} and (box.root / "tsconfig.json").is_file():
        compiler = box.root / "node_modules" / ".bin" / "tsc"
        executable = str(compiler) if compiler.exists() else shutil.which("tsc")
        command = [executable, "--noEmit", "--pretty", "false", "--project", str(box.root / "tsconfig.json")] if executable else None
    if (isolation != "none" or read_only) and command is not None:
        from . import shell
        result = await shell.run(shlex.join(command), box.root, timeout=timeout,
                                 isolation=isolation, isolate_network=isolate_network,
                                 read_only=read_only)
        return result.output.strip() or ("no syntax diagnostics" if result.ok else result.summary())
    if command is None:
        raise ToolError(f"no installed diagnostic engine supports {suffix or 'this file'}")
    process = await asyncio.create_subprocess_exec(
        *command, cwd=str(box.root), stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT)
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise ToolError("language diagnostics timed out") from exc
    output = stdout.decode("utf-8", "replace").strip()
    if not output and process.returncode == 0:
        return "no syntax diagnostics"
    return (output or f"diagnostic engine exited {process.returncode}")[:MAX_OUTPUT]


def references(box: Sandbox, symbol: str, path: str = ".", limit: int = 100) -> str:
    """Find identifier references while excluding common generated trees."""
    name = str(symbol or "").strip()
    if not re.fullmatch(r"[A-Za-z_$][\w$]*", name):
        raise ToolError("symbol must be one identifier")
    root = box.resolve(path)
    if not root.exists():
        raise ToolError(f"path does not exist: {path}")
    cap = max(1, min(int(limit), 500))
    rg = shutil.which("rg")
    if not rg:
        raise ToolError("find_references requires ripgrep (`rg`)")
    command = [rg, "--line-number", "--column", "--no-heading", "--color", "never",
               "--glob", "!.git/**", "--glob", "!node_modules/**",
               "--glob", "!build/**", "--glob", "!dist/**", "--glob", "!target/**",
               rf"\b{re.escape(name)}\b", str(root)]
    try:
        result = subprocess.run(command, cwd=box.root, capture_output=True, text=True,
                                timeout=20, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ToolError("reference search timed out") from exc
    rows = result.stdout.splitlines()
    if not rows:
        return f"no references to {name}"
    shown = rows[:cap]
    suffix = f"\n… {len(rows) - cap} more" if len(rows) > cap else ""
    return "\n".join(shown) + suffix


def _diagnostic_command(path: Path, suffix: str) -> list[str] | None:
    if suffix == ".py":
        python = shutil.which("python3") or shutil.which("python")
        code = ("import pathlib,sys; p=pathlib.Path(sys.argv[1]); "
                "compile(p.read_text(encoding='utf-8'),str(p),'exec')")
        return [python, "-c", code, str(path)] if python else None
    if suffix in {".js", ".mjs", ".cjs"}:
        node = shutil.which("node")
        return [node, "--check", str(path)] if node else None
    if suffix in {".ts", ".tsx"}:
        tsc = shutil.which("tsc")
        return [tsc, "--noEmit", "--pretty", "false", str(path)] if tsc else None
    if suffix in {".c", ".h", ".cc", ".cpp", ".hpp"}:
        compiler = shutil.which("clang") or shutil.which("gcc")
        return [compiler, "-fsyntax-only", str(path)] if compiler else None
    if suffix == ".go":
        go = shutil.which("gofmt")
        return [go, "-e", str(path)] if go else None
    if suffix == ".rs":
        rustc = shutil.which("rustc")
        return [rustc, "--emit=metadata", "-o", os.devnull, str(path)] if rustc else None
    return None
