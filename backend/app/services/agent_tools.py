from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sqlite3
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import (
    Mail,
    MailItem,
    PriceRule,
    QuotationDraft,
    QuotationHistory,
    QuotationHistoryItem,
    QuotationLearningFact,
    ReviewIssue,
)
from .excel_open_service import open_excel_location
from .external_price_engine import normalize_product_name
from .knowledge_service import search_knowledge, serialize_knowledge
from .memory_service import save_memory, search_memories
from .price_candidate_service import get_external_price_candidates
from .quote_math import calculate_supply_amount, quote_total, validate_quote_items
from .quotation_service import create_quotation
from .review_service import evaluate_mail_readiness


@dataclass
class AgentToolContext:
    session: Session
    settings: Settings
    mail: Mail
    user_message_id: int | None = None
    actions: list[dict[str, Any]] = field(default_factory=list)
    draft_updated: bool = False


OPENMOON_AGENT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "get_current_quote",
        "description": "현재 메일과 견적 품목, 규격, 수량, 단가, 공급금액, 합계, 검토 오류를 조회합니다.",
        "strict": True,
        "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "search_company_knowledge",
        "description": "열린문디자인 직원이 직접 관리하는 재질 특성, 사용처, 표준 규격, 제작 주의사항, 회사 업무 규칙을 검색합니다. 재질 추천이나 회사 기준 질문에는 우선 사용합니다.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "product_name": {"type": ["string", "null"]},
                "material_name": {"type": ["string", "null"]},
                "usage_context": {"type": ["string", "null"]},
                "limit": {"type": "integer"},
            },
            "required": ["query", "product_name", "material_name", "usage_context", "limit"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "search_current_price_candidates",
        "description": "현재 품목의 현재 단가 후보와 가격 근거를 조회합니다. 과거 가격을 그대로 적용하기 전에 현재 가격 확인이 필요할 때 사용합니다.",
        "strict": True,
        "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "search_price_table",
        "description": "열린문디자인 단가표 DB에서 품목 가격과 원본 Excel 시트/셀 위치를 검색합니다. 가격표를 묻거나 가격 출처를 확인할 때 사용합니다.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "product_name": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["product_name", "limit"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "open_price_source",
        "description": "사용자가 단가표/가격표 Excel을 열어줘, 보여줘, 띄워줘, 켜줘라고 요청할 때 회사 PC에서 원본 가격표 파일을 엽니다. Microsoft Excel이 있으면 시트/셀로 이동하고, 없으면 Windows 기본 XLSX 뷰어를 사용합니다. search_price_table 결과에 실제 시트/셀이 있으면 그 위치를 사용하고, 모르면 null을 전달해 파일 자체를 여세요. 파일 열기 요청에 대해 단순히 불가능하다고 답하지 마세요.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "source_sheet": {"type": ["string", "null"]},
                "source_cell": {"type": ["string", "null"]},
            },
            "required": ["source_sheet", "source_cell"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "search_quotation_history",
        "description": "과거 견적 DB에서 고객/기관 및 품목 기준으로 유사 견적을 검색합니다. '저번처럼', '전에 했던 것', '지난번 가격' 같은 요청에 사용합니다.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "customer_name": {"type": ["string", "null"]},
                "product_name": {"type": ["string", "null"]},
                "limit": {"type": "integer"},
            },
            "required": ["customer_name", "product_name", "limit"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "search_memory",
        "description": "이전 대화에서 저장된 회사 규칙, 고객 선호, 확정 사실을 검색합니다. 고객별 선호나 전에 합의한 내용을 확인할 때 사용합니다.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "customer_name": {"type": ["string", "null"]},
                "product_name": {"type": ["string", "null"]},
                "limit": {"type": "integer"},
            },
            "required": ["query", "customer_name", "product_name", "limit"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "remember_fact",
        "description": "사용자가 명시한 지속 가치가 있는 회사 규칙/고객 선호/확정 사실을 장기기억에 저장합니다. 일회성 주문값이나 AI 추론은 저장하지 않습니다.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "scope": {"type": "string", "enum": ["company", "customer"]},
                "memory_type": {"type": "string", "enum": ["fact", "preference", "rule"]},
                "customer_name": {"type": ["string", "null"]},
                "product_name": {"type": ["string", "null"]},
            },
            "required": ["content", "scope", "memory_type", "customer_name", "product_name"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "update_quote_item",
        "description": "사용자가 명확히 변경을 요청했을 때 현재 견적 품목의 규격·수량·재질 등을 수정합니다. 단가 직접 변경은 기존 명시적 단가 명령이 담당합니다.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "item_position": {"type": ["integer", "null"]},
                "product_name": {"type": ["string", "null"]},
                "field": {
                    "type": "string",
                    "enum": [
                        "specification",
                        "width_mm",
                        "height_mm",
                        "size_name",
                        "quantity",
                        "unit",
                        "paper",
                        "print_sides",
                        "material",
                        "detail_text",
                        "schedule_note",
                        "design_request",
                    ],
                },
                "value": {"type": "string"},
            },
            "required": ["item_position", "product_name", "field", "value"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "create_quotation_draft",
        "description": "사용자가 명시적으로 견적서 생성을 요청한 경우, 최종 품목/규격/수량/단가/공급금액을 검증하고 Excel 견적서 초안을 생성합니다.",
        "strict": True,
        "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
]


