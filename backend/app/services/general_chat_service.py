from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import GeneralChatMessage
from .agent_service import run_general_agent
from .ai_provider import is_ai_configured

# 전체 상담은 특정 메일에 묶여 자연스럽게 끊기는 메일별 채팅과 달리 하나의
# 공용 대화라서 상한이 없으면 계속 쌓인다. LLM에는 이미 최근 8개만 넘기고
# 있어서(agent_service.RECENT_CHAT_LIMIT) 그보다 훨씬 오래된 메시지는 답변
# 품질에 도움이 되지 않으면서 목록 조회(GET /api/chat/general) 응답만
# 계속 커지게 만든다. 최근 N개만 남기고 그보다 오래된 메시지는 지운다.
GENERAL_CHAT_RETENTION_LIMIT = 200


def _prune_general_chat(session: Session, keep: int = GENERAL_CHAT_RETENTION_LIMIT) -> None:
    total = session.scalar(select(func.count()).select_from(GeneralChatMessage))
    if not total or total <= keep:
        return

    cutoff_id = session.scalar(
        select(GeneralChatMessage.id)
        .order_by(GeneralChatMessage.id.desc())
        .offset(keep - 1)
        .limit(1)
    )
    if cutoff_id is None:
        return

    session.execute(delete(GeneralChatMessage).where(GeneralChatMessage.id < cutoff_id))


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
    session.flush()

    _prune_general_chat(session)

    session.commit()
    session.refresh(user)
    session.refresh(assistant)
    return user, assistant
