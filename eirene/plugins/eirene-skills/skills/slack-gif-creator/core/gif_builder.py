"""Assemble frames into an animated GIF sized and tuned for chat apps such as Slack."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops


class GIFBuilder:
    """Collect frames, then save one optimised looping GIF.

        builder = GIFBuilder(width=128, height=128, fps=12)
        builder.add_frame(frame)
        builder.save("out.gif", num_colors=48, optimize_for_emoji=True)
    """

    def __init__(self, width: int = 480, height: int = 480, fps: int = 15):
        if not 1 <= fps <= 50:
            raise ValueError("fps must be between 1 and 50")
        self.width, self.height, self.fps = width, height, fps
        self.frames: list[Image.Image] = []

    def add_frame(self, frame: Image.Image) -> None:
        if frame.size != (self.width, self.height):
            frame = frame.resize((self.width, self.height), Image.LANCZOS)
        # RGBA frames are kept so save(transparent=True) can use their alpha;
        # otherwise they are flattened onto white when saved.
        self.frames.append(frame.copy() if frame.mode == "RGBA" else frame.convert("RGB"))

    def add_frames(self, frames) -> None:
        for frame in frames:
            self.add_frame(frame)

    @property
    def duration_seconds(self) -> float:
        return len(self.frames) / self.fps

    def _durations(self, frames: list[Image.Image], remove_duplicates: bool) -> tuple[list[Image.Image], list[int]]:
        step = round(1000 / self.fps)
        if not remove_duplicates:
            return frames, [step] * len(frames)
        kept: list[Image.Image] = []
        durations: list[int] = []
        for frame in frames:
            if kept and ImageChops.difference(kept[-1].convert("RGB"), frame.convert("RGB")).getbbox() is None:
                durations[-1] += step
            else:
                kept.append(frame)
                durations.append(step)
        return kept, durations

    def save(self, path: str | Path, num_colors: int = 128, optimize_for_emoji: bool = False,
             remove_duplicates: bool = True, transparent: bool = False, loop: int = 0) -> dict:
        """Write the GIF and return {"path", "frames", "bytes", "seconds", "size"}.

        optimize_for_emoji caps the size at 128x128 and the palette at 48 colors.
        transparent keeps fully transparent pixels of RGBA frames transparent.
        """
        if not self.frames:
            raise ValueError("no frames to save")
        frames = list(self.frames)
        size = (self.width, self.height)
        if optimize_for_emoji:
            num_colors = min(num_colors, 48)
            if max(size) > 128:
                scale = 128 / max(size)
                size = (max(1, round(size[0] * scale)), max(1, round(size[1] * scale)))
                frames = [f.resize(size, Image.LANCZOS) for f in frames]
        num_colors = max(2, min(256, num_colors))
        frames, durations = self._durations(frames, remove_duplicates)

        # One shared palette for every frame keeps colors steady and the file small.
        sample = Image.new("RGB", (size[0], size[1] * len(frames)))
        for i, frame in enumerate(frames):
            sample.paste(_flatten(frame), (0, i * size[1]))
        reserve = 1 if transparent else 0
        palette_image = sample.quantize(colors=num_colors - reserve, method=Image.MEDIANCUT)

        converted = []
        for frame in frames:
            q = _flatten(frame).quantize(palette=palette_image, dither=Image.FLOYDSTEINBERG)
            if transparent and frame.mode == "RGBA":
                index = num_colors - 1
                mask = frame.getchannel("A").point(lambda a: 255 if a < 128 else 0)
                q.paste(index, mask=mask)
                q.info["transparency"] = index
            converted.append(q)

        path = Path(path)
        options = dict(save_all=True, append_images=converted[1:], duration=durations,
                       loop=loop, optimize=True, disposal=2 if transparent else 1)
        if transparent:
            options["transparency"] = num_colors - 1
        converted[0].save(path, format="GIF", **options)
        info = {"path": str(path.resolve()), "frames": len(converted), "bytes": path.stat().st_size,
                "seconds": sum(durations) / 1000, "size": size}
        print(f"saved {info['path']}: {info['size'][0]}x{info['size'][1]}, {info['frames']} frames, "
              f"{info['seconds']:.2f}s, {info['bytes'] / 1024:.1f} KB")
        return info


def _flatten(frame: Image.Image) -> Image.Image:
    if frame.mode != "RGBA":
        return frame.convert("RGB")
    base = Image.new("RGB", frame.size, (255, 255, 255))
    base.paste(frame, mask=frame.getchannel("A"))
    return base
