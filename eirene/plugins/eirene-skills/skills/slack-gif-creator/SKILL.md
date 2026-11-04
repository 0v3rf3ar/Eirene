---
name: slack-gif-creator
description: Make animated GIFs sized and tuned for Slack (custom emoji and in-message GIFs), with Pillow helpers for frames, easing and validation. Use when someone asks for an animated GIF or emoji, for example "make me a GIF of X doing Y for Slack".
---

# Slack GIF creator

Helpers and know-how for animated GIFs that look good and stay small in Slack and
similar chat apps.

**Requirements:** Python 3 with Pillow (`pip install pillow`). The helpers live
in `core/`; run your script with this skill's folder on `PYTHONPATH`, or copy
`core/` next to it.

## Slack's limits

**Size:**

- custom emoji: 128×128 (recommended), and at most 128 KB
- GIFs in messages: about 480×480

**Settings:**

- frame rate: 10–30 fps (lower is smaller)
- colors: 48–128 (fewer is smaller)
- length: under about 3 seconds for emoji

## Workflow

```python
from PIL import Image, ImageDraw
from core.gif_builder import GIFBuilder

# 1. a builder
builder = GIFBuilder(width=128, height=128, fps=12)

# 2. frames
for i in range(12):
    frame = Image.new("RGB", (128, 128), (240, 248, 255))
    draw = ImageDraw.Draw(frame)
    # draw this frame with Pillow shapes: ellipses, polygons, lines…
    builder.add_frame(frame)

# 3. save, optimised
builder.save("output.gif", num_colors=48, optimize_for_emoji=True)
```

Then check it:

```python
from core.validators import validate_gif
validate_gif("output.gif", is_emoji=True)
```

If your model can read images, open the saved GIF (or a few frames saved as PNG)
and look at it before handing it over.

## Drawing

### When the person supplies an image

Decide whether they want it:

- **used directly** — "animate this", "make this spin", "split this into frames";
- **as inspiration** — "something like this".

```python
from PIL import Image
source = Image.open("upload.png").convert("RGBA")
# animate it directly, or just sample its colors and style
```

### From scratch

Use Pillow's `ImageDraw` shapes:

```python
draw = ImageDraw.Draw(frame)
draw.ellipse([x1, y1, x2, y2], fill=(r, g, b), outline=(r, g, b), width=3)   # circles, ovals
draw.polygon([(x1, y1), (x2, y2), (x3, y3)], fill=(r, g, b), outline=(r, g, b), width=3)  # stars, any shape
draw.line([(x1, y1), (x2, y2)], fill=(r, g, b), width=5)
draw.rectangle([x1, y1, x2, y2], fill=(r, g, b), outline=(r, g, b), width=3)
draw.rounded_rectangle([x1, y1, x2, y2], radius=12, fill=(r, g, b))
```

Do not rely on emoji fonts (they differ between systems), and do not assume this
skill ships ready-made graphics. It does not.

### Make it look finished

Aim for polished and inventive, not placeholder shapes.

- **Thicker lines:** `width=2` or more for outlines and lines. One-pixel lines look
  jagged at emoji size.
- **Smooth edges:** draw on a canvas 4× larger and shrink it
  (`supersample()` and `finish()` in `core.frame_composer`).
- **Depth:** gradient backgrounds (`create_gradient_background`), layered shapes
  (a star inside a star), a soft glow behind a bright shape (`glow()`).
- **Interesting shapes:** a circle can have a highlight, a ring or a pattern; stars
  can sparkle; combine shapes.
- **Color:** vivid, complementary colors with contrast — dark outlines on light
  shapes, light outlines on dark ones. Think about the whole composition.
- **Complex shapes** (hearts, snowflakes…): build them from polygons and ellipses,
  compute points for symmetry, add details such as a highlight curve or fine
  branches. `heart_points()` and `star_points()` give clean outlines.

## Helpers

### `core.gif_builder.GIFBuilder`

```python
builder = GIFBuilder(width=128, height=128, fps=12)
builder.add_frame(frame)           # a Pillow image; resized if needed
builder.add_frames(frames)
builder.save("out.gif", num_colors=48, optimize_for_emoji=True,
             remove_duplicates=True, transparent=False)
```

`save` uses one shared palette across frames (steadier colors, smaller file),
merges identical consecutive frames into longer ones when `remove_duplicates`
is on, and returns the size, frame count, length and byte count.
`optimize_for_emoji` caps the size at 128×128 and the palette at 48 colors.
`transparent=True` keeps the fully transparent pixels of RGBA frames transparent
(GIF transparency is on/off, so soft edges become hard).