def _json_item(item: MailItem) -> dict[str, Any]:
    amount = calculate_supply_amount(item.quantity, item.unit_price)
    return {
        "id": item.id,
        "position": item.position,
        "product_name": item.product_name,
        "specification": item.specification,
        "width_mm": item.width_mm,
        "height_mm": item.height_mm,
        "size_name": item.size_name,
        "quantity": item.quantity,
        "unit": item.unit,
        "paper": item.paper,
        "print_sides": item.print_sides,
        "material": item.material,
        "unit_price": item.unit_price,
        "supply_amount": amount,
        "confirmed": item.confirmed,
    }


def _get_current_quote(ctx: AgentToolContext) -> dict[str, Any]:
    return {
        "mail_id": ctx.mail.id,
        "customer": ctx.mail.customer_organization or ctx.mail.customer_name,
        "subject": ctx.mail.original_subject,
        "status": ctx.mail.status,
        "items": [_json_item(item) for item in ctx.mail.items],
        "total": quote_total(list(ctx.mail.items)),
        "validation_errors": validate_quote_items(list(ctx.mail.items)),
    }


def _search_company_knowledge(
    ctx: AgentToolContext,
    *,
    query: str,
    product_name: str | None,
    material_name: str | None,
    usage_context: str | None,
    limit: int,
) -> dict[str, Any]:
    rows = search_knowledge(
        ctx.session,
        query=query,
        product_name=product_name,
        material_name=material_name,
        usage_context=usage_context,
        limit=max(1, min(limit, 20)),
    )
    return {
        "count": len(rows),
        "rows": [serialize_knowledge(row) for row in rows],
    }


def _search_current_price_candidates(ctx: AgentToolContext) -> dict[str, Any]:
    rows = get_external_price_candidates(ctx.session, ctx.settings, ctx.mail)
    compact = [
        {
            "item_id": row.get("item_id"),
            "product_name": row.get("product_name"),
            "unit_price": row.get("unit_price"),
            "amount": row.get("amount"),
            "source": row.get("source"),
            "reference": row.get("reference"),
            "score": row.get("score"),
            "reason": row.get("reason"),
            "needs_review": row.get("needs_review"),
            "source_sheet": row.get("source_sheet"),
            "source_cell": row.get("source_cell"),
        }
        for row in rows[:12]
    ]
    return {"count": len(compact), "candidates": compact}


