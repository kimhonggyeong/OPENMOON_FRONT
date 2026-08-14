from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, String, Text, or_, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from ..database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AgentKnowledge(Base):
    """직원이 직접 관리하는 열린문디자인의 안정적인 업무 지식."""

    __tablename__ = "agent_knowledge"

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(40), default="rule", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    product_name: Mapped[str | None] = mapped_column(String(255), index=True)
    material_name: Mapped[str | None] = mapped_column(String(255), index=True)
    usage_context: Mapped[str | None] = mapped_column(String(255), index=True)
    tags: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(80), default="manual")

    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    priority: Mapped[float] = mapped_column(Float, default=0.7)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )


def ensure_knowledge_table(session: Session) -> None:
    AgentKnowledge.__table__.create(bind=session.get_bind(), checkfirst=True)


def serialize_knowledge(row: AgentKnowledge) -> dict[str, object]:
    return {
        "id": row.id,
        "category": row.category,
        "title": row.title,
        "content": row.content,
        "product_name": row.product_name,
        "material_name": row.material_name,
        "usage_context": row.usage_context,
        "tags": row.tags,
        "source": row.source,
        "active": row.active,
        "priority": row.priority,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def create_knowledge(
    session: Session,
    *,
    category: str,
    title: str,
    content: str,
    product_name: str | None = None,
    material_name: str | None = None,
    usage_context: str | None = None,
    tags: str | None = None,
    priority: float = 0.7,
    source: str = "manual",
) -> AgentKnowledge:
    ensure_knowledge_table(session)
    title = title.strip()
    content = content.strip()
    if not title:
        raise ValueError("지식 제목이 비어 있습니다.")
    if not content:
        raise ValueError("지식 내용이 비어 있습니다.")

    row = AgentKnowledge(
        category=(category or "rule").strip(),
        title=title,
        content=content,
        product_name=(product_name or "").strip() or None,
        material_name=(material_name or "").strip() or None,
        usage_context=(usage_context or "").strip() or None,
        tags=(tags or "").strip() or None,
        priority=max(0.0, min(float(priority), 1.0)),
        source=source,
        active=True,
    )
    session.add(row)
    session.flush()
    return row


def update_knowledge(
    session: Session,
    knowledge_id: int,
    **changes: object,
) -> AgentKnowledge:
    ensure_knowledge_table(session)
    row = session.get(AgentKnowledge, knowledge_id)
    if row is None:
        raise ValueError("업무 지식을 찾을 수 없습니다.")

    allowed = {
        "category",
        "title",
        "content",
        "product_name",
        "material_name",
        "usage_context",
        "tags",
        "active",
        "priority",
    }
    for key, value in changes.items():
        if key not in allowed or value is None:
            continue
        if key in {
            "category",
            "title",
            "content",
            "product_name",
            "material_name",
            "usage_context",
            "tags",
        }:
            value = str(value).strip()
            if key in {"title", "content"} and not value:
                raise ValueError(f"{key} 값은 비울 수 없습니다.")
            if key in {"product_name", "material_name", "usage_context", "tags"}:
                value = value or None
        if key == "priority":
            value = max(0.0, min(float(value), 1.0))
        setattr(row, key, value)

    row.updated_at = _utcnow()
    session.flush()
    return row


def delete_knowledge(session: Session, knowledge_id: int) -> bool:
    ensure_knowledge_table(session)
    row = session.get(AgentKnowledge, knowledge_id)
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True


def list_knowledge(
    session: Session,
    *,
    query: str | None = None,
    category: str | None = None,
    active_only: bool = True,
    limit: int = 100,
) -> list[AgentKnowledge]:
    ensure_knowledge_table(session)
    stmt = select(AgentKnowledge)
    if active_only:
        stmt = stmt.where(AgentKnowledge.active.is_(True))
    if category:
        stmt = stmt.where(AgentKnowledge.category == category)
    if query:
        q = query.strip()
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                or_(
                    AgentKnowledge.title.ilike(like),
                    AgentKnowledge.content.ilike(like),
                    AgentKnowledge.product_name.ilike(like),
                    AgentKnowledge.material_name.ilike(like),
                    AgentKnowledge.usage_context.ilike(like),
                    AgentKnowledge.tags.ilike(like),
                )
            )
    stmt = stmt.order_by(
        AgentKnowledge.priority.desc(),
        AgentKnowledge.updated_at.desc(),
        AgentKnowledge.id.desc(),
    ).limit(max(1, min(limit, 500)))
    return list(session.scalars(stmt).all())


def search_knowledge(
    session: Session,
    *,
    query: str,
    product_name: str | None = None,
    material_name: str | None = None,
    usage_context: str | None = None,
    limit: int = 8,
) -> list[AgentKnowledge]:
    """
    V3는 별도 Vector DB를 도입하지 않고 SQLite LIKE 기반으로 시작한다.
    회사 지식 규모가 커지면 이 함수만 FTS/embedding 검색으로 교체할 수 있다.
    """
    ensure_knowledge_table(session)
    base = select(AgentKnowledge).where(AgentKnowledge.active.is_(True))

    has_scope_filter = False
    for value, column in (
        (product_name, AgentKnowledge.product_name),
        (material_name, AgentKnowledge.material_name),
        (usage_context, AgentKnowledge.usage_context),
    ):
        value = (value or "").strip()
        if value:
            has_scope_filter = True
            base = base.where(or_(column.is_(None), column.ilike(f"%{value}%")))

    synonym_map = {
        "야외": "실외",
        "실외": "야외",
        "오래": "장기",
        "장기간": "장기",
        "튼튼": "내구",
    }
    words: list[str] = []
    for token in (query or "").replace("/", " ").replace(",", " ").split():
        token = token.strip()
        if len(token) < 2:
            continue
        words.append(token)
        mapped = synonym_map.get(token)
        if mapped:
            words.append(mapped)
        if len(words) >= 10:
            break

    searchable_columns = (
        AgentKnowledge.title,
        AgentKnowledge.content,
        AgentKnowledge.product_name,
        AgentKnowledge.material_name,
        AgentKnowledge.usage_context,
        AgentKnowledge.tags,
    )
    stmt = base
    if words:
        stmt = stmt.where(
            or_(
                *[
                    column.ilike(f"%{word}%")
                    for word in words
                    for column in searchable_columns
                ]
            )
        )

    ordering = (
        AgentKnowledge.priority.desc(),
        AgentKnowledge.updated_at.desc(),
        AgentKnowledge.id.desc(),
    )
    safe_limit = max(1, min(limit, 20))
    rows = list(session.scalars(stmt.order_by(*ordering).limit(safe_limit)).all())

    # 품목/재질/사용환경이 이미 특정됐는데 자연어 표현만 달라 0건이 된 경우,
    # 해당 범위의 상위 지식을 fallback으로 반환한다.
    if not rows and has_scope_filter and words:
        rows = list(session.scalars(base.order_by(*ordering).limit(safe_limit)).all())
    return rows
