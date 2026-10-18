"""Sandboxed file tools."""

from __future__ import annotations

import pytest

from eirene.core.errors import SandboxError, ToolError
from eirene.tools import files, registry


def test_write_then_read(box, workdir):
    files.write_file(box, "a.txt", "one\ntwo\n")
    assert (workdir / "a.txt").read_text() == "one\ntwo\n"
    body = files.read_file(box, "a.txt")
    assert "1\tone" in body and "2\ttwo" in body


def test_write_creates_parents(box, workdir):
    files.write_file(box, "deep/nest/a.txt", "x")
    assert (workdir / "deep" / "nest" / "a.txt").exists()


def test_write_outside_rejected(box, outside):
    with pytest.raises(SandboxError):
        files.write_file(box, str(outside / "bad.txt"), "x")


def test_read_missing_file(box):
    with pytest.raises(ToolError):
        files.read_file(box, "nope.txt")


def test_read_directory_rejected(box, workdir):
    (workdir / "sub").mkdir()
    with pytest.raises(ToolError):
        files.read_file(box, "sub")


def test_read_binary_rejected(box, workdir):
    (workdir / "b.bin").write_bytes(bytes(range(256)) * 40)
    with pytest.raises(ToolError):
        files.read_file(box, "b.bin")


def test_read_offset_and_limit(box):
    files.write_file(box, "n.txt", "\n".join(str(i) for i in range(100)))
    body = files.read_file(box, "n.txt", offset=10, limit=5)
    assert "11\t10" in body
    assert "more lines" in body


def test_edit_replaces_once(box, workdir):
    files.write_file(box, "e.txt", "alpha beta alpha")
    with pytest.raises(ToolError):
        files.edit_file(box, "e.txt", "alpha", "gamma")
    files.edit_file(box, "e.txt", "alpha beta", "gamma beta")
    assert (workdir / "e.txt").read_text() == "gamma beta alpha"


def test_edit_replace_all(box, workdir):
    files.write_file(box, "e.txt", "a a a")
    files.edit_file(box, "e.txt", "a", "b", replace_all=True)
    assert (workdir / "e.txt").read_text() == "b b b"


def test_edit_missing_string(box):
    files.write_file(box, "e.txt", "hello")
    with pytest.raises(ToolError):
        files.edit_file(box, "e.txt", "goodbye", "hi")


def test_edit_identical_strings_rejected(box):
    files.write_file(box, "e.txt", "hello")
    with pytest.raises(ToolError):
        files.edit_file(box, "e.txt", "hello", "hello")


def test_list_dir(box, workdir):
    (workdir / "sub").mkdir()
    files.write_file(box, "z.txt", "x")
    body = files.list_dir(box, ".")
    assert "sub/" in body and "z.txt" in body


def test_list_missing_dir(box):
    with pytest.raises(ToolError):
        files.list_dir(box, "nope")


def test_glob_finds_and_skips_noise(box, workdir):
    files.write_file(box, "src/a.py", "x")
    files.write_file(box, "node_modules/b.py", "x")
    body = files.glob_files(box, "**/*.py")
    assert "a.py" in body
    assert "node_modules" not in body


def test_glob_absolute_pattern_rejected(box):
    with pytest.raises(ToolError):
        files.glob_files(box, "/etc/*")


def test_glob_no_match(box):
    assert "no matches" in files.glob_files(box, "*.nothing")


def test_diff_preview_shows_change(box):
    files.write_file(box, "d.txt", "one\n")
    diff = files.diff_preview(box, "d.txt", "two\n")
    assert "-one" in diff and "+two" in diff


def test_diff_preview_of_new_file(box):
    diff = files.diff_preview(box, "new.txt", "hello\n")
    assert "+hello" in diff


def test_touched_path():
    assert registry.touched_path("write_file", {"path": "a.txt"}) == "a.txt"
    assert registry.touched_path("read_file", {"path": "a.txt"}) is None


def test_escape_detection(box, outside):
    assert registry.sandbox_escape("write_file", {"path": str(outside / "x")}, box)
    assert not registry.sandbox_escape("write_file", {"path": "x"}, box)


