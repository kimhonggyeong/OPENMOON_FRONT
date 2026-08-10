from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import Settings, get_settings
from ..database import get_db
from ..models import ChatMessage, Mail
from ..schemas import ChatMessageOut, ChatRequest, ChatResponse, MailDetailOut
from ..services.chat_service import chat_with_mail

router = APIRouter(prefix="/api/mails", tags=["chat"])


def _mail_query(mail_id: int):
    return select(Mail).where(Mail.id == mail_id).options(
        selectinload(Mail.attachments), selectinload(Mail.items),
        selectinload(Mail.reviews), selectinload(Mail.drafts),
    )


@router.get("/{mail_id}/chat", response_model=list[ChatMessageOut])
def list_chat(mail_id: int, session: Session = Depends(get_db)):
    if session.get(Mail, mail_id) is None:
        raise HTTPException(404, "메일을 찾을 수 없습니다.")
    return session.scalars(select(ChatMessage).where(ChatMessage.mail_id == mail_id).order_by(ChatMessage.id)).all()


@router.post("/{mail_id}/chat", response_model=ChatResponse)
def send_chat(request: ChatRequest, mail_id: int, session: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    mail = session.scalar(_mail_query(mail_id))
    if mail is None:
        raise HTTPException(404, "메일을 찾을 수 없습니다.")
    try:
        user, assistant, draft_updated = chat_with_mail(session, settings, mail, request.message)
        refreshed = session.scalar(_mail_query(mail_id))
        return {"user_message": user, "assistant_message": assistant, "mail": refreshed, "draft_updated": draft_updated}
    except Exception as error:
        session.rollback()
        raise HTTPException(400, f"챗봇 처리 실패: {error}") from error
