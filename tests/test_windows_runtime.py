"""Windows runtime policy: portable checks, and native parity with the Linux sandbox."""

import asyncio
import os
import sys
from pathlib import Path

import pytest

from eirene.core import paths
from eirene.tools import windows_runtime as runtime

native = pytest.mark.skipif(os.name != "nt", reason="Windows AppContainer runtime")


def test_profile_names_are_stable_and_separate_access_levels():
    root = Path("C:/Work/App")
    names = {runtime._profile_name(root, read_only, network)
             for read_only in (False, True) for network in (False, True)}
    assert len(names) == 4 and all(len(name) <= 64 for name in names)
    assert runtime._profile_name(root, False, False) == runtime._profile_name(Path("c:/work/app"), False, False)
    assert runtime._profile_name(root, False, False) != runtime._profile_name(Path("C:/Work/Other"), False, False)


def test_toolchains_grant_install_roots_but_never_broad_or_private_folders(tmp_path, monkeypatch):
    home = tmp_path / "home"
    local, roaming = home / "AppData" / "Local", home / "AppData" / "Roaming"
    python = local / "Programs" / "Python" / "Python313"
    cargo, rustup, uv_bin, uv_python = home / ".cargo", home / ".rustup", home / ".local" / "bin", roaming / "uv" / "python"
    system = tmp_path / "Windows"
    for folder in (python / "Scripts", cargo / "bin", rustup, uv_bin, uv_python, system / "System32",
                   home / ".local" / "share" / "eirene"):
        folder.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(paths, "home", lambda: home / ".local" / "share" / "eirene")
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setenv("SystemRoot", str(system))
    for key in ("ProgramFiles", "ProgramFiles(x86)"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PATH", os.pathsep.join(map(str, [
        python / "Scripts", python, cargo / "bin", uv_bin, system / "System32",
        home, local / "Programs", home / ".local" / "share", tmp_path / "missing"])))
    found = set(runtime._toolchains(str(system / "System32" / "cmd.exe")))
    assert found == {python.resolve(), cargo.resolve(), rustup.resolve(), uv_bin.resolve(), uv_python.resolve()}


def test_python_shim_is_valid_and_inert_outside_the_sandbox(monkeypatch):
    compile(runtime._PYTHON_SHIM, "sitecustomize.py", "exec")
    monkeypatch.delenv("EIRENE_SANDBOX_SID", raising=False)
    before, meta = os.mkdir, list(sys.meta_path)
    namespace = {"__file__": str(Path(__file__)), "__name__": "sitecustomize_probe"}
    namespace_code = runtime._PYTHON_SHIM.replace("\n_chain()\n", "\n")
    exec(compile(namespace_code, "sitecustomize.py", "exec"), namespace)
    assert os.mkdir is before and sys.meta_path == meta


def test_private_environment_paths_cannot_be_overridden(tmp_path):
    from eirene.tools.windows_appcontainer import _environment
    home = tmp_path / "private"
    block = _environment(str(tmp_path), home, str(tmp_path / "local"), {
        "home": "outside", "TEMP": "outside", "Path": "explicit-tool-path",
        "LANG": "en_US.UTF-8",
    })
    values = dict(entry.split("=", 1) for entry in block.rstrip("\0").split("\0"))
    assert values["HOME"] == str(home) and values["TEMP"] == str(home)
    assert values["Path"] == "explicit-tool-path" and "PATH" not in values


@pytest.mark.parametrize("extra", [{"X": "bad\0value"}, {"BAD=KEY": "value"}, {"": "value"}])
def test_environment_rejects_invalid_entries(tmp_path, extra):
    from eirene.core.errors import ToolError
    from eirene.tools.windows_appcontainer import _environment
    with pytest.raises(ToolError):
        _environment(str(tmp_path), tmp_path, str(tmp_path), extra)


def test_windows_runtime_refuses_other_platforms():
    if os.name == "nt":
        pytest.skip("non-Windows contract")
    from eirene.core.errors import ToolError
    with pytest.raises(ToolError, match="requires Windows"):
        asyncio.run(runtime.start(["cmd"], Path.cwd(), Path.cwd()))


