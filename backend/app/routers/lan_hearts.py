from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..lan_heart import HeartStore


router = APIRouter(prefix="/api/lan-hearts", tags=["lan-hearts"])
store = HeartStore()


class HeartProxyUpdate(BaseModel):
    mail_key: str = Field(min_length=1, max_length=1000)
    hearted: bool
    user_id: str | None = Field(default=None, max_length=100)
    user_name: str | None = Field(default=None, max_length=50)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")


@router.get("")
def list_hearts():
    return store.all()


@router.put("")
def update_heart(request: HeartProxyUpdate):
    try:
        return {
            "mail_key": request.mail_key,
            **store.set(
                request.mail_key,
                request.hearted,
                user_id=request.user_id,
                user_name=request.user_name,
                color=request.color,
            ),
        }
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/status")
def connection_status():
    return {"configured": True}
