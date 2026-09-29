"""Provider-independent lifecycle hooks with explicit executable trust."""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess

from . import paths, plugins
from .errors import ToolError
from ..tools import shell


class PluginRuntime:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.started: set[str] = set()
        self.context: dict[tuple[str, str], str] = {}
        self.ponytail_mode: str | None = None

    def block(self, config) -> str:
        parts = [text for (name, _), text in self.context.items()
                 if config.plugin_enabled(name) and config.get("plugin_trust", {}).get(name)]
        return ("Plugin lifecycle instructions (latest mode changes override earlier defaults):\n" +
                "\n\n".join(parts)) if parts else ""

    async def submit(self, prompt, sandbox, config, *, plan=False, only=None):
        if plan:
            return []
        notices = []
        enabled = {p.name for p in plugins.discover()
                   if config.plugin_enabled(p.name) and plugins.executable_enabled(p, config)}
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
            if plugin.name not in self.started:
                events.insert(0, "SessionStart")
            for event in events:
                if event == "UserPromptSubmit":
                    self.context.pop((plugin.name, event), None)
                outputs = []
                for hook in plugin.lifecycle.get(event, []):
                    if event == "SessionStart" and not re.search(hook.get("matcher") or ".*", "startup"):
                        continue
                    data = paths.home() / "plugin-data" / plugin.name / self.session_id
                    data.mkdir(parents=True, exist_ok=True)
                    settings = paths.home() / "plugin-data" / plugin.name / "config"
                    settings.mkdir(parents=True, exist_ok=True)
                    env = {"CLAUDE_PLUGIN_ROOT": str(plugin.path),
                           "CODEX_PLUGIN_ROOT": str(plugin.path), "PLUGIN_ROOT": str(plugin.path),
                           "PLUGIN_DATA": str(data), "CLAUDE_PLUGIN_DATA": str(data),
                           "XDG_CONFIG_HOME": str(settings),
                           "EIRENE_SESSION_ID": self.session_id}
                    if plugin.name == "ponytail" and "PONYTAIL_DEFAULT_MODE" in os.environ:
                        env["PONYTAIL_DEFAULT_MODE"] = os.environ["PONYTAIL_DEFAULT_MODE"]
                    command = hook["command"]
                    if os.name == "nt":
                        for key in env:
                            command = command.replace("${" + key + "}", "%" + key + "%")
                    result = await shell.run(
                        command, sandbox.root,
                        timeout=hook.get("timeout", 30), max_bytes=60_000,
                        env=env, input_text=json.dumps({"session_id": self.session_id,
                            "cwd": str(sandbox.root), "hook_event_name": event,
                            "source": "startup", "prompt": prompt}),
                        isolation=str(config.get("execution_isolation", "auto")),
                        isolate_network=bool(config.get("isolate_network", True)),
                        read_paths=[str(plugin.path)], write_paths=[str(data), str(settings)])
                    if not result.ok:
                        raise ToolError(f"{plugin.name} {event} hook failed: {result.summary()}")
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
                except FileNotFoundError:
                    mode = "off"
                if mode not in {"lite", "full", "ultra", "review", "off"}:
                    raise ToolError("invalid Ponytail mode returned by hook")
                if mode != self.ponytail_mode:
                    if mode == "off":
                        rules = "Ponytail mode is OFF. Do not apply Ponytail rules until the user enables it again."
                    else:
                        script = ("process.stdout.write(require(process.env.PLUGIN_ROOT + "
                                  "'/hooks/ponytail-instructions.js').getPonytailInstructions("
                                  "process.env.EIRENE_PONYTAIL_MODE))")
                        argv = ["node", "-e", script]
                        result = await shell.run(
                            subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv),
                            sandbox.root, timeout=10, max_bytes=60_000,
                            env={"PLUGIN_ROOT": str(plugin.path), "EIRENE_PONYTAIL_MODE": mode},
                            isolation=str(config.get("execution_isolation", "auto")),
                            isolate_network=True, read_paths=[str(plugin.path)])
                        if not result.ok:
                            raise ToolError(f"Ponytail rules could not load: {result.summary()}")
                        rules = result.output.strip()
                    self.context[plugin.name, "SessionStart"] = rules
                    self.ponytail_mode = mode
        return notices


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
    if not isinstance(specific, dict):
        raise ToolError("invalid plugin hookSpecificOutput")
    if value.get("continue") is False or value.get("decision") == "block":
        raise ToolError(str(value.get("stopReason") or value.get("reason") or "blocked by plugin hook"))
    return (str(specific.get("additionalContext") or value.get("additionalContext") or ""),
            str(value.get("systemMessage") or ""))
