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


@pytest.mark.parametrize("current,versions,expected", [
    ("0.1.9", ["0.2.0b2", "0.2.0b10", "0.2.0b3"], "0.2.0b10"),
    ("0.2.0b2", ["0.2.0b2", "0.2.0b1"], None),
    ("0.2.0", ["0.2.0rc1", "0.1.9"], None),
    ("0.2.0rc1", ["0.2.0", "0.2.0b3"], "0.2.0"),
    ("0.1.9", ["0.3.0a1", "0.2.0"], "0.3.0a1"),
    ("0.1.9", [], None),
])
async def test_edge_selects_highest_newer_version(current, versions, expected):
    bodies = [{**metadata(version), "prerelease": "b" in version or "rc" in version or "a" in version}
              for version in versions]

    def respond(request):
        assert request.url.path.endswith("/releases")
        assert request.url.params["per_page"] == "100"
        return httpx.Response(200, json=bodies)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        release = await updates.check(client, current=current, edge=True)
    assert (release.version if release else None) == expected


async def test_edge_paginates_and_skips_drafts_and_nonversion_tags():
    pages = []

    def respond(request):
        page = request.url.params["page"]
        pages.append(page)
        if page == "1":
            return httpx.Response(200, json=[metadata("0.2.0")], headers={
                "Link": f'<{updates.RELEASES_URL}?page=2>; rel="next"'})
        return httpx.Response(200, json=[
            {**metadata("9.0.0"), "draft": True},
            {"tag_name": "nightly"}, {"tag_name": "v0.3.0invalid"},
            {**metadata("0.3.0b1"), "prerelease": True},
        ])

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        release = await updates.check(client, current="0.1.9", edge=True)
    assert release.version == "0.3.0b1"
    assert pages == ["1", "2"]


async def test_no_stable_release_is_up_to_date():
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(404))) as client:
        assert await updates.check(client, current="0.1.9") is None


@pytest.mark.parametrize("body", [{}, None, "invalid"])
async def test_edge_rejects_invalid_metadata(body):
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=body))) as client:
        with pytest.raises(updates.UpdateError, match="metadata|GitHub"):
            await updates.check(client, edge=True)


@pytest.mark.parametrize("edge", [False, True])
async def test_unexpected_asset_host_rejected(edge):
    body = metadata()
    body["assets"][0]["browser_download_url"] = "https://evil.example/binary"
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=[body] if edge else body))) as client:
        with pytest.raises(updates.UpdateError, match="unexpected"):
            await updates.check(client, current="0.1.9", edge=edge)


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


@pytest.mark.parametrize("args,edge", [("", False), ("edge", True)])
async def test_command_installs_requested_channel(monkeypatch, tmp_path, args, edge):
    from eirene.commands import update
    release = updates.Release("v0.2.0b1", "0.2.0b1", {})
    check = AsyncMock(return_value=release)
    download = AsyncMock(return_value=tmp_path / "eirene")
    install = Mock(return_value="installed")
    monkeypatch.setattr(updates, "check", check)
    monkeypatch.setattr(updates, "download", download)
    monkeypatch.setattr(updates, "install", install)
    app = SimpleNamespace(say=Mock(), status=SimpleNamespace(stop=Mock()))
    await update.run(app, args)
    check.assert_awaited_once_with(edge=edge)
    assert download.await_args.args == (release,)
    install.assert_called_once_with(tmp_path / "eirene")


@pytest.mark.parametrize("args", ["edge check", "check edge"])
async def test_command_edge_check_does_not_download(monkeypatch, args):
    from eirene.commands import update
    check = AsyncMock(return_value=updates.Release("v0.2.0b1", "0.2.0b1", {}))
    download = AsyncMock()
    monkeypatch.setattr(updates, "check", check)
    monkeypatch.setattr(updates, "download", download)
    app = SimpleNamespace(say=Mock(), status=SimpleNamespace(stop=Mock()))
    await update.run(app, args)
    check.assert_awaited_once_with(edge=True)
    download.assert_not_awaited()
    assert "Run /update edge" in app.say.call_args.args[0]


