from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..enums import AttachmentStatus, MailStatus, Severity
from ..models import Mail, MailItem, ReviewIssue
from .history_service import get_history_candidates
from .price_engine_adapter import calculate_item_price
from .quantity_suggestion_service import suggest_quantity_from_history
from .quote_math import missing_catalog_fields

# 품목별 세부사양의 기준 데이터는 config/product_catalog.json이다.
# 여기서는 공통 규격 필수값을 별도로 강제하지 않는다.


def _history_suggestions(session: Session, mail: Mail, item: MailItem, field: str) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    rows = get_history_candidates(session, mail, item, limit=10)
    seen: set[Any] = set()
    for history_item, quotation in rows:
        value = getattr(history_item, field, None)
        if value in (None, "") or value in seen:
            continue
        seen.add(value)
        suggestions.append(
            {
                "value": value,
                "quotation_date": str(quotation.quotation_date or ""),
                "specification": history_item.specification,
                "source_file": quotation.source_file,
                "source_sheet": quotation.source_sheet,
            }
        )
        if len(suggestions) >= 5:
            break
    return suggestions


def _add_issue(
    session: Session,
    mail_id: int,
    code: str,
    message: str,
    field_name: str | None = None,
    severity: str = Severity.BLOCKING,
    suggestions: list[Any] | None = None,
) -> None:
    session.add(
        ReviewIssue(
            mail_id=mail_id,
            code=code,
            field_name=field_name,
            message=message,
            severity=severity,
            suggestions=suggestions or [],
            source="AUTO",
        )
    )


