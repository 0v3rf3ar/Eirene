"""The companion follows live work without interfering with the input."""

import pytest

from eirene.ui.companion import ASSETS, Companion, PORTRAITS, emotion, portrait_frame, prepare_renderer
from eirene.ui.status import StatusLine


def test_parallel_writes_hold_expression_until_last_write_finishes(monkeypatch):
    status = StatusLine()
    monkeypatch.setattr(status, "update", lambda body: None)
    status.start()
    status.start_tool("edit-a", "write")
    status.start_tool("read", "read")
    status.start_tool("edit-b", "write")
    assert emotion(status, 1000) == "writing"
    status.finish_tool("edit-a")
    assert emotion(status, 1000) == "writing"
    status.finish_tool("edit-b")
    assert emotion(status, 1000) == "working"
    status.finish_tool("read")
    status.set_phase("reasoning")
    assert emotion(status, 1000) == "thinking"
    status.stop()
    assert emotion(status, 0) == "idle"
    assert emotion(status, 0, waiting_for_user=True) == "question"
    assert emotion(status, 61, waiting_for_user=True) == "sleepy"
    assert emotion(status, 61) == "sleepy"
    status.start()
    assert emotion(status, 61) == "thinking"
    status.set_phase("idle")
    assert emotion(status, 0) == "idle"
    assert emotion(status, 61) == "sleepy"


