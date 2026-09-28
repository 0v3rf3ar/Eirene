"""Markdown in the assistant's answers."""

from __future__ import annotations

from rich.console import Console
from rich.text import Text

from eirene.ui.markup import CODE_STYLE, Markdown, block, inline


def styles(body: Text) -> list[tuple[str, str]]:
    """Every styled run, as (text, style)."""
    out = []
    for span in body.spans:
        out.append((body.plain[span.start:span.end], str(span.style)))
    return out


def styled(body: str, width: int = 70) -> str:
    console = Console(width=width, force_terminal=True, color_system="truecolor")
    with console.capture() as capture:
        console.print(Markdown(body))
    return capture.get()


def test_bold_loses_the_stars():
    body = inline("this is **important** now")
    assert body.plain == "this is important now"
    assert ("important", "bold") in styles(body)


def test_underscore_bold_works_too():
    body = inline("this is __important__ now")
    assert body.plain == "this is important now"
    assert ("important", "bold") in styles(body)


def test_italic_loses_the_stars():
    body = inline("a *quiet* word")
    assert body.plain == "a quiet word"
    assert ("quiet", "italic") in styles(body)


def test_underscores_inside_a_word_are_left_alone():
    assert inline("call some_helper_name now").plain == "call some_helper_name now"
    assert inline("a*b*c").plain == "a*b*c"


def test_inline_code_gets_its_own_look():
    body = inline("run `pytest -q` first")
    assert body.plain == "run pytest -q first"
    text, style = [pair for pair in styles(body) if pair[0] == "pytest -q"][0]
    assert style == CODE_STYLE
    assert CODE_STYLE == "#f0f6fc on #3b4149", "white on grey, not red"


def test_code_spans_keep_their_markers_inside():
    body = inline("use `**not bold**` here")
    assert body.plain == "use **not bold** here"


def test_strikethrough():
    body = inline("it was ~~useful~~ dead code")
    assert body.plain == "it was useful dead code"
    assert ("useful", "strike") in styles(body)


def test_a_link_shows_its_target():
    body = inline("see [the docs](https://example.com) for more")
    assert body.plain == "see the docs (https://example.com) for more"
    assert any(pair[0] == "the docs" and "underline" in pair[1]
               for pair in styles(body))
    assert any(span.style.meta.get("@click") == "open_link('https://example.com')"
               for span in body.spans)


def test_bare_url_is_clickable_without_trailing_punctuation():
    body = inline("Visit https://example.com/docs.")
    assert body.plain == "Visit https://example.com/docs."
    assert any(span.style.meta.get("@click") == "open_link('https://example.com/docs')"
               for span in body.spans)


def test_headings_lose_the_hashes():
    top = block("# Weekly plan")
    assert top.plain == "Weekly plan"
    assert "bold" in str(top.spans[0].style)
    assert "underline" in str(top.spans[0].style)
    lower = block("### Details")
    assert lower.plain == "Details"
    assert str(lower.spans[0].style) == "bold"


def test_bullets_become_a_dot():
    body = block("- first thing")
    assert body.plain == "• first thing"
    assert ("• ", "dim") in styles(body)


def test_a_bullet_keeps_its_indent():
    assert block("    - nested").plain == "    • nested"


def test_bullet_markers_do_not_dim_the_whole_line():
    body = block("- keep **this** bright")
    bold = [pair for pair in styles(body) if pair[0] == "this"]
    assert bold and bold[0][1] == "bold", "the marker style must not bleed"


def test_numbered_lists_keep_their_numbers():
    body = block("2. second step")
    assert body.plain == "2. second step"


def test_quotes_get_a_bar():
    body = block("> mind the gap")
    assert body.plain == "│ mind the gap"


def test_a_rule_becomes_a_line():
    assert set(block("---").plain) == {"─"}
    assert set(block("***").plain) == {"─"}
    assert block("-- not a rule").plain == "-- not a rule"