def test_dangerous_command_flagged(box):
    assert registry.sandbox_escape("run_command", {"command": "rm -rf /"}, box)


def test_indirect_and_multiline_shell_requires_approval(box):
    assert "indirect" in registry.sandbox_escape(
        "run_command", {"command": "echo $(whoami)"}, box)
    assert "multiple" in registry.sandbox_escape(
        "run_command", {"command": "echo one\necho two"}, box)


def test_ordinary_command_not_flagged(box):
    assert not registry.sandbox_escape("run_command", {"command": "ls -la"}, box)
    assert not registry.sandbox_escape("run_command", {"command": "python3 app.py"}, box)


def test_outside_write_command_flagged(box):
    assert registry.sandbox_escape("run_command", {"command": "rm /etc/hosts"}, box)


def test_redirect_outside_flagged(box):
    assert registry.sandbox_escape("run_command", {"command": "echo x > /tmp/zzz"}, box)


async def test_execute_dispatch(box, workdir, config):
    out = await registry.execute("write_file", {"path": "t.txt", "content": "hi"}, box)
    assert "created" in out
    out = await registry.execute("run_command", {"command": "echo run"}, box)
    assert "run" in out


async def test_execute_unknown_tool(box):
    with pytest.raises(ToolError):
        await registry.execute("nope", {}, box)


async def test_execute_bad_arguments(box):
    with pytest.raises(ToolError):
        await registry.execute("read_file", {}, box)


async def test_execute_refused_command_raises(box):
    with pytest.raises(ToolError):
        await registry.execute("run_command", {"command": "top"}, box)


def test_specs_hide_exec_in_plan_mode():
    names = {spec["name"] for spec in registry.specs(include_exec=False)}
    assert "run_command" not in names
    assert "read_file" in names


def test_size_aware_read_and_focused_tail(box, workdir):
    (workdir / "large.txt").write_text("\n".join(f"row {i}" for i in range(500)))
    body = files.read_file(box, "large.txt", max_chars=1000)
    assert len(body) <= 1000
    assert "500 lines" in body and "bytes" in body
    assert "continue with offset=" in body
    tail = files.read_file(box, "large.txt", tail=True, limit=3, max_chars=1000)
    assert "498\trow 497" in tail and "500\trow 499" in tail
    assert "row 0\n" not in tail


def test_pattern_read_includes_neighbors(box, workdir):
    (workdir / "a.txt").write_text("before\ntarget\nafter\nunrelated\n")
    body = files.read_file(box, "a.txt", pattern="target", context=1)
    assert "1\tbefore" in body and "2\ttarget" in body and "3\tafter" in body
    assert "unrelated" not in body


@pytest.mark.parametrize("unit", ["abcdef", "سلام漢字"])
def test_long_line_can_be_read_without_losing_bytes(box, workdir, unit):
    import re
    data = unit * 1000
    (workdir / "long.txt").write_text(data, encoding="utf-8")
    body = files.read_file(box, "long.txt", max_chars=700)
    fragments = [body.split("1\t", 1)[1].split("\n…", 1)[0]]
    while match := re.search(r"byte_offset=(\d+)", body):
        body = files.read_file(box, "long.txt", max_chars=700, byte_offset=int(match[1]))
        fragments.append(body.split("\n", 1)[1].split("\nContinue", 1)[0].split("\n(end", 1)[0])
        assert len(body) <= 700
    assert "".join(fragments) == data


def test_unicode_text_is_readable_and_controls_are_removed(box, workdir):
    (workdir / "unicode.txt").write_text("سلام دنیا\n漢字\n\x1b]52;c;unsafe\x07text\n", encoding="utf-8")
    body = files.read_file(box, "unicode.txt")
    assert "سلام دنیا" in body and "漢字" in body
    assert "\x1b" not in body and "\x07" not in body and "unsafe" not in body


def test_small_file_with_many_short_lines_is_read_fully(box, workdir):
    (workdir / "short.txt").write_text("x\n" * 2100)
    body = files.read_file(box, "short.txt")
    assert "2100\tx" in body
    assert "(end of file)" in body
    assert "continue" not in body