async def test_invalid_update_arguments_do_not_check(monkeypatch):
    from eirene.commands import update
    check = AsyncMock()
    monkeypatch.setattr(updates, "check", check)
    app = SimpleNamespace(say=Mock())
    await update.run(app, "nightly")
    check.assert_not_awaited()
    assert "usage:" in app.say.call_args.args[0]


def test_windows_update_command_targets_this_installation_exactly():
    release = updates.Release("v0.2.1b2", "0.2.1b2", {})
    command = updates.windows_update_command(release, Path(r"C:\Users\O'Brien $x\Programs\eirene"))
    assert command == (
        "& ([scriptblock]::Create((irm "
        "'https://raw.githubusercontent.com/0v3rf3ar/Eirene/master/install.ps1'))) "
        "-Version 'v0.2.1b2' -InstallDir 'C:\\Users\\O''Brien $x\\Programs\\eirene' -NoPathUpdate")


def test_windows_frozen_install_refuses_self_replacement(tmp_path, monkeypatch):
    staged = tmp_path / "eirene-0.2.0.exe"
    staged.write_bytes(b"new")
    monkeypatch.setattr(updates.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updates.os, "name", "nt")
    with pytest.raises(updates.UpdateError, match="installer command"):
        updates.install(staged)


@pytest.mark.parametrize("args,tag", [("", "v0.2.0"), ("edge", "v0.3.0b1")])
async def test_windows_update_shows_installer_command_instead_of_replacing(monkeypatch, tmp_path, args, tag):
    from eirene.commands import update
    release = updates.Release(tag, tag[1:], {})
    monkeypatch.setattr(updates, "check", AsyncMock(return_value=release))
    download = AsyncMock()
    monkeypatch.setattr(updates, "download", download)
    monkeypatch.setattr(updates, "needs_installer", lambda: True)
    monkeypatch.setattr(update.sys, "executable", str(tmp_path / "eirene.exe"))
    copied = []
    monkeypatch.setattr(update, "copy_to_system", lambda text: copied.append(text) or "clip.exe")
    panel = SimpleNamespace(show_content=Mock())
    app = SimpleNamespace(say=Mock(), status=SimpleNamespace(stop=Mock()), aside=panel)
    await update.run(app, args)
    download.assert_not_awaited()
    expected = updates.windows_update_command(release, tmp_path.resolve())
    assert copied == [expected]
    shown = panel.show_content.call_args.args[0].plain
    assert expected in shown and "waits for every" in shown
    assert "copied to your clipboard" in app.say.call_args.args[0]
    assert not getattr(app, "_update_pending", False)


async def test_windows_update_without_clipboard_does_not_claim_a_copy(monkeypatch, tmp_path):
    from eirene.commands import update
    monkeypatch.setattr(updates, "check", AsyncMock(return_value=updates.Release("v0.2.0", "0.2.0", {})))
    monkeypatch.setattr(updates, "needs_installer", lambda: True)
    monkeypatch.setattr(update.sys, "executable", str(tmp_path / "eirene.exe"))
    monkeypatch.setattr(update, "copy_to_system", lambda text: "")
    app = SimpleNamespace(say=Mock(), status=SimpleNamespace(stop=Mock()),
                          aside=SimpleNamespace(show_content=Mock()))
    await update.run(app, "")
    assert "clipboard" not in app.say.call_args.args[0]


def test_only_frozen_windows_needs_the_installer(monkeypatch):
    monkeypatch.setattr(updates.os, "name", "nt")
    monkeypatch.setattr(updates.sys, "frozen", False, raising=False)
    assert not updates.needs_installer()
    monkeypatch.setattr(updates.sys, "frozen", True, raising=False)
    assert updates.needs_installer()
    monkeypatch.setattr(updates.os, "name", "posix")
    assert not updates.needs_installer()


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
