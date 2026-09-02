from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import Settings, get_settings
from ..database import get_db
from ..enums import DraftStatus
from ..models import QuotationDraft
from ..services.external_db_admin import delete_price, list_prices, remove_draft_from_history, save_price, sync_draft_to_history

router = APIRouter(prefix="/api/data-admin", tags=["data-admin"])


class PricePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_name: str
    category: str | None = None
    specification: str | None = None
    width_mm: float | None = None
    height_mm: float | None = None
    material: str | None = None
    paper: str | None = None
    print_side: str | None = None
    quantity: float | None = None
    unit: str | None = None
    unit_price: int | None = None
    total_price: int | None = None
    vat_included: bool = False


@router.post("/quotation-history/sync")
def sync_history(session: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    drafts = session.scalars(select(QuotationDraft).options(selectinload(QuotationDraft.items), selectinload(QuotationDraft.mail)).order_by(QuotationDraft.id)).all()
    sent_drafts = [draft for draft in drafts if draft.status == DraftStatus.SENT and draft.sent_at is not None]
    synced, errors = [], []
    removed_unapproved = 0
    for draft in drafts:
        if draft not in sent_drafts:
            removed_unapproved += remove_draft_from_history(settings.quotation_database_path, draft.id)
    for draft in sent_drafts:
        try:
            synced.append(sync_draft_to_history(settings.quotation_database_path, draft, draft.mail))
        except Exception as error:
            errors.append({"draft_id": draft.id, "error": str(error)})
    return {
        "processed": len(sent_drafts),
        "synced": len(synced),
        "failed": len(errors),
        "skipped_unapproved": len(drafts) - len(sent_drafts),
        "removed_unapproved": removed_unapproved,
        "errors": errors[:20],
    }

@router.get("/price-items")
def prices(search: str = Query(default="", max_length=100), settings: Settings = Depends(get_settings)):
    return list_prices(settings.price_database_path, search)


@router.post("/price-items")
def add_price(payload: PricePayload, settings: Settings = Depends(get_settings)):
    try:
        return save_price(settings.price_database_path, payload.model_dump())
    except Exception as error:
        raise HTTPException(400, str(error)) from error


@router.put("/price-items/{item_id}")
def edit_price(item_id: int, payload: PricePayload, settings: Settings = Depends(get_settings)):
    try:
        return save_price(settings.price_database_path, payload.model_dump(), item_id)
    except KeyError as error:
        raise HTTPException(404, str(error)) from error
    except Exception as error:
        raise HTTPException(400, str(error)) from error


@router.delete("/price-items/{item_id}")
def remove_price(item_id: int, settings: Settings = Depends(get_settings)):
    try:
        delete_price(settings.price_database_path, item_id)
        return {"deleted": item_id}
    except KeyError as error:
        raise HTTPException(404, str(error)) from error