def test_tail_retains_end_when_requested_lines_exceed_budget(box, workdir):
    (workdir / "tail.txt").write_text("\n".join(f"row {i} " + "x" * 100 for i in range(100)))
    body = files.read_file(box, "tail.txt", tail=True, limit=100, max_chars=700)
    assert len(body) <= 700
    assert "100\trow 99" in body
    assert "earlier lines omitted" in body


def test_patch_tool_is_removed():
    assert "apply_patch" not in registry.BY_NAME
    assert all(tool.name != "apply_patch" for tool in registry.TOOLS)


async def test_removed_patch_cannot_execute(box):
    with pytest.raises(ToolError):
        await registry.execute("apply_patch", {"patch": "anything"}, box)


def test_edit_empty_search_cannot_insert_everywhere(box, workdir):
    files.write_file(box, "a.txt", "hello")
    with pytest.raises(ToolError, match="must not be empty"):
        files.edit_file(box, "a.txt", "", "bad")
    assert (workdir / "a.txt").read_text() == "hello"


async def test_edit_requires_explicit_replacement(box, workdir):
    files.write_file(box, "a.txt", "hello")
    with pytest.raises(ToolError, match="must be strings"):
        await registry.execute("edit_file", {"path": "a.txt", "old_string": "hello"}, box)
    assert (workdir / "a.txt").read_text() == "hello"


def test_edit_preserves_crlf_from_normalized_reader_text(box, workdir):
    target = workdir / "a.txt"
    target.write_bytes(b"one\r\ntwo\r\nthree\r\n")
    files.edit_file(box, "a.txt", "one\ntwo", "one\nchanged")
    assert target.read_bytes() == b"one\r\nchanged\r\nthree\r\n"


@pytest.mark.parametrize("operation,code,message", [
    ("fsync", 28, "disk full"),
    ("replace", 13, "permission denied"),
    ("replace", 30, "read-only filesystem"),
    ("replace", 5, "I/O error"),
])
def test_edit_os_failures_preserve_original(box, workdir, monkeypatch, operation, code, message):
    import os
    target = workdir / "a.txt"
    target.write_bytes(b"hello\n")
    def fail(*args, **kwargs):
        raise OSError(code, os.strerror(code))
    monkeypatch.setattr(files.os, operation, fail)
    with pytest.raises(ToolError, match=message):
        files.edit_file(box, "a.txt", "hello", "updated")
    assert target.read_bytes() == b"hello\n"
    assert not list(workdir.glob(".eirene-edit-*"))


def test_edit_partial_write_failure_preserves_original(box, workdir, monkeypatch):
    import errno
    target = workdir / "a.txt"
    target.write_bytes(b"hello")
    original_factory = files.tempfile.NamedTemporaryFile
    class BrokenWriter:
        def __init__(self, wrapped):
            self.wrapped = wrapped
            self.name = wrapped.name
        def __enter__(self):
            self.wrapped.__enter__()
            return self
        def __exit__(self, *args):
            return self.wrapped.__exit__(*args)
        def write(self, data):
            self.wrapped.write(data[:2])
            raise OSError(errno.ENOSPC, "No space left on device")
    monkeypatch.setattr(files.tempfile, "NamedTemporaryFile",
                        lambda **kwargs: BrokenWriter(original_factory(**kwargs)))
    with pytest.raises(ToolError, match="disk full"):
        files.edit_file(box, "a.txt", "hello", "updated")
    assert target.read_bytes() == b"hello"
    assert not list(workdir.glob(".eirene-edit-*"))


def test_edit_detects_concurrent_change(box, workdir, monkeypatch):
    target = workdir / "a.txt"
    target.write_text("hello")
    fsync = files.os.fsync
    def concurrent_write(fd):
        fsync(fd)
        target.write_text("someone else's change")
    monkeypatch.setattr(files.os, "fsync", concurrent_write)
    with pytest.raises(ToolError, match="file changed"):
        files.edit_file(box, "a.txt", "hello", "updated")
    assert target.read_text() == "someone else's change"
    assert not list(workdir.glob(".eirene-edit-*"))


