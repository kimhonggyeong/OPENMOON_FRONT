from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..database import get_db
from ..models import GeneralChatMessage
from ..schemas import GeneralChatMessageOut, GeneralChatRequest, GeneralChatResponse
from ..services.general_chat_service import general_chat

router = APIRouter(prefix="/api/chat", tags=["general-chat"])


@router.get("/general", response_model=list[GeneralChatMessageOut])
def list_general_chat(session: Session = Depends(get_db)):
    return session.scalars(
        select(GeneralChatMessage).order_by(GeneralChatMessage.id)
    ).all()


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
