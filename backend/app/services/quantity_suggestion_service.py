from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from ..models import Mail, MailItem
from .external_price_engine import compact_text, extract_dimensions, normalize_product_name


def _same_dimensions(
    requested: tuple[float | None, float | None],
    candidate: tuple[float | None, float | None],
) -> bool:
    rw, rh = requested
    cw, ch = candidate
    if None in (rw, rh, cw, ch):
        return False

    def close(a: float, b: float) -> bool:
        return abs(a - b) <= max(abs(a), 1.0) * 0.01

    return bool(
        (close(float(rw), float(cw)) and close(float(rh), float(ch)))
        or (close(float(rw), float(ch)) and close(float(rh), float(cw)))
    )


def _same_specification(item: MailItem, row: sqlite3.Row) -> bool:
    requested_dimensions = (
        item.width_mm,
        item.height_mm,
    )
    if None in requested_dimensions:
        requested_dimensions = extract_dimensions(item.specification)

    candidate_dimensions = (
        row["width_mm"],
        row["height_mm"],
    )
    if None in candidate_dimensions:
        candidate_dimensions = extract_dimensions(row["specification_raw"])

    if None not in requested_dimensions:
        return _same_dimensions(requested_dimensions, candidate_dimensions)

    requested_spec = compact_text(item.specification)
    candidate_spec = compact_text(row["specification_raw"])
    if not requested_spec or not candidate_spec:
        return False

    return (
        requested_spec == candidate_spec
        or requested_spec in candidate_spec
        or candidate_spec in requested_spec
    )


def suggest_quantity_from_history(
    database_path: Path,
    mail: Mail,
    item: MailItem,
    recent_count: int = 5,
    minimum_repeats: int = 3,
) -> list[dict[str, Any]]:
    """최근 동일 조건의 수량이 반복될 때 검토용 예상 수량만 반환한다."""
    organization = compact_text(
        mail.customer_organization or mail.customer_name
    )
    if not organization or not database_path.exists():
        return []

    requested_product = normalize_product_name(item.product_name)

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT
                q.id AS quotation_id,
                q.quote_date,
                q.customer_organization,
                qi.product_name,
                qi.normalized_product,
                qi.specification_raw,
                qi.width_mm,
                qi.height_mm,
                qi.quantity,
                qi.unit,
                sf.file_name,
                q.sheet_name
            FROM quotation_items qi
            JOIN quotations q ON q.id = qi.quotation_id
            JOIN source_files sf ON sf.id = q.source_file_id
            WHERE qi.quantity IS NOT NULL
            ORDER BY COALESCE(q.quote_date, '') DESC, q.id DESC, qi.id DESC
            """
        ).fetchall()

    product_matches: list[sqlite3.Row] = []
    for row in rows:
        candidate_organization = compact_text(row["customer_organization"])
        if not candidate_organization or not (
            candidate_organization in organization
            or organization in candidate_organization
        ):
            continue
        candidate_product = normalize_product_name(
            row["normalized_product"] or row["product_name"]
        )
        if candidate_product != requested_product:
            continue
        product_matches.append(row)

    requested_has_spec = bool(
        compact_text(item.specification)
        or None not in (item.width_mm, item.height_mm)
    )
    if requested_has_spec:
        matches = [
            row for row in product_matches
            if _same_specification(item, row)
        ][:recent_count]
    else:
        # 현재 규격이 없으면 과거에 반복된 동일 규격만 비교 대상으로 삼는다.
        spec_counts = Counter(
            compact_text(row["specification_raw"])
            for row in product_matches
            if compact_text(row["specification_raw"])
        )
        stable_spec = next(
            (
                spec for spec, count in spec_counts.most_common()
                if count >= minimum_repeats
            ),
            None,
        )
        if stable_spec is None:
            return []
        matches = [
            row for row in product_matches
            if compact_text(row["specification_raw"]) == stable_spec
        ][:recent_count]

    if len(matches) < minimum_repeats:
        return []

    quantities = [float(row["quantity"]) for row in matches]
    quantity_counts = Counter(quantities)
    quantity, repeat_count = quantity_counts.most_common(1)[0]
    if repeat_count < minimum_repeats or repeat_count <= len(matches) / 2:
        return []

    display_quantity: int | float = int(quantity) if quantity.is_integer() else quantity
    unit = next((str(row["unit"]) for row in matches if row["unit"]), item.unit or "")
    dates = [str(row["quote_date"] or "날짜 미확인") for row in matches]
    references = [
        f"{row['file_name']} / {row['sheet_name']}"
        for row in matches
    ]

    return [
        {
            "value": display_quantity,
            "unit": unit,
            "recent_count": len(matches),
            "repeat_count": repeat_count,
            "dates": dates,
            "references": references,
            "source": "quotation_history_db",
            "message": (
                (
                    f"최근 동일 회사·품목·규격 {len(matches)}회 모두 "
                    if repeat_count == len(matches)
                    else f"최근 동일 회사·품목·규격 {len(matches)}회 중 {repeat_count}회 "
                )
                + f"{display_quantity}{unit} 주문 — 예상 수량 {display_quantity}{unit}"
            ),
        }
    ]
