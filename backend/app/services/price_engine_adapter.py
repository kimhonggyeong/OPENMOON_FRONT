from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Mail, MailItem
from .external_price_engine import (
    PriceDecision,
    apply_prices,
)


def calculate_mail_prices(
    session: Session,
    settings: Settings,
    mail: Mail,
) -> list[PriceDecision]:
    """
    새 SQLite 가격 엔진을 이용해 메일의 모든 품목 가격을 검색한다.

    우선순위:
    1. 동일하거나 유사한 과거 견적
    2. 단가표 SQLite DB
    3. 찾지 못하면 미확정
    """

    del session

    if not settings.use_external_price_engine:
        return []

    if not settings.quotation_database_path.exists():
        raise FileNotFoundError(
            "기존 견적 DB를 찾을 수 없습니다: "
            f"{settings.quotation_database_path}"
        )

    if not settings.price_database_path.exists():
        raise FileNotFoundError(
            "단가표 DB를 찾을 수 없습니다: "
            f"{settings.price_database_path}"
        )

    decisions = apply_prices(
        items=mail.items,
        customer_organization=(
            mail.customer_organization
            or mail.customer_name
        ),
        quotation_database_path=(
            settings.quotation_database_path
        ),
        price_database_path=(
            settings.price_database_path
        ),
    )

    return decisions


def calculate_item_price(
    settings: Settings,
    mail: Mail,
    item: MailItem,
) -> PriceDecision:
    """
    특정 품목 하나만 가격 엔진으로 검색한다.
    """

    if not settings.quotation_database_path.exists():
        raise FileNotFoundError(
            "기존 견적 DB를 찾을 수 없습니다: "
            f"{settings.quotation_database_path}"
        )

    if not settings.price_database_path.exists():
        raise FileNotFoundError(
            "단가표 DB를 찾을 수 없습니다: "
            f"{settings.price_database_path}"
        )

    decisions = apply_prices(
        items=[item],
        customer_organization=(
            mail.customer_organization
            or mail.customer_name
        ),
        quotation_database_path=(
            settings.quotation_database_path
        ),
        price_database_path=(
            settings.price_database_path
        ),
    )

    if not decisions:
        return PriceDecision(
            item_index=0,
            product_name=item.product_name,
            unit_price=None,
            amount=None,
            source="unresolved",
            reference=None,
            score=0.0,
            reason=(
                "가격 검색 결과가 없습니다."
            ),
            needs_review=True,
        )

    return decisions[0]


def apply_price_decisions_to_mail(
    session: Session,
    mail: Mail,
    decisions: list[PriceDecision],
) -> None:
    """
    가격 검색 결과를 MailItem에 적용한다.

    확정·검토 상태와 가격 출처는 evidence JSON에 보존한다.
    """

    item_map = {
        index: item
        for index, item in enumerate(
            mail.items
        )
    }

    for decision in decisions:
        item = item_map.get(
            decision.item_index
        )

        if item is None:
            continue

        item.unit_price = (
            decision.unit_price
        )

        item.amount = (
            decision.amount
        )

        current_evidence: dict[str, Any] = (
            dict(item.evidence or {})
        )

        current_evidence["price"] = {
            **asdict(decision),
        }

        item.evidence = current_evidence

        # 검토가 필요 없는 고신뢰 가격만 자동 확정한다.
        item.confirmed = (
            decision.unit_price is not None
            and not decision.needs_review
        )

        session.add(item)

    session.flush()


def price_decision_to_dict(
    decision: PriceDecision,
) -> dict[str, Any]:
    return asdict(decision)