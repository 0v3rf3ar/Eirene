"""Editing, pasting, completion and focus."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from textual import events

from eirene.app import Eirene
from eirene.ui.chat import UserBlock
from eirene.ui.format import display_path, pasted_label


class Recorder:
    """Provider stub that answers immediately."""

    supports_tools = True
    protocol = "test"

    async def stream(self, messages, model, *, system="", tools=None, max_tokens=8192):
        from eirene.providers.base import Done, TextDelta
        yield TextDelta("ok")
        yield Done("stop")

    async def models(self):
        return ["test-model"]


async def start(workdir, size=(100, 32)):
    app = Eirene(workdir)
    context = app.run_test(size=size)
    pilot = await context.__aenter__()
    await pilot.pause()
    return app, pilot, context


def content(widget) -> str:
    return widget._Static__content.plain


async def settle(pilot, times=4):
    for _ in range(times):
        await pilot.pause()


# placeholder

async def test_there_is_no_placeholder(workdir):
    app, pilot, context = await start(workdir)
    try:
        assert not getattr(app.prompt, "placeholder", "")
        assert app.prompt.text == ""
    finally:
        await context.__aexit__(None, None, None)


# multiline

async def test_backslash_enter_starts_a_new_line(workdir):
    app, pilot, context = await start(workdir)
    try:
        for char in "first\\":
            await pilot.press(char if char != "\\" else "backslash")
        await pilot.press("enter")
        await settle(pilot)
        assert app.prompt.text == "first\n", app.prompt.text
        assert app.prompt.document.line_count == 2
    finally:
        await context.__aexit__(None, None, None)


async def test_backslash_is_removed_from_the_line(workdir):
    app, pilot, context = await start(workdir)
    try:
        app.prompt.value = "one\\"
        await settle(pilot)
        await pilot.press("enter")
        await settle(pilot)
        assert "\\" not in app.prompt.text
        for char in "two":
            await pilot.press(char)
        await settle(pilot)
        assert app.prompt.text == "one\ntwo"
    finally:
        await context.__aexit__(None, None, None)


async def test_enter_without_a_backslash_sends(workdir):
    app, pilot, context = await start(workdir)
    try:
        app.prompt.value = "just send it"
        await settle(pilot)
        await pilot.press("enter")
        await settle(pilot)
        assert app.prompt.text == ""
        assert app.prompt.recent == ["just send it"]
    finally:
        await context.__aexit__(None, None, None)


async def test_theme_command_is_recalled_but_not_logged(workdir):
    app, pilot, context = await start(workdir)
    try:
        before = len(app.transcript.children)
        app.prompt.value = "/theme matrix"
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause()
            if app.command and app.command.done():
                break
        assert app.prompt.recent[-1] == "/theme matrix"
        assert len(app.transcript.children) == before
        await pilot.press("up")
        assert app.prompt.text == "/theme matrix"
    finally:
        await context.__aexit__(None, None, None)


async def test_multiline_message_is_sent_whole(workdir):
    app, pilot, context = await start(workdir)
    try:
        app.prompt.value = "alpha\\"
        await settle(pilot)
        await pilot.press("enter")
        for char in "beta":
            await pilot.press(char)
        await pilot.press("enter")
        await settle(pilot)
        sent = [content(b) for b in app.transcript.children
                if isinstance(b, UserBlock)]
        assert sent and "alpha" in sent[0] and "beta" in sent[0]
    finally:
        await context.__aexit__(None, None, None)


async def test_arrows_move_inside_a_multiline_draft(workdir):
    app, pilot, context = await start(workdir)
    try:
        app.prompt.value = "line one\nline two"
        await settle(pilot)
        assert app.prompt.cursor_location[0] == 1
        await pilot.press("up")
        await settle(pilot)
        assert app.prompt.cursor_location[0] == 0
        assert app.prompt.text == "line one\nline two", "must not recall history"
    finally:
        await context.__aexit__(None, None, None)


# paste folding

async def test_long_paste_is_folded(workdir):
    app, pilot, context = await start(workdir)
    try:
        pasted = "\n".join(f"line {n}" for n in range(23))
        app.prompt.post_message(events.Paste(pasted))
        await settle(pilot)
        assert app.prompt.text == "[pasted 23 lines]"
        assert app.prompt.unfold(app.prompt.text) == pasted
    finally:
        await context.__aexit__(None, None, None)


async def test_folded_paste_is_sent_in_full(workdir):
    app, pilot, context = await start(workdir)
    app.agent.use(Recorder(), "test", "test-model")
    try:
        pasted = "\n".join(f"line {n}" for n in range(23))
        app.prompt.post_message(events.Paste(pasted))
        await settle(pilot)
        await pilot.press("enter")
        for _ in range(40):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        body = app.session.path.read_text(encoding="utf-8")
        assert "line 22" in body, "the folded token must expand on send"
        assert "[pasted" not in body
    finally:
        await context.__aexit__(None, None, None)


async def test_short_paste_is_inserted_as_is(workdir):
    app, pilot, context = await start(workdir)
    try:
        app.prompt.post_message(events.Paste("hello there"))
        await settle(pilot)
        assert app.prompt.text == "hello there"
    finally:
        await context.__aexit__(None, None, None)


async def test_two_pastes_both_expand(workdir):
    app, pilot, context = await start(workdir)
    try:
        first = "\n".join(f"a{n}" for n in range(10))
        second = "\n".join(f"b{n}" for n in range(20))
        app.prompt.post_message(events.Paste(first))
        await settle(pilot)
        app.prompt.post_message(events.Paste(second))
        await settle(pilot)
        expanded = app.prompt.unfold(app.prompt.text)
        assert "a9" in expanded and "b19" in expanded
    finally:
        await context.__aexit__(None, None, None)


def test_paste_labels():
    assert pasted_label("a\nb\nc") == "[pasted 3 lines]"
    assert pasted_label("x" * 300) == "[pasted 300 chars]"


# slash menu

async def test_slash_opens_the_command_menu(workdir):
    app, pilot, context = await start(workdir)
    try:
        await pilot.press("slash")
        await settle(pilot)
        assert app.slash.open
        assert app.prompt.menu_open
        listing = content(app.slash)
        assert "/help" in listing and "/connect" in listing
    finally:
        await context.__aexit__(None, None, None)


async def test_slash_menu_is_alphabetical(workdir):
    app, pilot, context = await start(workdir)
    try:
        await pilot.press("slash")
        await settle(pilot)
        names = [name for name, _summary in app.slash.matches]
        assert names == sorted(names)
    finally:
        await context.__aexit__(None, None, None)


async def test_menu_filters_as_you_type(workdir):
    app, pilot, context = await start(workdir)
    try:
        await pilot.press("slash", "c", "o")
        await settle(pilot)
        listing = content(app.slash)
        assert "/connect" in listing
        assert "/help" not in listing
    finally:
        await context.__aexit__(None, None, None)


async def test_menu_closes_when_nothing_matches(workdir):
    app, pilot, context = await start(workdir)
    try:
        await pilot.press("slash", "z", "z")
        await settle(pilot)
        assert not app.slash.open
        assert not app.prompt.menu_open
    finally:
        await context.__aexit__(None, None, None)


async def test_arrows_drive_the_menu_not_history(workdir):
    app, pilot, context = await start(workdir)
    try:
        app.prompt.recent = ["earlier message"]
        app.prompt._position = 1
        await pilot.press("slash")
        await settle(pilot)
        first = app.slash.choice
        await pilot.press("down")
        await settle(pilot)
        assert app.slash.choice != first
        assert app.prompt.text == "/", "history must not fire while the menu is open"
    finally:
        await context.__aexit__(None, None, None)


async def test_enter_runs_the_command_straight_away(workdir):
    """Typing /usage and pressing enter must not need a second enter."""
    app, pilot, context = await start(workdir)
    try:
        for char in "/usage":
            await pilot.press("slash" if char == "/" else char)
        await settle(pilot)
        assert app.slash.open
        await pilot.press("enter")
        for _ in range(30):
            await pilot.pause()
            if app.command and app.command.done():
                break
        assert app.prompt.text == "", "no leftover text to re-send"
        assert app.prompt.recent[-1] == "/usage"
        assert not app.slash.open
        body = content(app.aside.body)
        assert "nothing sent yet" in body, "the command actually ran"
        assert app.aside.open
    finally:
        await context.__aexit__(None, None, None)


async def test_enter_runs_exit_on_the_first_press(workdir):
    app, pilot, context = await start(workdir)
    for char in "/exit":
        await pilot.press("slash" if char == "/" else char)
    await settle(pilot)
    await pilot.press("enter")
    for _ in range(30):
        await pilot.pause()
        if not app.is_running:
            break
    assert not app.is_running, "one enter must be enough"
    await context.__aexit__(None, None, None)


async def test_enter_on_a_partial_name_runs_the_highlighted_one(workdir):
    app, pilot, context = await start(workdir)
    try:
        await pilot.press("slash", "u")
        await settle(pilot)
        assert app.slash.choice == "usage"
        await pilot.press("enter")
        for _ in range(30):
            await pilot.pause()
            if app.command and app.command.done():
                break
        assert app.prompt.text == ""
        assert app.prompt.recent[-1] == "/usage"
    finally:
        await context.__aexit__(None, None, None)


async def test_enter_completes_commands_that_need_arguments(workdir):
    app, pilot, context = await start(workdir)
    try:
        await pilot.press("slash", "b", "t", "w")
        await settle(pilot)
        await pilot.press("enter")
        await settle(pilot)
        assert app.prompt.text == "/btw ", "leave room for the question"
        assert not app.slash.open
    finally:
        await context.__aexit__(None, None, None)


async def test_tab_completes_without_running(workdir):
    app, pilot, context = await start(workdir)
    try:
        await pilot.press("slash", "s", "k")
        await settle(pilot)
        await pilot.press("tab")
        await settle(pilot)
        assert app.prompt.text == "/skills "
        assert app.command is None, "tab completes, it does not run"
    finally:
        await context.__aexit__(None, None, None)


async def test_esc_dismisses_the_menu_and_keeps_the_text(workdir):
    app, pilot, context = await start(workdir)
    try:
        await pilot.press("slash", "h")
        await settle(pilot)
        assert app.slash.open
        await pilot.press("escape")
        await settle(pilot)
        assert not app.slash.open
        assert app.prompt.text == "/h"
    finally:
        await context.__aexit__(None, None, None)


async def test_recalling_a_slash_command_does_not_reopen_the_menu(workdir):
    app, pilot, context = await start(workdir)
    try:
        app.prompt.value = "/usage"
        await settle(pilot)
        await pilot.press("enter")
        await settle(pilot)
        await pilot.press("up")
        await settle(pilot)
        assert app.prompt.text == "/usage"
        assert not app.slash.open, "recall must not hijack the next arrow key"
    finally:
        await context.__aexit__(None, None, None)


# focus

async def test_typing_anywhere_lands_in_the_input(workdir):
    app, pilot, context = await start(workdir)
    try:
        app.set_focus(None)
        await settle(pilot)
        assert not app.prompt.has_focus
        await pilot.press("h", "e", "y")
        await settle(pilot)
        assert app.prompt.has_focus
        assert app.prompt.text == "hey"
    finally:
        await context.__aexit__(None, None, None)


async def test_the_transcript_never_takes_focus(workdir):
    app, pilot, context = await start(workdir)
    try:
        assert not app.transcript.can_focus
        assert not app.transcript.can_focus_children
        assert app.prompt.has_focus
    finally:
        await context.__aexit__(None, None, None)


async def test_arrows_do_not_scroll_the_transcript(workdir):
    app, pilot, context = await start(workdir)
    try:
        for index in range(40):
            await app.push(UserBlock(f"message {index}"))
        await settle(pilot)
        before = app.transcript.scroll_offset.y
        await pilot.press("up")
        await pilot.press("up")
        await settle(pilot)
        assert app.transcript.scroll_offset.y == before
    finally:
        await context.__aexit__(None, None, None)


# appearance

async def test_user_rows_have_a_full_width_grey_background(workdir):
    app, pilot, context = await start(workdir)
    try:
        block = await app.push(UserBlock("hello"))
        await settle(pilot)
        assert block.styles.background.hex.lower() == "#30343a", "grey row background"
        assert block.styles.color.hex.lower() == "#f8f8f2", "sent text must stay white"
        assert block.region.width == app.size.width
    finally:
        await context.__aexit__(None, None, None)


async def test_sent_text_selection_contrasts_with_the_user_row(workdir):
    app, pilot, context = await start(workdir)
    try:
        theme = app.get_theme("eirene")
        assert theme.variables["screen-selection-background"] == "ansi_bright_blue"
        assert theme.variables["screen-selection-foreground"] == "ansi_black"
        assert theme.variables["screen-selection-background"] != "ansi_bright_black"
    finally:
        await context.__aexit__(None, None, None)


async def test_the_theme_is_ansi_so_the_terminal_shows_through(workdir):
    app, pilot, context = await start(workdir)
    try:
        theme = app.get_theme("eirene")
        assert theme.ansi is True
        assert theme.background == "ansi_default"
        assert theme.variables["ansi-background"] == "ansi_default"
    finally:
        await context.__aexit__(None, None, None)


# paths

def test_home_becomes_a_tilde(monkeypatch, tmp_path):
    if os.name == "nt":
        pytest.skip("posix only")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert display_path(tmp_path / "code" / "app") == "~/code/app"
    assert display_path(tmp_path) == "~"


def test_paths_outside_home_are_untouched(monkeypatch, tmp_path):
    if os.name == "nt":
        pytest.skip("posix only")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    assert display_path("/srv/app") == "/srv/app"


def test_a_similar_prefix_is_not_mistaken_for_home(monkeypatch, tmp_path):
    if os.name == "nt":
        pytest.skip("posix only")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/home/bob")))
    assert display_path("/home/bobby/code") == "/home/bobby/code"


def test_long_paths_are_shortened():
    long = "/" + "/".join(f"segment{n}" for n in range(12))
    shown = display_path(long, limit=40)
    assert len(shown) <= 41
    assert shown.endswith("segment11")
    assert "…" in shown


@pytest.mark.skipif(os.name != "nt", reason="windows only")
def test_windows_keeps_the_whole_path():
    assert display_path("C:\\Users\\me\\code") == "C:\\Users\\me\\code"


def test_elided_paths_have_no_double_separator():
    long = "/tmp/claude-1000/-home-user-project/abcdef0123456789/scratchpad/work"
    shown = display_path(long, limit=40)
    assert "//" not in shown
    assert shown.startswith("/…/")
    assert shown.endswith("work")


def test_a_single_huge_segment_is_clamped_to_the_limit():
    long = "/" + "/".join("x" * 30 for _ in range(6))
    shown = display_path(long, limit=20)
    assert len(shown) == 20, "the limit wins over keeping a segment whole"
    assert shown.startswith("…")
    assert shown.endswith("x")


@pytest.mark.parametrize("limit", range(4, 40))
def test_display_path_never_exceeds_its_limit(limit):
    long = "/tmp/claude-1000/-home-user-project/deadbeef/scratchpad/work"
    assert len(display_path(long, limit=limit)) <= limit


async def test_mouse_wheel_still_scrolls(workdir):
    from textual.events import MouseScrollDown

    app, pilot, context = await start(workdir)
    try:
        for index in range(60):
            await app.push(UserBlock(f"message {index}"))
        await settle(pilot)
        app.transcript.scroll_to(y=0, animate=False)
        await settle(pilot)
        assert app.transcript.scroll_offset.y == 0
        for _ in range(5):
            app.transcript.post_message(
                MouseScrollDown(widget=app.transcript, x=1, y=1, delta_x=0, delta_y=1,
                                button=0, shift=False, meta=False, ctrl=False,
                                screen_x=1, screen_y=1))
        await settle(pilot, 8)
        assert app.transcript.scroll_offset.y > 0, "the wheel must still scroll"
    finally:
        await context.__aexit__(None, None, None)


def test_every_banner_is_intact():
    from rich.cells import cell_len
    from eirene.ui import art

    assert len(art.BANNERS) == 2
    for text in art.BANNERS:
        lines = text.strip("\n").splitlines()
        assert lines
        assert all(cell_len(line) == len(line) for line in lines), \
            "banners must use single-cell glyphs or the layout drifts"
        assert "\x1b" not in text, "no embedded colour escapes"
        assert not any(line.rstrip() != line for line in lines), \
            "no trailing whitespace"


def test_banners_are_sorted_by_width():
    from eirene.ui import art
    widths = [size for _, size in art.SIZED]
    assert widths == sorted(widths)
    assert widths[0] == 16 and widths[-1] == 24


def test_banners_include_requested_art_and_all_click_animations():
    from eirene.ui import art

    wanted = ("┏━╸╻┏━┓┏━╸┏┓╻┏━╸", "░█▀▀░▀█▀░█▀▄")
    for gone in ("▗▄▄▄▖▄  ▄▄▄ ▗▞▀▚▖", "█▀██▀▀▀", "▄▄▄ .▪  ▄▄▄"):
        assert not any(gone in banner for banner in art.BANNERS), gone
    for fragment in wanted:
        assert any(fragment in banner for banner in art.BANNERS), fragment
    effects = {art.banner_animation(banner) for banner in art.BANNERS}
    assert effects == set(art.SIGNATURES)
    assert len(art.SIGNATURES) == len(art.BANNERS)


def test_startup_tips_have_multiple_deterministic_choices():
    from eirene.ui import art

    assert len(art.TIPS) >= 6
    assert {art.tip(seed) for seed in range(len(art.TIPS))} == set(art.TIPS)


def test_banner_choice_is_random_but_always_fits():
    from eirene.ui import art

    seen = {art.banner(100) for _ in range(200)}
    assert len(seen) == len(art.BANNERS), "every banner should turn up"
    for width in range(4, 120):
        chosen = art.banner(width)
        assert art.art_width(chosen) <= max(width - art.BANNER_MARGIN, 1) \
            or chosen == "eirene"


@pytest.mark.parametrize("width,expected", [
    (100, "big"), (58, "big"), (50, "big"), (49, "big"), (28, "big"),
    (27, "big"), (20, "big"),
    (19, "tiny"), (15, "tiny"),
    (14, "word"), (4, "word"),
])
def test_banner_steps_down_as_the_terminal_shrinks(width, expected):
    from eirene.ui import art

    chosen = art.banner(width)
    if expected == "big":
        assert chosen.strip("\n") in [t for t, _ in art.SIZED]
    elif expected == "tiny":
        assert chosen == art.TINY_BANNER
    else:
        assert chosen == "eirene"


@pytest.mark.parametrize("size", [(100, 32), (46, 20), (26, 14), (18, 10), (10, 8)])
async def test_banner_never_overflows_the_terminal(workdir, size):
    from eirene.ui.chat import ArtBlock
    from rich.cells import cell_len

    app, pilot, context = await start(workdir, size=size)
    try:
        arts = [b for b in app.transcript.children if isinstance(b, ArtBlock)]
        assert arts, "a banner is always shown"
        shown = content(arts[0])
        for line in shown.splitlines():
            assert cell_len(line) <= app.size.width
        assert app.transcript.region.width <= app.size.width
        rendered = arts[0].size.height
        assert rendered == len(shown.splitlines()), "the banner must not wrap"
    finally:
        await context.__aexit__(None, None, None)


async def test_a_tiny_terminal_still_starts(workdir):
    app, pilot, context = await start(workdir, size=(12, 6))
    try:
        assert app.is_running
        assert app.prompt.has_focus
        app.prompt.value = "hi"
        await settle(pilot)
        assert app.prompt.text == "hi"
    finally:
        await context.__aexit__(None, None, None)


async def test_a_command_with_arguments_still_sends_on_enter(workdir):
    from eirene.core.modes import Mode

    app, pilot, context = await start(workdir)
    try:
        app.prompt.value = "/agents plan"
        await settle(pilot)
        assert not app.slash.open, "a space closes the completion menu"
        await pilot.press("enter")
        for _ in range(30):
            await pilot.pause()
            if app.command and app.command.done():
                break
        assert app.agent.mode is Mode.PLAN
        assert app.prompt.text == ""
    finally:
        await context.__aexit__(None, None, None)


async def test_typing_a_command_then_a_space_leaves_the_menu(workdir):
    app, pilot, context = await start(workdir)
    try:
        for char in "/btw":
            await pilot.press("slash" if char == "/" else char)
        await settle(pilot)
        assert app.slash.open
        await pilot.press("space")
        await settle(pilot)
        assert not app.slash.open
        assert app.prompt.text == "/btw "
    finally:
        await context.__aexit__(None, None, None)


async def test_the_api_key_is_masked_while_typing(workdir):
    app, pilot, context = await start(workdir)
    try:
        asking = asyncio.create_task(app.ask_text("API key", secret=True))
        await pilot.pause()
        await pilot.press(*"sk-secret-1")
        await pilot.pause()
        prompt = app.prompt
        assert prompt.value == "sk-secret-1"
        assert prompt.get_line(0).plain == "•" * 11
        await pilot.press("enter")
        assert await asking == "sk-secret-1"
    finally:
        await context.__aexit__(None, None, None)


async def test_a_secret_never_lands_in_the_history(workdir):
    app, pilot, context = await start(workdir)
    try:
        asking = asyncio.create_task(app.ask_text("API key", secret=True))
        await pilot.pause()
        await pilot.press(*"sk-secret-2")
        await pilot.press("enter")
        assert await asking == "sk-secret-2"
        await pilot.pause()
        assert "sk-secret-2" not in app.prompt.recent
    finally:
        await context.__aexit__(None, None, None)


async def test_masking_is_dropped_afterwards(workdir):
    app, pilot, context = await start(workdir)
    try:
        asking = asyncio.create_task(app.ask_text("API key", secret=True))
        await pilot.pause()
        await pilot.press(*"abcdefgh")
        await pilot.press("enter")
        await asking
        await pilot.pause()
        app.prompt.value = "plain text"
        assert app.prompt.get_line(0).plain == "plain text"
    finally:
        await context.__aexit__(None, None, None)


def test_notices_never_carry_control_characters_into_the_transcript():
    from eirene.ui.format import safe_notice

    assert safe_notice("hostile \x1b[2Jtext\rwith\x07control") == "hostile text with control"
    assert safe_notice("a\tb  c") == "a b c"
    assert safe_notice("") == ""
    assert safe_notice("keeps\nits\nlines") == "keeps\nits\nlines", "height must survive"
    long = safe_notice("word " * 200)
    assert len(long) <= 401 and long.endswith("…")
