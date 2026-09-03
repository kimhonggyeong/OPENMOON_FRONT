from __future__ import annotations

from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import FileResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import (
    Session,
    selectinload,
)

from ..config import Settings, get_settings
from ..database import get_db
from ..models import (
    Attachment,
    Mail,
    MailItem,
    QuotationHistory,
)
from ..schemas import (
    AnalysisUpdate,
    HistoryCandidateOut,
    MailDetailOut,
    MailListOut,
    MailStarUpdate,
    MailSyncRequest,
    OpenHistorySourceRequest,
    PriceCandidateOut,
)
from ..services.history_service import (
    get_external_history_candidates,
    get_history_candidates,
    is_known_external_history_source,
)
from ..services.excel_open_service import (
    open_excel_location,
    resolve_quotation_source_path,
)
from ..services.llm_service import analyze_mail
from ..services.mail_service import (
    import_eml_bytes,
    set_imap_star,
    sync_imap,
)
from ..services.price_candidate_service import (
    get_external_price_candidates,
)
from ..services.price_service import (
    resolve_standard_product,
)
from ..services.quote_math import (
    SPEC_HIDDEN_KEY,
)
from ..services.review_service import (
    evaluate_mail_readiness,
)


router = APIRouter(
    prefix="/api/mails",
    tags=["mails"],
)


@router.post("/history/open-source")
def open_history_source(
    request: OpenHistorySourceRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Open only a quotation source that is already registered in history."""
    known = is_known_external_history_source(
        settings.quotation_database_path,
        request.source_file,
        request.source_sheet,
    )
    if not known:
        known = session.scalar(
            select(QuotationHistory.id).where(
                QuotationHistory.source_file == request.source_file,
                QuotationHistory.source_sheet == request.source_sheet,
            )
        ) is not None
    if not known:
        raise HTTPException(403, "등록된 과거 견적 파일만 열 수 있습니다.")
    try:
        source_path = resolve_quotation_source_path(
            request.source_file,
            settings.quotation_files_path,
        )
        return open_excel_location(
            source_path,
            sheet=request.source_sheet,
        )
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    except Exception as error:
        raise HTTPException(400, f"과거 견적 Excel 열기 실패: {error}") from error


@router.post("/history/source-file")
def download_history_source(
    request: OpenHistorySourceRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Send a registered history workbook to a LAN guest for local viewing."""
    known = is_known_external_history_source(
        settings.quotation_database_path,
        request.source_file,
        request.source_sheet,
    )
    if not known:
        known = session.scalar(
            select(QuotationHistory.id).where(
                QuotationHistory.source_file == request.source_file,
                QuotationHistory.source_sheet == request.source_sheet,
            )
        ) is not None
    if not known:
        raise HTTPException(403, "등록된 과거 견적 파일만 내려받을 수 있습니다.")
    try:
        source_path = resolve_quotation_source_path(
            request.source_file,
            settings.quotation_files_path,
        )
        return FileResponse(
            source_path,
            filename=source_path.name,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"X-Openmoon-Suffix": source_path.suffix.lower()},
        )
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error


# =========================================================
# 공통 메일 상세 조회 쿼리
# =========================================================

def _mail_query():
    return select(Mail).options(
        selectinload(Mail.attachments),
        selectinload(Mail.items),
        selectinload(Mail.reviews),
        selectinload(Mail.drafts),
    )


# =========================================================
# 메일 목록
# =========================================================

@router.get(
    "",
    response_model=list[MailListOut],
)
def list_mails(
    status: str | None = Query(
        default=None
    ),
    search: str | None = Query(
        default=None
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
    ),
    session: Session = Depends(get_db),
):
    query = select(Mail).where(
        Mail.deleted_at.is_(None)
    ).order_by(
        # 전달된 원본의 작성 시각이 아니라 실제 받은편지함에
        # 도착한 바깥 메일 시각을 기준으로 최신순 정렬한다.
        Mail.outer_sent_at
        .desc()
        .nullslast(),
        Mail.id.desc(),
    )

    if status:
        query = query.where(
            Mail.status == status
        )

    if search:
        pattern = f"%{search}%"

        query = query.where(
            Mail.original_subject.ilike(
                pattern
            )
            | Mail.original_sender_name.ilike(
                pattern
            )
            | Mail.original_sender_email.ilike(
                pattern
            )
            | Mail.customer_organization.ilike(
                pattern
            )
        )

    return session.scalars(
        query.limit(limit)
    ).all()


