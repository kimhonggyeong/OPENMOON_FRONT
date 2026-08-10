from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment]

from ..config import Settings
from ..models import (
    ChatMessage, Mail, MailItem, QuotationDraft, QuotationLearningFact, ReviewIssue,
)
from .history_service import get_history_candidates
from .learning_service import learning_facts_for_mail
from .price_candidate_service import get_external_price_candidates
from .quotation_service import create_quotation
from .review_service import evaluate_mail_readiness


def _item_for_command(mail: Mail, text: str) -> MailItem | None:
    ordinal = re.search(r"(\d+)\s*(?:번|번째)\s*(?:품목|항목)?", text)
    if ordinal:
        position = int(ordinal.group(1))
        return next((item for item in mail.items if item.position == position), None)
    named = [item for item in mail.items if item.product_name and item.product_name in text]
    if len(named) == 1:
        return named[0]
    return mail.items[0] if len(mail.items) == 1 else None


def _record_fact(
    session: Session, mail: Mail, user_message: ChatMessage, item: MailItem | None,
    field: str, old: Any, new: Any, applied: bool,
) -> None:
    session.add(QuotationLearningFact(
        mail_id=mail.id,
        chat_message_id=user_message.id,
        item_id=item.id if item else None,
        fact_type="USER_CORRECTION" if old not in (None, "") else "USER_CONFIRMED_FACT",
        field_name=field,
        old_value=old,
        new_value=new,
        customer_name=mail.customer_organization or mail.customer_name,
        product_name=item.product_name if item else None,
        specification=item.specification if item else None,
        source="chat_user",
        confirmed=True,
        applied=applied,
        confidence=1.0,
    ))


def _apply_command(session: Session, settings: Settings, mail: Mail, message: ChatMessage):
    text = message.content.strip()
    item = _item_for_command(mail, text)
    actions: list[dict[str, Any]] = []

    quantity = re.search(
        r"수량(?:을|은|이)?\s*(\d+(?:\.\d+)?)\s*(개|장|부|매|곽|세트)?(?:로)?\s*(?:바꿔|변경|수정|해줘|해주세요|입력|확정)", text
    )
    if not quantity:
        quantity = re.search(
            r"(\d+(?:\.\d+)?)\s*(개|장|부|매|곽|세트)(?:로)?\s*(?:바꿔|변경|수정|해줘|해주세요|입력|확정)", text
        )
    if quantity:
        if item is None:
            return [], "품목이 여러 개라서 대상을 정할 수 없습니다. ‘2번째 품목 수량을 2개로 바꿔줘’처럼 말씀해 주세요."
        old = item.quantity
        value = float(quantity.group(1))
        item.quantity = value
        if quantity.group(2):
            item.unit = quantity.group(2)
        if item.unit_price is not None:
            item.amount = int(round(value * item.unit_price))
        item.confirmed = bool(item.unit_price is not None)
        _record_fact(session, mail, message, item, "quantity", old, value, True)
        actions.append({"field": "quantity", "item_id": item.id, "old": old, "new": value})

    unit_price = re.search(
        r"(?:단가|가격)(?:를|은|이)?\s*([\d,]+)\s*원?(?:으로)?\s*(?:바꿔|변경|수정|해줘|해주세요|입력|확정)", text
    )
    if unit_price:
        if item is None:
            return [], "품목이 여러 개라서 단가를 바꿀 대상을 지정해 주세요."
        old = item.unit_price
        value = int(unit_price.group(1).replace(",", ""))
        item.unit_price = value
        item.amount = int(round(value * item.quantity)) if item.quantity is not None else None
        item.confirmed = True
        evidence = dict(item.evidence or {})
        evidence["price"] = {"source": "manual", "reason": "사용자 대화로 확정한 단가"}
        item.evidence = evidence
        _record_fact(session, mail, message, item, "unit_price", old, value, True)
        actions.append({"field": "unit_price", "item_id": item.id, "old": old, "new": value})

    if not actions:
        return [], None

    session.flush()
    # 기존 누락 이슈는 새 값 기준으로 다시 계산한다.
    for issue in session.scalars(select(ReviewIssue).where(
        ReviewIssue.mail_id == mail.id, ReviewIssue.resolved.is_(False)
    )).all():
        if any(issue.field_name == f"items.{a['item_id']}.{a['field']}" for a in actions):
            issue.resolved = True
            issue.resolution_value = next(a["new"] for a in actions if issue.field_name == f"items.{a['item_id']}.{a['field']}")
    session.commit()
    evaluate_mail_readiness(session, settings, mail)

    draft_updated = False
    existing = session.scalar(select(QuotationDraft).where(QuotationDraft.mail_id == mail.id))
    blocking = session.scalar(select(ReviewIssue.id).where(
        ReviewIssue.mail_id == mail.id,
        ReviewIssue.resolved.is_(False),
        ReviewIssue.severity == "blocking",
    ))
    if existing is not None and blocking is None:
        create_quotation(session, settings, mail)
        draft_updated = True
    return actions, draft_updated


