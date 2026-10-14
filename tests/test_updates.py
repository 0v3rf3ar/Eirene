"""Release selection, hostile archives, verified downloads and replacement safety."""

from __future__ import annotations

import hashlib
import io
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from eirene.core import updates


def metadata(version="0.2.0"):
    tag = f"v{version}"
    name = updates.asset_name(version)
    base = f"https://github.com/{updates.REPOSITORY}/releases/download/{tag}/"
    return {"tag_name": tag, "assets": [
        {"name": asset, "browser_download_url": base + asset}
        for asset in [name, "SHA256SUMS"]]}


@pytest.mark.parametrize("current,latest,available", [
    ("0.1.9", "0.2.0", True), ("0.1.9", "0.1.10", True),
    ("0.2.0", "0.2.0", False), ("0.3.0", "0.2.0", False),
    ("0.2.0rc1", "0.2.0", True), ("0.1.9", "0.2.0rc1", False),
])
async def test_version_comparison(current, latest, available):
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=metadata(latest)))) as client:
        assert bool(await updates.check(client, current=current)) == available


@pytest.mark.parametrize("flag", ["draft", "prerelease"])
async def test_skip_unpublished_releases(flag):
    body = {**metadata(), flag: True}
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=body))) as client:
        assert await updates.check(client, current="0.1.9") is None


async def test_unexpected_asset_host_rejected():
    body = metadata()
    body["assets"][0]["browser_download_url"] = "https://evil.example/binary"
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=body))) as client:
        with pytest.raises(updates.UpdateError, match="unexpected"):
            await updates.check(client)


async def test_rate_limit_is_actionable():
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(403))) as client:
        with pytest.raises(updates.UpdateError, match="GitHub"):
            await updates.check(client)


@pytest.mark.parametrize("system,machine,label", [
    ("Linux", "x86_64", "Linux-amd64"), ("Linux", "aarch64", "Linux-arm64"),
    ("Darwin", "arm64", "MacOS-silicon"), ("Windows", "AMD64", "Windows-amd64"),
])
def test_platform_assets(system, machine, label):
    assert label in updates.asset_name("0.2.0", system=system, machine=machine)


def test_unsupported_platform():
    with pytest.raises(updates.UpdateError, match="no release binary"):
        updates.asset_name("0.2.0", system="Darwin", machine="x86_64")


def archive_bytes():
    output = io.BytesIO()
    if updates.asset_name("0.2.0").endswith(".zip"):
        with zipfile.ZipFile(output, "w") as bundle:
            bundle.writestr("eirene.exe", b"binary")
    else:
        with tarfile.open(fileobj=output, mode="w:gz") as bundle:
            member = tarfile.TarInfo("eirene")
            member.size = 6
            bundle.addfile(member, io.BytesIO(b"binary"))
    return output.getvalue()


@pytest.mark.parametrize("corrupt", [False, True])
async def test_download_checks_checksum_before_execution(monkeypatch, corrupt):
    body = metadata()
    archive = archive_bytes()
    name = updates.asset_name("0.2.0")
    digest = "0" * 64 if corrupt else hashlib.sha256(archive).hexdigest()
    manifest = f"{digest}  {name}\r\n".encode()
    smoke = Mock()
    monkeypatch.setattr(updates, "_smoke_test", smoke)

    def respond(request):
        if request.url == updates.API_URL:
            return httpx.Response(200, json=body)
        return httpx.Response(200, content=manifest if request.url.path.endswith("SHA256SUMS") else archive)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        release = await updates.check(client, current="0.1.9")
        if corrupt:
            with pytest.raises(updates.UpdateError, match="checksum mismatch"):
                await updates.download(release, client=client)
            smoke.assert_not_called()
        else:
            staged = await updates.download(release, client=client)
            assert staged.read_bytes() == b"binary"
            smoke.assert_called_once()


def test_tar_symlink_rejected(tmp_path):
    archive = tmp_path / "hostile.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        member = tarfile.TarInfo("eirene")
        member.type = tarfile.SYMTYPE
        member.linkname = "/etc/passwd"
        bundle.addfile(member)
    with pytest.raises(updates.UpdateError):
        updates._extract(archive, tmp_path / "binary", False)
    assert not (tmp_path / "binary").exists()


async def test_oversize_download(tmp_path, monkeypatch):
    monkeypatch.setattr(updates, "MAX_DOWNLOAD", 1)
    body = metadata()
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"xx"))) as client:
        release = updates.Release(body["tag_name"], "0.2.0", {
            item["name"]: item["browser_download_url"] for item in body["assets"]})
        with pytest.raises(updates.UpdateError, match="size limit"):
            await updates.download(release, client=client)


def test_source_install_never_replaces_python(tmp_path, monkeypatch):
    monkeypatch.setattr(updates.sys, "frozen", False, raising=False)
    staged = tmp_path / "new"
    staged.write_bytes(b"binary")
    assert "source installation" in updates.install(staged)
    assert staged.exists()


@pytest.mark.skipif(updates.os.name == "nt", reason="POSIX atomic replacement")
def test_frozen_install_atomic(tmp_path, monkeypatch):
    target, staged = tmp_path / "eirene", tmp_path / "new"
    target.write_bytes(b"old")
    target.chmod(0o755)
    staged.write_bytes(b"new")
    monkeypatch.setattr(updates.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updates.sys, "executable", str(target))
    assert "restart" in updates.install(staged)
    assert target.read_bytes() == b"new"
    assert target.stat().st_mode & 0o111