@router.patch(
    "/{mail_id}/star",
    response_model=MailListOut,
)
def update_mail_star(
    mail_id: int,
    request: MailStarUpdate,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    mail = session.get(Mail, mail_id)
    if mail is None:
        raise HTTPException(status_code=404, detail="메일을 찾을 수 없습니다.")

    try:
        set_imap_star(settings, mail, request.starred)
    except Exception as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    mail.starred = request.starred
    session.commit()
    session.refresh(mail)
    return mail


# =========================================================
# 메일 동기화
#
# 중요:
# /{mail_id}보다 반드시 위에 있어야 한다.
# =========================================================

@router.post("/sync")
def sync_mailbox(
    request: MailSyncRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(
        get_settings
    ),
):
    try:
        return sync_imap(
            session=session,
            settings=settings,
            limit=request.limit,
            include_existing=(
                request.include_existing
            ),
        )

    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error


# =========================================================
# EML 파일 가져오기
#
# 중요:
# /{mail_id}보다 반드시 위에 있어야 한다.
# =========================================================

@router.post(
    "/import-eml",
    response_model=list[MailListOut],
)
def upload_eml(
    files: list[UploadFile] = File(...),
    session: Session = Depends(get_db),
    settings: Settings = Depends(
        get_settings
    ),
):
    result: list[Mail] = []

    for file in files:
        if (
            not file.filename
            or not file.filename
            .lower()
            .endswith(".eml")
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "EML 파일만 업로드할 수 있습니다: "
                    f"{file.filename}"
                ),
            )

        raw = file.file.read()

        try:
            mail = import_eml_bytes(
                session=session,
                settings=settings,
                raw=raw,
            )

        except Exception as error:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{file.filename} 가져오기 실패: "
                    f"{type(error).__name__}: {error}"
                ),
            ) from error

        result.append(mail)

    return result


# =========================================================
# 첨부파일 다운로드
# =========================================================

@router.get(
    "/attachments/{attachment_id}/file"
)
def get_attachment(
    attachment_id: int,
    session: Session = Depends(get_db),
):
    attachment = session.get(
        Attachment,
        attachment_id,
    )

    if attachment is None:
        raise HTTPException(
            status_code=404,
            detail="첨부파일을 찾을 수 없습니다.",
        )

    path = Path(
        attachment.saved_path
    )

    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="저장된 첨부파일이 없습니다.",
        )

    return FileResponse(
        path=path,
        filename=attachment.filename,
        media_type=(
            attachment.content_type
            or "application/octet-stream"
        ),
    )


# =========================================================
# 메일 상세 조회
#
# 고정 경로들보다 뒤에 둔다.
# =========================================================

@router.get(
    "/{mail_id}",
    response_model=MailDetailOut,
)
def get_mail(
    mail_id: int,
    session: Session = Depends(get_db),
):
    mail = session.scalar(
        _mail_query().where(
            Mail.id == mail_id,
            Mail.deleted_at.is_(None),
        )
    )

    if mail is None:
        raise HTTPException(
            status_code=404,
            detail="메일을 찾을 수 없습니다.",
        )

    return mail


# =========================================================
# 메일 삭제
#
# 실제 IMAP 메일은 삭제하지 않고 로컬에서 soft-delete한다.
# account + uid 행을 유지하므로 이후 동기화에서도 같은 메일이
# 다시 신규 메일로 생성되지 않는다.
# =========================================================

