from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Lock

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator


router = APIRouter(prefix="/api/lan-presence", tags=["lan-presence"])
_lock = Lock()
_users: dict[str, dict[str, str]] = {}
_presence_timeout = timedelta(seconds=45)


class PresenceUpdate(BaseModel):
    user_id: str = Field(min_length=1, max_length=100)
    user_name: str = Field(min_length=1, max_length=50)
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")

    @field_validator("user_id", "user_name")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


def _active_users(now: datetime) -> list[dict[str, str]]:
    expired = [user_id for user_id, value in _users.items() if now - datetime.fromisoformat(value["last_seen"]) > _presence_timeout]
    for user_id in expired:
        _users.pop(user_id, None)
    return sorted((dict(value) for value in _users.values()), key=lambda value: (value["user_name"].casefold(), value["user_id"]))


@router.get("")
def list_presence():
    with _lock:
        return _active_users(datetime.now(timezone.utc))


@router.put("")
def update_presence(request: PresenceUpdate):
    now = datetime.now(timezone.utc)
    with _lock:
        _users[request.user_id] = {"user_id": request.user_id, "user_name": request.user_name, "color": request.color.upper(), "last_seen": now.isoformat()}
        return _active_users(now)


@router.delete("/{user_id}")
def remove_presence(user_id: str):
    with _lock:
        _users.pop(user_id.strip(), None)
        return _active_users(datetime.now(timezone.utc))
