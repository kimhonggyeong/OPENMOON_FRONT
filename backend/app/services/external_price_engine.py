from __future__ import annotations

import math
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

class OrderItemLike(Protocol):
    product_name: str
    specification: str | None
    quantity: float | None
    unit: str | None
    unit_price: int | None
    amount: int | None


@dataclass
class PriceDecision:
    item_index: int
    product_name: str
    unit_price: int | None
    amount: int | None
    source: str
    reference: str | None
    score: float
    reason: str
    needs_review: bool


PRODUCT_ALIASES = {
    "친환경배너": [
        "친환경배너",
        "친환경 배너",
        "에코배너",
    ],

    "현수막": [
        "현수막",
        "게릴라현수막",
        "육교현수막",
        "시청현수막",
    ],

    "배너": [
        "배너",
        "부직포배너",
        "패트지배너",
        "메쉬배너",
        "엑스배너",
        "x배너",
        "롤배너",
    ],

    "명함": [
        "명함",
        "카드명함",
        "점자명함",
    ],

    "포스터": [
        "포스터",
    ],

    "어깨띠": [
        "어깨띠",
    ],

    "전단지": [
        "전단",
        "전단지",
    ],

    "리플릿": [
        "리플릿",
        "리플렛",
    ],

    "카다로그": [
        "책자",
        "카다로그",
        "카탈로그",
        "브로슈어",
        "브로셔",
    ],

    "양식지": [
        "양식지",
        "서식지",
        "ncr",
        "ncr지",
    ],

    "봉투": [
        "봉투",
        "대봉투",
        "소봉투",
        "자켓봉투",
        "창봉투",
        "옵셋봉투",
    ],

    "상장지": [
        "상장지",
        "상장용지",
    ],

    "책제본": [
        "책제본",
        "제본",
    ],

    "골지보드": [
        "골지",
        "골지보드",
        "허니콤",
        "허니콤보드",
    ],

    "포맥스": [
        "포맥스",
        "표찰",
        "포맥스안내판",
    ],

    "아크릴": [
        "아크릴",
        "아크릴안내판",
    ],

    "사원증": [
        "사원증",
        "명찰",
        "id카드",
        "아이디카드",
    ],

    "인포그래픽": [
        "인포그래픽",
        "ppt",
        "ppt디자인",
    ],

    "간판": [
        "간판",
        "후렉스",
        "천갈이",
    ],

    "초대장": [
        "초대장",
    ],

    "스티커": [
        "스티커",
        "라벨",
    ],
}

SIZE_PATTERN = re.compile(
    r"(?<!\d)(\d+(?:\.\d+)?)\s*(mm|㎜|cm|㎝|m|인치|inch|in)?\s*"
    r"[*xX×ｘ]\s*(\d+(?:\.\d+)?)\s*(mm|㎜|cm|㎝|m|인치|inch|in)?",
    re.IGNORECASE,
)

STOP_WORDS = {
    "제작", "요청", "의뢰", "디자인", "변경", "인쇄", "시안", "배송", "부탁",
    "규격", "사이즈", "사용", "포함", "개", "장", "매", "곽", "부", "세트",
}


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def compact_text(value: Any) -> str:
    return re.sub(r"[\s:：·ㆍ\-_()/\[\]{},.+]", "", normalize_text(value)).lower()


def normalize_product_name(value: str) -> str:
    compact = compact_text(value)
    for normalized, aliases in PRODUCT_ALIASES.items():
        if any(compact_text(alias) in compact for alias in aliases):
            return normalized
    return normalize_text(value).splitlines()[0][:100]


def _dimension_to_mm(number: float, unit: str | None) -> float:
    unit = (unit or "mm").lower()
    if unit in {"cm", "㎝"}:
        return number * 10
    if unit == "m":
        return number * 1000
    if unit in {"인치", "inch", "in"}:
        return number * 25.4
    return number


def extract_dimensions(text: str | None) -> tuple[float | None, float | None]:
    if not text:
        return None, None
    match = SIZE_PATTERN.search(text)
    if not match:
        return None, None
    first = float(match.group(1))
    first_unit = match.group(2)
    second = float(match.group(3))
    second_unit = match.group(4)
    unit = second_unit or first_unit or "mm"
    return _dimension_to_mm(first, unit), _dimension_to_mm(second, unit)


