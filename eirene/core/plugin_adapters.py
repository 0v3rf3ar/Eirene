"""Small launch adaptations for the catalog's third-party MCP packages."""
from __future__ import annotations

from pathlib import Path
import shutil

from . import paths


def adapt_manifest(manifest):
    for server in manifest["mcp_servers"].values():
        command = server["command"]
        if manifest["name"] == "playwright" and command == ["npx", "@playwright/mcp@latest"]:
            server.update(command=["npx", "-y", "@playwright/mcp@latest"],
                          network=True, startup_timeout=180, eirene_adapter="playwright")
        if manifest["name"] == "serena" and command == [
                "uvx", "--from", "git+https://github.com/oraios/serena", "serena", "start-mcp-server"]:
            # Match the documented uvx interpreter selection and project-aware
            # CLI startup rather than relying on the marketplace defaults.
            server.update(command=["uvx", "-p", "3.13", "--from", "git+https://github.com/oraios/serena",
                "serena", "start-mcp-server", "--project-from-cwd", "--open-web-dashboard", "false"],
                network=True, startup_timeout=300, eirene_adapter="serena")
    return manifest


def bind_mcp(definition, owner):
    """Give enabled package launchers dedicated writable caches under Eirene data."""
    adapter = definition.get("eirene_adapter")
    if adapter not in {"playwright", "serena"} or owner != adapter:
        return definition
    result = {**definition}
    data = paths.home() / "plugin-data" / owner / "mcp"
    data.mkdir(parents=True, exist_ok=True)
    env = dict(result.get("env", {}))
    env.setdefault("XDG_CACHE_HOME", str(data))
    if adapter == "playwright":
        env.setdefault("npm_config_cache", str(data))
        env.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(data / "browsers"))
    else:
        env.setdefault("UV_CACHE_DIR", str(data))
        env.setdefault("UV_PYTHON_INSTALL_DIR", str(data / "python"))
        env.setdefault("SERENA_HOME", str(data / "serena"))
    result["env"] = env
    result["write_paths"] = [*result.get("write_paths", []), str(data)]
    executable = shutil.which(result["command"][0])
    if executable:
        result["read_paths"] = [*result.get("read_paths", []), str(Path(executable).resolve().parent)]
    return result
