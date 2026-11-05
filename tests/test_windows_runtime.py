"""Windows runtime policy: portable checks, and native parity with the Linux sandbox."""

import asyncio
import os
import shutil
import subprocess
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
    machine = tmp_path / "Android" / "sdk" / "platform-tools"
    machine.mkdir(parents=True)
    monkeypatch.setenv("PATH", os.pathsep.join(map(str, [
        python / "Scripts", python, cargo / "bin", uv_bin, system / "System32",
        home, local / "Programs", home / ".local" / "share", tmp_path / "missing", machine])))
    found = set(runtime._toolchains(str(system / "System32" / "cmd.exe")))
    assert found == {python.resolve(), cargo.resolve(), rustup.resolve(), uv_bin.resolve(), uv_python.resolve()}


def test_toolchain_grants_run_in_the_background_and_are_recorded_once_done(tmp_path, monkeypatch):
    import threading
    release, calls = threading.Event(), []
    def icacls(path, *arguments):
        calls.append(path)
        release.wait(5)
        if path.name == "broken":
            raise runtime.ToolError("denied")
    monkeypatch.setattr(runtime, "_icacls", icacls)
    folders = [tmp_path / "python", tmp_path / "broken"]
    runtime._grant_toolchains("S-1-15-3-1024-9", folders)
    # The command does not wait for propagation through the toolchain.
    assert runtime._granted_toolchains() == {}
    runtime._grant_toolchains("S-1-15-3-1024-9", folders)  # already in progress: not repeated
    release.set()
    for _ in range(100):
        if not runtime._toolchain_busy:
            break
        threading.Event().wait(0.02)
    assert calls == folders
    assert runtime._granted_toolchains() == {"S-1-15-3-1024-9": [str(folders[0]).casefold()]}
    calls.clear()
    runtime._grant_toolchains("S-1-15-3-1024-9", folders)
    for _ in range(100):
        if not runtime._toolchain_busy:
            break
        threading.Event().wait(0.02)
    assert calls == [folders[1]], "only the failed folder is retried"


def test_a_launcher_loose_in_the_profile_never_grants_the_profile(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".local" / "share" / "eirene").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(paths, "home", lambda: home / ".local" / "share" / "eirene")
    assert not runtime._narrow(home) and not runtime._narrow(home.parent)
    assert not runtime._narrow(home / ".local") and not runtime._narrow(home / ".local" / "share" / "eirene")
    assert runtime._narrow(home / "tools" / "node")


def test_python_shim_is_valid_and_inert_outside_the_sandbox(monkeypatch):
    compile(runtime._PYTHON_SHIM, "sitecustomize.py", "exec")
    monkeypatch.delenv("EIRENE_SANDBOX_SID", raising=False)
    before, meta = os.mkdir, list(sys.meta_path)
    namespace = {"__file__": str(Path(__file__)), "__name__": "sitecustomize_probe"}
    namespace_code = runtime._PYTHON_SHIM.replace("\n_chain()\n", "\n")
    exec(compile(namespace_code, "sitecustomize.py", "exec"), namespace)
    assert os.mkdir is before and sys.meta_path == meta


