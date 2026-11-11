"""Conversation sessions persisted as small JSON files."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vspagent.security import write_private_file

SAFE_ID = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
MAX_MESSAGES = 80


def _new_id() -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:6]}"


@dataclass
class Session:
    id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    cwd: str = ""
    title: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def append(self, message: dict[str, Any]) -> None:
        self.messages.append(message)
        self.updated_at = time.time()
        if not self.title:
            self.title = self._title_from(message)

    @staticmethod
    def _title_from(message: dict[str, Any]) -> str:
        if message.get("role") != "user":
            return ""
        text = str(message.get("content", "")).strip().replace("\n", " ")
        return text[:60]

    def add_usage(self, usage: dict[str, int]) -> None:
        for key, value in usage.items():
            if isinstance(value, int):
                self.usage[key] = self.usage.get(key, 0) + value

    def compact(self, keep: int = MAX_MESSAGES) -> None:
        """Drop old turns without splitting an assistant/tool-call sequence."""
        if len(self.messages) <= keep:
            return
        removed = len(self.messages) - keep
        kept = self.messages[-keep:]
        while kept and kept[0].get("role") != "user":
            kept.pop(0)
        if not kept:
            kept = self.messages[-keep:]
        self.messages = [
            {
                "role": "user",
                "content": f"[Earlier conversation compacted: {removed} messages removed.]",
            },
            *kept,
        ]
        self.updated_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "messages": self.messages,
            "provider": self.provider,
            "model": self.model,
            "cwd": self.cwd,
            "title": self.title,
            "usage": self.usage,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Session:
        return cls(
            id=str(data["id"]),
            messages=list(data.get("messages", [])),
            provider=str(data.get("provider", "")),
            model=str(data.get("model", "")),
            cwd=str(data.get("cwd", "")),
            title=str(data.get("title", "")),
            usage=dict(data.get("usage", {})),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
        )


class SessionStore:
    """Read and write sessions under the user data directory."""

    def __init__(self, root: str | Path | None = None) -> None:
        if root is None:
            from vspagent.config import sessions_dir

            root = sessions_dir()
        self.root = Path(root).expanduser()

    def path_for(self, session_id: str) -> Path:
        if not session_id or any(character not in SAFE_ID for character in session_id):
            raise ValueError(f"invalid session id: {session_id!r}")
        return self.root / f"{session_id}.json"

    def new(self, provider: str, model: str, cwd: str) -> Session:
        return Session(id=_new_id(), provider=provider, model=model, cwd=cwd)

    def save(self, session: Session) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.path_for(session.id)
        session.updated_at = time.time()
        write_private_file(target, json.dumps(session.to_dict(), indent=2), mode=0o600)
        return target

    def load(self, session_id: str) -> Session:
        target = self.path_for(session_id)
        if not target.exists():
            raise FileNotFoundError(f"session not found: {session_id}")
        data = json.loads(target.read_text(encoding="utf-8"))
        return Session.from_dict(data)

    def latest(self) -> Session | None:
        sessions = self.list(limit=1)
        return sessions[0] if sessions else None

    def list(self, limit: int = 20) -> list[Session]:
        if not self.root.exists():
            return []
        sessions = []
        for path in self.root.glob("*.json"):
            try:
                sessions.append(Session.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
        sessions.sort(key=lambda item: item.updated_at, reverse=True)
        return sessions[:limit]

    def delete(self, session_id: str) -> bool:
        target = self.path_for(session_id)
        if target.exists():
            target.unlink()
            return True
        return False
