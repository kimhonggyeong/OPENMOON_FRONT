from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment]

from ..config import Settings
from ..database import Base
from ..models import ChatMessage


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ConversationSummary(Base):
    __tablename__ = "agent_conversation_summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    mail_id: Mapped[int] = mapped_column(ForeignKey("mails.id"), unique=True, index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    covered_message_id: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )


def ensure_summary_table(session: Session) -> None:
    ConversationSummary.__table__.create(bind=session.get_bind(), checkfirst=True)


def get_summary(session: Session, mail_id: int) -> ConversationSummary | None:
    ensure_summary_table(session)
    return session.scalar(
        select(ConversationSummary).where(ConversationSummary.mail_id == mail_id)
    )


def _messages_for_summary(
    session: Session,
    mail_id: int,
    *,
    recent_keep: int,
) -> tuple[list[ChatMessage], list[ChatMessage]]:
    rows = list(
        session.scalars(
            select(ChatMessage)
            .where(ChatMessage.mail_id == mail_id)
            .order_by(ChatMessage.id.asc())
        ).all()
    )
    if len(rows) <= recent_keep:
        return [], rows
    return rows[:-recent_keep], rows[-recent_keep:]


def _summarize(
    settings: Settings,
    previous_summary: str,
    messages: list[ChatMessage],
) -> str | None:
    if not settings.openai_api_key or OpenAI is None or not messages:
        return None

    chunks = []
    for row in messages[-20:]:
        content = (row.content or "").strip()
        if len(content) > 1400:
            content = content[:1400] + "…"
        chunks.append(f"{row.role}: {content}")

    previous = previous_summary.strip() if previous_summary else "없음"
    prompt = (
        "기존 요약:\n"
        + previous
        + "\n\n새로 반영할 대화:\n"
        + "\n".join(chunks)
    )

    client = OpenAI(api_key=settings.openai_api_key)
    response = client.responses.create(
        model=settings.openai_model,
        instructions=(
            "열린문디자인 견적 업무 대화를 다음 대화에서 이어갈 수 있게 압축 요약하세요. "
            "고객/기관, 품목, 규격, 수량, 재질, 가격, 사용자가 확정한 변경, 아직 해결되지 않은 질문만 보존하세요. "
            "AI의 추측은 사실처럼 남기지 말고, 일회성 잡담은 제거하세요. "
            "한국어 700자 이내의 평문으로 작성하세요."
        ),
        input=[{"role": "user", "content": prompt}],
    )
    value = (response.output_text or "").strip()
    return value or None


def get_or_refresh_summary(
    session: Session,
    settings: Settings,
    mail_id: int,
    *,
    recent_keep: int = 8,
    minimum_total_messages: int = 16,
    refresh_after_messages: int = 8,
) -> str | None:
    """긴 대화를 매번 전부 보내지 않도록 오래된 메시지만 누적 요약한다."""
    ensure_summary_table(session)
    old_rows, recent_rows = _messages_for_summary(
        session,
        mail_id,
        recent_keep=recent_keep,
    )
    total_count = len(old_rows) + len(recent_rows)
    existing = get_summary(session, mail_id)

    if total_count < minimum_total_messages or not old_rows:
        return existing.summary if existing else None

    target_message_id = old_rows[-1].id
    covered = existing.covered_message_id if existing else 0
    pending = [row for row in old_rows if row.id > covered]

    if existing and len(pending) < refresh_after_messages:
        return existing.summary

    try:
        summary = _summarize(
            settings,
            existing.summary if existing else "",
            pending if existing else old_rows,
        )
    except Exception:
        return existing.summary if existing else None

    if not summary:
        return existing.summary if existing else None

    if existing is None:
        existing = ConversationSummary(
            mail_id=mail_id,
            summary=summary,
            covered_message_id=target_message_id,
        )
        session.add(existing)
    else:
        existing.summary = summary
        existing.covered_message_id = target_message_id
        existing.updated_at = _utcnow()

    session.flush()
    return summary
