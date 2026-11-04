"""A small Eirene companion, using terminal graphics when available."""

from __future__ import annotations

import os
import random
import sys
import time
from functools import lru_cache
from pathlib import Path

from textual.containers import Container

SLEEP_AFTER = 60
ANGER_WINDOW = 3
ANGER_FOR = 1.0
FURIOUS_FOR = 1.3
ASSETS = Path(__file__).with_name("companion_assets")
PORTRAITS = {"idle": "idle.png", "question": "q.png", "thinking": "work.png",
             "writing": "work.png", "working": "work.png", "sleepy": "sleepy.png",
             "angry": "angry.png", "furious": "furious.png"}
# Idle moments: short animations she plays now and then while you leave her be.
# Each is a list of (frame, seconds); refreshes run every 0.4 seconds.
MOMENT_GAP = (8.0, 22.0)
MOMENTS = {
    "glint": [("glint-1.png", 0.4), ("glint-2.png", 0.4), ("glint-3.png", 0.4)],
    "hum": [("hum-1.png", 0.8), ("hum-2.png", 0.8), ("hum-3.png", 0.8),
            ("idle.png", 0.4), ("hum-1.png", 0.8), ("hum-2.png", 0.8), ("hum-3.png", 0.8)],
    "double-blink": [("idle-blink.png", 0.4), ("idle.png", 0.4), ("idle-blink.png", 0.4)],
    "rest-eyes": [("idle-blink.png", 2.0)],
}
QUESTION_PHASES = {"waiting for confirmation", "waiting for input", "waiting for required user input"}


def prepare_renderer(config):
    """Probe before Textual owns stdin; never probe redirected or plain output."""
    if (config.get("accessible_icons", False)
            or "NO_COLOR" in os.environ or not sys.__stdout__
            or not sys.__stdout__.isatty()):
        return None
    try:
        from textual_image.widget import Image, SixelImage, TGPImage
        # Avoid a large, blurry character-cell picture on ordinary terminals.
        if Image is SixelImage:
            from .sixel_portrait import SixelPortrait
            return SixelPortrait
        # The library's automatic Kitty widget is a sibling of TGPImage,
        # with the same renderable; it is not TGPImage itself.
        if getattr(Image, "_Renderable", None) is TGPImage._Renderable:
            from .kitty_portrait import KittyPortrait
            return KittyPortrait
        return None
    except (ImportError, OSError, RuntimeError):
        return None


def emotion(status, idle_seconds: float, waiting_for_user: bool = False) -> str:
    if waiting_for_user:
        return "sleepy" if idle_seconds >= SLEEP_AFTER else "question"
    if status.active and status.phase == "idle":
        return "sleepy" if idle_seconds >= SLEEP_AFTER else "idle"
    if status.active:
        if status.writing_files:
            return "writing"
        if status.running_tools or status.phase in {"answering", "working", "running"}:
            return "working"
        return "thinking"
    return "sleepy" if idle_seconds >= SLEEP_AFTER else "idle"


@lru_cache(maxsize=16)
def portrait_bounds(filename: str):
    """Ignore nearly transparent background specks when framing the artwork."""
    from PIL import Image
    with Image.open(ASSETS / filename) as source:
        return source.convert("RGBA").getchannel("A").point(
            lambda alpha: 255 if alpha >= 128 else 0).getbbox()


@lru_cache(maxsize=16)
def portrait_frame(filename: str):
    """Keep each portrait's feet on the bottom edge of its display frame."""
    from PIL import Image
    with Image.open(ASSETS / filename) as source:
        base, offset = source.info.get("base"), source.info.get("offset")
        sprite = source.convert("RGBA")
    if base:
        # A delta frame: only the changed pixels, pasted over its base picture.
        if base == filename:
            raise ValueError(f"{filename} is its own base")
        x, y = (int(value) for value in offset.split(","))
        canvas = portrait_frame(base).copy()
        canvas.paste(sprite, (x, y), sprite.getchannel("A").point(lambda a: 255 if a else 0))
        return canvas
    # Bundled frames are already scaled and aligned; keep their pixels intact.
    if sprite.size == (128, 128):
        return sprite
    sprite.putalpha(sprite.getchannel("A").point(
        lambda alpha: alpha if alpha >= 128 else 0))
    bounds = portrait_bounds(filename)
    if filename in {"idle.png", "idle-blink.png"}:
        # Both eye poses use the same source rectangle and scale.
        poses = [portrait_bounds(name) for name in ("idle.png", "idle-blink.png")]
        poses = [box for box in poses if box is not None]
        if poses:
            bounds = (min(box[0] for box in poses), min(box[1] for box in poses),
                      max(box[2] for box in poses), max(box[3] for box in poses))
    if bounds:
        sprite = sprite.crop(bounds)
    sprite.thumbnail((112, 112), Image.Resampling.NEAREST)
    bounds = sprite.getchannel("A").getbbox()
    if bounds:
        sprite = sprite.crop(bounds)
    canvas = Image.new("RGBA", (128, 128))
    canvas.alpha_composite(sprite, ((128 - sprite.width) // 2,
                                   128 - sprite.height))
    return canvas