def _tokenize(text: str | None) -> set[str]:
    if not text:
        return set()
    tokens = re.findall(r"[가-힣A-Za-z0-9]+", text.lower())
    return {
        token for token in tokens
        if len(token) >= 2 and token not in STOP_WORDS and not token.isdigit()
    }


def _dimension_score(
    requested: tuple[float | None, float | None],
    candidate: tuple[float | None, float | None],
) -> float:
    rw, rh = requested
    cw, ch = candidate
    if rw is None or rh is None:
        return 10.0
    if cw is None or ch is None:
        return -18.0

    def error(a: float, b: float, c: float, d: float) -> float:
        return abs(a - c) / max(a, 1) + abs(b - d) / max(b, 1)

    relative_error = min(error(rw, rh, cw, ch), error(rw, rh, ch, cw))
    if relative_error <= 0.01:
        return 30.0
    if relative_error <= 0.10:
        return 24.0
    if relative_error <= 0.25:
        return 14.0
    if relative_error <= 0.50:
        return 3.0
    return -20.0


def _quantity_score(requested: float | None, candidate: float | None) -> float:
    if requested is None:
        return 4.0
    if candidate is None:
        return -3.0
    if requested == candidate:
        return 12.0
    ratio = max(requested, candidate) / max(min(requested, candidate), 0.0001)
    if ratio <= 1.25:
        return 9.0
    if ratio <= 2:
        return 4.0
    if ratio <= 5:
        return -2.0
    return -8.0


