from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, or_, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from ..database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AgentMemory(Base):
    """메일을 넘어 재사용할 열린문디자인 업무 기억."""

    __tablename__ = "agent_memories"

    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(20), default="customer", index=True)
    memory_type: Mapped[str] = mapped_column(String(40), default="fact", index=True)
    customer_name: Mapped[str | None] = mapped_column(String(255), index=True)
    product_name: Mapped[str | None] = mapped_column(String(255), index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_mail_id: Mapped[int | None] = mapped_column(ForeignKey("mails.id"), index=True)
    source_chat_message_id: Mapped[int | None] = mapped_column(ForeignKey("chat_messages.id"), index=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    importance: Mapped[float] = mapped_column(Float, default=0.7)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )


def ensure_memory_table(session: Session) -> None:
    AgentMemory.__table__.create(bind=session.get_bind(), checkfirst=True)


def serialize_memory(row: AgentMemory) -> dict[str, object]:
    return {
        "id": row.id,
        "scope": row.scope,
        "memory_type": row.memory_type,
        "customer_name": row.customer_name,
        "product_name": row.product_name,
        "content": row.content,
        "confirmed": row.confirmed,
        "importance": row.importance,
        "source_mail_id": row.source_mail_id,
        "source_chat_message_id": row.source_chat_message_id,
        "last_used_at": row.last_used_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def save_memory(
    session: Session,
    *,
    content: str,
    scope: str,
    memory_type: str,
    customer_name: str | None,
    product_name: str | None,
    source_mail_id: int | None,
    source_chat_message_id: int | None,
    importance: float = 0.7,
) -> AgentMemory:
    ensure_memory_table(session)
    content = content.strip()
    if not content:
        raise ValueError("기억할 내용이 비어 있습니다.")

    existing = session.scalar(
        select(AgentMemory).where(
            AgentMemory.content == content,
            AgentMemory.customer_name == customer_name,
            AgentMemory.product_name == product_name,
            AgentMemory.confirmed.is_(True),
        )
    )
    if existing is not None:
        existing.last_used_at = _utcnow()
        existing.importance = max(float(existing.importance or 0), importance)
        session.flush()
        return existing

    memory = AgentMemory(
        scope=scope,
        memory_type=memory_type,
        customer_name=(customer_name or "").strip() or None,
        product_name=(product_name or "").strip() or None,
        content=content,
        source_mail_id=source_mail_id,
        source_chat_message_id=source_chat_message_id,
        confirmed=True,
        importance=max(0.0, min(float(importance), 1.0)),
    )
    session.add(memory)
    session.flush()
    return memory


def list_memories(
    session: Session,
    *,
    query: str | None = None,
    customer_name: str | None = None,
    product_name: str | None = None,
    confirmed_only: bool = True,
    limit: int = 100,
) -> list[AgentMemory]:
    ensure_memory_table(session)
    stmt = select(AgentMemory)
    if confirmed_only:
        stmt = stmt.where(AgentMemory.confirmed.is_(True))
    if customer_name:
        stmt = stmt.where(AgentMemory.customer_name.ilike(f"%{customer_name.strip()}%"))
    if product_name:
        stmt = stmt.where(AgentMemory.product_name.ilike(f"%{product_name.strip()}%"))
    if query:
        q = query.strip()
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                or_(
                    AgentMemory.content.ilike(like),
                    AgentMemory.customer_name.ilike(like),
                    AgentMemory.product_name.ilike(like),
                    AgentMemory.memory_type.ilike(like),
                )
            )
    stmt = stmt.order_by(
        AgentMemory.importance.desc(),
        AgentMemory.updated_at.desc(),
        AgentMemory.id.desc(),
    ).limit(max(1, min(limit, 500)))
    return list(session.scalars(stmt).all())


def update_memory(
    session: Session,
    memory_id: int,
    **changes: object,
) -> AgentMemory:
    ensure_memory_table(session)
    row = session.get(AgentMemory, memory_id)
    if row is None:
        raise ValueError("장기기억을 찾을 수 없습니다.")

    allowed = {
        "scope",
        "memory_type",
        "customer_name",
        "product_name",
        "content",
        "confirmed",
        "importance",
    }
    for key, value in changes.items():
        if key not in allowed or value is None:
            continue
        if key in {"scope", "memory_type", "customer_name", "product_name", "content"}:
            value = str(value).strip()
            if key == "content" and not value:
                raise ValueError("기억 내용은 비울 수 없습니다.")
            if key in {"customer_name", "product_name"}:
                value = value or None
        if key == "importance":
            value = max(0.0, min(float(value), 1.0))
        setattr(row, key, value)

    row.updated_at = _utcnow()
    session.flush()
    return row


def delete_memory(session: Session, memory_id: int) -> bool:
    ensure_memory_table(session)
    row = session.get(AgentMemory, memory_id)
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True


def search_memories(
    session: Session,
    *,
    customer_name: str | None = None,
    product_name: str | None = None,
    query: str | None = None,
    limit: int = 8,
) -> list[AgentMemory]:
    ensure_memory_table(session)
    stmt = select(AgentMemory).where(AgentMemory.confirmed.is_(True))

    if customer_name:
        stmt = stmt.where(
            or_(
                AgentMemory.scope == "company",
                AgentMemory.customer_name.is_(None),
                AgentMemory.customer_name.ilike(f"%{customer_name}%"),
            )
        )

    if product_name:
        stmt = stmt.where(
            or_(
                AgentMemory.product_name.is_(None),
                AgentMemory.product_name.ilike(f"%{product_name}%"),
            )
        )

    words = [
        word.strip()
        for word in (query or "").replace("/", " ").replace(",", " ").split()
        if len(word.strip()) >= 2
    ][:6]
    # 고객/품목이 이미 특정된 경우에는 자연어 질문의 표현 차이 때문에
    # 관련 기억을 놓치지 않도록 keyword를 hard filter로 사용하지 않는다.
    if words and not customer_name and not product_name:
        stmt = stmt.where(or_(*[AgentMemory.content.ilike(f"%{word}%") for word in words]))

    stmt = stmt.order_by(
        AgentMemory.importance.desc(),
        AgentMemory.updated_at.desc(),
        AgentMemory.id.desc(),
    ).limit(max(1, min(limit, 20)))

    rows = list(session.scalars(stmt).all())
    now = _utcnow()
    for row in rows:
        row.last_used_at = now
    session.flush()
    return rows


def memory_context_for_mail(
    session: Session,
    *,
    customer_name: str | None,
    product_names: list[str],
    query: str,
    limit: int = 6,
) -> list[dict[str, object]]:
    product = product_names[0] if len(product_names) == 1 else None
    rows = search_memories(
        session,
        customer_name=customer_name,
        product_name=product,
        query=query,
        limit=limit,
    )
    return [
        {
            "id": row.id,
            "scope": row.scope,
            "type": row.memory_type,
            "customer": row.customer_name,
            "product": row.product_name,
            "content": row.content,
        }
        for row in rows
    ]
