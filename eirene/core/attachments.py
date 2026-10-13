"""Stored user attachments and provider-native vision messages."""
from __future__ import annotations
import base64
import mimetypes
import os
import shlex
import re
import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit
from .errors import ToolError
from . import paths
from ..tools.sandbox import Sandbox

MAX_IMAGE_BYTES = 10_000_000
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
DEFAULT_ATTACHMENT_BYTES = 20_000_000
MAX_DROPPED_FILES = 10


def dropped_paths(text: str, root: Path) -> list[Path]:
    """Recognize terminal drops: quoted/escaped paths or local file URIs.

    Only a paste consisting entirely of existing files is treated as a drop.
    """
    raw = text.strip()
    if not raw:
        return []

    def resolve(value: str) -> Path | None:
        if value.startswith("file://"):
            uri = urlsplit(value)
            if uri.netloc not in {"", "localhost"} or uri.query or uri.fragment:
                return None
            value = unquote(uri.path)
        path = Path(value).expanduser()
        if not path.is_absolute():
            if not value.startswith(("./", "../")):
                return None
            path = root / path
        try:
            return path.resolve() if path.is_file() else None
        except (OSError, ValueError, RuntimeError):
            return None

    single = resolve(raw)
    if single is not None:
        return [single]
    try:
        values = shlex.split(raw, posix=os.name != "nt")
    except ValueError:
        return []
    paths = [resolve(value.strip('"') if os.name == "nt" else value)
             for value in values]
    return list(dict.fromkeys(paths)) if paths and all(paths) else []


def attachment_path(attachment_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", attachment_id):
        raise ToolError("invalid attachment ID")
    return paths.home() / "attachments" / f"{attachment_id}.bin"


def store_attachment(path: Path, max_bytes: int = DEFAULT_ATTACHMENT_BYTES) -> dict:
    """Snapshot an explicitly dropped file, retaining bytes independently of its source."""
    try:
        if not path.is_file():
            raise ToolError("attachment must be a regular file")
        if path.stat().st_size > max_bytes:
            raise ToolError(f"attachment exceeds the {max_bytes / 1_000_000:g} MB limit")
        with path.open("rb") as handle:
            data = handle.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ToolError(f"attachment exceeds the {max_bytes / 1_000_000:g} MB limit")
        attachment_id = uuid.uuid4().hex
        target = attachment_path(attachment_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        paths._tighten(target.parent)
        with target.open("xb") as handle:
            target.chmod(0o600)
            handle.write(data)
    except OSError as exc:
        raise ToolError(f"cannot read attachment {path.name}: {exc}") from exc
    return {"id": attachment_id, "name": path.name, "size": len(data),
            "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream"}


def attachment_manifest(text: str, files: list[dict]) -> str:
    """Tell the model which attached files it may read, without inlining contents."""
    if files:
        text += "\n\nAttached files (use read_attachment with attachment_id):"
        for item in files:
            text += f"\n- {item['name']}: attachment_id={item['id']}, {item['size']} bytes, {item['mime_type']}"
    return text


def attachment_image(item: dict) -> dict | None:
    if item.get("mime_type") not in IMAGE_TYPES:
        return None
    try:
        data = attachment_path(item["id"]).read_bytes()
    except OSError as exc:
        raise ToolError(f"cannot read attachment: {exc}") from exc
    return {"name": item["name"], "mime_type": item["mime_type"],
            "data": base64.b64encode(data).decode("ascii")}


def read_attachment(item: dict, offset: int = 0, limit: int = 4096, *,
                    encoding: str = "auto", max_chars: int = 12000) -> str:
    """Read bounded byte pages; binary files can be retrieved as base64."""
    if encoding not in {"auto", "text", "base64"}:
        raise ToolError("encoding must be auto, text, or base64")
    if item.get("mime_type") in IMAGE_TYPES and encoding == "auto":
        return f"Loaded attached image {item['name']} for vision."
    start = max(0, offset)
    limit = max(1, min(limit, 200_000, max(1, (max_chars - 500) // 4)))
    try:
        with attachment_path(item["id"]).open("rb") as handle:
            size = handle.seek(0, 2)
            handle.seek(min(start, size))
            start = handle.tell()
            data = handle.read(limit)
    except OSError as exc:
        raise ToolError(f"cannot read attachment: {exc}") from exc
    end = start + len(data)
    if encoding == "base64":
        body = base64.b64encode(data).decode("ascii")
    else:
        import codecs
        try:
            if b"\x00" in data:
                raise UnicodeError("binary content")
            decoder = codecs.getincrementaldecoder("utf-8")()
            body = decoder.decode(data, final=end >= size)
            pending, _ = decoder.getstate()
            end -= len(pending)
            if end == start and data:
                raise UnicodeError("page too small for a character; increase limit")
        except UnicodeError:
            if encoding == "text":
                raise ToolError("attachment is not UTF-8 text; use encoding=base64")
            body = base64.b64encode(data).decode("ascii")
            encoding = "base64"
    footer = (f"\nMore: read_attachment attachment_id={item['id']}, offset={end}, encoding={encoding}."
              if end < size else "\n(end of attachment)")
    return f"Attachment {item['name']} ({encoding}): bytes {start}-{end} of {size}\n{body}{footer}"

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
