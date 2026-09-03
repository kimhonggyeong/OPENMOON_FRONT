from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..database import get_db
from ..models import GeneralChatMessage
from ..schemas import GeneralChatMessageOut, GeneralChatRequest, GeneralChatResponse
from ..services.general_chat_service import GENERAL_CHAT_RETENTION_LIMIT, general_chat

router = APIRouter(prefix="/api/chat", tags=["general-chat"])


@router.get("/general", response_model=list[GeneralChatMessageOut])
def list_general_chat(session: Session = Depends(get_db)):
    # 저장 자체를 general_chat_service._prune_general_chat이 최근
    # GENERAL_CHAT_RETENTION_LIMIT개로 유지하지만, 조회 응답도 방어적으로
    # 같은 상한을 걸어 예상보다 데이터가 많이 남아 있어도 매번 느려지지 않게 한다.
    rows = session.scalars(
        select(GeneralChatMessage)
        .order_by(GeneralChatMessage.id.desc())
        .limit(GENERAL_CHAT_RETENTION_LIMIT)
    ).all()
    return list(reversed(rows))


@router.post("/general", response_model=GeneralChatResponse)
def send_general_chat(
    request: GeneralChatRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    try:
        user, assistant = general_chat(session, settings, request.message)
        return {"user_message": user, "assistant_message": assistant}
    except Exception as error:
        session.rollback()
        raise HTTPException(400, f"챗봇 처리 실패: {error}") from error