@router.delete("/{mail_id}")
def delete_mail(
    mail_id: int,
    session: Session = Depends(get_db),
):
    mail = session.get(
        Mail,
        mail_id,
    )

    if (
        mail is None
        or mail.deleted_at is not None
    ):
        raise HTTPException(
            status_code=404,
            detail="메일을 찾을 수 없습니다.",
        )

    from datetime import datetime, timezone

    mail.deleted_at = (
        datetime.now(timezone.utc)
        .replace(tzinfo=None)
    )

    session.commit()

    return {
        "deleted": mail_id,
        "mode": "soft",
        "imap_deleted": False,
    }


# =========================================================
# AI 메일 분석
# =========================================================

@router.post(
    "/{mail_id}/analyze",
    response_model=MailDetailOut,
)
def run_analysis(
    mail_id: int,
    session: Session = Depends(get_db),
    settings: Settings = Depends(
        get_settings
    ),
):
    mail = session.scalar(
        _mail_query().where(
            Mail.id == mail_id
        )
    )

    if mail is None:
        raise HTTPException(
            status_code=404,
            detail="메일을 찾을 수 없습니다.",
        )

    try:
        analyze_mail(
            session=session,
            settings=settings,
            mail=mail,
        )

        analyzed_mail = session.scalar(
            _mail_query().where(
                Mail.id == mail_id
            )
        )

        if analyzed_mail is None:
            raise RuntimeError(
                "분석 후 메일 데이터를 다시 불러오지 못했습니다."
            )

        evaluate_mail_readiness(
            session=session,
            settings=settings,
            mail=analyzed_mail,
        )

        result = session.scalar(
            _mail_query().where(
                Mail.id == mail_id
            )
        )

        if result is None:
            raise RuntimeError(
                "검토 처리 후 메일 데이터를 불러오지 못했습니다."
            )

        return result

    except HTTPException:
        raise

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=(
                "메일 분석 실패: "
                f"{type(error).__name__}: {error}"
            ),
        ) from error


# =========================================================
# 분석 결과 수동 수정
# =========================================================

@router.patch(
    "/{mail_id}/analysis",
    response_model=MailDetailOut,
)
def update_analysis(
    mail_id: int,
    request: AnalysisUpdate,
    session: Session = Depends(get_db),
    settings: Settings = Depends(
        get_settings
    ),
):
    mail = session.scalar(
        _mail_query().where(
            Mail.id == mail_id
        )
    )

    if mail is None:
        raise HTTPException(
            status_code=404,
            detail="메일을 찾을 수 없습니다.",
        )

    try:
        for field in (
            "customer_organization",
            "customer_department",
            "customer_name",
            "customer_phone",
            "customer_email",
            "delivery_place",
            "payment_terms",
            "requested_date",
            "request_types",
            "commitment_status",
            "summary",
            "reason",
        ):
            setattr(
                mail,
                field,
                getattr(request, field),
            )

        # 품목의 종류(정규화된 품목명)가 바뀌면, 이전 품목 기준으로
        # 저장된 "인쇄 숨김" 사양 키가 새 품목의 같은 키 필드에
        # 잘못 이어붙는 것을 막기 위해 이전 매핑을 기억해둔다.
        previous_products = {
            existing_item.id: (
                existing_item.normalized_product
                or existing_item.product_name
            )
            for existing_item in mail.items
        }

        # 기존 품목을 삭제한 뒤
        # 화면에서 전달된 현재 품목으로 다시 생성한다.
        session.execute(
            delete(MailItem).where(
                MailItem.mail_id == mail.id
            )
        )

        session.flush()

        for position, item in enumerate(
            request.items,
            start=1,
        ):
            data = item.model_dump(
                exclude={"id"}
            )

            product_name = str(
                data.get("product_name")
                or ""
            ).strip()

            if not product_name:
                raise ValueError(
                    f"{position}번째 품목명이 비어 있습니다."
                )

            data["product_name"] = (
                product_name
            )

            data["normalized_product"] = (
                data.get(
                    "normalized_product"
                )
                or resolve_standard_product(
                    session,
                    product_name,
                )
            )

            previous_product = previous_products.get(item.id)
            if (
                previous_product is not None
                and previous_product != data["normalized_product"]
                and isinstance(data.get("spec_attributes"), dict)
            ):
                data["spec_attributes"] = {
                    key: value
                    for key, value in data["spec_attributes"].items()
                    if key != SPEC_HIDDEN_KEY
                }

            session.add(
                MailItem(
                    mail_id=mail.id,
                    position=position,
                    **data,
                )
            )

        session.commit()

        updated_mail = session.scalar(
            _mail_query().where(
                Mail.id == mail_id
            )
        )

        if updated_mail is None:
            raise RuntimeError(
                "수정된 메일을 다시 불러오지 못했습니다."
            )

        evaluate_mail_readiness(
            session=session,
            settings=settings,
            mail=updated_mail,
        )

        result = session.scalar(
            _mail_query().where(
                Mail.id == mail_id
            )
        )

        if result is None:
            raise RuntimeError(
                "검토 처리 후 메일을 다시 불러오지 못했습니다."
            )

        return result

    except HTTPException:
        raise

    except Exception as error:
        session.rollback()

        raise HTTPException(
            status_code=400,
            detail=(
                "분석 내용 저장 실패: "
                f"{type(error).__name__}: {error}"
            ),
        ) from error