def test_the_backticks_never_show():
    body = "text\n```python\nx = **1**\n```\n"
    drawn = [line.plain.rstrip() for line in Markdown(body).lines()]
    assert "```" not in "".join(drawn)
    assert drawn[0] == "text"
    assert drawn[1].startswith("╭─ python ")
    assert "x = **1**" in drawn[2]
    assert drawn[3].startswith("╰")


def test_code_keeps_its_markers_inside_a_fence():
    drawn = [line.plain.rstrip() for line in
             Markdown("```py\nb = a ** 2  # ~~keep~~\n```").lines()]
    assert "b = a ** 2  # ~~keep~~" in drawn[-2]


def test_a_fence_without_a_language_has_no_label():
    drawn = [line.plain.rstrip() for line in Markdown("```\nraw text\n```").lines()]
    assert drawn[0].startswith("╭─")
    assert "raw text" in drawn[1]
    assert drawn[2].startswith("╰")


def test_code_lines_have_a_border_without_a_background():
    out = styled("```python\nx = 1\n```")
    assert "48;2;40;42;54" not in out
    plain = Markdown("```python\nx = 1\n```").plain()
    assert "╭─ python" in plain and "╰" in plain


def test_code_border_uses_the_normal_foreground_colour():
    from eirene.ui import palette

    top = Markdown("```python\nx = 1\n```").lines()[0]
    assert str(top.style) == "dim"
    assert all(palette.GREY not in str(span.style) for span in top.spans), \
        "the border must not borrow the comment colour"


def test_the_panel_spans_the_width():
    lines = Markdown("```python\nx = 1\n```", 50).lines()
    assert all(len(line.plain) == 50 for line in lines)


def test_fenced_code_is_highlighted():
    from eirene.ui import palette

    out = styled("```python\ndef go():\n    return 1\n```")
    red, green, blue = (int(palette.BLUE[i:i + 2], 16) for i in (1, 3, 5))
    assert f"38;2;{red};{green};{blue}" in out, "keywords keep the palette"


def test_prose_around_a_fence_still_renders():
    drawn = [line.plain.rstrip() for line in
             Markdown("**before**\n```\nraw\n```\n**after**").lines()]
    assert drawn[0] == "before"
    assert "raw" in drawn[2]
    assert drawn[-1] == "after"


def test_plain_prose_keeps_its_line_count():
    body = "# one\n\n- two **bold**\n\n> quote\n"
    assert len(Markdown(body).lines()) == len(body.splitlines())


def test_the_plain_mirror_matches_the_render():
    body = "# Title\n\nSome **bold** and `code` here.\n- a bullet\n"
    mirror = Markdown(body).plain()
    rendered = [line.plain for line in Markdown(body).lines()]
    assert mirror.splitlines() == rendered
    assert "**" not in mirror
    assert "`" not in mirror


def test_an_unfinished_marker_is_harmless():
    assert inline("half **way through").plain == "half **way through"
    drawn = [line.plain.rstrip() for line in Markdown("```python\ndef go():").lines()]
    assert drawn[0].startswith("╭─ python")
    assert "def go():" in drawn[1]
    assert drawn[2].startswith("╰")


def test_empty_input_is_one_blank_line():
    assert [line.plain for line in Markdown("").lines()] == [""]


def test_underline_from_html():
    body = inline("keep <u>this part</u> in mind")
    assert body.plain == "keep this part in mind"
    assert ("this part", "underline") in styles(body)


def test_underline_from_plus_signs():
    body = inline("keep ++this part++ in mind")
    assert body.plain == "keep this part in mind"
    assert ("this part", "underline") in styles(body)


def test_html_bold_italic_and_strike():
    assert ("loud", "bold") in styles(inline("a <b>loud</b> word"))
    assert ("soft", "italic") in styles(inline("a <i>soft</i> word"))
    assert ("gone", "strike") in styles(inline("a <del>gone</del> word"))


def test_a_table_becomes_a_grid():
    body = "| File | Lines |\n|------|-------|\n| a.py | 12 |\n"
    drawn = [line.plain for line in Markdown(body).lines()]
    assert drawn[0].startswith("┌") and drawn[0].endswith("┐")
    assert "File" in drawn[1] and "Lines" in drawn[1]
    assert drawn[2].startswith("├")
    assert "a.py" in drawn[3] and "12" in drawn[3]
    assert drawn[-1].startswith("└") and drawn[-1].endswith("┘")
    assert not any("|---" in line for line in drawn)


