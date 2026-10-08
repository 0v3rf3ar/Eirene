"""Startup detection, host-only prompts, and available shell options."""
import pytest

from eirene.core import platforms, prompt
from eirene.providers.local_profile import LocalProfile
from eirene.tools import registry
from test_agent import Script, build


def host(system, available):
    return platforms.Host(system, "cmd" if system == "Windows" else "bash",
                          "arm64", 8, 16, 0, tuple(available), ())


@pytest.mark.parametrize("system,commands,expected,excluded", [
    ("Windows", ["powershell"], "Get-Content", ["sed -n", "Linux command profile", "macOS command profile"]),
    ("Windows", [], "CMD only", ["Get-Content", "sed -n", "powershell=true"]),
    ("Darwin", ["sed", "tail", "grep"], "BSD", ["powershell=true", "Linux command profile", "rg -n"]),
    ("Linux", ["sed", "tail", "rg"], "Bubblewrap", ["powershell=true", "macOS command profile", "Get-Content"]),
])
def test_models_get_only_host_guidance(system, commands, expected, excluded):
    snapshot = host(system, commands)
    original = prompt.build("/project", "auto", system, snapshot.shell, "2026-09-29", host=snapshot)
    assert expected in original
    assert "arm64, 8 CPU threads, ~16 GiB RAM" in original
    assert "memory estimate unknown" in original
    assert "Host tools:" in original
    for other in excluded:
        assert other not in original
    for tier in ("compact", "balanced", "full"):
        result = LocalProfile(tier, 3, 16, 8, 0).system(original)
        assert "Hardware:" in result
        assert "Host tools:" in result
        assert "Bounded read commands:" in original
        for other in excluded:
            assert other not in result
        if tier == "compact":
            assert len(result) < 1400


def test_detection_is_local_and_inventory_is_platform_specific(monkeypatch):
    from eirene.providers import local_profile
    checked = []
    monkeypatch.setattr(platforms.platform, "system", lambda: "Windows")
    monkeypatch.setattr(platforms.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(platforms.os, "cpu_count", lambda: 12)
    monkeypatch.setattr(local_profile, "_ram_gb", lambda: 32)
    monkeypatch.setattr(local_profile, "_gpu_vram_gb", lambda: 0)

    def which(name):
        checked.append(name)
        return f"C:/tools/{name}.exe" if name in {"git", "pwsh"} else None

    monkeypatch.setattr(platforms.shutil, "which", which)
    snapshot = platforms.Host.detect()
    assert snapshot.architecture == "AMD64" and snapshot.cpu_threads == 12
    assert snapshot.available == ("git", "pwsh")
    assert "powershell=true" in snapshot.shell
    assert "sed" not in checked and "grep" not in checked
    assert "npm" in snapshot.missing


@pytest.mark.parametrize("system,available,powershell,pty", [
    ("Windows", ["pwsh"], True, False),
    ("Windows", [], False, False),
    ("Linux", ["rg"], False, True),
    ("Darwin", ["sed"], False, True),
])
def test_only_supported_shell_options_are_sent(system, available, powershell, pty):
    specs = host(system, available).tool_specs(registry.specs())
    for name in ("run_command", "start_process"):
        properties = next(s for s in specs if s["name"] == name)["parameters"]["properties"]
        assert ("powershell" in properties) == powershell
        assert ("pty" in properties) == pty
    # Global tool definitions still support all platforms.
    assert "powershell" in registry.BY_NAME["run_command"].schema["properties"]


def test_agent_reuses_startup_snapshot(workdir, monkeypatch):
    calls = []
    snapshot = host("Windows", ["pwsh", "git"])

    def detect():
        calls.append(True)
        return snapshot

    monkeypatch.setattr(platforms.Host, "detect", detect)
    runner = build(workdir, Script([]))
    first = runner.system_prompt()
    runner.system_prompt()
    runner.tool_specs()
    assert len(calls) == 1
    assert "OS: Windows" in first
    assert "Hardware:" in first
    assert "Linux command profile" not in first


def test_compact_windows_inventory_stays_small():
    snapshot = platforms.Host(
        "Windows", "cmd (PowerShell available through powershell=true)", "AMD64",
        16, 32, 8, ("git", "rg", "node", "npm", "pytest", "cargo", "go", "pwsh",
                    "powershell", "python", "py"), ())
    original = prompt.build("C:/project", "auto", "Windows", snapshot.shell,
                            "2026-09-29", host=snapshot)
    compact = LocalProfile("compact", 3, 16, 8, 0).system(original)
    assert len(compact) < 1400
    assert "Hardware:" in compact and "Host tools:" in compact