# =========================================================
# 새 외부 가격 엔진 후보 조회
# =========================================================

@router.get(
    "/{mail_id}/price-candidates",
    response_model=list[
        PriceCandidateOut
    ],
)
def get_mail_price_candidates(
    mail_id: int,
    session: Session = Depends(get_db),
    settings: Settings = Depends(
        get_settings
    ),
):
    mail = session.scalar(
        select(Mail)
        .where(
            Mail.id == mail_id
        )
        .options(
            selectinload(Mail.items)
        )
    )

    if mail is None:
        raise HTTPException(
            status_code=404,
            detail="메일을 찾을 수 없습니다.",
        )

    try:
        return get_external_price_candidates(
            session=session,
            settings=settings,
            mail=mail,
        )

    except FileNotFoundError as error:
        raise HTTPException(
            status_code=500,
            detail=str(error),
        ) from error

    except RuntimeError as error:
        raise HTTPException(
            status_code=500,
            detail=str(error),
        ) from error

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=(
                "가격 후보 조회 실패: "
                f"{type(error).__name__}: {error}"
            ),
        ) from error


# =========================================================
# 기존 내부 DB 기준 과거 견적 후보 조회
# =========================================================

@router.get(
    "/{mail_id}/history",
    response_model=list[
        HistoryCandidateOut
    ],
)
def history_candidates(
    mail_id: int,
    scope: str = Query(default="customer", pattern="^(customer|company)$"),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    mail = session.scalar(
        _mail_query().where(
            Mail.id == mail_id
        )
    )

    if mail is None:
        raise HTTPException(
            status_code=404,
            detail="메일을 찾을 수 없습니다.",
        )

    external_rows = get_external_history_candidates(
        settings.quotation_database_path,
        mail,
        scope=scope,
    )
    if external_rows:
        return [HistoryCandidateOut(**row) for row in external_rows]

    # 이전 방식으로 가져온 내부 이력이 있는 설치 환경을 위한 호환 경로.
    results: list[HistoryCandidateOut] = []

    if scope == "company":
        return results

    for item in mail.items:
        rows = get_history_candidates(
            session=session,
            mail=mail,
            item=item,
        )

        for history_item, quotation in rows:
            results.append(
                HistoryCandidateOut(
                    quotation_id=(
                        quotation.id
                    ),
                    quotation_date=(
                        quotation.quotation_date
                    ),
                    customer_name=(
                        quotation.customer_name
                    ),
                    product_name=(
                        history_item.product_name
                    ),
                    specification=(
                        history_item.specification
                    ),
                    width_mm=(
                        history_item.width_mm
                    ),
                    height_mm=(
                        history_item.height_mm
                    ),
                    quantity=(
                        history_item.quantity
                    ),
                    unit_price=(
                        history_item.unit_price
                    ),
                    amount=(
                        history_item.amount
                    ),
                    source_file=(
                        quotation.source_file
                    ),
                    source_sheet=(
                        quotation.source_sheet
                    ),
                )
            )

    return results