def test_edit_preserves_executable_mode(box, workdir):
    import stat
    target = workdir / "a.sh"
    target.write_text("hello")
    target.chmod(0o751)
    files.edit_file(box, "a.sh", "hello", "updated")
    assert stat.S_IMODE(target.stat().st_mode) == 0o751


@pytest.mark.parametrize("body,message", [(b"hello\xff", "invalid UTF-8"),
                                           (b"hello\x00", "binary file")])
def test_edit_rejects_non_text(box, workdir, body, message):
    target = workdir / "a.txt"
    target.write_bytes(body)
    with pytest.raises(ToolError, match=message):
        files.edit_file(box, "a.txt", "hello", "updated")
    assert target.read_bytes() == body


def test_edit_rejects_non_boolean_replace_all(box, workdir):
    files.write_file(box, "a.txt", "hello hello")
    with pytest.raises(ToolError, match="boolean"):
        files.edit_file(box, "a.txt", "hello", "updated", "false")
    assert (workdir / "a.txt").read_text() == "hello hello"


def test_preview_does_not_claim_ambiguous_edit(box):
    files.write_file(box, "a.txt", "hello hello")
    assert "2 matches" in files.edit_preview(box, "a.txt", "hello", "updated")


def test_preview_matches_crlf_edit(box, workdir):
    (workdir / "a.txt").write_bytes(b"one\r\ntwo\r\n")
    preview = files.edit_preview(box, "a.txt", "one\ntwo", "one\nchanged")
    assert "-two" in preview and "+changed" in preview
    files.edit_file(box, "a.txt", "one\ntwo", "one\nchanged")
    assert (workdir / "a.txt").read_bytes() == b"one\r\nchanged\r\n"


@pytest.mark.parametrize("code,message", [(13, "permission denied"), (122, "quota exceeded")])
def test_edit_temp_creation_failure_preserves_original(box, workdir, monkeypatch, code, message):
    import errno
    if code == 122:
        code = errno.EDQUOT
    target = workdir / "a.txt"
    target.write_text("hello")
    def fail(**kwargs):
        raise OSError(code, "storage failure")
    monkeypatch.setattr(files.tempfile, "NamedTemporaryFile", fail)
    with pytest.raises(ToolError, match=message):
        files.edit_file(box, "a.txt", "hello", "updated")
    assert target.read_text() == "hello"


def test_edit_cleanup_failure_reports_both_errors(box, workdir, monkeypatch):
    import errno
    target = workdir / "a.txt"
    target.write_text("hello")
    def full(*args):
        raise OSError(errno.ENOSPC, "No space left on device")
    unlink = type(target).unlink
    def denied(path, *args, **kwargs):
        if path.name.startswith(".eirene-edit-"):
            raise PermissionError(errno.EACCES, "Permission denied")
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(files.os, "fsync", full)
    monkeypatch.setattr(type(target), "unlink", denied)
    with pytest.raises(ToolError, match="disk full.*temporary cleanup failed"):
        files.edit_file(box, "a.txt", "hello", "updated")
    assert target.read_text() == "hello"
    for temporary in workdir.glob(".eirene-edit-*"):
        unlink(temporary)


def test_edit_missing_and_directory_targets(box, workdir):
    with pytest.raises(ToolError, match="missing"):
        files.edit_file(box, "missing.txt", "hello", "updated")
    with pytest.raises(ToolError, match="regular text file"):
        files.edit_file(box, ".", "hello", "updated")


def test_edit_hard_link_is_not_silently_broken(box, workdir):
    target = workdir / "a.txt"
    target.write_text("hello")
    (workdir / "alias.txt").hardlink_to(target)
    with pytest.raises(ToolError, match="hard-linked"):
        files.edit_file(box, "a.txt", "hello", "updated")
    assert target.read_text() == "hello"
    assert (workdir / "alias.txt").read_text() == "hello"


def test_edit_surrogate_replacement_leaves_original(box, workdir):
    target = workdir / "a.txt"
    target.write_text("hello")
    with pytest.raises(ToolError, match="invalid Unicode"):
        files.edit_file(box, "a.txt", "hello", "\ud800")
    assert target.read_text() == "hello"
