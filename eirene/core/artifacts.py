"""Private output artifacts; transcripts carry IDs, never arbitrary file paths."""
from __future__ import annotations

import re
import uuid
from . import paths

MAX_BYTES = 20_000_000


def location(artifact_id: str):
    if not re.fullmatch(r"[a-f0-9]{32}", artifact_id):
        raise ValueError("invalid output artifact ID")
    return paths.home() / "outputs" / f"{artifact_id}.txt"


class Writer:
    def __init__(self):
        self.id = uuid.uuid4().hex
        path = location(self.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        paths._tighten(path.parent)
        self.handle = path.open("xb")
        path.chmod(0o600)
        self.size = 0
        self.truncated = False

    def feed(self, text: str):
        data = text.encode("utf-8", "replace")
        room = max(0, MAX_BYTES - self.size)
        self.handle.write(data[:room])
        self.size += min(len(data), room)
        if len(data) > room and not self.truncated:
            self.handle.write(b"\n[output artifact reached its 20 MB limit]\n")
            self.truncated = True
        self.handle.flush()

    def close(self):
        self.handle.close()


def read(artifact_id: str, offset: int = 0, limit: int = 50000) -> str:
    with location(artifact_id).open("rb") as handle:
        handle.seek(max(0, offset))
        data = handle.read(max(1, min(limit, 200_000)))
    return data.decode("utf-8", "replace")


def read_page(artifact_id: str, offset: int = 0, limit: int = 4096, *,
              max_chars: int = 12000) -> str:
    """Byte-addressed UTF-8 pages with exact continuation, bounded before decode."""
    import codecs
    maximum = max(0, max_chars)
    if maximum < 256:
        return "Output read deferred: compact context before retrieving details."[:maximum]
    limit = max(1, min(limit, 200_000))
    start = max(0, offset)
    with location(artifact_id).open("rb") as handle:
        size = handle.seek(0, 2)
        handle.seek(min(start, size))
        start = handle.tell()
        data = handle.read(max(4, min(limit, (maximum - 220) // 4)))
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    body = decoder.decode(data, final=start + len(data) >= size)
    pending, _ = decoder.getstate()
    end = start + len(data) - len(pending)
    header = f"Output {artifact_id}: bytes {start}-{end} of {size}\n"
    footer = (f"\nMore output: use read_output artifact_id={artifact_id}, next_offset={end} "
              f"(pass offset={end}), limit={limit}." if end < size else "\n(end of output)")
    return header + body + footer