### `core.validators`

```python
from core.validators import validate_gif, is_slack_ready
passes, info = validate_gif("my.gif", is_emoji=True, verbose=True)
if is_slack_ready("my.gif"):
    print("ready")
```

Or from the command line: `python -m core.validators my.gif [--message]`.

### `core.easing`

Smooth motion instead of linear:

```python
from core.easing import interpolate, progress
t = progress(i, frame_count)                   # 0.0 … 1.0
y = interpolate(start=0, end=100, t=t, easing="ease_out")
```

Curves: `linear`, `ease_in`, `ease_out`, `ease_in_out`, `bounce_in`,
`bounce_out`, `elastic_out`, `back_in`, `back_out`. `ping_pong(t)` goes
0 → 1 → 0 for loops that return to the start.

### `core.frame_composer`

The `draw_*` helpers take a Pillow image or an `ImageDraw.Draw` for it:

```python
create_blank_frame(width, height, color=(255, 255, 255))
create_gradient_background(width, height, top_color, bottom_color, horizontal=False)
draw_circle(frame, (x, y), radius, fill=None, outline=None, width=3)
draw_star(frame, (x, y), size, fill=(255, 215, 0), outline=None, width=3, points=5, rotation=-90)
draw_heart(frame, (x, y), size, fill=(230, 57, 70), outline=None, width=3)
draw_text(frame, "text", (x, y), size=24, fill=(0, 0, 0), anchor="mm", stroke=None, stroke_width=0)
star_points(...), heart_points(...)        # outlines, for your own polygons
load_font(size, path=None)                 # a TrueType font, or Pillow's default
glow(rgba_layer, radius=6, strength=1.0)   # blurred copy to paste behind a shape
paste_rotated(frame, rgba_sprite, (x, y), angle=0, scale=1.0)
supersample(width, height, factor=4)       # a 4x RGBA canvas to draw on
finish(canvas, width, height=None, background=None)   # shrink it back; height defaults to width
```

With `supersample`, draw at 4× coordinates (a 128 px emoji is drawn on 512 px).

## Motion ideas

**Shake / vibrate** — offset the position with `sin`/`cos` of the frame index,
plus a little seeded randomness for a natural feel; on x, y or both.

**Pulse / heartbeat** — scale with `sin(t * frequency * 2π)`, between about 0.8
and 1.2 of the base size. For a heartbeat: two quick beats, then a rest.

**Bounce** — fall with `ease_in` (accelerating), land with `bounce_out`; or add
gravity to the vertical speed each frame.

**Spin / rotate** — `sprite.rotate(angle, resample=Image.BICUBIC, expand=True)`
or `paste_rotated()`. For a wobble, drive the angle with a sine wave.

**Fade in / out** — change the alpha of an RGBA layer, or
`Image.blend(a, b, alpha)`; 0 → 1 to fade in, 1 → 0 to fade out.

**Slide** — start outside the frame and `ease_out` to the target; `back_out` for
a small overshoot.

**Zoom** — scale from small to large (or back) around the centre and crop; a light
blur on the fastest frames adds drama.

**Burst / particles** — particles with seeded random angles and speeds; each frame
`x += vx`, `y += vy`, add gravity to `vy`, and fade them out.

**Seamless loops** — make the last frame lead back into the first: use full sine
periods, `ping_pong()`, or animate over `t` in `[0, 1)` (do not draw `t = 1`,
which repeats frame 0).

## Making files smaller

Only when asked to reduce the size, try some of these:

1. **Fewer frames** — lower fps (10 instead of 20) or a shorter loop.
2. **Fewer colors** — `num_colors=48` instead of 128.
3. **Smaller size** — 128×128 instead of 480×480.
4. **Merge duplicates** — `remove_duplicates=True` (the default).
5. **Emoji mode** — `optimize_for_emoji=True`.
6. **Flat colors** — large flat areas and no dithered gradients compress best.

```python
builder.save("emoji.gif", num_colors=48, optimize_for_emoji=True, remove_duplicates=True)
```

## What this skill is

It gives you Slack's limits, motion ideas, and small helpers (builder, validator,
easing, drawing). The animation itself — what moves and how — you write with
Pillow. There are no fixed templates, no emoji font rendering and no bundled
artwork. Combine ideas freely (bounce and spin, pulse and slide) and use all of
Pillow.