class Companion(Container):
    DEFAULT_CSS = """
    Companion {
        position: absolute;
        overlay: screen;
        layer: overlay;
        width: 18;
        height: 6;
        display: none;
        align: right bottom;
        background: transparent;
    }
    Companion .portrait {
        width: auto;
        height: 6;
        margin-right: 1;
        background: transparent;
    }
    """

    def __init__(self, renderer=None):
        super().__init__()
        self.renderer = renderer
        if getattr(renderer, "TRANSPARENT_OVERLAY", False):
            self.visible = False
        self.state = "idle"
        self._last_interaction = time.monotonic()
        self._asked_question = False
        self._pending_questions = 0
        self._was_working = False
        self._tick = 0
        self._drawn = None
        self._portrait = None
        self._last_poke = float("-inf")
        self._poke_count = 0
        self._angry_until = 0.0
        self._anger_timer = None
        self._random = random.Random()
        self._moment = None
        self._moment_started = 0.0
        self._next_moment = time.monotonic() + self._random.uniform(*MOMENT_GAP)

    def poke_at(self, x: int, y: int) -> bool:
        """Only clicks on her visible pixels count, including the native overlay."""
        if not self.display or self._portrait is None or self._portrait.image is None:
            return False
        region = (self._portrait._placement_region
                  if getattr(self._portrait, "TRANSPARENT_OVERLAY", False)
                  else self._portrait.region)
        if not region.contains(x, y):
            return False
        image = self._portrait.image
        left = int((x - region.x) * image.width / region.width)
        top = int((y - region.y) * image.height / region.height)
        right = max(left + 1, int((x - region.x + 1) * image.width / region.width))
        bottom = max(top + 1, int((y - region.y + 1) * image.height / region.height))
        if image.getchannel("A").crop((left, top, right, bottom)).getextrema()[1] < 128:
            return False
        now = time.monotonic()
        self._poke_count = self._poke_count + 1 if now - self._last_poke <= ANGER_WINDOW else 1
        self._last_poke = now
        duration = FURIOUS_FOR if self._poke_count >= 3 else ANGER_FOR
        self._angry_until = now + duration
        if self._anger_timer is not None:
            self._anger_timer.stop()
        # End the reaction at its deadline instead of waiting for the next blink tick.
        self._anger_timer = self.set_timer(duration, self.refresh_companion)
        self.wake()
        self.refresh_companion()
        return True

    def _moment_frame(self, now: float):
        """The frame of the idle moment playing now, starting one when it is due."""
        if self._moment is None:
            if now < self._next_moment:
                return None
            self._moment = MOMENTS[self._random.choice(sorted(MOMENTS))]
            self._moment_started = now
        elapsed = now - self._moment_started
        for filename, seconds in self._moment:
            if elapsed < seconds:
                return filename
            elapsed -= seconds
        self._moment = None
        self._next_moment = now + self._random.uniform(*MOMENT_GAP)
        return None

    def compose(self):
        if self.renderer is not None:
            self._portrait = self.renderer(classes="portrait")
            yield self._portrait

    def on_mount(self):
        self.set_interval(0.4, self.refresh_companion)
        self.refresh_companion()
        self.call_after_refresh(self.position_portrait)

    def position_portrait(self):
        """Anchor to the input border without taking space in the bottom dock."""
        if not self.display:
            return
        border = self.app.query("Composer Rule").first()
        if getattr(self._portrait, "TRANSPARENT_OVERLAY", False):
            self._portrait.place_above_input(border.region.y)
            self.call_after_refresh(self._portrait.paint)
            return
        self.styles.offset = (max(0, self.app.size.width - self.size.width),
                              max(0, border.region.y - self.size.height))

    def wake(self):
        """Attention stops an idle moment; they only happen while you leave her be."""
        now = time.monotonic()
        self._last_interaction = now
        self._moment = None
        self._next_moment = now + self._random.uniform(*MOMENT_GAP)

    def start_turn(self):
        self._asked_question = False
        self.refresh_companion()

    def finish_turn(self, asking: bool = False):
        """Keep a question visible until the user responds."""
        self._last_interaction = time.monotonic()
        self._asked_question = asking
        self.refresh_companion()

    def begin_question(self):
        self._pending_questions += 1
        self.wake()
        self.refresh_companion()

    def end_question(self):
        self._pending_questions = max(0, self._pending_questions - 1)
        self.wake()
        self.refresh_companion()

    def refresh_companion(self):
        config = self.app.config
        status = self.app.status
        now = time.monotonic()
        waiting = (self._asked_question or self._pending_questions > 0 or
                   self.app.permission.waiting or
                   (status.active and status.phase in QUESTION_PHASES))
        working = status.active and not waiting
        if working or self._was_working:
            self._last_interaction = now
        self._was_working = working
        self.state = emotion(status, now - self._last_interaction, waiting)
        if now < self._angry_until:
            self.state = "furious" if self._poke_count >= 3 else "angry"
        reduced = config.get("reduce_motion", False)
        self._tick = 0 if reduced else self._tick + 1
        self.display = bool(self._portrait is not None and
                            config.get("companion", False) and
                            "NO_COLOR" not in os.environ and
                            not config.get("accessible_icons", False) and
                            self.app.size.width >= 48 and self.app.size.height >= 20)
        if not self.display:
            if getattr(self._portrait, "TRANSPARENT_OVERLAY", False):
                self._portrait.clear()
            return
        self.call_after_refresh(self.position_portrait)
        filename = PORTRAITS[self.state]
        moment = self._moment_frame(now) if self.state == "idle" and not reduced else None
        if self.state != "idle" or reduced:
            # Anything else she does postpones her next idle moment.
            self._moment = None
            self._next_moment = now + self._random.uniform(*MOMENT_GAP)
        if moment is not None:
            filename = moment
        elif self.state == "idle" and not reduced and self._tick % 10 == 9:
            filename = "idle-blink.png"
        if filename != self._drawn:
            try:
                self._portrait.image = portrait_frame(filename)
            except (OSError, ValueError):
                # Missing/corrupt art hides the companion without replacement text.
                self._portrait.display = False
                self._portrait = None
                self.display = False
            self._drawn = filename