def test_table_columns_line_up():
    body = "| a | b |\n|---|---|\n| longer cell | x |\n"
    drawn = [line.plain for line in Markdown(body).lines()]
    assert len({len(line) for line in drawn}) == 1, "every row the same width"


def test_table_alignment_is_honoured():
    body = "| left | mid | right |\n|:-----|:---:|------:|\n| a | b | c |\n"
    row = [line.plain for line in Markdown(body).lines()][3]
    cells = [cell for cell in row.split("│") if cell.strip()]
    assert cells[0].startswith(" a"), "left aligned"
    assert cells[2].rstrip().endswith("c"), "right aligned"
    middle = cells[1]
    assert middle.index("b") > 1 and middle.rstrip() != middle


def test_table_cells_keep_their_markup():
    body = "| what | note |\n|------|------|\n| `x.py` | **big** |\n"
    lines = Markdown(body).lines()
    row = lines[3]
    assert "`" not in row.plain and "*" not in row.plain
    assert any("bold" in str(span.style) for span in row.spans)


def test_a_header_only_table_still_draws():
    body = "| one | two |\n|-----|-----|\n"
    drawn = [line.plain for line in Markdown(body).lines()]
    assert len(drawn) == 4
    assert "one" in drawn[1]


def test_a_lone_pipe_line_is_not_a_table():
    drawn = [line.plain for line in Markdown("| not a table").lines()]
    assert drawn == ["| not a table"]


def test_a_table_inside_a_fence_is_left_alone():
    body = "```\n| a | b |\n|---|---|\n```"
    drawn = [line.plain.rstrip() for line in Markdown(body).lines()]
    assert "| a | b |" in drawn[1]
    assert "|---|---|" in drawn[2]


def test_a_very_wide_cell_is_trimmed():
    from eirene.ui.markup import MAX_CELL
    body = f"| a |\n|---|\n| {'x' * 200} |\n"
    drawn = [line.plain for line in Markdown(body).lines()]
    assert all(len(line) <= MAX_CELL + 6 for line in drawn)
    assert "…" in drawn[3]


def test_wrapped_numbered_items_align_beneath_the_text_and_have_space():
    source = ("Common motivations include:\n"
              "10. **Emotional connection:** A desire for intimacy, affection, or companionship.\n"
              "11. **Novelty:** The excitement of discovering something new.\n"
              "Every situation is different.")
    lines = Markdown(source, 38).lines()
    plain = [line.plain for line in lines]
    first = next(i for i, line in enumerate(plain) if line.startswith("10."))
    second = next(i for i, line in enumerate(plain) if line.startswith("11."))
    assert plain[first - 1] == plain[second - 1] == ""
    assert all(line.startswith("    ") for line in plain[first + 1:second - 1])
    assert plain[-2] == "" and plain[-1] == "Every situation is different."
    assert all(line.cell_len <= 38 for line in lines)
    assert any("bold" in str(span.style) for line in lines for span in line.spans)


def test_short_lists_stay_compact_and_nested_lists_keep_hanging_indent():
    source = "- first\n- second\n    - nested detail " + "説明 " * 20
    lines = Markdown(source, 32).lines()
    assert [line.plain for line in lines[:2]] == ["• first", "• second"]
    nested = next(i for i, line in enumerate(lines) if line.plain.startswith("    •"))
    assert all(line.plain.startswith("      ") for line in lines[nested + 1:])
    assert all(line.cell_len <= 32 for line in lines)


def test_prose_has_a_readable_measure_and_blank_lines_do_not_accumulate():
    lines = Markdown("word " * 100 + "\n\n\n\nNext paragraph.", 180).lines()
    assert all(line.cell_len <= 88 for line in lines)
    plain = "\n".join(line.plain for line in lines)
    assert "\n\n\n" not in plain
    assert all(line.plain == line.plain.rstrip() for line in lines)
