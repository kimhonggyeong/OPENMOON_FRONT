from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


DEFAULT_BASE_BUILDER = Path(r"C:\Users\hk010\PycharmProjects\OPENMOON\build_price_db.py")

# These workbooks use bare numbers for quantity in repeated horizontal blocks.
# Each tuple is (first column in block, last column in block, quantity column).
BARE_QUANTITY_BLOCKS = {
    "리플릿": [
        (1, 5, 1), (8, 14, 8), (18, 24, 18), (28, 36, 28),
        (38, 46, 38), (50, 56, 50), (58, 66, 58),
    ],
    "카다로그": [
        (1, 12, 1), (14, 25, 14), (27, 38, 27), (40, 58, 40),
    ],
}


def load_base_builder(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("openmoon_price_builder", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"기존 빌더를 불러올 수 없습니다: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def explicit_quantity(module: ModuleType, ws: Any, row: int, price_col: int) -> tuple[float | None, str | None]:
    # Prefer values that explicitly carry a unit, e.g. 500매.
    for col in range(price_col - 1, max(0, price_col - 15), -1):
        raw = module.get_merged_top_left_value(ws, row, col)
        quantity, unit = module.extract_quantity_strict(raw)
        if quantity is not None:
            return quantity, unit

    # Leaflet/catalog sheets use a fixed leading quantity column per block.
    for first_col, last_col, quantity_col in BARE_QUANTITY_BLOCKS.get(ws.title.strip(), []):
        if first_col <= price_col <= last_col:
            raw = module.get_merged_top_left_value(ws, row, quantity_col)
            quantity = module.to_float(raw)
            if quantity is not None and 0 < quantity <= 100_000:
                return quantity, "매"
    return None, None


def context_details(module: ModuleType, ws: Any, row: int, price_col: int) -> tuple[float | None, str | None, str | None, str | None]:
    quantity, unit = explicit_quantity(module, ws, row, price_col)
    values = [
        module.normalize_text(module.get_merged_top_left_value(ws, row, col))
        for col in range(max(1, price_col - 12), price_col)
    ]
    joined = " / ".join(value for value in values if value)
    material = next(
        (
            keyword
            for keyword in (
                "아트지", "스노우지", "모조지", "백상지", "랑데뷰",
                "휘라레", "반누보", "레자크", "크라프트", "부직포",
                "패트지", "메쉬", "포맥스", "아크릴", "골판지", "허니콤",
            )
            if keyword in joined
        ),
        None,
    )
    return quantity, unit, material, module.infer_print_side(joined)


def fixed_explicit_sale_parser(
    module: ModuleType,
    ws: Any,
    connection: Any,
    *,
    force_product_name: str | None = None,
    vat_included: int | None = None,
) -> int:
    inserted = 0
    sale_headers = {module.compact_text(value) for value in module.EXPLICIT_SALE_HEADERS}
    non_sale_headers = {module.compact_text(value) for value in module.NON_SALE_HEADERS}

    for row in range(1, ws.max_row + 1):
        for col in range(1, ws.max_column + 1):
            price = module.to_int_price(ws.cell(row, col).value)
            if price is None:
                continue
            _, header_text = module.find_header_above(ws, row, col, max_distance=5)
            if header_text is None:
                continue
            header_compact = module.compact_text(header_text)
            if header_compact in non_sale_headers or header_compact not in sale_headers:
                continue

            quantity, unit, material, print_side = context_details(module, ws, row, col)
            product_name, specification = module.find_product_and_specification(ws, row, col)
            product_name = force_product_name or product_name
            width_mm, height_mm = module.extract_size(specification)

            # In these sheets '단가' is the selling amount for the row's order quantity,
            # not a per-copy price. Never multiply it by quantity again.
            item = module.PriceItem(
                product_name=product_name,
                normalized_name=module.normalize_product_name(product_name, ws.title),
                category=ws.title.strip(),
                specification=specification or f"{header_text} 기준",
                width_mm=width_mm,
                height_mm=height_mm,
                thickness_mm=module.extract_thickness(specification),
                material=material,
                paper=module.extract_paper(specification),
                print_side=print_side,
                quantity=quantity,
                quantity_min=quantity,
                quantity_max=quantity,
                unit=unit,
                unit_price=None,
                total_price=price,
                vat_included=vat_included,
                sheet_name=ws.title,
                row_number=row,
                column_number=col,
                original_text=module.row_original_text(ws, row),
                confidence=0.9,
                review_required=0,
            )
            before = connection.total_changes
            module.insert_price_item(connection, item)
            if connection.total_changes > before:
                inserted += 1
    return inserted


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a corrected OPENMOON price database.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--base-builder", type=Path, default=DEFAULT_BASE_BUILDER)
    args = parser.parse_args()

    module = load_base_builder(args.base_builder)

    def patched_parser(ws: Any, connection: Any, **kwargs: Any) -> int:
        return fixed_explicit_sale_parser(module, ws, connection, **kwargs)

    module.parse_explicit_sale_columns = patched_parser
    module.build_price_database(args.input, args.db)


if __name__ == "__main__":
    main()
