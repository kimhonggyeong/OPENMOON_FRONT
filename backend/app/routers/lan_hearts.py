from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..lan_heart import HeartStore


router = APIRouter(prefix="/api/lan-hearts", tags=["lan-hearts"])
store = HeartStore()


class HeartProxyUpdate(BaseModel):
    mail_key: str = Field(min_length=1, max_length=1000)
    hearted: bool


@router.get("")
def list_hearts():
    return store.all()


@router.put("")
def update_heart(request: HeartProxyUpdate):
    try:
        return {
            "mail_key": request.mail_key,
            "hearted": store.set(request.mail_key, request.hearted),
        }
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/status")
def connection_status():
    return {"configured": True}
