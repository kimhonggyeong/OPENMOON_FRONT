from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import Settings
from ..models import GeneralChatMessage
from .agent_service import run_general_agent
from .ai_provider import is_ai_configured


def general_chat(
    session: Session, settings: Settings, text: str
) -> tuple[GeneralChatMessage, GeneralChatMessage]:
    """특정 메일/견적과 무관한 일반 상담 메시지를 처리하고 대화 기록에 남긴다."""
    user = GeneralChatMessage(role="user", content=text)
    session.add(user)
    session.flush()

    if is_ai_configured(settings):
        agent_result = run_general_agent(session, settings, text, user_message_id=user.id)
        answer = agent_result.answer
        evidence = agent_result.evidence
    else:
        answer = "AI 공급자가 설정되어 있지 않아 이 상담 모드를 사용할 수 없습니다."
        evidence = []

    assistant = GeneralChatMessage(role="assistant", content=answer, evidence=evidence)
    session.add(assistant)
    session.commit()
    session.refresh(user)
    session.refresh(assistant)
    return user, assistant