def test_plain_output_does_not_probe_terminal(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert prepare_renderer({}) is None


def test_kitty_auto_widget_is_recognized(monkeypatch):
    from types import SimpleNamespace
    import textual_image.widget as widgets
    import eirene.ui.companion as companion_mod
    from eirene.ui.kitty_portrait import KittyPortrait

    class AutoKittyImage:
        _Renderable = widgets.TGPImage._Renderable

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(companion_mod, "sys", SimpleNamespace(
        __stdout__=SimpleNamespace(isatty=lambda: True)))
    monkeypatch.setattr(widgets, "Image", AutoKittyImage)
    assert prepare_renderer({}) is KittyPortrait


def test_sixel_and_ordinary_terminal_detection(monkeypatch):
    from types import SimpleNamespace
    import textual_image.widget as widgets
    import eirene.ui.companion as companion_mod

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(companion_mod, "sys", SimpleNamespace(
        __stdout__=SimpleNamespace(isatty=lambda: True)))
    monkeypatch.setattr(widgets, "Image", widgets.SixelImage)
    from eirene.ui.sixel_portrait import SixelPortrait
    assert prepare_renderer({}) is SixelPortrait
    monkeypatch.setattr(widgets, "Image", widgets.HalfcellImage)
    assert prepare_renderer({}) is None


@pytest.mark.parametrize("name", ["idle.png", "idle-blink.png", "q.png", "work.png", "sleepy.png", "angry.png", "furious.png"])
def test_packaged_portraits_touch_the_bottom_of_the_frame(name):
    from PIL import Image
    path = ASSETS / name
    assert path.stat().st_size < 5_000
    with Image.open(path) as source:
        assert source.size == (128, 128)
        assert source.info["Author"] == "s3p"
    frame = portrait_frame(name)
    assert frame.size == (128, 128) and frame.mode == "RGBA"
    assert frame.getchannel("A").getbbox()[3] == frame.height
    assert frame.getpixel((0, 0))[3] == 0


def test_blink_keeps_same_silhouette_size_and_position():
    idle = portrait_frame("idle.png")
    blink = portrait_frame("idle-blink.png")
    assert idle.getchannel("A").getbbox() == blink.getchannel("A").getbbox()
    assert idle.tobytes() != blink.tobytes()


def test_sixel_encoder_skips_transparent_pixels_including_last_band():
    from PIL import Image
    from eirene.ui.sixel_portrait import transparent_sixels

    image = Image.new("RGBA", (4, 8), (0, 0, 0, 0))
    image.putpixel((1, 0), (255, 0, 0, 255))
    image.putpixel((1, 5), (255, 0, 0, 255))
    image.putpixel((2, 7), (255, 0, 0, 255))
    data = transparent_sixels(image)
    assert data.startswith('\x1bP0;1;0q"1;1;4;8')
    assert ";2;100;0;0" in data
    assert ";2;0;0;0" not in data, "transparent black must never get a color register"
    assert "?`$-" in data, "rows 0 and 5 are painted; other bits stay transparent"
    assert "??A$\x1b\\" in data, "partial last band paints only row 7"


@pytest.mark.parametrize("platform,terminal,inline,expected", [
    ("win32", "windows-terminal", False, True),
    ("win32", "", False, False),
    ("linux", "windows-terminal", False, False),
    ("win32", "windows-terminal", True, False),
])
def test_windows_terminal_updates_enable_sync(monkeypatch, platform, terminal, inline, expected):
    from types import SimpleNamespace
    from textual.app import App
    from textual._compositor import CompositorUpdate
    import eirene.app as app_mod

    monkeypatch.setattr(app_mod, "sys", SimpleNamespace(platform=platform))
    monkeypatch.setenv("WT_SESSION", terminal)
    calls = []
    monkeypatch.setattr(App, "_display", lambda self, screen, update: calls.append(self._sync_available))
    app = app_mod.Eirene.__new__(app_mod.Eirene)
    app._driver = SimpleNamespace(is_inline=inline)
    app._sync_available = False
    app_mod.Eirene._display(app, SimpleNamespace(query=lambda widget: []), CompositorUpdate())
    assert calls == [expected]


async def test_sixel_overlay_survives_typing_blinks_resize_and_disable(workdir, monkeypatch):
    from types import SimpleNamespace
    from textual.app import App
    from eirene.ui.sixel_portrait import PortraitUpdate, SixelPortrait
    import eirene.app as app_mod
    from test_tui import start

    frames = []
    original_display = App._display

    def capture(self, screen, renderable):
        if isinstance(renderable, PortraitUpdate):
            frames.append(renderable.render_segments(self.console))
        original_display(self, screen, renderable)

    monkeypatch.setattr(app_mod, "prepare_renderer", lambda config: SixelPortrait)
    monkeypatch.setattr(App, "_display", capture)
    app, pilot, context = await start(workdir, companion=True)
    try:
        companion = app.query_one(Companion)
        portrait = companion._portrait
        assert not companion.visible and not portrait.visible
        initial = portrait.terminal_sequence()
        assert '\x1bP0;1;0q' in initial and initial.endswith("\x1b8")
        cached = portrait._encoded
        for key in "hello":
            await pilot.press(key)
            assert portrait.terminal_sequence() == initial
            assert portrait._encoded is cached
            assert not portrait.children, "no Sixel implementation is recomposed"
        assert app.prompt.value == "hello"
        assert any('\x1bP0;1;0q' in frame for frame in frames)
        assert portrait._placement_region.bottom == app.query("Composer Rule").first().region.y
        region = portrait._placement_region
        update = SimpleNamespace(spans=[(region.bottom + 1, 0, app.size.width)],
                                 render_segments=lambda console: "text update")
        assert PortraitUpdate(update, portrait).render_segments(app.console) == "text update"
        update.spans = [(region.bottom - 1, region.x, region.right)]
        assert '\x1bP0;1;0q' in PortraitUpdate(update, portrait).render_segments(app.console)
        companion._tick = 8
        companion.refresh_companion()
        assert companion._drawn == "idle-blink.png"
        assert portrait.terminal_sequence() != initial
        assert companion._portrait is portrait
        await pilot.resize_terminal(64, 24)
        await pilot.pause()
        assert portrait._placement_region.bottom == app.query("Composer Rule").first().region.y
        app.config.set("companion", False)
        companion.refresh_companion()
        await pilot.pause()
        assert portrait.terminal_sequence() == ""
        assert not portrait._placed
        assert '\x1bP0;1;0q' not in frames[-1]
    finally:
        await context.__aexit__(None, None, None)


async def test_sleep_wake_reduced_motion_and_compact_layout(workdir, monkeypatch):
    from textual_image.widget import HalfcellImage
    import eirene.app as app_mod
    from test_tui import start

    monkeypatch.setattr(app_mod, "prepare_renderer", lambda config: HalfcellImage)
    app, pilot, context = await start(workdir, companion=True)
    try:
        companion = app.query_one(Companion)
        companion._last_interaction -= 61
        companion.refresh_companion()
        assert companion.state == "sleepy"
        await pilot.press("x")
        companion.refresh_companion()
        assert companion.state == "idle"
        assert app.prompt.value == "x"
        app.config.set("reduce_motion", True)
        companion.refresh_companion()
        assert companion._tick == 0
        await pilot.resize_terminal(40, 18)
        companion.refresh_companion()
        assert not companion.display
        assert app.prompt.region.bottom <= app.size.height
        await pilot.resize_terminal(100, 32)
        companion.refresh_companion()
        assert companion.display
        app.config.set("companion", False)
        companion.refresh_companion()
        assert not companion.display
    finally:
        await context.__aexit__(None, None, None)


async def test_graphics_companion_stays_on_input_border_and_blinks(workdir, monkeypatch):
    from textual_image.widget import HalfcellImage
    import eirene.app as app_mod
    from test_tui import start

    # Exercise the real image widget without requiring a physical graphics terminal.
    monkeypatch.setattr(app_mod, "prepare_renderer", lambda config: HalfcellImage)
    app, pilot, context = await start(workdir, companion=True)
    try:
        companion = app.query_one(Companion)
        assert companion.display
        assert len(companion.children) == 1
        assert companion._portrait.region.height == 6
        assert companion.region.bottom <= app.prompt.region.y
        assert companion._portrait.region.right <= app.size.width
        image = companion._portrait.image
        companion._tick = 0
        for _ in range(8):
            companion.refresh_companion()
            assert companion._portrait.image is image
        companion.refresh_companion()
        assert companion._portrait.image is not image, "idle animation is a blink"
        assert image.getchannel("A").getbbox() == companion._portrait.image.getchannel("A").getbbox()
        assert companion._portrait.image.getchannel("A").getbbox()[3] == 128
        assert companion._portrait.region.bottom == app.query("Rule").first().region.y
        app.status.start()
        app.status.start_tool("file", "write")
        companion.refresh_companion()
        assert companion.state == "writing"
        assert companion._portrait.image.getchannel("A").getbbox()[3] == 128
        app.config.set("reduce_motion", True)
        companion.refresh_companion()
        image = companion._portrait.image
        companion.refresh_companion()
        assert companion._portrait.image is image
        app.status.stop()
        companion.refresh_companion()
        assert companion.state == "idle"
        await pilot.resize_terminal(64, 24)
        await pilot.pause()
        assert companion.region.bottom <= app.prompt.region.y
        assert companion._portrait.region.bottom == app.query("Rule").first().region.y
    finally:
        await context.__aexit__(None, None, None)


async def test_no_graphics_has_no_fallback_or_reserved_space(workdir):
    from test_tui import start

    app, pilot, context = await start(workdir, companion=True)
    try:
        companion = app.query_one(Companion)
        assert not companion.display
        assert not companion.children
        assert companion.region.height == 0
    finally:
        await context.__aexit__(None, None, None)


async def test_companion_never_changes_status_input_or_transcript_layout(workdir, monkeypatch):
    from textual_image.widget import HalfcellImage
    import eirene.app as app_mod
    from test_tui import start

    monkeypatch.setattr(app_mod, "prepare_renderer", lambda config: HalfcellImage)
    app, pilot, context = await start(workdir, companion=True)
    try:
        companion = app.query_one(Companion)
        assert companion.parent is app.screen
        app.status.start()
        for size in ((100, 32), (64, 24)):
            await pilot.resize_terminal(*size)
            for draft in ("", "first line\nsecond line\nthird line"):
                app.prompt.value = draft
                app.config.set("companion", False)
                companion.refresh_companion()
                await pilot.pause()
                widgets = [app.query_one("Composer"), app.status, app.prompt,
                           app.mode_line, app.transcript, app.query("Rule").first()]
                original = [widget.region for widget in widgets]
                app.config.set("companion", True)
                companion.refresh_companion()
                await pilot.pause()
                assert companion.display
                assert [widget.region for widget in widgets] == original
                assert companion._portrait.region.bottom == app.query("Rule").first().region.y
    finally:
        await context.__aexit__(None, None, None)


async def test_thinking_uses_laptop_and_completed_answer_returns_to_idle(workdir, monkeypatch):
    import asyncio
    from textual_image.widget import HalfcellImage
    import eirene.app as app_mod
    from eirene.providers.base import TextDelta, Done
    from test_tui import Script, start, type_line

    monkeypatch.setattr(app_mod, "prepare_renderer", lambda config: HalfcellImage)
    finish = asyncio.Event()

    class SlowReply(Script):
        async def stream(self, *args, **kwargs):
            yield TextDelta("Hello")
            await finish.wait()
            yield Done("stop")

    app, pilot, context = await start(workdir, SlowReply(), companion=True)
    try:
        companion = app.query_one(Companion)
        assert companion.state == "idle"
        await type_line(pilot, "hello")
        companion.refresh_companion()
        assert PORTRAITS[companion.state] == "work.png"
        finish.set()
        for _ in range(40):
            await pilot.pause()
            if app.turn.done():
                break
        assert app.turn.done()
        assert companion.state == "idle"
        await pilot.press("x")
        companion.refresh_companion()
        assert companion.state == "idle"
        companion.finish_turn(False)
        assert companion.state == "idle"
    finally:
        finish.set()
        await context.__aexit__(None, None, None)


@pytest.mark.parametrize("kind", ["question", "approval", "menu"])
async def test_question_pose_only_for_model_questions_and_approvals(workdir, monkeypatch, kind):
    import asyncio
    from textual_image.widget import HalfcellImage
    import eirene.app as app_mod
    from test_tui import start

    monkeypatch.setattr(app_mod, "prepare_renderer", lambda config: HalfcellImage)
    app, pilot, context = await start(workdir, companion=True)
    task = None
    try:
        companion = app.query_one(Companion)
        if kind == "question":
            task = asyncio.create_task(app._choose("Which approach?", ["A", "B"]))
        elif kind == "approval":
            task = asyncio.create_task(app._approve("write_file", "a.txt", "", "Allow edit?"))
        else:
            task = asyncio.create_task(app.ask_choice("Theme", [("default", "Default", "")]))
        await pilot.pause()
        companion.refresh_companion()
        assert companion.state == ("idle" if kind == "menu" else "question")
        if kind != "menu":
            companion._last_interaction -= 61
            companion.refresh_companion()
            assert companion.state == "sleepy"
            companion.wake()
            companion.refresh_companion()
            assert companion.state == "question"
        app.picker.cancel()
        app.permission.cancel()
        await task
        companion.refresh_companion()
        assert companion.state == "idle"
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await context.__aexit__(None, None, None)


async def test_prose_question_remains_until_next_turn(workdir):
    from test_tui import start

    app, pilot, context = await start(workdir, companion=True)
    try:
        companion = app.query_one(Companion)
        companion.finish_turn(asking=True)
        assert companion.state == "question"
        companion.wake()
        companion.refresh_companion()
        assert companion.state == "question"
        app.status.start()
        companion.start_turn()
        assert companion.state == "thinking"
        assert PORTRAITS[companion.state] == "work.png"
    finally:
        await context.__aexit__(None, None, None)


async def test_kitty_overlay_preserves_alpha_without_painting_text_background(workdir, monkeypatch):
    import base64
    import io
    from PIL import Image
    import eirene.app as app_mod
    from eirene.ui.kitty_portrait import KittyPortrait
    from test_tui import start

    output = []
    monkeypatch.setattr(app_mod, "prepare_renderer", lambda config: KittyPortrait)
    monkeypatch.setattr(KittyPortrait, "_write", lambda self, data: output.append(data))
    app, pilot, context = await start(workdir, companion=True)
    try:
        companion = app.query_one(Companion)
        portrait = companion._portrait
        assert companion.display
        assert not companion.visible and not portrait.visible
        assert portrait._placement_region.height == 6 and portrait._placement_region.width > 0
        assert portrait._placement_region.bottom == app.query("Rule").first().region.y
        uploads = [item for item in output if "a=t," in item]
        assert uploads
        chunks = []
        for command in uploads[-1].split("\x1b_G")[1:]:
            chunks.append(command.split(";", 1)[1].removesuffix("\x1b\\"))
        with Image.open(io.BytesIO(base64.b64decode("".join(chunks)))) as image:
            assert image.mode == "RGBA"
            assert image.getpixel((0, 0))[3] == 0
        placements = [item for item in output if "a=p," in item]
        assert placements and "z=1" in placements[-1] and "C=1" in placements[-1]
        assert "U=1" not in placements[-1], "no background-painting Unicode placeholders"
        assert placements[-1].endswith("\x1b8"), "restore the input cursor"
        app.config.set("companion", False)
        companion.refresh_companion()
        assert "a=d,d=I" in output[-1]
        assert not portrait._uploaded and not portrait._placed
    finally:
        await context.__aexit__(None, None, None)


async def test_clicks_escalate_anger_and_cool_down_to_current_activity(workdir, monkeypatch):
    from types import SimpleNamespace
    from textual_image.widget import HalfcellImage
    import eirene.app as app_mod
    import eirene.ui.companion as companion_mod
    from test_tui import start

    monkeypatch.setattr(app_mod, "prepare_renderer", lambda config: HalfcellImage)
    app, pilot, context = await start(workdir, companion=True)
    try:
        companion = app.query_one(Companion)
        clock = SimpleNamespace(now=companion._last_interaction)
        monkeypatch.setattr(companion_mod, "time", SimpleNamespace(monotonic=lambda: clock.now))
        region = companion._portrait.region
        x, y = region.x + region.width // 2, region.y + region.height // 2
        assert not companion.poke_at(region.x, region.y), "transparent padding is not clickable"
        assert not companion.poke_at(0, 0)
        assert companion._poke_count == 0
        assert companion.poke_at(x, y)
        assert companion.state == "angry"
        assert companion._angry_until == pytest.approx(clock.now + 1.0)
        clock.now += 0.5
        assert companion.poke_at(x, y)
        assert companion.state == "angry"
        clock.now += 0.5
        assert companion.poke_at(x, y)
        assert companion.state == "furious"
        assert companion._angry_until == pytest.approx(clock.now + 1.3)
        app.status.start()
        clock.now = companion._angry_until - 0.001
        companion.refresh_companion()
        assert companion.state == "furious"
        clock.now = companion._angry_until
        companion.refresh_companion()
        assert companion.state == "thinking"
        clock.now += 3
        assert companion.poke_at(x, y)
        assert companion.state == "angry", "a later click starts a fresh reaction"
        companion._asked_question = True
        clock.now = companion._angry_until - 0.001
        companion.refresh_companion()
        assert companion.state == "angry"
        clock.now = companion._angry_until
        companion.refresh_companion()
        assert companion.state == "question"
    finally:
        await context.__aexit__(None, None, None)


async def test_native_kitty_picture_reacts_to_real_mouse_events(workdir, monkeypatch):
    import eirene.app as app_mod
    from eirene.ui.kitty_portrait import KittyPortrait
    from test_tui import start

    monkeypatch.setattr(app_mod, "prepare_renderer", lambda config: KittyPortrait)
    monkeypatch.setattr(KittyPortrait, "_write", lambda self, data: None)
    app, pilot, context = await start(workdir, companion=True)
    try:
        companion = app.query_one(Companion)
        region = companion._portrait._placement_region
        point = (region.x + region.width // 2, region.y + region.height // 2)
        await pilot.click(app.screen, offset=point)
        assert companion.state == "angry"
        await pilot.click(app.screen, offset=point)
        await pilot.click(app.screen, offset=point)
        assert companion.state == "furious"
        assert app.prompt.value == ""
    finally:
        await context.__aexit__(None, None, None)


async def test_companion_command_is_opt_in_and_saves_toggle(workdir, monkeypatch):
    from textual_image.widget import HalfcellImage
    import eirene.app as app_mod
    from eirene.commands import commands
    from eirene.core.config import Config
    from test_tui import start, type_line

    monkeypatch.setattr(app_mod, "prepare_renderer", lambda config: HalfcellImage)
    app, pilot, context = await start(workdir)
    try:
        companion = app.query_one(Companion)
        assert not app.config.get("companion")
        assert not companion.display and companion._portrait.image is None
        assert "companion" in {command.name for command in commands(app)}
        transcript = tuple(app.transcript.children)
        await type_line(pilot, "/companion on")
        assert companion.display
        assert Config.load().get("companion") is True
        assert tuple(app.transcript.children) == transcript
        await type_line(pilot, "/companion off")
        assert not companion.display
        assert Config.load().get("companion") is False
        assert tuple(app.transcript.children) == transcript
        await type_line(pilot, "/companion")
        assert companion.display
        assert Config.load().get("companion") is True
        assert tuple(app.transcript.children) == transcript
    finally:
        await context.__aexit__(None, None, None)


async def test_unsupported_terminal_hides_command_and_cannot_enable_companion(workdir, monkeypatch):
    import eirene.app as app_mod
    from eirene.commands import commands
    from test_tui import start, type_line

    monkeypatch.setattr(app_mod, "prepare_renderer", lambda config: None)
    app, pilot, context = await start(workdir)
    try:
        assert "companion" not in {command.name for command in commands(app)}
        app.prompt.value = "/companion"
        await pilot.pause()
        assert "companion" not in {name for name, _ in app.slash.matches}
        await type_line(pilot, "/companion on")
        assert not app.config.get("companion")
        assert not app.query_one(Companion).display
    finally:
        await context.__aexit__(None, None, None)
