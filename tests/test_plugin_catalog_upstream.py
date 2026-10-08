"""Opt-in integration audit against real upstream checkouts, without network or hooks.

Clone the four upstream repositories at PREFIX-{official,superpowers,skills,vercel},
then run with EIRENE_PLUGIN_AUDIT_PREFIX=PREFIX. Normal CI uses structural fixtures.
"""
import os
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from eirene.commands import lookup
from eirene.core import plugins, skills
from eirene.core.plugin_catalog import BUNDLES
from eirene.core.plugin_install import install

PREFIX = os.environ.get("EIRENE_PLUGIN_AUDIT_PREFIX")
pytestmark = pytest.mark.skipif(not PREFIX, reason="requires explicit upstream fixture checkouts")


@pytest.mark.parametrize("shortcut", [name for name, _, _ in BUNDLES if name not in {"ponytail", "omniroute"}])
def test_real_catalog_bundle_imports_and_exposes_entrypoint(shortcut, monkeypatch, config):
    sources = {
        "https://github.com/anthropics/claude-plugins-official.git": "official",
        "https://github.com/obra/superpowers.git": "superpowers",
        "https://github.com/anthropics/skills.git": "skills",
        "https://github.com/vercel-labs/agent-skills.git": "vercel",
    }
    def clone(argv, **kwargs):
        root = Path(PREFIX + "-" + sources[argv[-2]])
        assert root.is_dir(), f"missing upstream fixture: {root}"
        shutil.copytree(root, argv[-1], symlinks=True, ignore=shutil.ignore_patterns(".git"))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr("eirene.core.plugin_install.subprocess.run", clone)
    name, count = install(shortcut)
    plugin = plugins.discover()[0]
    assert plugin.name == name and plugin.catalog_shortcut == shortcut
    assert any((plugin.skills, plugin.commands, plugin.agents, plugin.mcp_servers))
    assert count == len(plugin.skills)
    app = SimpleNamespace(config=config)
    assert lookup(shortcut, app), f"/{shortcut} is unavailable"
    for skill in skills.discover():
        assert skills.load(skill).strip()
    assert plugins.merged_mcp_servers(config) == {}
    assert not config.get("plugin_trust", {}).get(name)


async def test_real_superpowers_startup_injects_guidance(config, box):
    from eirene.core.plugin_runtime import PluginRuntime
    root = Path(PREFIX + "-superpowers")
    if not shutil.which("bash"):
        pytest.skip("upstream hook needs bash")
    name, _ = install(str(root))
    config.set("plugin_trust", {name: True})
    config.set("execution_isolation", "none")
    runtime = PluginRuntime("upstream-bootstrap")
    await runtime.submit("Review the project", box, config)
    assert "using-superpowers" in runtime.block(config)
    assert "You have superpowers" in runtime.block(config)


@pytest.mark.skipif(os.environ.get("EIRENE_LIVE_MCP_AUDIT") != "1", reason="explicitly opt in to package downloads and MCP startup")
@pytest.mark.parametrize("name, required_tools", [
    ("playwright", {"browser_navigate", "browser_snapshot"}),
    ("serena", {"find_symbol", "find_referencing_symbols"}),
])
async def test_real_mcp_server_catalog(name, required_tools, config, box):
    from eirene.core.mcp import MCPManager
    executable = (os.environ.get("EIRENE_AUDIT_UVX") if name == "serena" else None) or shutil.which("npx" if name == "playwright" else "uvx")
    if not executable:
        pytest.skip("MCP launcher is missing")
    install(str(Path(PREFIX + "-official") / "external_plugins" / name))
    config.set("mcp_enabled", {f"{name}__{name}": True})
    definitions = plugins.merged_mcp_servers(config)
    definitions[f"{name}__{name}"]["command"][0] = executable
    manager = MCPManager(definitions, box.root)
    try:
        await manager.ensure()
        assert not manager.errors, manager.errors
        remote = {tool.remote_name for tool in manager.tools.values()}
        assert required_tools <= remote
    finally:
        await manager.close()