def _excel_column_name(column_number: int | None) -> str:
    # price_items.column_number는 Excel의 1-based 열 번호로 사용한다.
    if column_number is None or column_number <= 0:
        return ""

    result = ""
    number = int(column_number)
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _search_price_table(
    ctx: AgentToolContext,
    *,
    product_name: str,
    limit: int,
) -> dict[str, Any]:
    """
    실제 가격 엔진과 동일한 price_table.db / price_items를 직접 조회한다.

    V3 초기 버전처럼 openmoon.db의 PriceRule을 조회하지 않는다.
    """
    requested_name = product_name.strip()
    normalized_name = normalize_product_name(requested_name)
    limit = max(1, min(int(limit), 100))

    database_path = Path(ctx.settings.price_database_path)
    if not database_path.exists():
        raise FileNotFoundError(
            f"단가 DB를 찾을 수 없습니다: {database_path}"
        )

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row

    try:
        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(price_items)"
            ).fetchall()
        }

        required = {
            "id",
            "product_name",
            "normalized_name",
            "unit_price",
            "total_price",
            "sheet_name",
            "row_number",
            "review_required",
        }
        missing = required - columns
        if missing:
            raise RuntimeError(
                "price_table.db의 price_items 구조가 올바르지 않습니다. "
                "누락 컬럼: " + ", ".join(sorted(missing))
            )

        preferred_columns = [
            "id",
            "product_name",
            "normalized_name",
            "category",
            "specification",
            "width_mm",
            "height_mm",
            "width_mm_min",
            "width_mm_max",
            "height_mm_min",
            "height_mm_max",
            "thickness_mm",
            "material",
            "paper",
            "color",
            "print_side",
            "quantity",
            "quantity_min",
            "quantity_max",
            "unit",
            "unit_price",
            "total_price",
            "vat_included",
            "sheet_name",
            "row_number",
            "column_number",
            "original_text",
            "confidence",
            "review_required",
        ]
        selected_columns = [
            column
            for column in preferred_columns
            if column in columns
        ]

        sql = f"""
            SELECT {", ".join(selected_columns)}
            FROM price_items
            WHERE review_required = 0
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
        """

        rows = connection.execute(
            sql,
            (
                normalized_name,
                f"%{normalized_name}%",
                f"%{requested_name}%",
                limit,
            ),
        ).fetchall()
    finally:
        connection.close()

    result_rows: list[dict[str, Any]] = []

    for row in rows:
        data = dict(row)
        row_number = data.get("row_number")
        column_number = data.get("column_number")

        excel_column = _excel_column_name(
            int(column_number)
            if column_number is not None
            else None
        )
        source_cell = (
            f"{excel_column}{int(row_number)}"
            if excel_column and row_number is not None
            else ""
        )

        result_rows.append(
            {
                "id": data.get("id"),
                "product_name": data.get("product_name"),
                "normalized_name": data.get("normalized_name"),
                "category": data.get("category"),
                "specification": data.get("specification"),
                "width_mm": data.get("width_mm"),
                "height_mm": data.get("height_mm"),
                "width_mm_min": data.get("width_mm_min"),
                "width_mm_max": data.get("width_mm_max"),
                "height_mm_min": data.get("height_mm_min"),
                "height_mm_max": data.get("height_mm_max"),
                "thickness_mm": data.get("thickness_mm"),
                "material": data.get("material"),
                "paper": data.get("paper"),
                "color": data.get("color"),
                "print_side": data.get("print_side"),
                "quantity": data.get("quantity"),
                "quantity_min": data.get("quantity_min"),
                "quantity_max": data.get("quantity_max"),
                "unit": data.get("unit"),
                "unit_price": data.get("unit_price"),
                "total_price": data.get("total_price"),
                "vat_included": data.get("vat_included"),
                "confidence": data.get("confidence"),
                "review_required": data.get("review_required"),
                "source_sheet": data.get("sheet_name"),
                "source_cell": source_cell,
                "source_row": row_number,
                "source_column": column_number,
                "original_text": data.get("original_text"),
            }
        )

    return {
        "query": requested_name,
        "normalized_product": normalized_name,
        "count": len(result_rows),
        "price_database_file": str(database_path),
        "price_table_file": str(ctx.settings.price_table_path),
        "rows": result_rows,
    }


def _open_price_source(
    ctx: AgentToolContext,
    *,
    source_sheet: str | None,
    source_cell: str | None,
) -> dict[str, Any]:
    return open_excel_location(
        ctx.settings.price_table_path,
        sheet=source_sheet,
        cell=source_cell,
    )


def _search_quotation_history(
    ctx: AgentToolContext,
    *,
    customer_name: str | None,
    product_name: str | None,
    limit: int,
) -> dict[str, Any]:
    limit = max(1, min(limit, 20))
    stmt = select(QuotationHistoryItem, QuotationHistory).join(
        QuotationHistory,
        QuotationHistoryItem.quotation_id == QuotationHistory.id,
    )
    if customer_name:
        stmt = stmt.where(QuotationHistory.customer_name.ilike(f"%{customer_name.strip()}%"))
    if product_name:
        p = product_name.strip()
        stmt = stmt.where(
            or_(
                QuotationHistoryItem.product_name.ilike(f"%{p}%"),
                QuotationHistoryItem.normalized_product.ilike(f"%{p}%"),
                QuotationHistoryItem.specification.ilike(f"%{p}%"),
            )
        )
    rows = ctx.session.execute(
        stmt.order_by(
            QuotationHistory.quotation_date.desc().nullslast(),
            QuotationHistory.id.desc(),
            QuotationHistoryItem.row_number.asc(),
        ).limit(limit)
    ).all()
    return {
        "count": len(rows),
        "rows": [
            {
                "quotation_id": quotation.id,
                "quotation_date": str(quotation.quotation_date or ""),
                "customer_name": quotation.customer_name,
                "source_file": quotation.source_file,
                "source_sheet": quotation.source_sheet,
                "product_name": item.product_name,
                "specification": item.specification,
                "quantity": item.quantity,
                "unit": item.unit,
                "unit_price": item.unit_price,
                "amount": item.amount,
                "note": item.note,
            }
            for item, quotation in rows
        ],
    }


