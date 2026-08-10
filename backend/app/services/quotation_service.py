from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import Settings
from ..enums import (
    DraftStatus,
    MailStatus,
    Severity,
)
from ..models import (
    Mail,
    QuotationDraft,
    QuotationDraftItem,
    ReviewIssue,
)
from .price_engine_adapter import (
    calculate_item_price,
)
from .utils import sanitize_filename


# =========================================================
# 품목 표시 문자열
# =========================================================

def _item_text(
    item: Any,
) -> str:
    lines: list[str] = []

    if item.product_name:
        lines.append(
            str(item.product_name).strip()
        )

    if item.specification:
        specification = str(
            item.specification
        ).strip()

        if specification:
            lines.append(
                f"({specification})"
            )

    return "\n".join(lines)


# =========================================================
# 미해결 필수 검토 확인
# =========================================================

def _ensure_no_blocking_reviews(
    session: Session,
    mail: Mail,
) -> None:
    blocking = session.scalar(
        select(ReviewIssue.id).where(
            ReviewIssue.mail_id == mail.id,
            ReviewIssue.resolved.is_(False),
            ReviewIssue.severity
            == Severity.BLOCKING,
        )
    )

    if blocking:
        raise ValueError(
            "검토가 필요한 필수 항목이 "
            "남아 있어 견적서를 생성할 수 없습니다."
        )


# =========================================================
# 단가와 금액 결정
# =========================================================

def _resolve_item_price(
    settings: Settings,
    mail: Mail,
    item: Any,
) -> tuple[
    int | None,
    int | None,
    dict[str, Any],
]:
    """
    품목의 확정 단가와 금액을 반환한다.

    우선순위:
    1. 담당자가 입력하거나 이미 확정된 단가
    2. 새 SQLite 가격 엔진의 고신뢰 결과
    3. 미확정이면 오류
    """

    # -----------------------------------------------------
    # 이미 입력된 단가
    # -----------------------------------------------------

    if item.unit_price is not None:
        unit_price = int(
            item.unit_price
        )

        amount = (
            int(item.amount)
            if item.amount is not None
            else None
        )

        if (
            amount is None
            and item.quantity is not None
        ):
            amount = int(
                round(
                    float(item.quantity)
                    * unit_price
                )
            )

        source: dict[str, Any] = {
            "type": (
                "MANUAL"
                if item.confirmed
                else "MAIL"
            ),
            "reason": (
                "담당자가 확정한 단가"
                if item.confirmed
                else "메일 또는 분석 결과의 단가"
            ),
        }

        price_evidence = (
            dict(item.evidence or {})
            .get("price")
        )

        if isinstance(
            price_evidence,
            dict,
        ):
            source.update(
                price_evidence
            )

        return (
            unit_price,
            amount,
            source,
        )

    # -----------------------------------------------------
    # 새 가격 엔진 검색
    # -----------------------------------------------------

    decision = calculate_item_price(
        settings=settings,
        mail=mail,
        item=item,
    )

    if decision.unit_price is None:
        return (
            None,
            None,
            {
                "type": "UNRESOLVED",
                "source": decision.source,
                "reference": decision.reference,
                "score": decision.score,
                "reason": decision.reason,
                "needs_review": True,
            },
        )

    unit_price = int(
        decision.unit_price
    )

    amount = (
        int(decision.amount)
        if decision.amount is not None
        else None
    )

    if (
        amount is None
        and item.quantity is not None
    ):
        amount = int(
            round(
                float(item.quantity)
                * unit_price
            )
        )

    source = {
        "type": (
            decision.source.upper()
        ),
        "source": decision.source,
        "reference": decision.reference,
        "score": decision.score,
        "reason": decision.reason,
        "needs_review": (
            decision.needs_review
        ),
    }

    return (
        unit_price,
        amount,
        source,
    )


# =========================================================
# 견적서 생성
# =========================================================