def test_node_options_load_the_shim_and_keep_what_was_already_set():
    shim = Path("C:/Users/A B/stdio.cjs")
    assert runtime._node_options(shim) == '--require "C:/Users/A B/stdio.cjs"'
    assert runtime._node_options(shim, "--max-old-space-size=99") == '--require "C:/Users/A B/stdio.cjs" --max-old-space-size=99'


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
@pytest.mark.parametrize("env", [{}, {"EIRENE_SANDBOX_SID": "S-1-15-2-1"}], ids=["outside", "sandbox-sid-off-windows"])
def test_node_shim_is_valid_and_inert_off_windows_or_outside_the_sandbox(tmp_path, env):
    if os.name == "nt" and env:
        pytest.skip("the shim is active here; the native tests cover it")
    shim = tmp_path / "stdio.cjs"
    shim.write_text(runtime._NODE_SHIM, encoding="utf-8")
    script = "console.log(require('child_process').execFileSync(process.execPath, ['-p', '1+1'], {encoding: 'utf8'}).trim())"
    base = {k: v for k, v in os.environ.items() if k != "EIRENE_SANDBOX_SID"}
    result = subprocess.run(["node", "--require", str(shim), "-e", script], env={**base, **env},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and result.stdout.strip() == "2", result.stderr


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


NODE_CHILD_CASES = {
    "execFileSync": "console.log(c.execFileSync(process.execPath, ['-p', '40+2'], {encoding: 'utf8'}).trim())",
    "execSync": "console.log(c.execSync('cmd /c echo 42', {encoding: 'utf8'}).trim())",
    "spawnSync input": "console.log(c.spawnSync(process.execPath, ['-e', "
        "'process.stdin.pipe(process.stdout)'], {input: '42', encoding: 'utf8'}).stdout)",
    "spawnSync timeout": "const r = c.spawnSync(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], "
        "{stdio: ['ignore', 'pipe', 'ignore'], timeout: 500}); console.log(r.error.code === 'ETIMEDOUT' ? 42 : r.error)",
    "maxBuffer": "try { c.execFileSync(process.execPath, ['-p', '\"x\".repeat(5000)'], {maxBuffer: 10}) } "
        "catch (e) { console.log(e.code === 'ENOBUFS' ? 42 : e.code) }",
    "spawn": "const k = c.spawn(process.execPath, ['-p', '40+2']); let o = ''; k.stdout.on('data', d => o += d); "
        "k.on('close', s => console.log(s === 0 ? o.trim() : s))",
    "exec": "c.exec('cmd /c echo 42', (e, o) => console.log(e || o.trim()))",
    "stdin": "const k = c.spawn(process.execPath, ['-e', 'process.stdin.pipe(process.stdout)']); let o = ''; "
        "k.stdout.on('data', d => o += d); k.on('close', () => console.log(o)); k.stdin.end('42')",
    "large output": "const k = c.spawn(process.execPath, ['-e', 'process.stdout.write(\"x\".repeat(3e6))']); let n = 0; "
        "k.stdout.on('data', d => n += d.length); k.on('close', () => console.log(n === 3e6 ? 42 : n))",
    "kill": "const k = c.spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)']); "
        "k.on('close', (_, s) => console.log(s === 'SIGTERM' ? 42 : s)); setTimeout(() => k.kill(), 200)",
    "missing program": "c.spawn('no-such-program-x').on('error', e => console.log(e.code === 'ENOENT' ? 42 : e.code))",
}


@native
@pytest.mark.parametrize("case", NODE_CHILD_CASES)
async def test_native_node_child_processes_with_piped_stdio_finish(workdir, case):
    """libuv's stdio pipes are denied in an AppContainer and it retries forever without the shim."""
    if not shutil.which("node"):
        pytest.skip("needs node")
    paths.use_session_temp(workdir, "node-" + case.replace(" ", "-"))
    (workdir / "probe.js").write_text("const c = require('child_process');\n" + NODE_CHILD_CASES[case], encoding="utf-8")
    result = await _run("node probe.js", workdir, input_text="")
    assert result.exit_code == 0 and "42" in result.output, result.summary()


@native
async def test_native_a_node_channel_fails_plainly_instead_of_hanging(workdir):
    if not shutil.which("node"):
        pytest.skip("needs node")
    paths.use_session_temp(workdir, "node-fork")
    (workdir / "probe.js").write_text(
        "try { require('child_process').fork(__filename + '.none'); console.log('forked') }"
        " catch (e) { console.log('refused ' + e.code) }", encoding="utf-8")
    result = await _run("node probe.js", workdir, input_text="")
    assert result.exit_code == 0 and "refused ENOTSUP" in result.output, result.summary()


@native
async def test_native_node_scripts_load_from_a_grant_outside_the_workspace(workdir, outside):
    """Node resolves a script by stat'ing each folder above it; a grant must allow that walk."""
    if not shutil.which("node"):
        pytest.skip("needs node")
    paths.use_session_temp(workdir, "node-grant")
    nested = outside / "plugin" / "hooks"
    nested.mkdir(parents=True)
    (nested / "run.js").write_text("console.log('loaded')", encoding="utf-8")
    result = await _run(f'node "{nested / "run.js"}"', workdir, input_text="", read_paths=[str(outside / "plugin")])
    assert result.exit_code == 0 and "loaded" in result.output, result.summary()


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
