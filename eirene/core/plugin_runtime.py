"""Provider-independent lifecycle hooks with explicit executable trust."""
from __future__ import annotations
from .permissions import isolation, isolate_network

import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

from . import paths, plugins
from .errors import ToolError
from .logging import get as get_logger
from ..tools import shell


class PluginRuntime:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.started: set[str] = set()
        self.context: dict[tuple[str, str], str] = {}
        self.ponytail_mode: str | None = None
        # Hooks that failed this session. A broken optional hook costs its timeout once,
        # not on every prompt; asking for it by name (/ponytail) still retries it.
        self.failed: set[tuple[str, str]] = set()

    def _skip(self, name: str, event: str, reason: str) -> str:
        """A hook that breaks is the plugin's problem; the turn goes on without it."""
        self.failed.add((name, event))
        reason = " ".join(reason.split())
        reason = reason if len(reason) <= 300 else reason[:300] + "…"
        get_logger().warning("plugin.hook_failed", extra={"plugin": name, "hook_event": event, "error": reason})
        return f"{name}: {event} hook skipped for this session: {reason}"

    def block(self, config) -> str:
        parts = [text for (name, _), text in self.context.items()
                 if config.plugin_active(name)]
        return ("Plugin lifecycle instructions (latest mode changes override earlier defaults):\n" +
                "\n\n".join(parts)) if parts else ""

    async def submit(self, prompt, sandbox, config, *, plan=False, only=None):
        if plan:
            return []
        notices = []
        enabled = {p.name for p in plugins.discover()
                   if config.plugin_active(p.name)}
        self.started.intersection_update(enabled)
        if "ponytail" not in enabled:
            self.ponytail_mode = None
        for key in list(self.context):
            if key[0] not in enabled:
                del self.context[key]
        for plugin in plugins.discover():
            if plugin.name not in enabled or (only is not None and plugin.name != only):
                continue
            events = ["UserPromptSubmit"]
            if plugin.name not in self.started or (only and (plugin.name, "SessionStart") in self.failed):
                events.insert(0, "SessionStart")
            for event in events:
                if event == "UserPromptSubmit":
                    self.context.pop((plugin.name, event), None)
                if only is None and (plugin.name, event) in self.failed:
                    continue
                outputs = []
                for hook in plugin.lifecycle.get(event, []):
                    if event == "SessionStart" and not re.search(hook.get("matcher") or ".*", "startup"):
                        continue
                    data = paths.home() / "plugin-data" / plugin.name / self.session_id
                    settings = paths.home() / "plugin-data" / plugin.name / "config"
                    env = {"CLAUDE_PLUGIN_ROOT": str(plugin.path),
                           "CODEX_PLUGIN_ROOT": str(plugin.path), "PLUGIN_ROOT": str(plugin.path),
                           "PLUGIN_DATA": str(data), "CLAUDE_PLUGIN_DATA": str(data),
                           "XDG_CONFIG_HOME": str(settings),
                           "EIRENE_SESSION_ID": self.session_id}
                    if plugin.name == "ponytail" and "PONYTAIL_DEFAULT_MODE" in os.environ:
                        env["PONYTAIL_DEFAULT_MODE"] = os.environ["PONYTAIL_DEFAULT_MODE"]
                    command = hook["command"]
                    if shell.IS_WINDOWS:
                        for key in env:
                            command = command.replace("${" + key + "}", "%" + key + "%")
                    # Hooks are written for cmd on Windows (%VAR% above, .cmd wrappers);
                    # the default shell there is PowerShell, which expands neither.
                    try:
                        data.mkdir(parents=True, exist_ok=True)
                        settings.mkdir(parents=True, exist_ok=True)
                        result = await shell.run(
                            command, sandbox.root,
                            shell_name="cmd" if shell.IS_WINDOWS else "auto",
                            timeout=hook.get("timeout", 30), max_bytes=60_000,
                            env=env, input_text=json.dumps({"session_id": self.session_id,
                                "cwd": str(sandbox.root), "hook_event_name": event,
                                "source": "startup", "prompt": prompt}),
                            isolation=isolation(config),
                            isolate_network=isolate_network(config),
                            read_paths=[str(plugin.path), *tool_dirs(command)],
                            write_paths=[str(data), str(settings)])
                    except (ToolError, OSError) as exc:
                        notices.append(self._skip(plugin.name, event, str(exc)))
                        break
                    if not result.ok:
                        # Exit 2 is how a prompt hook refuses a prompt on purpose; any
                        # other failure is the hook breaking, not a decision.
                        if event == "UserPromptSubmit" and result.exit_code == 2:
                            raise ToolError(f"{plugin.name} blocked this prompt: {result.summary()}")
                        notices.append(self._skip(plugin.name, event, result.summary()))
                        break
                    self.failed.discard((plugin.name, event))
                    context, notice = parse_output(result.output)
                    if context:
                        outputs.append(context)
                    if notice:
                        notices.append(f"{plugin.name}: {notice}")
                if outputs:
                    self.context[plugin.name, event] = "\n".join(outputs)
                if event == "SessionStart":
                    self.started.add(plugin.name)
            # Ponytail's tracker emits a mode confirmation, not a fresh ruleset.
            # Read its session-local state and use the upstream rule generator so
            # off/ultra do not retain the startup full-mode instructions.
            if plugin.name == "ponytail" and (plugin.path / "hooks/ponytail-instructions.js").is_file():
                state = paths.home() / "plugin-data" / plugin.name / self.session_id
                try:
                    mode = (state / ".ponytail-active").read_text().strip()
                except OSError:
                    mode = "off"
                if mode not in {"lite", "full", "ultra", "review", "off"}:
                    notices.append(self._skip(plugin.name, "mode", f"invalid mode {mode[:40]!r}"))
                    continue
                if mode != self.ponytail_mode and (only is not None or (plugin.name, "rules") not in self.failed):
                    if mode == "off":
                        rules = "Ponytail mode is OFF. Do not apply Ponytail rules until the user enables it again."
                    else:
                        script = ("process.stdout.write(require(process.env.PLUGIN_ROOT + "
                                  "'/hooks/ponytail-instructions.js').getPonytailInstructions("
                                  "process.env.EIRENE_PONYTAIL_MODE))")
                        argv = [shutil.which("node") or "node", "-e", script]
                        # Launch node directly so no shell's quoting rules apply.
                        try:
                            result = await shell.run(
                                subprocess.list2cmdline(argv) if shell.IS_WINDOWS else shlex.join(argv),
                                sandbox.root, argv=argv, timeout=10, max_bytes=60_000,
                                env={"PLUGIN_ROOT": str(plugin.path), "EIRENE_PONYTAIL_MODE": mode},
                                isolation=isolation(config),
                                isolate_network=isolate_network(config),
                                read_paths=[str(plugin.path), *tool_dirs(argv[0])])
                            failure = "" if result.ok else result.summary()
                        except (ToolError, OSError) as exc:
                            failure = str(exc)
                        if failure:
                            notices.append(self._skip(plugin.name, "rules", failure))
                            continue
                        self.failed.discard((plugin.name, "rules"))
                        rules = result.output.strip()
                    self.context[plugin.name, "SessionStart"] = rules
                    self.ponytail_mode = mode
        return notices


