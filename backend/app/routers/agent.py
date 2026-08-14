from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..database import get_db
from ..services.excel_open_service import open_excel_location
from ..services.knowledge_service import (
    create_knowledge,
    delete_knowledge,
    list_knowledge,
    serialize_knowledge,
    update_knowledge,
)
from ..services.memory_service import (
    delete_memory,
    list_memories,
    serialize_memory,
    update_memory,
)


router = APIRouter(prefix="/api/agent", tags=["agent"])


class MemoryUpdateRequest(BaseModel):
    content: str | None = None
    scope: str | None = None
    memory_type: str | None = None
    customer_name: str | None = None
    product_name: str | None = None
    confirmed: bool | None = None
    importance: float | None = Field(default=None, ge=0.0, le=1.0)


class KnowledgeCreateRequest(BaseModel):
    category: str = "rule"
    title: str
    content: str
    product_name: str | None = None
    material_name: str | None = None
    usage_context: str | None = None
    tags: str | None = None
    priority: float = Field(default=0.7, ge=0.0, le=1.0)


class KnowledgeUpdateRequest(BaseModel):
    category: str | None = None
    title: str | None = None
    content: str | None = None
    product_name: str | None = None
    material_name: str | None = None
    usage_context: str | None = None
    tags: str | None = None
    active: bool | None = None
    priority: float | None = Field(default=None, ge=0.0, le=1.0)


class OpenPriceSourceRequest(BaseModel):
    source_sheet: str | None = None
    source_cell: str | None = None


@router.get("/memories")
def get_memories(
    query: str | None = Query(default=None),
    customer_name: str | None = Query(default=None),
    product_name: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_db),
):
    rows = list_memories(
        session,
        query=query,
        customer_name=customer_name,
        product_name=product_name,
        confirmed_only=True,
        limit=limit,
    )
    return [serialize_memory(row) for row in rows]


@router.patch("/memories/{memory_id}")
def patch_memory(
    memory_id: int,
    request: MemoryUpdateRequest,
    session: Session = Depends(get_db),
):
    try:
        row = update_memory(
            session,
            memory_id,
            **request.model_dump(exclude_none=True),
        )
        session.commit()
        session.refresh(row)
        return serialize_memory(row)
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        session.rollback()
        raise HTTPException(status_code=400, detail=f"장기기억 수정 실패: {error}") from error


@router.delete("/memories/{memory_id}")
def remove_memory(
    memory_id: int,
    session: Session = Depends(get_db),
):
    try:
        deleted = delete_memory(session, memory_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="장기기억을 찾을 수 없습니다.")
        session.commit()
        return {"deleted": memory_id}
    except HTTPException:
        session.rollback()
        raise
    except Exception as error:
        session.rollback()
        raise HTTPException(status_code=400, detail=f"장기기억 삭제 실패: {error}") from error


@router.get("/knowledge")
def get_knowledge(
    query: str | None = Query(default=None),
    category: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_db),
):
    rows = list_knowledge(
        session,
        query=query,
        category=category,
        active_only=True,
        limit=limit,
    )
    return [serialize_knowledge(row) for row in rows]


@router.post("/knowledge")
def add_knowledge(
    request: KnowledgeCreateRequest,
    session: Session = Depends(get_db),
):
    try:
        row = create_knowledge(
            session,
            **request.model_dump(),
        )
        session.commit()
        session.refresh(row)
        return serialize_knowledge(row)
    except Exception as error:
        session.rollback()
        raise HTTPException(status_code=400, detail=f"업무 지식 저장 실패: {error}") from error


@router.patch("/knowledge/{knowledge_id}")
def patch_knowledge(
    knowledge_id: int,
    request: KnowledgeUpdateRequest,
    session: Session = Depends(get_db),
):
    try:
        row = update_knowledge(
            session,
            knowledge_id,
            **request.model_dump(exclude_none=True),
        )
        session.commit()
        session.refresh(row)
        return serialize_knowledge(row)
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        session.rollback()
        raise HTTPException(status_code=400, detail=f"업무 지식 수정 실패: {error}") from error


@router.delete("/knowledge/{knowledge_id}")
def remove_knowledge(
    knowledge_id: int,
    session: Session = Depends(get_db),
):
    try:
        deleted = delete_knowledge(session, knowledge_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="업무 지식을 찾을 수 없습니다.")
        session.commit()
        return {"deleted": knowledge_id}
    except HTTPException:
        session.rollback()
        raise
    except Exception as error:
        session.rollback()
        raise HTTPException(status_code=400, detail=f"업무 지식 삭제 실패: {error}") from error


@router.post("/open-price-source")
def open_price_source(
    request: OpenPriceSourceRequest,
    settings: Settings = Depends(get_settings),
):
    """브라우저 입력으로 임의 경로를 열지 않고 설정된 단가표만 연다."""
    try:
        return open_excel_location(
            settings.price_table_path,
            sheet=request.source_sheet,
            cell=request.source_cell,
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"Excel 열기 실패: {error}") from error