async def _run(command, root, **kwargs):
    from eirene.tools import shell
    return await shell.run(command, root, shell_name="cmd", isolation="auto", isolate_network=True,
                           allow_blocked=True, timeout=60, **kwargs)


@native
async def test_native_commands_run_concurrently(workdir):
    paths.use_session_temp(workdir, "concurrent")
    started = asyncio.get_running_loop().time()
    results = await asyncio.gather(*(_run("ping -n 3 127.0.0.1 >nul & echo done", workdir) for _ in range(2)))
    assert all(result.exit_code == 0 and "done" in result.output for result in results)
    assert asyncio.get_running_loop().time() - started < 3.5, "sandboxed commands were serialized"


@native
async def test_native_python_private_temp_folders_work(workdir):
    paths.use_session_temp(workdir, "python-temp")
    probe = "import tempfile, os; d = tempfile.mkdtemp(); open(os.path.join(d, 'f'), 'w').write('x'); print(os.listdir(d))"
    result = await _run(f'"{sys.executable}" -c "{probe}"', workdir)
    assert result.exit_code == 0 and "['f']" in result.output, result.output


@native
async def test_native_mcp_server_runs_in_the_sandbox(workdir, outside):
    from eirene.core.mcp import MCPManager
    paths.use_session_temp(workdir, "mcp")
    (workdir / "server.py").write_text(
        "import sys, json\n"
        "for line in sys.stdin:\n"
        "    msg = json.loads(line)\n"
        "    if 'id' not in msg: continue\n"
        "    if msg['method'] == 'initialize': result = {'protocolVersion': '2025-06-18', 'capabilities': {}}\n"
        "    elif msg['method'] == 'tools/list': result = {'tools': [{'name': 'read', 'inputSchema': {'type': 'object'}}]}\n"
        "    else:\n"
        "        try: text = open(msg['params']['arguments']['path']).read()\n"
        "        except OSError as exc: text = type(exc).__name__\n"
        "        result = {'content': [{'type': 'text', 'text': text}]}\n"
        "    print(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': result}), flush=True)\n")
    (workdir / "inside.txt").write_text("inside")
    manager = MCPManager({"probe": {"command": [sys.executable, "server.py"], "_isolation": "auto"}}, workdir)
    try:
        await manager.ensure()
        assert not manager.errors
        assert await manager.call("mcp__probe__read", {"path": str(workdir / "inside.txt")}) == "inside"
        assert await manager.call("mcp__probe__read", {"path": str(outside / "secret.txt")}) == "PermissionError"
    finally:
        await manager.close()


@native
async def test_native_programs_built_in_the_sandbox_run_normally_on_the_host(workdir):
    import subprocess
    paths.use_session_temp(workdir, "labels")
    whoami = Path(os.environ["SystemRoot"]) / "System32" / "whoami.exe"
    result = await _run(f'copy "{whoami}" tool.exe', workdir)
    assert result.exit_code == 0, result.output
    # A Low label would start it at Low integrity, unable to use the user's own files.
    label = subprocess.run(["icacls", str(workdir / "tool.exe")], capture_output=True, text=True).stdout
    assert "Low Mandatory Level" not in label
    assert subprocess.run([str(workdir / "tool.exe")], capture_output=True).returncode == 0


@native
async def test_native_links_in_the_workspace_do_not_extend_its_grant(workdir, outside):
    """Workspaces may hold junctions: inheritance stops at the link and access is
    checked against the target's own ACL, so the target stays out of reach."""
    import subprocess
    subprocess.run(["cmd", "/c", "mklink", "/J", str(workdir / "escape"), str(outside)],
                   check=True, capture_output=True)
    paths.use_session_temp(workdir, "links")
    result = await _run(r"type escape\secret.txt", workdir)
    assert result.exit_code != 0 and "do not read" not in result.output
    assert "S-1-15-2-" not in subprocess.run(["icacls", str(outside)], capture_output=True, text=True).stdout