def _reference_context(session: Session, settings: Settings, mail: Mail):
    evidence: list[dict[str, Any]] = []
    lines: list[str] = []
    try:
        for row in get_external_price_candidates(session, settings, mail)[:8]:
            evidence.append({"type": row["source"], "label": row.get("reference") or row["reason"]})
            lines.append(f"가격 후보: {row['product_name']} / {row['unit_price']}원 / {row['source']} / {row.get('reference') or ''}")
    except Exception:
        pass
    for item in mail.items:
        for history_item, quotation in get_history_candidates(session, mail, item, limit=3):
            label = f"{quotation.customer_name} {quotation.quotation_date or ''} {history_item.product_name} {history_item.quantity or '-'} {history_item.unit or ''} {history_item.unit_price or '-'}원"
            evidence.append({"type": "history", "label": label, "source_file": quotation.source_file})
            lines.append("과거 견적: " + label)
    for fact in learning_facts_for_mail(session, mail, limit=8):
        label = f"{fact.customer_name or '-'} / {fact.product_name or '-'} / {fact.field_name}={fact.new_value}"
        evidence.append({"type": "human_decision", "label": label})
        lines.append("사람이 확정한 과거 판단: " + label)
    return lines[:15], evidence[:15]


def _answer(session: Session, settings: Settings, mail: Mail, text: str):
    refs, evidence = _reference_context(session, settings, mail)
    history = session.scalars(select(ChatMessage).where(ChatMessage.mail_id == mail.id).order_by(ChatMessage.id.desc()).limit(12)).all()
    history_text = "\n".join(f"{m.role}: {m.content}" for m in reversed(history))
    items = [{"position": i.position, "product": i.product_name, "spec": i.specification, "quantity": i.quantity, "unit": i.unit, "unit_price": i.unit_price} for i in mail.items]
    if not settings.openai_api_key or OpenAI is None:
        return "현재 견적 정보와 DB 근거를 확인했습니다. 값을 변경하려면 ‘수량을 2개로 바꿔줘’처럼 말씀해 주세요.", evidence
    prompt = f"""당신은 열린문디자인 견적 보조 챗봇입니다. 아래 현재 메일과 견적 DB 근거만 이용해 한국어로 간결히 답하세요. 가격/수량의 출처를 구분하고 모르면 모른다고 하세요. 실제 변경은 서버가 별도로 처리하므로 변경했다고 거짓말하지 마세요.\n기관: {mail.customer_organization}\n제목: {mail.original_subject}\n품목: {json.dumps(items, ensure_ascii=False)}\nDB 근거:\n{chr(10).join(refs) or '없음'}\n최근 대화:\n{history_text}\n사용자: {text}"""
    client = OpenAI(api_key=settings.openai_api_key)
    response = client.responses.create(model=settings.openai_model, input=prompt)
    return (response.output_text or "답변을 생성하지 못했습니다."), evidence


def chat_with_mail(session: Session, settings: Settings, mail: Mail, text: str):
    user = ChatMessage(mail_id=mail.id, role="user", content=text)
    session.add(user)
    session.flush()
    actions, result = _apply_command(session, settings, mail, user)
    draft_updated = result is True
    if actions:
        details = []
        for action in actions:
            item = session.get(MailItem, action["item_id"])
            label = item.product_name if item else "품목"
            field = "수량" if action["field"] == "quantity" else "단가"
            value = f"{action['new']:g}{item.unit or ''}" if action["field"] == "quantity" else f"{action['new']:,}원"
            details.append(f"{label}의 {field}을(를) {value}로 변경했습니다.")
        answer = " ".join(details) + (" 기존 견적서 초안도 업데이트했습니다." if draft_updated else " 변경 이력을 학습 자료로 저장했습니다.")
        evidence = [{"type": "user_instruction", "label": "사용자 대화로 직접 확정"}]
    elif isinstance(result, str):
        answer, evidence = result, []
    else:
        answer, evidence = _answer(session, settings, mail, text)
    assistant = ChatMessage(mail_id=mail.id, role="assistant", content=answer, evidence=evidence, action_payload={"actions": actions, "draft_updated": draft_updated})
    session.add(assistant)
    session.commit()
    session.refresh(user)
    session.refresh(assistant)
    return user, assistant, draft_updated