@pytest.mark.skipif(updates.os.name == "nt", reason="POSIX replacement failure")
def test_failed_install_keeps_old_binary(tmp_path, monkeypatch):
    target, staged = tmp_path / "eirene", tmp_path / "new"
    target.write_bytes(b"old")
    staged.write_bytes(b"new")
    monkeypatch.setattr(updates.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updates.sys, "executable", str(target))
    monkeypatch.setattr(updates.os, "replace", Mock(side_effect=PermissionError("locked")))
    with pytest.raises(PermissionError):
        updates.install(staged)
    assert target.read_bytes() == b"old"
    assert not list(tmp_path.glob(".eirene-update-*"))


async def test_command_check_does_not_download(monkeypatch):
    from eirene.commands import update
    monkeypatch.setattr(updates, "check", AsyncMock(return_value=updates.Release("v0.2.0", "0.2.0", {})))
    download = AsyncMock()
    monkeypatch.setattr(updates, "download", download)
    app = SimpleNamespace(say=Mock(), status=SimpleNamespace(stop=Mock()))
    await update.run(app, "check")
    download.assert_not_awaited()
    assert "/update" in app.say.call_args.args[0]


def test_windows_helper_waits_retries_and_preserves_backup(tmp_path, monkeypatch):
    pending = tmp_path / "pending's-é.exe"
    target = tmp_path / "eirene.exe"
    pending.write_bytes(b"new")
    spawn = Mock()
    monkeypatch.setattr(updates.subprocess, "Popen", spawn)
    message = updates._windows_install(pending, target)
    script_path = pending.with_suffix(".ps1")
    assert script_path.read_bytes().startswith(b"\xef\xbb\xbf")
    script = script_path.read_text(encoding="utf-8-sig")
    assert "Wait-Process" in script and "Get-Process" in script
    assert "pending''s-é.exe" in script
    assert "[System.IO.File]::Replace($pending, $target, $backup)" in script
    assert "Copy-Item" not in script and "Move-Item" not in script
    assert "Out-File -LiteralPath $errorLog" in script
    assert "if ($attempt -eq 29) { throw }" in script
    assert "$attempt -lt 30" in script
    assert "scheduled" in message
    assert spawn.call_args.args[0][0] == "powershell.exe"
    assert spawn.call_args.kwargs["cwd"] == str(target.parent)
    assert str(target.with_suffix(".update-error.txt")) in message


def test_windows_helper_launch_failure_cleans_script(tmp_path, monkeypatch):
    pending = tmp_path / "pending.exe"
    pending.write_bytes(b"new")
    monkeypatch.setattr(updates.subprocess, "Popen", Mock(side_effect=OSError("launch failed")))
    with pytest.raises(OSError, match="launch failed"):
        updates._windows_install(pending, tmp_path / "eirene.exe")
    assert not pending.with_suffix(".ps1").exists()
    assert pending.read_bytes() == b"new"


@pytest.mark.skipif(updates.os.name != "nt", reason="native Windows PowerShell replacement")
def test_windows_helper_replaces_binary_and_existing_backup(tmp_path, monkeypatch):
    root = tmp_path / "Eirene's-é"
    root.mkdir()
    target, pending = root / "eirene.exe", root / "pending.exe"
    backup = target.with_suffix(".previous.exe")
    error = target.with_suffix(".update-error.txt")
    target.write_bytes(b"old")
    pending.write_bytes(b"new")
    backup.write_bytes(b"older")
    error.write_text("stale error")
    # An absent PID lets the helper run without waiting for the pytest process.
    monkeypatch.setattr(updates.os, "getpid", lambda: 2147483647)
    with monkeypatch.context() as patch:
        patch.setattr(updates.subprocess, "Popen", Mock())
        updates._windows_install(pending, target)
    result = updates.subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(pending.with_suffix(".ps1"))], capture_output=True, timeout=45)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert target.read_bytes() == b"new"
    assert backup.read_bytes() == b"old"
    assert not pending.exists()
    assert not pending.with_suffix(".ps1").exists()
    assert not error.exists()


async def test_typo_alias_dispatches_update(monkeypatch):
    from eirene.commands import dispatch
    monkeypatch.setattr(updates, "check", AsyncMock(return_value=None))
    app = SimpleNamespace(say=Mock(), config=SimpleNamespace(provider=None),
                          status=SimpleNamespace(stop=Mock()))
    await dispatch(app, "/udpate check")
    updates.check.assert_awaited_once()
    assert "up to date" in app.say.call_args.args[0]


async def test_startup_notice_and_failure(monkeypatch):
    from eirene.app import Eirene
    app = SimpleNamespace(say=Mock(), runtime_logger=Mock())
    monkeypatch.setattr(updates, "check", AsyncMock(return_value=updates.Release("v0.2.0", "0.2.0", {})))
    await Eirene._check_updates(app)
    assert "Run /update" in app.say.call_args.args[0]
    app.say.reset_mock()
    monkeypatch.setattr(updates, "check", AsyncMock(side_effect=updates.UpdateError("offline")))
    await Eirene._check_updates(app)
    app.say.assert_not_called()
    app.runtime_logger.debug.assert_called_once()