def tool_dirs(command: str) -> list[str]:
    """Let a sandboxed hook reach its interpreter when it lives outside system folders.

    nvm, asdf and per-user installs keep node in the home directory, which the
    Linux and macOS sandboxes do not expose; Windows grants it automatically.
    """
    try:
        program = shlex.split(command)[0] if command.strip() else ""
    except ValueError:
        return []
    executable = shutil.which(program) if program else None
    if shell.IS_WINDOWS or not executable:
        return []
    folder = Path(executable).resolve().parent
    system = (Path("/usr"), Path("/bin"), Path("/sbin"), Path("/opt/homebrew"))
    return [] if any(folder == root or root in folder.parents for root in system) else [str(folder)]


def parse_output(output: str) -> tuple[str, str]:
    output = output.strip()
    if not output:
        return "", ""
    try:
        value = json.loads(output)
    except ValueError:
        return output, ""
    if not isinstance(value, dict):
        return "", ""
    specific = value.get("hookSpecificOutput") or {}
    malformed = not isinstance(specific, dict)
    specific = {} if malformed else specific
    if value.get("continue") is False or value.get("decision") == "block":
        raise ToolError(str(value.get("stopReason") or value.get("reason") or "blocked by plugin hook"))
    return (str(specific.get("additionalContext") or value.get("additionalContext") or ""),
            str(value.get("systemMessage") or ("ignored malformed hookSpecificOutput" if malformed else "")))
