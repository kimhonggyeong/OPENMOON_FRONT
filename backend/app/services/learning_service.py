from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import Mail, QuotationLearningFact


def learning_facts_for_mail(
    session: Session, mail: Mail, limit: int = 20
) -> list[QuotationLearningFact]:
    """동일 고객 또는 동일 이메일에서 사람이 확정한 최근 판단만 반환한다."""
    customer = (mail.customer_organization or mail.customer_name or "").strip()
    sender = (mail.customer_email or mail.original_sender_email or "").strip()
    matchers = []
    if customer:
        matchers.append(QuotationLearningFact.customer_name.contains(customer))
    if sender:
        matchers.append(Mail.original_sender_email == sender)
        matchers.append(Mail.customer_email == sender)
    if not matchers:
        return []
    query = (
        select(QuotationLearningFact)
        .join(Mail, QuotationLearningFact.mail_id == Mail.id)
        .where(
            QuotationLearningFact.confirmed.is_(True),
            QuotationLearningFact.applied.is_(True),
            or_(*matchers),
        )
        .order_by(QuotationLearningFact.id.desc())
        .limit(limit)
    )
    return session.scalars(query).all()


def learning_context(session: Session, mail: Mail, limit: int = 12) -> str:
    rows = learning_facts_for_mail(session, mail, limit)
    if not rows:
        return ""
    lines = ["사람이 대화로 확정했던 과거 판단(참고용이며 현재 메일보다 우선하지 않음):"]
    for row in rows:
        lines.append(
            f"- 고객={row.customer_name or '-'}, 품목={row.product_name or '-'}, "
            f"규격={row.specification or '-'}, {row.field_name}: "
            f"{row.old_value!r} -> {row.new_value!r}"
        )
    return "\n".join(lines)
