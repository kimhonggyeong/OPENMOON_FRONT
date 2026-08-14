from __future__ import annotations

from typing import Any


def calculate_supply_amount(
    quantity: float | int | None,
    unit_price: float | int | None,
) -> int | None:
    """견적 공급금액의 단일 계산 규칙: 수량 × 단가."""
    if quantity is None or unit_price is None:
        return None
    return int(round(float(quantity) * int(unit_price)))


def normalize_item_amount(item: Any) -> int | None:
    amount = calculate_supply_amount(
        getattr(item, "quantity", None),
        getattr(item, "unit_price", None),
    )
    item.amount = amount
    return amount


def quote_total(items: list[Any]) -> int | None:
    if not items:
        return None
    amounts: list[int] = []
    for item in items:
        amount = calculate_supply_amount(
            getattr(item, "quantity", None),
            getattr(item, "unit_price", None),
        )
        if amount is None:
            return None
        amounts.append(amount)
    return sum(amounts)


def has_quote_spec(item: Any) -> bool:
    """견적서의 규격 칸에 넣을 최소 정보가 있는지 확인."""
    return any(
        value not in (None, "")
        for value in (
            getattr(item, "specification", None),
            getattr(item, "size_name", None),
            getattr(item, "width_mm", None),
            getattr(item, "height_mm", None),
            getattr(item, "paper", None),
            getattr(item, "material", None),
        )
    )


def validate_quote_items(items: list[Any]) -> list[str]:
    errors: list[str] = []
    if not items:
        return ["견적서에 입력할 품목이 없습니다."]

    for index, item in enumerate(items, start=1):
        product = str(getattr(item, "product_name", "") or "").strip()
        label = product or f"{index}번째 품목"

        if not product:
            errors.append(f"{index}번째 품목명이 비어 있습니다.")
        if not has_quote_spec(item):
            errors.append(f"{label}의 규격/재질 정보를 확인해 주세요.")
        if getattr(item, "quantity", None) is None:
            errors.append(f"{label}의 수량을 확인해 주세요.")
        if getattr(item, "unit_price", None) is None:
            errors.append(f"{label}의 단가를 확인해 주세요.")

    return errors
