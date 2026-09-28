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
    (workdir / "long.txt").write_text(data)
    body = files.read_file(box, "long.txt", max_chars=700)
    fragments = [body.split("1\t", 1)[1].split("\n…", 1)[0]]
    while match := re.search(r"byte_offset=(\d+)", body):
        body = files.read_file(box, "long.txt", max_chars=700, byte_offset=int(match[1]))
        fragments.append(body.split("\n", 1)[1].split("\nContinue", 1)[0].split("\n(end", 1)[0])
        assert len(body) <= 700
    assert "".join(fragments) == data


def test_unicode_text_is_readable_and_controls_are_removed(box, workdir):
    (workdir / "unicode.txt").write_text("سلام دنیا\n漢字\n\x1b]52;c;unsafe\x07text\n")
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
