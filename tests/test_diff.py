"""Change rendering: numbers, highlighting and colour bands."""

from __future__ import annotations

import pytest
from rich.console import Console

from eirene.tools import files
from eirene.tools.sandbox import Sandbox
from eirene.ui import diff, palette

BEFORE = "alpha\nbravo\ncharlie\ndelta\necho\n"
AFTER = "alpha\nbravo\nCHARLIE\ndelta\nfoxtrot\necho\n"


def render(change: diff.Change, width: int = 60) -> str:
    console = Console(width=width, force_terminal=False, no_color=True)
    with console.capture() as capture:
        console.print(diff.ChangeView(change))
    return capture.get()


def styled(change: diff.Change, width: int = 60) -> str:
    console = Console(width=width, force_terminal=True, color_system="truecolor")
    with console.capture() as capture:
        console.print(diff.ChangeView(change))
    return capture.get()


def make(workdir, name="notes.txt", before=BEFORE, after=AFTER):
    (workdir / name).write_text(before, encoding="utf-8")
    text = files.diff_preview(Sandbox(workdir), name, after)
    return diff.parse(name, text, "Update")


def test_counts_the_lines(workdir):
    change = make(workdir)
    assert change.added == 2
    assert change.removed == 1
    assert change.summary == "Added 2 lines, removed 1 line"


def test_one_line_each_reads_singular(workdir):
    change = make(workdir, before="a\n", after="b\n")
    assert change.summary == "Added 1 line, removed 1 line"


def test_rows_carry_line_numbers(workdir):
    change = make(workdir)
    added = [row for row in change.rows if row.sign == "+"]
    removed = [row for row in change.rows if row.sign == "-"]
    assert [row.text for row in added] == ["CHARLIE", "foxtrot"]
    assert [row.text for row in removed] == ["charlie"]
    assert all(row.number for row in change.rows)
    assert removed[0].number == 3
    assert added[0].number == 3


def test_the_header_names_the_file(workdir):
    change = make(workdir)
    out = render(change)
    assert "● Update(" in out and "notes.txt)" in out
    assert "▤" not in out
    assert "Added 2 lines, removed 1 line" in out


@pytest.mark.parametrize("name", [
    "script.py", "app.js", "styles.css", "data.json", "README.md",
    "photo.png", "settings.toml", "Dockerfile", "extensionless",
])
def test_change_headers_contain_only_the_path_inside_parentheses(workdir, name):
    change = make(workdir, name=name)
    header = render(change).splitlines()[0]
    assert header == f"● Update({name})"


def test_added_and_removed_lines_are_marked(workdir):
    change = make(workdir)
    out = render(change)
    assert "+ CHARLIE" in out
    assert "- charlie" in out
    assert "  3 " in out


def test_added_lines_get_a_dark_green_band(workdir):
    change = make(workdir)
    out = styled(change)
    assert diff.ADDED_BACKGROUND == "on #0e2b16"
    assert diff.REMOVED_BACKGROUND == "on #3d1214"
    assert "48;2;14;43;22" in out, "added lines need the dark green background"
    assert "48;2;61;18;20" in out, "removed lines need the dark red background"


def test_the_band_spans_the_row(workdir):
    change = make(workdir, name="notes.txt", before="a\n", after="bb\n")
    out = styled(change, width=40)
    banded = [line for line in out.splitlines() if "48;2;14;43;22" in line]
    assert banded
    plain = render(change, width=40).splitlines()
    row = [line for line in plain if line.strip().endswith("bb")][0]
    assert len(row.rstrip()) <= 40


def test_python_is_syntax_highlighted(workdir):
    change = make(workdir, name="code.py", before="x = 1\n",
                  after="def go():\n    return 1\n")
    out = styled(change)
    assert "\x1b[" in out
    assert diff.lexer_for("code.py") == "python"


def test_lexer_guessing():
    assert diff.lexer_for("a/b/thing.rs") == "rust"
    assert diff.lexer_for("Dockerfile") == "docker"
    assert diff.lexer_for("Makefile") == "make"
    assert diff.lexer_for("eirene.service") == "ini"
    assert diff.lexer_for("notes.unknown") == "text"


def test_a_new_file_is_all_additions(workdir):
    text = files.diff_preview(Sandbox(workdir), "fresh.txt", "one\ntwo\n")
    change = diff.parse("fresh.txt", text, "Create")
    assert change.action == "Create"
    assert change.added == 2
    assert change.removed == 0
    assert "● Create(" in render(change) and "fresh.txt)" in render(change)


def test_a_huge_diff_is_trimmed(workdir):
    before = "".join(f"line {i}\n" for i in range(400))
    after = "".join(f"changed {i}\n" for i in range(400))
    change = make(workdir, before=before, after=after)
    assert len(change.rows) == diff.MAX_ROWS
    assert change.hidden > 0
    assert "more lines" in render(change)


def test_a_loose_preview_still_renders():
    change = diff.parse("thing.py", "- old line\n+ new line", "Update")
    assert change.added == 1
    assert change.removed == 1
    out = render(change)
    assert "+ new line" in out
    assert "- old line" in out


def test_an_empty_diff_is_harmless():
    change = diff.parse("thing.py", "", "Update")
    assert change.rows == []
    assert "● Update(" in render(change) and "thing.py)" in render(change)


def test_an_edit_preview_is_a_real_diff(workdir):
    (workdir / "code.py").write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
    text = files.edit_preview(Sandbox(workdir), "code.py", "b = 2", "b = 22")
    change = diff.parse("code.py", text, "Update")
    assert change.added == 1
    assert change.removed == 1
    assert [row.text for row in change.rows if row.sign == "+"] == ["b = 22"]
    assert [row.number for row in change.rows if row.sign == "-"] == [2]


