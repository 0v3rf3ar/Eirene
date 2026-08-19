"""Append-only jsonl session log."""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Iterator

from .errors import SessionError
from . import paths

SCHEMA = 2
NAME_LIMIT = 60
NAME_WORDS = 6

# Openers that say nothing about the subject.
FILLER = re.compile(
    r"^(?:(?:hey|hi|hello|ok|okay|so|now|please|pls|kindly|eirene)[\s,]+|"
    r"(?:can|could|would|will)\s+you\s+(?:please\s+)?|"
    r"(?:i\s+(?:want|need|would\s+like)\s+(?:you\s+)?(?:to\s+)?)|"
    r"(?:let'?s|lets)\s+|(?:help\s+me\s+(?:to\s+)?)|"
    r"(?:make\s+sure\s+(?:you\s+)?)|(?:go\s+ahead\s+and\s+))+",
    re.IGNORECASE)


def name_from(text: str) -> str:
    """A short stand-in title until the model picks one."""
    cleaned = " ".join(str(text or "").split())
    cleaned = re.sub(r"\[pasted [^\]]*\]", "", cleaned).strip()
    cleaned = FILLER.sub("", cleaned).strip()
    if not cleaned:
        return "untitled"
    words = cleaned.split()
    short = " ".join(words[:NAME_WORDS]).rstrip(",.;:!?-")
    if len(words) > NAME_WORDS:
        short += "…"
    if len(short) > NAME_LIMIT:
        short = short[:NAME_LIMIT].rsplit(" ", 1)[0] + "…"
    return short[0].upper() + short[1:] if short else "untitled"


def clean_title(text: str, fallback: str = "") -> str:
    """Tidy a title the model wrote."""
    line = " ".join(str(text or "").split())
    line = re.sub(r"<think>.*?</think>", "", line, flags=re.IGNORECASE | re.DOTALL)
    line = line.split("\n")[0].strip().strip('"\'`').rstrip(".,;:!")
    line = re.sub(r"^(?:title|name)\s*[:\-]\s*", "", line, flags=re.IGNORECASE).strip()
    if not line or len(line) > NAME_LIMIT * 2 or len(line.split()) > 12:
        return fallback
    if len(line) > NAME_LIMIT:
        line = line[:NAME_LIMIT].rsplit(" ", 1)[0] + "…"
    return line[0].upper() + line[1:]


class Message(dict):
    """Normalised chat message."""

    @staticmethod
    def user(text: str, attachments: list[dict] | None = None) -> "Message":
        message = Message(role="user", content=text)
        if attachments:
            message["attachments"] = attachments
        return message

    @staticmethod
    def assistant(text: str = "", tool_calls: list[dict] | None = None) -> "Message":
        msg = Message(role="assistant", content=text)
        if tool_calls:
            msg["tool_calls"] = tool_calls
        return msg

    @staticmethod
    def tool(call_id: str, name: str, content: str, is_error: bool = False,
             seconds: float = 0.0) -> "Message":
        return Message(role="tool", tool_call_id=call_id, name=name,
                       content=content, is_error=is_error, seconds=seconds)

    @staticmethod
    def system(text: str) -> "Message":
        return Message(role="system", content=text)


