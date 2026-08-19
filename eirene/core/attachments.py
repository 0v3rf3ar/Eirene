"""Bounded image encoding for provider-native vision messages."""
from __future__ import annotations
import base64
import mimetypes
from .errors import ToolError
from ..tools.sandbox import Sandbox

MAX_IMAGE_BYTES = 10_000_000
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}

def prepare_image(box: Sandbox, path: str) -> dict:
    target = box.resolve(path)
    if not target.is_file():
        raise ToolError(f"{box.relative(target)} is not a file")
    mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    try:
        size = target.stat().st_size
        if mime not in IMAGE_TYPES:
            raise ToolError("read_image requires a PNG, JPEG, GIF or WebP file")
        if size > MAX_IMAGE_BYTES:
            raise ToolError("image exceeds 10 MB")
        data = base64.b64encode(target.read_bytes()).decode("ascii")
    except OSError as exc:
        raise ToolError(f"cannot read image {box.relative(target)}: {exc}") from exc
    return {"name": target.name, "mime_type": mime, "data": data}
