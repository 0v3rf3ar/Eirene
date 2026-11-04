"""Small drawing helpers for GIF frames. All colors are (r, g, b) or (r, g, b, a).

Every draw_* helper takes either a Pillow image or an ImageDraw.Draw for it.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageFilter, ImageFont

Color = tuple[int, ...]


def _pen(target) -> ImageDraw.ImageDraw:
    """An ImageDraw for target, which may already be one."""
    return target if isinstance(target, ImageDraw.ImageDraw) else ImageDraw.Draw(target)


def create_blank_frame(width: int, height: int, color: Color = (255, 255, 255)) -> Image.Image:
    return Image.new("RGB", (width, height), color[:3])


def create_gradient_background(width: int, height: int, top: Color, bottom: Color,
                               *, horizontal: bool = False) -> Image.Image:
    """A smooth two-color gradient, vertical by default."""
    size = width if horizontal else height
    strip = Image.new("RGB", (size, 1))
    for i in range(size):
        t = i / max(1, size - 1)
        strip.putpixel((i, 0), tuple(round(a + (b - a) * t) for a, b in zip(top[:3], bottom[:3])))
    if horizontal:
        return strip.resize((width, height), Image.NEAREST)
    return strip.rotate(-90, expand=True).resize((width, height), Image.NEAREST)


def draw_circle(frame: Image.Image, center: tuple[float, float], radius: float,
                fill: Color | None = None, outline: Color | None = None, width: int = 3) -> None:
    x, y = center
    _pen(frame).ellipse([x - radius, y - radius, x + radius, y + radius],
                                  fill=fill, outline=outline, width=width)


def star_points(center: tuple[float, float], outer: float, inner: float | None = None,
                points: int = 5, rotation: float = -90) -> list[tuple[float, float]]:
    """Vertices of a star; rotation in degrees (-90 points the first tip up)."""
    inner = outer * 0.45 if inner is None else inner
    cx, cy = center
    result = []
    for i in range(points * 2):
        r = outer if i % 2 == 0 else inner
        a = math.radians(rotation + i * 180 / points)
        result.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return result


def draw_star(frame: Image.Image, center: tuple[float, float], size: float,
              fill: Color | None = (255, 215, 0), outline: Color | None = None, width: int = 3,
              points: int = 5, rotation: float = -90) -> None:
    _pen(frame).polygon(star_points(center, size, points=points, rotation=rotation),
                                  fill=fill, outline=outline, width=width)


def heart_points(center: tuple[float, float], size: float, steps: int = 60) -> list[tuple[float, float]]:
    """A smooth heart outline using the classic parametric curve."""
    cx, cy = center
    scale = size / 17
    pts = []
    for i in range(steps):
        t = 2 * math.pi * i / steps
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((cx + x * scale, cy - y * scale))
    return pts


def draw_heart(frame: Image.Image, center: tuple[float, float], size: float,
               fill: Color | None = (230, 57, 70), outline: Color | None = None, width: int = 3) -> None:
    _pen(frame).polygon(heart_points(center, size), fill=fill, outline=outline, width=width)


def load_font(size: int, path: str | None = None) -> ImageFont.ImageFont:
    """A TrueType font if one can be found, else Pillow's default font."""
    for candidate in ([path] if path else []) + ["DejaVuSans-Bold.ttf", "Arial Bold.ttf",
                                                  "arialbd.ttf", "Helvetica.ttc", "DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def draw_text(frame: Image.Image, text: str, position: tuple[float, float], size: int = 24,
              fill: Color = (0, 0, 0), *, anchor: str = "mm", stroke: Color | None = None,
              stroke_width: int = 0, font_path: str | None = None) -> None:
    """Text at position; anchor "mm" centres it there. Avoid emoji: fonts for them vary."""
    _pen(frame).text(position, text, fill=fill, font=load_font(size, font_path), anchor=anchor,
                               stroke_width=stroke_width, stroke_fill=stroke)


def glow(layer: Image.Image, radius: float = 6, strength: float = 1.0) -> Image.Image:
    """A blurred copy of an RGBA layer, to paste behind the sharp one for a soft glow."""
    blurred = layer.filter(ImageFilter.GaussianBlur(radius))
    if strength != 1.0:
        alpha = blurred.getchannel("A").point(lambda v: min(255, int(v * strength)))
        blurred.putalpha(alpha)
    return blurred


def paste_rotated(frame: Image.Image, sprite: Image.Image, center: tuple[float, float],
                  angle: float = 0, scale: float = 1.0) -> None:
    """Paste an RGBA sprite centred at center, rotated (degrees, counter-clockwise) and scaled."""
    if scale != 1.0:
        w, h = sprite.size
        sprite = sprite.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    if angle:
        sprite = sprite.rotate(angle, resample=Image.BICUBIC, expand=True)
    x = round(center[0] - sprite.width / 2)
    y = round(center[1] - sprite.height / 2)
    frame.paste(sprite, (x, y), sprite if sprite.mode == "RGBA" else None)


def supersample(width: int, height: int, factor: int = 4, color: Color = (0, 0, 0, 0)) -> Image.Image:
    """A larger RGBA canvas to draw on; shrink it with finish() for smooth edges."""
    return Image.new("RGBA", (width * factor, height * factor), color)


def finish(canvas: Image.Image, width: int, height: int | None = None,
           background: Color | None = None) -> Image.Image:
    """Downscale a supersampled canvas (height defaults to width), optionally onto a background."""
    height = width if height is None else height
    small = canvas.resize((width, height), Image.LANCZOS)
    if background is None:
        return small
    base = Image.new("RGBA", (width, height), tuple(background[:3]) + (255,))
    return Image.alpha_composite(base, small.convert("RGBA")).convert("RGB")
