from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Mail
from .price_engine_adapter import (
    calculate_mail_prices,
)


def _source_label(
    source: str,
) -> str:
    labels = {
        "history": "기존 견적서",
        "price_table": "단가표 DB",
        "mail": "메일 원문",
        "unresolved": "미확정",
    }

    return labels.get(
        source,
        source,
    )


def _extract_source_location(
    reference: str | None,
) -> tuple[str, str]:
    """
    외부 가격 엔진의 reference 문자열에서
    기존 화면 호환용 시트와 셀 정보를 가능한 범위에서 추출한다.

    정확히 해석할 수 없는 경우 빈 문자열을 반환한다.
    """

    if not reference:
        return "", ""

    # 단가 DB/시트명 행 15 ID 123
    price_match = re.search(
        r"단가 DB/(?P<sheet>.+?)\s+행\s+"
        r"(?P<row>\d+)",
        reference,
    )

    if price_match:
        return (
            price_match.group("sheet").strip(),
            f"행 {price_match.group('row')}",
        )

    # 단가 DB 선형보간/시트명 ID ...
    interpolation_match = re.search(
        r"단가 DB 선형보간/"
        r"(?P<sheet>.+?)\s+ID\s+",
        reference,
    )

    if interpolation_match:
        return (
            interpolation_match.group(
                "sheet"
            ).strip(),
            "선형보간",
        )

    # 과거 견적 파일 / 시트 / 블록 ...
    history_match = re.search(
        r"과거 견적\s+"
        r"(?P<file>.+?)\s*/\s*"
        r"(?P<sheet>.+?)\s*/\s*"
        r"블록\s+(?P<block>\d+)",
        reference,
    )

    if history_match:
        return (
            history_match.group(
                "sheet"
            ).strip(),
            (
                "블록 "
                + history_match.group(
                    "block"
                )
            ),
        )

    return "", ""


def get_external_price_candidates(
    session: Session,
    settings: Settings,
    mail: Mail,
) -> list[dict[str, Any]]:
    """
    새 가격 엔진 결과를 PriceCandidateOut과
    호환되는 딕셔너리 목록으로 변환한다.
    """

    decisions = calculate_mail_prices(
        session=session,
        settings=settings,
        mail=mail,
    )

    results: list[dict[str, Any]] = []

    for index, decision in enumerate(
        decisions
    ):
        if (
            0 <= decision.item_index
            < len(mail.items)
        ):
            item = mail.items[
                decision.item_index
            ]
        elif index < len(mail.items):
            item = mail.items[index]
        else:
            continue

        source_sheet, source_cell = (
            _extract_source_location(
                decision.reference
            )
        )

        exact = bool(
            decision.unit_price is not None
            and not decision.needs_review
        )

        results.append(
            {
                "item_id": item.id,
                "item_index": index,
                "product_name": (
                    decision.product_name
                ),
                "unit_price": (
                    decision.unit_price
                ),
                "amount": (
                    decision.amount
                ),
                "source": (
                    decision.source
                ),
                "reference": (
                    decision.reference
                ),
                "score": (
                    decision.score
                ),
                "reason": (
                    decision.reason
                ),
                "needs_review": (
                    decision.needs_review
                ),
                "exact": exact,
                "source_sheet": (
                    source_sheet
                ),
                "source_cell": (
                    source_cell
                ),
                "context": (
                    f"{_source_label(decision.source)}"
                    + (
                        f" · {decision.reference}"
                        if decision.reference
                        else ""
                    )
                ),
                "vat": None,
                "automation_status": (
                    "담당자확인"
                    if decision.needs_review
                    else "자동적용가능"
                ),
            }
        )

    return results