def evaluate_mail_readiness(session: Session, settings: Settings, mail: Mail) -> list[ReviewIssue]:
    # 사용자가 해결한 기록은 남기고, 자동 미해결 이슈만 다시 만든다.
    session.execute(
        delete(ReviewIssue).where(
            ReviewIssue.mail_id == mail.id,
            ReviewIssue.source == "AUTO",
            ReviewIssue.resolved.is_(False),
        )
    )
    session.flush()

    # 이전 웹 분석 결과도 재분석 없이 원본 프로그램 방식으로 보정한다.
    if not mail.customer_organization and mail.customer_department:
        mail.customer_organization = mail.customer_department.strip()

    # 주문·견적 업무가 아닌 메일은 고객·품목·가격 누락 검토 대상이 아니다.
    if mail.analysis_payload.get("is_order_related") is False:
        mail.status = MailStatus.NOT_RELEVANT
        session.commit()
        session.refresh(mail)
        return []

    if not mail.customer_id and not mail.customer_organization:
        _add_issue(
            session,
            mail.id,
            "CUSTOMER_NOT_IDENTIFIED",
            "고객 또는 기관을 식별할 수 없습니다.",
            "customer_organization",
        )

    if mail.confidence is not None and mail.confidence < settings.low_confidence_threshold:
        _add_issue(
            session,
            mail.id,
            "LOW_ANALYSIS_CONFIDENCE",
            f"메일 분석 신뢰도가 {mail.confidence:.2f}로 기준보다 낮습니다.",
        )

    if not mail.items:
        _add_issue(session, mail.id, "NO_ORDER_ITEM", "주문 품목을 확인할 수 없습니다.", "items")

    for item in mail.items:
        product = item.normalized_product or item.product_name

        # 품목별 사양(규격, 용지, 재질 등)은 product_catalog 기준이며
        # 여기서 공통 필수값으로 차단하지 않는다.
        # 다만 마감처리·시공여부는 시공비·납품 방식 등 가격/일정 결정에
        # 직결되므로, 카탈로그에 해당 품목의 필드가 정의돼 있는데
        # 값이 비어있으면 검토 필요로 차단한다.
        for field in missing_catalog_fields(
            item, keys={"finishing", "installation_delivery"}
        ):
            label = str(field.get("label") or field.get("key") or "사양")
            _add_issue(
                session,
                mail.id,
                "MISSING_ITEM_SPEC",
                f"{product}의 {label} 정보가 없습니다.",
                f"items.{item.id}.spec_attributes.{field.get('key')}",
            )

        # 견적 금액 계산에 반드시 필요한 수량은 담당자가 확인하도록 한다.
        if item.quantity in (None, ""):
            quantity_suggestions = suggest_quantity_from_history(
                settings.quotation_database_path,
                mail,
                item,
            )
            _add_issue(
                session,
                mail.id,
                "MISSING_QUANTITY",
                (
                    f"{product}의 수량 확인이 필요합니다. "
                    f"{quantity_suggestions[0]['message']}"
                    if quantity_suggestions
                    else f"{product}의 수량을 확인할 수 없습니다."
                ),
                f"items.{item.id}.quantity",
                suggestions=quantity_suggestions,
            )

        # 원본 price_engine.py는 규격이 없더라도 고객·품목·수량으로
        # 과거 견적을 먼저 검색한다. 웹 전용 필수 규격 검사로 이를 막지 않는다.
        if item.unit_price is not None and item.confirmed:
            pass
        else:
            decision = calculate_item_price(
                settings=settings,
                mail=mail,
                item=item,
            )

            item.unit_price = decision.unit_price
            item.amount = decision.amount
            item.confirmed = bool(
                decision.unit_price is not None
                and not decision.needs_review
            )
            evidence = dict(item.evidence or {})
            evidence["price"] = asdict(decision)
            item.evidence = evidence

        if item.unit_price is not None and item.confirmed:
            pass
        elif decision.unit_price is None:
            _add_issue(
                session,
                mail.id,
                "NO_PRICE_CANDIDATE",
                f"{product}에 적용할 가격 후보를 찾지 못했습니다.",
                f"items.{item.id}.unit_price",
            )
        else:
            _add_issue(
                session,
                mail.id,
                "PRICE_REVIEW_REQUIRED",
                f"{product}의 가격 {decision.unit_price:,}원은 검토가 필요한 후보입니다.",
                f"items.{item.id}.unit_price",
                suggestions=[asdict(decision)],
            )

    for attachment in mail.attachments:
        if attachment.status in {
            AttachmentStatus.MANUAL_REVIEW,
            AttachmentStatus.FAILED,
            AttachmentStatus.IMAGE_PENDING,
        }:
            _add_issue(
                session,
                mail.id,
                "ATTACHMENT_REVIEW_REQUIRED",
                f"첨부파일 '{attachment.filename}'의 자동 분석이 완료되지 않았습니다.",
                f"attachments.{attachment.id}",
            )

    reference_words = ("지난번", "저번", "작년", "이전처럼", "전에 했던", "그때처럼")
    body = f"{mail.original_subject or ''} {mail.original_body or ''}"
    if any(word in body for word in reference_words):
        history_found = any(get_history_candidates(session, mail, item, limit=1) for item in mail.items)
        if not history_found:
            _add_issue(
                session,
                mail.id,
                "UNRESOLVED_HISTORY_REFERENCE",
                "이전 제작물을 가리키는 표현이 있지만 연결할 고객 견적 이력을 찾지 못했습니다.",
                "history_reference",
            )

    # AI의 missing_information은 분석 결과 영역에 이미 표시된다.
    # 같은 내용을 검토 항목으로 중복 생성하지 않는다.

    session.flush()
    unresolved = session.scalars(
        select(ReviewIssue).where(ReviewIssue.mail_id == mail.id, ReviewIssue.resolved.is_(False))
    ).all()
    blocking = [issue for issue in unresolved if issue.severity == Severity.BLOCKING]
    mail.status = MailStatus.REVIEW_REQUIRED if blocking else MailStatus.READY_FOR_QUOTE
    session.commit()
    session.refresh(mail)
    return unresolved


def apply_review_resolution(session: Session, issue: ReviewIssue, value: Any) -> None:
    issue.resolution_value = value
    issue.resolved = True

    if issue.field_name and issue.field_name.startswith("items."):
        _, item_id, field = issue.field_name.split(".", 2)
        item = session.get(MailItem, int(item_id))
        if item and hasattr(item, field):
            setattr(item, field, value)
            item.confirmed = True
            if field == "unit_price":
                evidence = dict(item.evidence or {})
                evidence["price"] = {
                    "source": "manual",
                    "type": "MANUAL",
                    "reason": "담당자가 검토 화면에서 직접 입력한 단가",
                }
                item.evidence = evidence
                if item.quantity is not None:
                    item.amount = int(round(float(item.quantity) * int(value)))
            elif field == "quantity" and item.unit_price is not None:
                item.amount = int(round(float(value) * int(item.unit_price)))
    elif issue.field_name and issue.field_name.startswith("customer_"):
        mail = session.get(Mail, issue.mail_id)
        if mail and hasattr(mail, issue.field_name):
            setattr(mail, issue.field_name, value)
    session.commit()