def _find_item(ctx: AgentToolContext, *, item_position: int | None, product_name: str | None) -> MailItem:
    if item_position is not None:
        item = next((row for row in ctx.mail.items if row.position == item_position), None)
        if item is not None:
            return item
    if product_name:
        matches = [
            row
            for row in ctx.mail.items
            if product_name in (row.product_name or "") or (row.product_name or "") in product_name
        ]
        if len(matches) == 1:
            return matches[0]
    if len(ctx.mail.items) == 1:
        return ctx.mail.items[0]
    raise ValueError("수정할 품목을 특정할 수 없습니다. 품목 순번 또는 품목명을 지정해 주세요.")


def _parse_update_value(field_name: str, value: str) -> Any:
    if field_name in {"width_mm", "height_mm", "quantity"}:
        try:
            return float(value.replace(",", "").strip())
        except ValueError as error:
            raise ValueError(f"{field_name}에는 숫자 값을 사용해야 합니다: {value}") from error
    return value.strip()


def _update_quote_item(ctx: AgentToolContext, **arguments: Any) -> dict[str, Any]:
    item = _find_item(
        ctx,
        item_position=arguments.get("item_position"),
        product_name=arguments.get("product_name"),
    )
    field = str(arguments["field"])
    old_value = getattr(item, field)
    new_value = _parse_update_value(field, str(arguments["value"]))
    setattr(item, field, new_value)

    price_affecting_fields = {
        "specification",
        "width_mm",
        "height_mm",
        "size_name",
        "paper",
        "print_sides",
        "material",
    }
    if field in price_affecting_fields:
        item.unit_price = None
        item.amount = None
        item.confirmed = False
        evidence = dict(item.evidence or {})
        evidence.pop("price", None)
        item.evidence = evidence
    elif field == "quantity":
        item.amount = calculate_supply_amount(item.quantity, item.unit_price)

    ctx.session.add(
        QuotationLearningFact(
            mail_id=ctx.mail.id,
            chat_message_id=ctx.user_message_id,
            item_id=item.id,
            fact_type="USER_CORRECTION" if old_value not in (None, "") else "USER_CONFIRMED_FACT",
            field_name=field,
            old_value=old_value,
            new_value=new_value,
            customer_name=ctx.mail.customer_organization or ctx.mail.customer_name,
            product_name=item.product_name,
            specification=item.specification,
            source="agent_chat_user",
            confirmed=True,
            applied=True,
            confidence=1.0,
        )
    )
    ctx.session.flush()
    evaluate_mail_readiness(ctx.session, ctx.settings, ctx.mail)

    existing = ctx.session.scalar(select(QuotationDraft).where(QuotationDraft.mail_id == ctx.mail.id))
    blocking = ctx.session.scalar(
        select(ReviewIssue.id).where(
            ReviewIssue.mail_id == ctx.mail.id,
            ReviewIssue.resolved.is_(False),
            ReviewIssue.severity == "blocking",
        )
    )
    if existing is not None and blocking is None and not validate_quote_items(list(ctx.mail.items)):
        create_quotation(ctx.session, ctx.settings, ctx.mail)
        ctx.draft_updated = True

    action = {
        "source": "agent",
        "field": field,
        "item_id": item.id,
        "item_position": item.position,
        "product_name": item.product_name,
        "old": old_value,
        "new": new_value,
    }
    ctx.actions.append(action)
    return {"updated": True, "action": action, "current_quote": _get_current_quote(ctx)}


def _create_quotation_draft(ctx: AgentToolContext) -> dict[str, Any]:
    errors = validate_quote_items(list(ctx.mail.items))
    if errors:
        return {"created": False, "validation_errors": errors, "quote": _get_current_quote(ctx)}

    draft = create_quotation(ctx.session, ctx.settings, ctx.mail)
    ctx.draft_updated = True
    return {
        "created": True,
        "draft_id": draft.id,
        "file_path": draft.file_path,
        "total_amount": draft.total_amount,
    }