def test_an_edit_that_does_not_match_falls_back(workdir):
    (workdir / "code.py").write_text("a = 1\n", encoding="utf-8")
    text = files.edit_preview(Sandbox(workdir), "code.py", "zzz", "yyy")
    change = diff.parse("code.py", text, "Update")
    assert change.added == 1
    assert change.removed == 1


def test_a_note_is_shown_when_the_change_failed(workdir):
    change = make(workdir)
    console = Console(width=60, force_terminal=False, no_color=True)
    with console.capture() as capture:
        console.print(diff.ChangeView(change, "could not write it"))
    assert "could not write it" in capture.get()


def test_the_code_is_syntax_highlighted_in_colour(workdir):
    change = make(workdir, name="code.py", before="x = 1\n",
                  after="def go():\n    return 1\n")
    out = styled(change)
    assert "38;2;85;85;255" in out, "keywords need the vivid blue"
    assert diff.SYNTAX_THEME is palette.CODE_THEME


@pytest.mark.parametrize("name", ["code.py", "notes.txt"])
@pytest.mark.parametrize("background", ["#ffffff", "#282a36", "#1e1e2e"])
def test_the_theme_does_not_paint_its_own_background(workdir, name, background):
    change = make(workdir, name=name, before="x = 1\ny = 2\n",
                  after="x = 1\ny = 3\n")
    rows = diff.ChangeView(change).rows(60)
    console = Console(width=60, force_terminal=True, color_system="truecolor")
    for row, rendered in zip(change.rows, rows):
        if row.sign != " ":
            continue
        assert row.text == "x = 1"
        segments = list(console.render(rendered))
        assert all(segment.style is None or segment.style.bgcolor is None
                   for segment in segments)
        with console.capture() as capture:
            console.print(rendered, style=f"on {background}")
        out = capture.get()
        red, green, blue = (int(background[i:i + 2], 16) for i in (1, 3, 5))
        assert f"48;2;{red};{green};{blue}" in out
        assert "48;2;0;0;0" not in out
        assert "49m" not in out


def test_the_header_matches_the_layout(workdir):
    change = make(workdir)
    lines = render(change).splitlines()
    assert lines[0].startswith("● Update(")
    assert lines[0].endswith("notes.txt)")
    assert lines[1].startswith("└ Added 2 lines, removed 1 line")


def test_plain_text_lines_up_with_the_gutter(workdir):
    change = make(workdir)
    view = diff.ChangeView(change)
    rows = view.plain(60).splitlines()[2:]
    assert rows[0].startswith(" " * 3)
    for row, line in zip(change.rows, rows):
        assert line.rstrip().endswith(row.text)
        assert len(line.rstrip()) - len(row.text) == view.gutter()


def test_stripping_the_gutter_leaves_the_code(workdir):
    change = make(workdir)
    view = diff.ChangeView(change)
    body = "\n".join(view.plain(60).splitlines()[2:])
    code = diff.strip_gutter(body, view.gutter())
    assert code.splitlines() == [row.text for row in change.rows]
    assert not any(line.startswith(("+", "-")) for line in code.splitlines())


def test_the_header_survives_gutter_stripping(workdir):
    change = make(workdir)
    view = diff.ChangeView(change)
    kept = diff.strip_gutter(view.plain(60), view.gutter())
    assert kept.splitlines()[0].startswith("● Update")


def test_the_chat_and_the_diffs_share_one_palette():
    from eirene.ui import markup

    assert diff.SYNTAX_THEME is markup.SYNTAX_THEME
    assert diff.SYNTAX_THEME is palette.CODE_THEME


@pytest.mark.parametrize("code,colour,what", [
    ("async def go():\n", palette.BLUE, "keywords"),
    ("async def go():\n", palette.GREEN, "function names"),
    ("x = str(1)\n", palette.CYAN, "builtin types"),
    ("x = None\n", palette.BLUE, "constants"),
    ("x = 20\n", palette.MAGENTA, "numbers"),
    ('x = "hi"\n', palette.YELLOW, "strings"),
    ("x = 1  # note\n", palette.GREY, "comments"),
    ("self.x = 1\n", palette.CYAN, "self"),
    ("@property\n", palette.CYAN, "decorators"),
    ("x = a -> b\n", palette.FOREGROUND, "operators and punctuation"),
])
def test_the_palette_matches_the_screenshot(workdir, code, colour, what):
    change = make(workdir, name="code.py", before="pass\n", after=code)
    out = styled(change, width=70)
    red, green, blue = (int(colour[1:3], 16), int(colour[3:5], 16),
                        int(colour[5:7], 16))
    assert f"38;2;{red};{green};{blue}" in out, f"{what} should be {colour}"


def test_the_palette_is_the_saturated_ansi_set():
    """The vividness comes from using the ANSI brights exactly."""
    assert palette.BLUE == "#5555ff"
    assert palette.GREEN == "#55ff55"
    assert palette.CYAN == "#55ffff"
    assert palette.YELLOW == "#ffff55"
    assert palette.MAGENTA == "#ff55ff"
    assert palette.RED == "#ff5555"
    assert palette.FOREGROUND == "#ffffff"
    named = {palette.BLUE, palette.GREEN, palette.CYAN, palette.YELLOW,
             palette.MAGENTA, palette.RED, palette.FOREGROUND, palette.GREY}
    assert len(named) == 8, "every code colour must stay distinguishable"