def search_history_price(
    database_path: Path,
    item: OrderItemLike,
    customer_organization: str | None,
    limit: int = 30,
    minimum_score: float = 65.0,
) -> PriceDecision | None:
    if not database_path.exists():
        return None

    normalized_product = normalize_product_name(item.product_name)
    requested_spec = normalize_text(item.specification)
    requested_dimensions = extract_dimensions(requested_spec or item.product_name)
    requested_tokens = _tokenize(f"{item.product_name} {requested_spec}")

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT
                sf.file_name,
                sf.file_path,
                q.sheet_name,
                q.block_index,
                q.quote_date,
                q.customer_organization,
                qi.product_name,
                qi.normalized_product,
                qi.specification_raw,
                qi.width_mm,
                qi.height_mm,
                qi.quantity,
                qi.unit,
                qi.unit_price,
                qi.amount,
                qi.source_row
            FROM quotation_items qi
            JOIN quotations q ON q.id = qi.quotation_id
            JOIN source_files sf ON sf.id = q.source_file_id
            WHERE qi.unit_price IS NOT NULL
              AND qi.unit_price > 0
              AND (
                    qi.normalized_product = ?
                 OR qi.product_name LIKE ?
                 OR qi.normalized_product LIKE ?
              )
            ORDER BY q.quote_date DESC, qi.id DESC
            LIMIT ?
            """,
            (
                normalized_product,
                f"%{item.product_name}%",
                f"%{normalized_product}%",
                limit,
            ),
        ).fetchall()
    finally:
        connection.close()

    best: tuple[float, sqlite3.Row, str] | None = None
    for row in rows:
        score = 45.0 if row["normalized_product"] == normalized_product else 28.0
        score += _dimension_score(
            requested_dimensions,
            (row["width_mm"], row["height_mm"]),
        )
        score += _quantity_score(item.quantity, row["quantity"])

        candidate_text = f"{row['product_name']} {row['specification_raw'] or ''}"
        candidate_tokens = _tokenize(candidate_text)
        if requested_tokens:
            overlap = len(requested_tokens & candidate_tokens) / max(len(requested_tokens), 1)
            score += overlap * 18.0
            if overlap == 0 and len(requested_tokens) >= 2:
                score -= 8.0

        if customer_organization and row["customer_organization"]:
            if compact_text(customer_organization) == compact_text(row["customer_organization"]):
                score += 10.0

        if item.unit and row["unit"]:
            score += 3.0 if compact_text(item.unit) == compact_text(row["unit"]) else -3.0

        reason = (
            f"과거 견적 {row['file_name']} / {row['sheet_name']} / "
            f"블록 {row['block_index']} / 행 {row['source_row']}"
        )
        if best is None or score > best[0]:
            best = (score, row, reason)

    if best is None or best[0] < minimum_score:
        return None

    score, row, reason = best
    unit_price = int(row["unit_price"])
    amount = (
        int(round(item.quantity * unit_price))
        if item.quantity is not None
        else None
    )
    return PriceDecision(
        item_index=-1,
        product_name=item.product_name,
        unit_price=unit_price,
        amount=amount,
        source="history",
        reference=reason,
        score=round(score, 1),
        reason="품목·규격·수량이 유사한 기존 견적을 사용",
        needs_review=score < 78,
    )

def _value_matches(
    requested: str | None,
    candidate: str | None
) -> bool:
    """
    요청 조건이 없으면 비교하지 않는다.

    요청 조건이 있는 경우 후보 문자열에
    해당 표현이 포함되는지 확인한다.
    """

    requested_text = compact_text(
        requested
    )

    candidate_text = compact_text(
        candidate
    )

    if not requested_text:
        return True

    if not candidate_text:
        return False

    return (
        requested_text in candidate_text
        or candidate_text in requested_text
    )


def _range_contains(
    requested: float | None,
    exact_value: float | None,
    minimum: float | None,
    maximum: float | None
) -> bool:
    if requested is None:
        return True

    if exact_value is not None:
        return abs(
            requested - exact_value
        ) <= 1

    if (
        minimum is not None
        and requested < minimum
    ):
        return False

    if (
        maximum is not None
        and requested > maximum
    ):
        return False

    return (
        minimum is not None
        or maximum is not None
    )


def _quantity_in_range(
    requested: float | None,
    exact_quantity: float | None,
    minimum: float | None,
    maximum: float | None
) -> bool:
    if requested is None:
        return True

    if exact_quantity is not None:
        return requested == exact_quantity

    if (
        minimum is not None
        and requested < minimum
    ):
        return False

    if (
        maximum is not None
        and requested > maximum
    ):
        return False

    return (
        minimum is not None
        or maximum is not None
    )


def _extract_requested_attributes(
    item: OrderItemLike
) -> dict[str, Any]:
    specification = normalize_text(
        item.specification
    )

    combined_text = normalize_text(
        f"{item.product_name} {specification}"
    )

    width_mm, height_mm = (
        extract_dimensions(
            combined_text
        )
    )

    material = None

    material_keywords = [
        "부직포",
        "패트지",
        "메쉬",
        "아트지",
        "스노우지",
        "모조지",
        "휘라레",
        "랑데뷰",
        "반누보",
        "포맥스",
        "아크릴",
        "일반코팅",
        "고급지",
    ]

    for keyword in material_keywords:
        if keyword in combined_text:
            material = keyword
            break

    print_side = None

    if "양면" in combined_text:
        print_side = "양면"

    elif "단면" in combined_text:
        print_side = "단면"

    thickness_mm = None

    thickness_match = re.search(
        r"(\d+(?:\.\d+)?)\s*T\b",
        combined_text,
        re.IGNORECASE
    )

    if thickness_match:
        thickness_mm = float(
            thickness_match.group(1)
        )

    return {
        "specification": specification,
        "width_mm": width_mm,
        "height_mm": height_mm,
        "material": material,
        "print_side": print_side,
        "thickness_mm": thickness_mm,
    }

def interpolate_price(
    requested_size: float,
    lower_size: float,
    lower_price: int,
    upper_size: float,
    upper_price: int,
) -> int | None:
    if upper_size <= lower_size:
        return None

    if not (
        lower_size
        <= requested_size
        <= upper_size
    ):
        return None

    ratio = (
        requested_size - lower_size
    ) / (
        upper_size - lower_size
    )

    interpolated = (
        lower_price
        + ratio
        * (
            upper_price
            - lower_price
        )
    )

    return int(
        round(
            interpolated
        )
    )


def _row_price_kind_and_value(
    row: sqlite3.Row
) -> tuple[str, int] | None:
    """
    DB 행의 가격 의미를 통일한다.

    unit_price가 있으면 개당 단가,
    없고 total_price가 있으면 해당 조건 전체 가격으로 본다.
    """
    if row["unit_price"] is not None:
        return "unit", int(row["unit_price"])

    if row["total_price"] is not None:
        return "total", int(row["total_price"])

    return None


def _optional_text_equal(
    left: Any,
    right: Any
) -> bool:
    """
    두 값이 모두 비어 있으면 같음.
    한쪽만 비어 있으면 다름.
    둘 다 있으면 공백·기호를 제거해 비교한다.
    """
    left_text = compact_text(left)
    right_text = compact_text(right)

    if not left_text and not right_text:
        return True

    if not left_text or not right_text:
        return False

    return left_text == right_text


def _same_interpolation_family(
    first: sqlite3.Row,
    second: sqlite3.Row
) -> bool:
    """
    두 가격 행이 같은 가격표 계열인지 검사한다.

    품목만 같다고 보간하면
    재질·단면·두께·수량 조건이 다른 가격을 섞을 수 있으므로
    주요 조건이 같은 행끼리만 보간한다.
    """
    if (
        first["normalized_name"]
        != second["normalized_name"]
    ):
        return False

    first_price = _row_price_kind_and_value(
        first
    )
    second_price = _row_price_kind_and_value(
        second
    )

    if (
        first_price is None
        or second_price is None
        or first_price[0] != second_price[0]
    ):
        return False

    text_columns = (
        "category",
        "material",
        "paper",
        "color",
        "print_side",
        "unit",
    )

    for column in text_columns:
        if not _optional_text_equal(
            first[column],
            second[column]
        ):
            return False

    first_thickness = first[
        "thickness_mm"
    ]
    second_thickness = second[
        "thickness_mm"
    ]

    if (
        first_thickness is None
        and second_thickness is None
    ):
        pass

    elif (
        first_thickness is None
        or second_thickness is None
        or abs(
            float(first_thickness)
            - float(second_thickness)
        ) > 0.1
    ):
        return False

    # 수량표 가격은 동일 수량 조건끼리만 보간
    quantity_columns = (
        "quantity",
        "quantity_min",
        "quantity_max",
    )

    for column in quantity_columns:
        first_value = first[column]
        second_value = second[column]

        if (
            first_value is None
            and second_value is None
        ):
            continue

        if (
            first_value is None
            or second_value is None
            or abs(
                float(first_value)
                - float(second_value)
            ) > 0.0001
        ):
            return False

    return True


def _orient_candidate_dimensions(
    requested_width: float,
    requested_height: float,
    candidate_width: float,
    candidate_height: float,
) -> tuple[float, float]:
    """
    DB에 가로·세로 방향이 반대로 저장된 경우도 고려한다.
    요청 규격과 오차가 더 작은 방향으로 정렬한다.
    """
    direct_error = (
        abs(
            requested_width
            - candidate_width
        )
        + abs(
            requested_height
            - candidate_height
        )
    )

    swapped_error = (
        abs(
            requested_width
            - candidate_height
        )
        + abs(
            requested_height
            - candidate_width
        )
    )

    if swapped_error < direct_error:
        return (
            candidate_height,
            candidate_width,
        )

    return (
        candidate_width,
        candidate_height,
    )


def _row_matches_requested_attributes(
    row: sqlite3.Row,
    item: OrderItemLike,
    attributes: dict[str, Any],
) -> bool:
    """
    보간 후보가 메일 주문의 재질·인쇄면·두께·수량과 맞는지 검사한다.
    요청에 조건이 적혀 있지 않은 항목은 비교하지 않는다.
    """
    requested_material = attributes[
        "material"
    ]

    if requested_material:
        candidate_material = normalize_text(
            f"{row['material'] or ''} "
            f"{row['paper'] or ''} "
            f"{row['specification'] or ''}"
        )

        if not _value_matches(
            requested_material,
            candidate_material
        ):
            return False

    requested_side = attributes[
        "print_side"
    ]

    if requested_side:
        if compact_text(
            requested_side
        ) != compact_text(
            row["print_side"]
        ):
            return False

    requested_thickness = attributes[
        "thickness_mm"
    ]

    if requested_thickness is not None:
        candidate_thickness = row[
            "thickness_mm"
        ]

        if (
            candidate_thickness is None
            or abs(
                float(requested_thickness)
                - float(candidate_thickness)
            ) > 0.1
        ):
            return False

    if item.quantity is not None:
        if not _quantity_in_range(
            requested=item.quantity,
            exact_quantity=row["quantity"],
            minimum=row["quantity_min"],
            maximum=row["quantity_max"],
        ):
            return False

    return True


def _find_interpolated_price(
    rows: list[sqlite3.Row],
    item: OrderItemLike,
    attributes: dict[str, Any],
    item_index: int,
) -> PriceDecision | None:
    """
    동일한 가격표 계열에서 요청 규격을 양쪽으로 감싸는
    두 가격을 찾아 선형 보간한다.

    가로 또는 세로 한 축만 달라지는 경우에만 적용한다.
    범위 밖 외삽은 하지 않는다.
    """
    requested_width = attributes[
        "width_mm"
    ]
    requested_height = attributes[
        "height_mm"
    ]

    if (
        requested_width is None
        or requested_height is None
    ):
        return None

    candidates: list[
        tuple[sqlite3.Row, float, float]
    ] = []

    for row in rows:
        if (
            row["width_mm"] is None
            or row["height_mm"] is None
        ):
            continue

        # 범위 가격은 이미 구간 매칭으로 처리하므로
        # 보간에는 정확한 규격 행만 사용한다.
        if any(
            row[column] is not None
            for column in (
                "width_mm_min",
                "width_mm_max",
                "height_mm_min",
                "height_mm_max",
            )
        ):
            continue

        if not _row_matches_requested_attributes(
            row,
            item,
            attributes,
        ):
            continue

        oriented_width, oriented_height = (
            _orient_candidate_dimensions(
                requested_width,
                requested_height,
                float(row["width_mm"]),
                float(row["height_mm"]),
            )
        )

        # 정확히 같은 규격이 있으면 기존 정확 매칭 로직을 사용
        if (
            abs(
                oriented_width
                - requested_width
            ) <= 1
            and abs(
                oriented_height
                - requested_height
            ) <= 1
        ):
            return None

        candidates.append(
            (
                row,
                oriented_width,
                oriented_height,
            )
        )

    best_pair: tuple[
        float,
        sqlite3.Row,
        float,
        sqlite3.Row,
        float,
        str,
    ] | None = None

    for first_index in range(
        len(candidates)
    ):
        first_row, first_width, first_height = (
            candidates[first_index]
        )

        for second_index in range(
            first_index + 1,
            len(candidates)
        ):
            (
                second_row,
                second_width,
                second_height,
            ) = candidates[second_index]

            if not _same_interpolation_family(
                first_row,
                second_row
            ):
                continue

            axis: str | None = None
            first_size: float | None = None
            second_size: float | None = None
            requested_size: float | None = None

            # 세로가 같은 계열이면 가로 기준 보간
            if (
                abs(
                    first_height
                    - second_height
                ) <= 1
                and abs(
                    first_height
                    - requested_height
                ) <= 1
            ):
                axis = "가로"
                first_size = first_width
                second_size = second_width
                requested_size = requested_width

            # 가로가 같은 계열이면 세로 기준 보간
            elif (
                abs(
                    first_width
                    - second_width
                ) <= 1
                and abs(
                    first_width
                    - requested_width
                ) <= 1
            ):
                axis = "세로"
                first_size = first_height
                second_size = second_height
                requested_size = requested_height

            if (
                axis is None
                or first_size is None
                or second_size is None
                or requested_size is None
            ):
                continue

            lower_size = min(
                first_size,
                second_size
            )
            upper_size = max(
                first_size,
                second_size
            )

            if not (
                lower_size
                < requested_size
                < upper_size
            ):
                continue

            if first_size <= second_size:
                lower_row = first_row
                upper_row = second_row
            else:
                lower_row = second_row
                upper_row = first_row

            span = (
                upper_size
                - lower_size
            )

            # 요청값을 가장 좁게 감싸는 두 행을 우선
            if (
                best_pair is None
                or span < best_pair[0]
            ):
                best_pair = (
                    span,
                    lower_row,
                    lower_size,
                    upper_row,
                    upper_size,
                    axis,
                )

    if best_pair is None:
        return None

    (
        _,
        lower_row,
        lower_size,
        upper_row,
        upper_size,
        axis,
    ) = best_pair

    lower_price_data = (
        _row_price_kind_and_value(
            lower_row
        )
    )
    upper_price_data = (
        _row_price_kind_and_value(
            upper_row
        )
    )

    if (
        lower_price_data is None
        or upper_price_data is None
        or lower_price_data[0]
        != upper_price_data[0]
    ):
        return None

    price_kind = lower_price_data[0]

    requested_size = (
        requested_width
        if axis == "가로"
        else requested_height
    )

    interpolated_value = interpolate_price(
        requested_size=requested_size,
        lower_size=lower_size,
        lower_price=lower_price_data[1],
        upper_size=upper_size,
        upper_price=upper_price_data[1],
    )

    if interpolated_value is None:
        return None

    if price_kind == "unit":
        unit_price = interpolated_value

        amount = (
            int(
                round(
                    unit_price
                    * item.quantity
                )
            )
            if item.quantity is not None
            else None
        )

    else:
        amount = interpolated_value

        unit_price = (
            int(
                round(
                    amount
                    / item.quantity
                )
            )
            if (
                item.quantity is not None
                and item.quantity > 0
            )
            else None
        )

    reference = (
        "단가 DB 선형보간/"
        f"{lower_row['sheet_name']} "
        f"ID {lower_row['id']} "
        f"({lower_size:g}mm, "
        f"{lower_price_data[1]:,}원)"
        " ↔ "
        f"ID {upper_row['id']} "
        f"({upper_size:g}mm, "
        f"{upper_price_data[1]:,}원)"
    )

    return PriceDecision(
        item_index=item_index,
        product_name=item.product_name,
        unit_price=unit_price,
        amount=amount,
        source="price_table",
        reference=reference,
        score=90.0,
        reason=(
            f"같은 품목·재질·수량 조건의 "
            f"{axis} 규격 사이 가격을 선형 보간"
        ),
        needs_review=True,
    )


def search_price_table_db(
    database_path: Path,
    item: OrderItemLike,
    item_index: int,
    limit: int = 200
) -> PriceDecision | None:
    """
    검색 순서:

    1. 품목·규격·수량·재질이 정확히 맞는 단가
    2. 같은 가격표 계열의 앞뒤 규격을 이용한 선형 보간
    3. 기존 점수 방식의 가장 가까운 단가
    4. 모두 실패하면 None
    """
    if not database_path.exists():
        return None

    normalized_product = (
        normalize_product_name(
            item.product_name
        )
    )

    attributes = (
        _extract_requested_attributes(
            item
        )
    )

    connection = sqlite3.connect(
        database_path
    )

    connection.row_factory = (
        sqlite3.Row
    )

    try:
        columns = {
            row["name"]
            for row in connection.execute(
                """
                PRAGMA table_info(
                    price_items
                )
                """
            ).fetchall()
        }

        required_columns = {
            "normalized_name",
            "unit_price",
            "total_price",
            "review_required",
        }

        missing_columns = (
            required_columns
            - columns
        )

        if missing_columns:
            raise RuntimeError(
                "price_table.db 구조가 올바르지 "
                "않습니다. 누락 컬럼: "
                + ", ".join(
                    sorted(
                        missing_columns
                    )
                )
            )

        rows = connection.execute(
            """
            SELECT
                id,
                product_name,
                normalized_name,
                category,
                specification,

                width_mm,
                height_mm,
                width_mm_min,
                width_mm_max,
                height_mm_min,
                height_mm_max,

                thickness_mm,
                material,
                paper,
                color,
                print_side,

                quantity,
                quantity_min,
                quantity_max,
                unit,

                unit_price,
                total_price,
                vat_included,

                sheet_name,
                row_number,
                column_number,
                original_text,

                confidence,
                review_required

            FROM price_items

            WHERE
                review_required = 0

                AND (
                    normalized_name = ?
                    OR normalized_name LIKE ?
                    OR product_name LIKE ?
                )

                AND (
                    unit_price IS NOT NULL
                    OR total_price IS NOT NULL
                )

            ORDER BY
                confidence DESC,
                id ASC

            LIMIT ?
            """,
            (
                normalized_product,
                f"%{normalized_product}%",
                f"%{item.product_name}%",
                limit,
            )
        ).fetchall()

    finally:
        connection.close()

    if not rows:
        return None

    requested_width = attributes[
        "width_mm"
    ]
    requested_height = attributes[
        "height_mm"
    ]

    # -------------------------------------------------
    # 1. 정확한 규격 후보 우선 검색
    # -------------------------------------------------

    exact_best_row: sqlite3.Row | None = None
    exact_best_score = float("-inf")
    exact_best_reason = ""

    # 기존 근접 후보도 동시에 계산
    best_row: sqlite3.Row | None = None
    best_score = float("-inf")
    best_reason = ""

    for row in rows:
        score = 0.0
        reasons: list[str] = []

        if (
            row["normalized_name"]
            == normalized_product
        ):
            score += 40
            reasons.append(
                "표준 품목 일치"
            )
        else:
            score += 20

        width_matches = _range_contains(
            requested=requested_width,
            exact_value=row["width_mm"],
            minimum=row["width_mm_min"],
            maximum=row["width_mm_max"],
        )

        height_matches = _range_contains(
            requested=requested_height,
            exact_value=row["height_mm"],
            minimum=row["height_mm_min"],
            maximum=row["height_mm_max"],
        )

        swapped_width_matches = (
            _range_contains(
                requested=requested_width,
                exact_value=row["height_mm"],
                minimum=row[
                    "height_mm_min"
                ],
                maximum=row[
                    "height_mm_max"
                ],
            )
        )

        swapped_height_matches = (
            _range_contains(
                requested=requested_height,
                exact_value=row["width_mm"],
                minimum=row[
                    "width_mm_min"
                ],
                maximum=row[
                    "width_mm_max"
                ],
            )
        )

        dimension_exact = False

        if (
            requested_width is not None
            and requested_height is not None
        ):
            dimension_exact = (
                (
                    width_matches
                    and height_matches
                )
                or (
                    swapped_width_matches
                    and swapped_height_matches
                )
            )

            if dimension_exact:
                score += 30
                reasons.append(
                    "규격 일치"
                )
            else:
                score -= 35

        elif (
            row["width_mm"] is not None
            or row["height_mm"] is not None
            or row["width_mm_min"] is not None
            or row["height_mm_min"] is not None
        ):
            score += 2

        quantity_matches = _quantity_in_range(
            requested=item.quantity,
            exact_quantity=row["quantity"],
            minimum=row["quantity_min"],
            maximum=row["quantity_max"],
        )

        if quantity_matches:
            if item.quantity is not None:
                score += 20
                reasons.append(
                    "수량 일치"
                )
        elif item.quantity is not None:
            score -= 25

        requested_material = attributes[
            "material"
        ]

        material_matches = True

        if requested_material:
            candidate_material = (
                normalize_text(
                    f"{row['material'] or ''} "
                    f"{row['paper'] or ''} "
                    f"{row['specification'] or ''}"
                )
            )

            material_matches = _value_matches(
                requested_material,
                candidate_material
            )

            if material_matches:
                score += 15
                reasons.append(
                    "재질 일치"
                )
            else:
                score -= 15

        requested_side = attributes[
            "print_side"
        ]

        side_matches = True

        if requested_side:
            side_matches = (
                compact_text(
                    requested_side
                )
                == compact_text(
                    row["print_side"]
                )
            )

            if side_matches:
                score += 10
                reasons.append(
                    "인쇄면 일치"
                )
            else:
                score -= 12

        requested_thickness = attributes[
            "thickness_mm"
        ]

        thickness_matches = True

        if requested_thickness is not None:
            candidate_thickness = row[
                "thickness_mm"
            ]

            thickness_matches = (
                candidate_thickness
                is not None
                and abs(
                    requested_thickness
                    - candidate_thickness
                ) <= 0.1
            )

            if thickness_matches:
                score += 10
                reasons.append(
                    "두께 일치"
                )
            else:
                score -= 10

        requested_tokens = _tokenize(
            attributes[
                "specification"
            ]
        )

        candidate_tokens = _tokenize(
            normalize_text(
                f"{row['product_name']} "
                f"{row['specification'] or ''} "
                f"{row['material'] or ''} "
                f"{row['paper'] or ''}"
            )
        )

        if requested_tokens:
            overlap = (
                len(
                    requested_tokens
                    & candidate_tokens
                )
                / len(
                    requested_tokens
                )
            )

            score += overlap * 15

        confidence = row["confidence"]

        if confidence is not None:
            score += float(
                confidence
            ) * 5

        reason = ", ".join(
            reasons
        )

        if score > best_score:
            best_score = score
            best_row = row
            best_reason = reason

        if (
            dimension_exact
            and quantity_matches
            and material_matches
            and side_matches
            and thickness_matches
            and score > exact_best_score
        ):
            exact_best_score = score
            exact_best_row = row
            exact_best_reason = reason

    selected_row: sqlite3.Row | None = None
    selected_score = 0.0
    selected_reason = ""

    if exact_best_row is not None:
        selected_row = exact_best_row
        selected_score = exact_best_score
        selected_reason = exact_best_reason

    else:
        # -------------------------------------------------
        # 2. 정확한 규격이 없을 때 선형 보간
        # -------------------------------------------------

        interpolated_decision = (
            _find_interpolated_price(
                rows=rows,
                item=item,
                attributes=attributes,
                item_index=item_index,
            )
        )

        if interpolated_decision is not None:
            return interpolated_decision

        # -------------------------------------------------
        # 3. 보간도 불가능하면 기존 근접 검색
        # -------------------------------------------------

        if (
            best_row is None
            or best_score < 55
        ):
            return None

        selected_row = best_row
        selected_score = best_score
        selected_reason = best_reason

    price_data = _row_price_kind_and_value(
        selected_row
    )

    if price_data is None:
        return None

    price_kind, price_value = price_data

    if price_kind == "unit":
        unit_price = price_value

        amount = (
            int(
                round(
                    unit_price
                    * item.quantity
                )
            )
            if item.quantity is not None
            else None
        )

    else:
        amount = price_value

        unit_price = (
            int(
                round(
                    amount
                    / item.quantity
                )
            )
            if (
                item.quantity is not None
                and item.quantity > 0
            )
            else None
        )

    reference = (
        f"단가 DB/{selected_row['sheet_name']} "
        f"행 {selected_row['row_number']} "
        f"ID {selected_row['id']}"
    )

    return PriceDecision(
        item_index=item_index,
        product_name=item.product_name,
        unit_price=unit_price,
        amount=amount,
        source="price_table",
        reference=reference,
        score=round(
            selected_score,
            1
        ),
        reason=(
            "단가 DB 검색: "
            + (
                selected_reason
                or "가장 가까운 판매 조건"
            )
        ),
        needs_review=(
            selected_score < 80
        ),
    )


def apply_prices(
    items: list[OrderItemLike],
    customer_organization: str | None,

    quotation_database_path: Path,
    price_database_path: Path,
) -> list[PriceDecision]:
    decisions: list[PriceDecision] = []

    for index, item in enumerate(
        items
    ):
        # 고객 메일의 희망가·예산·과거 가격은 사용하지 않음
        item.unit_price = None
        item.amount = None

        # -------------------------------------------------
        # 2. 기존 실제 견적서 검색
        # -------------------------------------------------

        decision = search_history_price(
            database_path=(
                quotation_database_path
            ),
            item=item,
            customer_organization=(
                customer_organization
            ),
        )

        # -------------------------------------------------
        # 3. 유사 견적이 없으면 단가표 DB 검색
        # -------------------------------------------------

        if decision is None:
            decision = search_price_table_db(
                database_path=(
                    price_database_path
                ),
                item=item,
                item_index=index,
            )

        # -------------------------------------------------
        # 4. 가격 미확정
        # -------------------------------------------------

        if decision is None:
            decisions.append(
                PriceDecision(
                    item_index=index,
                    product_name=(
                        item.product_name
                    ),
                    unit_price=None,
                    amount=None,
                    source="unresolved",
                    reference=None,
                    score=0.0,
                    reason=(
                        "유사 견적과 단가 DB에서 "
                        "확정 가능한 가격을 찾지 못함"
                    ),
                    needs_review=True,
                )
            )

            continue

        # -------------------------------------------------
        # 5. 분석 품목에 결과 적용
        # -------------------------------------------------

        decision.item_index = index

        item.unit_price = (
            decision.unit_price
        )

        item.amount = (
            decision.amount
        )

        decisions.append(
            decision
        )

    return decisions