def _price_locations(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        sheet = str(row.get("source_sheet") or "").strip()
        cell = str(row.get("source_cell") or "").strip()
        if not sheet and not cell:
            continue
        key = (sheet, cell)
        if key in seen:
            continue
        seen.add(key)
        result.append({"sheet": sheet, "cell": cell})
        if len(result) >= 5:
            break
    return result


def execute_agent_tool(
    ctx: AgentToolContext,
    name: str,
    arguments: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if name == "get_current_quote":
        result = _get_current_quote(ctx)
        evidence = [{"type": "quote_state", "label": "현재 견적 상태 조회"}]
    elif name == "search_company_knowledge":
        result = _search_company_knowledge(ctx, **arguments)
        evidence = [{
            "type": "knowledge",
            "label": f"회사 업무 지식 {result['count']}건 조회",
            "count": result["count"],
            "preview": [row.get("title") for row in result["rows"][:3]],
        }]
    elif name == "search_current_price_candidates":
        result = _search_current_price_candidates(ctx)
        evidence = [{
            "type": "price",
            "label": f"현재 가격 후보 {result['count']}건 조회",
            "count": result["count"],
            "locations": _price_locations(result["candidates"]),
        }]
    elif name == "search_price_table":
        result = _search_price_table(ctx, **arguments)
        evidence = [{
            "type": "price_table",
            "label": f"단가표 '{arguments['product_name']}' {result['count']}건 조회",
            "count": result["count"],
            "source_file": result["price_table_file"],
            "locations": _price_locations(result["rows"]),
        }]
    elif name == "open_price_source":
        result = _open_price_source(ctx, **arguments)
        evidence = [{
            "type": "excel_opened",
            "label": "단가표 Excel 위치 열기",
            "source_file": result.get("file_path"),
            "locations": [{
                "sheet": result.get("sheet") or "",
                "cell": result.get("cell") or "",
            }],
        }]
    elif name == "search_quotation_history":
        result = _search_quotation_history(ctx, **arguments)
        evidence = [{
            "type": "history",
            "label": f"과거 견적 {result['count']}건 조회",
            "count": result["count"],
            "preview": [
                f"{row.get('quotation_date') or '-'} · {row.get('product_name') or '-'}"
                for row in result["rows"][:3]
            ],
        }]
    elif name == "search_memory":
        rows = search_memories(ctx.session, **arguments)
        result = {
            "count": len(rows),
            "memories": [
                {
                    "id": row.id,
                    "scope": row.scope,
                    "memory_type": row.memory_type,
                    "customer_name": row.customer_name,
                    "product_name": row.product_name,
                    "content": row.content,
                }
                for row in rows
            ],
        }
        evidence = [{
            "type": "memory",
            "label": f"장기기억 {result['count']}건 조회",
            "count": result["count"],
            "preview": [row["content"] for row in result["memories"][:3]],
        }]
    elif name == "remember_fact":
        customer_name = arguments.get("customer_name")
        if arguments["scope"] == "customer" and not customer_name:
            customer_name = ctx.mail.customer_organization or ctx.mail.customer_name
        memory = save_memory(
            ctx.session,
            content=arguments["content"],
            scope=arguments["scope"],
            memory_type=arguments["memory_type"],
            customer_name=customer_name,
            product_name=arguments.get("product_name"),
            source_mail_id=ctx.mail.id,
            source_chat_message_id=ctx.user_message_id,
        )
        result = {"saved": True, "memory_id": memory.id, "content": memory.content}
        evidence = [{"type": "memory_saved", "label": f"장기기억 저장: {memory.content}"}]
    elif name == "update_quote_item":
        result = _update_quote_item(ctx, **arguments)
        evidence = [{
            "type": "agent_action",
            "label": f"{result['action']['product_name']} {result['action']['field']} 변경",
        }]
    elif name == "create_quotation_draft":
        result = _create_quotation_draft(ctx)
        evidence = [{
            "type": "quotation",
            "label": "견적서 초안 생성" if result.get("created") else "견적서 생성 전 필수값 확인",
            "draft_id": result.get("draft_id"),
        }]
    else:
        raise ValueError(f"지원하지 않는 Agent Tool입니다: {name}")

    return result, evidence