def create_quotation(
    session: Session,
    settings: Settings,
    mail: Mail,
) -> QuotationDraft:
    _ensure_no_blocking_reviews(
        session,
        mail,
    )

    if mail.analysis_payload.get("is_order_related") is False:
        raise ValueError("견적 업무와 관련된 메일만 견적서를 생성할 수 있습니다.")

    if not mail.items:
        raise ValueError(
            "견적서에 입력할 품목이 없습니다."
        )

    if (
        not settings
        .quotation_template_path
        .exists()
    ):
        raise FileNotFoundError(
            "견적서 템플릿을 찾을 수 없습니다: "
            f"{settings.quotation_template_path}"
        )

    customer_name = (
        mail.customer_organization
        or mail.customer_name
        or "고객"
    )

    # 같은 메일에서 이미 만든 견적서가 있으면 새 기록과 새 파일을
    # 만들지 않고 기존 견적서와 파일을 갱신한다.
    draft = session.scalar(
        select(QuotationDraft)
        .where(QuotationDraft.mail_id == mail.id)
        .order_by(QuotationDraft.id.desc())
        .options(selectinload(QuotationDraft.items))
    )

    if draft is not None:
        output_path = Path(draft.file_path)
        generated_root = settings.generated_quotes_dir.resolve()
        try:
            output_path.resolve().relative_to(generated_root)
        except ValueError:
            output_path = generated_root / sanitize_filename(
                f"견적서_{customer_name}_{draft.id}.xlsx",
                120,
            )

        draft.items.clear()
        draft.status = DraftStatus.DRAFT
        draft.customer_name = customer_name
        draft.approved_at = None
        draft.sent_at = None
        draft.sent_to = None
        draft.error_message = None
    else:
        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )
        output_name = sanitize_filename(
            f"견적서_{customer_name}_{timestamp}.xlsx",
            120,
        )
        output_path = settings.generated_quotes_dir / output_name
        draft = QuotationDraft(
            mail_id=mail.id,
            status=DraftStatus.DRAFT,
            file_path=str(output_path.resolve()),
            customer_name=customer_name,
        )
        session.add(draft)

    draft.file_path = str(output_path.resolve())
    draft.email_subject = (
        "[열린문디자인] 요청하신 견적서를 보내드립니다"
        f" - {customer_name}"
    )
    draft.email_body = (
        f"안녕하세요. {customer_name} 담당자님.\n\n"
        "요청하신 견적서를 첨부하여 보내드립니다.\n"
        "검토 후 문의사항이 있으시면 회신 부탁드립니다.\n\n"
        "감사합니다.\n열린문디자인"
    )

    # 템플릿 파일 전체 복사
    # 이미지·병합·서식·행 높이를 유지한다.
    shutil.copy2(
        settings.quotation_template_path,
        output_path,
    )

    session.flush()

    # YullinMoon_Ver3.py와 동일하게 모든 품목의 금액이
    # 확정된 경우에만 전체 금액을 확정한다.
    total = 0
    total_is_complete = True

    selected: list[
        QuotationDraftItem
    ] = []

    # -----------------------------------------------------
    # 품목 가격 확정 및 초안 품목 생성
    # -----------------------------------------------------

    for position, item in enumerate(
        mail.items,
        start=1,
    ):
        (
            unit_price,
            amount,
            source,
        ) = _resolve_item_price(
            settings=settings,
            mail=mail,
            item=item,
        )

        # MailItem에도 최종 확정 가격 반영
        item.unit_price = unit_price
        item.amount = amount

        if amount is not None:
            total += amount
        else:
            total_is_complete = False

        record = QuotationDraftItem(
            draft_id=draft.id,
            position=position,
            product_name=(
                item.product_name
            ),
            specification=(
                item.specification
            ),
            quantity=item.quantity,
            unit=item.unit,
            unit_price=unit_price,
            amount=amount,
            note=item.schedule_note,
            price_source=source,
        )

        session.add(record)
        session.flush()

        selected.append(record)

    # -----------------------------------------------------
    # Excel 템플릿 작성
    # -----------------------------------------------------

    workbook = load_workbook(
        output_path
    )

    try:
        sheet_name = (
            settings
            .quotation_template_sheet
        )

        if sheet_name in workbook.sheetnames:
            sheet = workbook[
                sheet_name
            ]
        else:
            # 지정 시트가 없으면 첫 번째 시트 사용
            sheet = workbook.worksheets[0]

        # 견적서 시트만 남김
        for other in list(
            workbook.worksheets
        ):
            if other != sheet:
                workbook.remove(
                    other
                )

        sheet.title = "견적서"
        workbook.active = 0

        # -------------------------------------------------
        # 고객 정보
        # -------------------------------------------------

        sheet["B3"] = (
            f"{customer_name} 귀하"
        )

        sheet["D4"] = (
            mail.customer_department
            or "담당자 귀하"
        )

        sheet["D5"] = datetime.now()

        sheet["D6"] = (
            mail.delivery_place
            or settings.default_delivery_place
        )

        sheet["D7"] = (
            mail.payment_terms
            or settings.default_payment_terms
        )

        sheet["D8"] = (
            settings.default_validity
        )

        sheet["L5"] = (
            mail.customer_name
            or ""
        )

        sheet["L6"] = (
            mail.customer_phone
            or ""
        )

        sheet["L7"] = (
            mail.customer_email
            or mail.original_sender_email
            or ""
        )

        # -------------------------------------------------
        # 기존 품목 영역 초기화
        # -------------------------------------------------

        for row in range(
            14,
            24,
        ):
            for column in (
                3,
                6,
                7,
                9,
                12,
            ):
                sheet.cell(
                    row,
                    column,
                ).value = None

        # -------------------------------------------------
        # 품목 입력
        # YullinMoon_Ver3.py와 동일하게 detail_text는
        # 품목 바로 다음 행에 별도로 배치한다.
        # -------------------------------------------------

        current_row = 14

        for draft_item, mail_item in zip(
            selected,
            mail.items,
        ):
            if current_row > 23:
                break

            row_number = current_row

            sheet.cell(
                row_number,
                3,
            ).value = _item_text(draft_item)

            sheet.cell(
                row_number,
                6,
            ).value = draft_item.quantity

            sheet.cell(
                row_number,
                7,
            ).value = draft_item.unit_price

            sheet.cell(
                row_number,
                9,
            ).value = draft_item.amount

            sheet.cell(
                row_number,
                12,
            ).value = draft_item.note

            detail_text = str(
                mail_item.detail_text or ""
            ).strip()

            if detail_text and current_row < 23:
                sheet.cell(
                    current_row + 1,
                    3,
                ).value = detail_text
                current_row += 2
            else:
                current_row += 1

        # -------------------------------------------------
        # 공급금액 수식
        # -------------------------------------------------

        if total_is_complete:
            # openpyxl은 수식을 계산하지 않으므로 일부 미리보기에서는
            # 캐시가 없는 수식 셀이 빈칸으로 보인다. 이미 Python에서
            # 계산한 확정 금액을 직접 기록해 모든 Excel 뷰어에서 즉시
            # 공급금액이 표시되도록 한다. 기존 셀의 한글/통화 서식은 유지된다.
            sheet["G24"] = total
            sheet["D10"] = total
            sheet["I10"] = total
        else:
            sheet["G24"] = ""
            sheet["D10"] = ""
            sheet["I10"] = ""

        try:
            workbook.calculation.fullCalcOnLoad = True
            workbook.calculation.forceFullCalc = True
            workbook.calculation.calcMode = "auto"

        except AttributeError:
            pass

        workbook.save(
            output_path
        )

    except Exception:
        # Excel 생성 실패 시 불완전한 파일 제거
        try:
            workbook.close()
        except Exception:
            pass

        output_path.unlink(
            missing_ok=True
        )

        session.rollback()

        raise

    finally:
        try:
            workbook.close()
        except Exception:
            pass

    # -----------------------------------------------------
    # 최종 DB 상태
    # -----------------------------------------------------

    draft.total_amount = (
        total
        if selected and total_is_complete
        else None
    )

    mail.status = (
        MailStatus.QUOTE_CREATED
    )

    session.commit()
    session.refresh(draft)

    return draft


# =========================================================
# 견적 승인
# =========================================================

def approve_draft(
    session: Session,
    draft: QuotationDraft,
) -> QuotationDraft:
    if draft.status != DraftStatus.DRAFT:
        raise ValueError(
            "초안 상태의 견적서만 "
            "승인할 수 있습니다."
        )

    draft.status = (
        DraftStatus.APPROVED
    )

    draft.approved_at = (
        datetime.now()
        .astimezone()
        .replace(tzinfo=None)
    )

    draft.mail.status = (
        MailStatus.APPROVED
    )

    session.commit()
    session.refresh(draft)

    return draft