class Session:
    """One conversation, one jsonl file."""

    def __init__(self, session_id: str, sandbox: Path, path: Path):
        self.id = session_id
        self.sandbox = sandbox
        self.path = path
        self.messages: list[Message] = []
        self.transcript_messages: list[Message] | None = None
        self.started = time.time()
        self.name = ""
        self._handle = None
        self._closed = False

    # lifecycle

    @classmethod
    def create(cls, sandbox: Path, session_id: str | None = None) -> "Session":
        """Reserve a session; the file waits for real input."""
        session_id = session_id or str(uuid.uuid4())
        paths.ensure_tree()
        path = paths.sessions_dir() / f"{session_id}.jsonl"
        return cls(session_id, sandbox, path)

    @property
    def saved(self) -> bool:
        return self._handle is not None or self.path.exists()

    def start(self) -> None:
        """Open the log on the first real input."""
        if self._handle or self._closed:
            return
        paths.ensure_tree()
        self._open()
        self._write({"t": "meta", "schema": SCHEMA, "id": self.id,
                     "name": self.name, "sandbox": str(self.sandbox),
                     "started": self.started})

    def clear(self) -> None:
        """Forget the history and delete the log."""
        self.messages.clear()
        self.transcript_messages = None
        self.close()
        self._closed = False
        self.name = ""
        self.started = time.time()
        try:
            self.path.unlink()
        except OSError:
            pass

    @classmethod
    def resume(cls, session_id: str) -> "Session":
        path = paths.sessions_dir() / f"{session_id}.jsonl"
        if not path.exists():
            raise SessionError(f"no session {session_id}")
        records = list(read_records(path))
        meta = next((r for r in records if r.get("t") == "meta"), {})
        sandbox = Path(meta.get("sandbox", Path.cwd()))
        session = cls(session_id, sandbox, path)
        session.name = str(meta.get("name") or "")
        for record in records:
            if record.get("t") == "rename" and record.get("name"):
                session.name = str(record["name"])
        session.messages = replay(records)
        session.transcript_messages = replay(records, apply_compaction=False)
        if not session.name:
            first = next((m for m in session.messages if m.get("role") == "user"), None)
            session.name = name_from(str(first.get("content", ""))) if first else ""
        session._open()
        return session

    def _open(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = open(self.path, "a", encoding="utf-8")
        except OSError as exc:
            raise SessionError(f"cannot open session log: {exc}") from exc

    def close(self) -> None:
        self._closed = True
        if self._handle:
            try:
                self._handle.flush()
                self._handle.close()
            except OSError:
                pass
            self._handle = None

    # writing

    def _write(self, record: dict[str, Any]) -> None:
        if not self._handle:
            return
        record.setdefault("ts", time.time())
        try:
            self._handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._handle.flush()
        except (OSError, TypeError, ValueError):
            pass

    def add_user(self, text: str, attachments: list[dict] | None = None) -> Message:
        if not self.name:
            self.name = name_from(text)
        self.start()
        msg = Message.user(text, attachments)
        self.messages.append(msg)
        record = {"t": "user", "content": text}
        if attachments:
            record["attachments"] = attachments
        self._write(record)
        return msg

    def add_assistant(self, text: str, tool_calls: list[dict] | None = None,
                      thinking: str = "") -> Message:
        msg = Message.assistant(text, tool_calls)
        self.messages.append(msg)
        record: dict[str, Any] = {"t": "assistant", "content": text}
        if tool_calls:
            record["tool_calls"] = tool_calls
        if thinking:
            record["thinking"] = thinking
        self._write(record)
        return msg

    def add_tool_result(self, call_id: str, name: str, content: str,
                        is_error: bool = False, seconds: float = 0.0) -> Message:
        msg = Message.tool(call_id, name, content, is_error, seconds)
        self.messages.append(msg)
        self._write({"t": "tool_result", "tool_call_id": call_id, "name": name,
                     "content": content, "is_error": is_error, "seconds": seconds})
        return msg

    def rename(self, name: str) -> None:
        """Give the session a better title."""
        title = (name or "").strip()
        if not title or title == self.name:
            return
        self.name = title
        self._write({"t": "rename", "name": title})

    def add_note(self, kind: str, **fields: Any) -> None:
        """Log a non-conversational event."""
        self._write({"t": kind, **fields})

    def replace_history(self, messages: list[Message], summary: str) -> None:
        """Swap history after a compaction."""
        self.messages = list(messages)
        self._write({"t": "compact", "summary": summary,
                     "messages": [dict(m) for m in messages]})


def read_records(path: Path) -> Iterator[dict[str, Any]]:
    """Yield records, skipping corrupt lines."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if isinstance(record, dict):
                    yield record
    except OSError as exc:
        raise SessionError(f"cannot read session: {exc}") from exc


def replay(records: list[dict[str, Any]], *, apply_compaction: bool = True) -> list[Message]:
    """Rebuild message history from records."""
    messages: list[Message] = []
    for record in records:
        kind = record.get("t")
        if kind == "user":
            messages.append(Message.user(record.get("content", ""),
                                         record.get("attachments")))
        elif kind == "assistant":
            messages.append(Message.assistant(record.get("content", ""),
                                              record.get("tool_calls")))
        elif kind == "tool_result":
            messages.append(Message.tool(record.get("tool_call_id", ""),
                                         record.get("name", ""),
                                         record.get("content", ""),
                                         record.get("is_error", False),
                                         float(record.get("seconds") or 0.0)))
        elif kind == "compact" and apply_compaction:
            messages = [Message(m) for m in record.get("messages", [])]
    return messages


def list_sessions(limit: int = 50, sandbox: Path | str | None = None) -> list[dict[str, Any]]:
    """Recent sessions, newest first."""
    directory = paths.sessions_dir()
    if not directory.exists():
        return []
    wanted = str(Path(sandbox).expanduser().resolve()) if sandbox else ""
    files = sorted(directory.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for path in files:
        if len(out) >= limit:
            break
        info = {"id": path.stem, "path": str(path), "mtime": path.stat().st_mtime,
                "sandbox": "", "name": "", "turns": 0}
        try:
            for record in read_records(path):
                if record.get("t") == "meta":
                    info["sandbox"] = record.get("sandbox", "")
                    info["name"] = record.get("name") or ""
                elif record.get("t") == "rename" and record.get("name"):
                    info["name"] = str(record["name"])
                elif record.get("t") == "user":
                    info["turns"] += 1
                    if not info["name"]:
                        info["name"] = name_from(str(record.get("content", "")))
        except SessionError:
            continue
        if not info["name"]:
            info["name"] = "untitled"
        if wanted and info["sandbox"] != wanted:
            continue
        out.append(info)
    return out


def search_sessions(query: str, *, sandbox: Path | str | None = None,
                    limit: int = 20) -> list[dict[str, Any]]:
    """Search titles and conversational text without loading corrupt records."""
    needle = " ".join(query.lower().split())
    if not needle:
        return list_sessions(limit=limit, sandbox=sandbox)
    results = []
    for info in list_sessions(limit=500, sandbox=sandbox):
        haystack = [str(info.get("name") or "")]
        snippets = []
        try:
            for record in read_records(Path(info["path"])):
                if record.get("t") in ("user", "assistant"):
                    content = " ".join(str(record.get("content") or "").split())
                    haystack.append(content)
                    if needle in content.lower() and len(snippets) < 2:
                        snippets.append(content[:180])
        except SessionError:
            continue
        if needle in "\n".join(haystack).lower():
            results.append({**info, "snippets": snippets})
            if len(results) >= limit:
                break
    return results


def export_session(session_id: str, destination: Path, format: str = "markdown") -> Path:
    session = Session.resume(session_id)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if format == "json":
            payload = {"schema": SCHEMA, "id": session.id, "name": session.name,
                       "sandbox": str(session.sandbox),
                       "messages": [dict(message) for message in session.messages]}
            destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                                   encoding="utf-8")
        elif format == "markdown":
            rows = [f"# {session.name or 'Eirene session'}", ""]
            for message in session.messages:
                role = message.get("role")
                if role not in ("user", "assistant", "tool"):
                    continue
                title = {"user": "User", "assistant": "Eirene", "tool": "Tool"}[role]
                if role == "tool":
                    title += f": {message.get('name', '')}"
                rows.extend([f"## {title}", "", str(message.get("content") or ""), ""])
            destination.write_text("\n".join(rows), encoding="utf-8")
        else:
            raise SessionError("export format must be markdown or json")
    except OSError as exc:
        raise SessionError(f"cannot export session: {exc}") from exc
    finally:
        session.close()
    return destination


def import_session(source: Path, sandbox: Path) -> "Session":
    """Import a JSON export into a new append-only local session."""
    try:
        body = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise SessionError(f"cannot import session: {exc}") from exc
    if not isinstance(body, dict) or not isinstance(body.get("messages"), list):
        raise SessionError("import file is not an Eirene session export")
    session = Session.create(sandbox)
    session.name = clean_title(str(body.get("name") or ""))
    for raw in body["messages"]:
        if not isinstance(raw, dict):
            continue
        role = raw.get("role")
        if role == "user":
            session.add_user(str(raw.get("content") or ""), raw.get("attachments"))
        elif role == "assistant":
            session.add_assistant(str(raw.get("content") or ""), raw.get("tool_calls"))
        elif role == "tool":
            session.add_tool_result(str(raw.get("tool_call_id") or ""),
                                    str(raw.get("name") or ""),
                                    str(raw.get("content") or ""),
                                    bool(raw.get("is_error")),
                                    float(raw.get("seconds") or 0.0))
    session.close()
    return session
