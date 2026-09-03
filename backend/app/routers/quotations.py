from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import Settings, get_settings
from ..database import get_db
from ..enums import DraftStatus, MailStatus, Severity
from ..models import Mail, QuotationDraft, ReviewIssue
from ..schemas import (
    ApproveQuotationRequest,
    CreateQuotationRequest,
    DraftOut,
    EmailPreview,
    QuotationStorageOptions,
    UpdateQuotationEmailRequest,
)
from ..services.quotation_service import (
    approve_draft,
    create_quotation,
    customer_pdf_path,
    get_storage_options,
)
from ..services.smtp_service import _email_content, send_draft, validate_send_ready

router = APIRouter(prefix="/api/quotations", tags=["quotations"])


def _draft_query():
    return select(QuotationDraft).options(selectinload(QuotationDraft.items))


@router.get("", response_model=list[DraftOut])
def list_drafts(session: Session = Depends(get_db)):
    return session.scalars(_draft_query().order_by(QuotationDraft.id.desc())).all()


def _mail_for_quote(mail_id: int, session: Session) -> Mail | None:
    return session.scalar(
        select(Mail)
        .where(Mail.id == mail_id)
        .options(
            selectinload(Mail.items),
            selectinload(Mail.reviews),
            selectinload(Mail.attachments),
        )
    )


@router.get("/storage-options/{mail_id}", response_model=QuotationStorageOptions)
def storage_options(
    mail_id: int,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    mail = _mail_for_quote(mail_id, session)
    if not mail:
        raise HTTPException(404, "메일을 찾을 수 없습니다.")
    return get_storage_options(settings, mail)


@router.post("/from-mail/{mail_id}", response_model=DraftOut)
def create_from_mail(
    mail_id: int,
    request: CreateQuotationRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    mail = _mail_for_quote(mail_id, session)
    if not mail:
        raise HTTPException(404, "메일을 찾을 수 없습니다.")
    try:
        draft = create_quotation(
            session,
            settings,
            mail,
            storage_mode=request.mode,
            target_path=Path(request.file_path),
        )
        return session.scalar(_draft_query().where(QuotationDraft.id == draft.id))
    except Exception as error:
        raise HTTPException(400, str(error)) from error


@router.patch("/{draft_id}/email", response_model=DraftOut)
def update_draft_email(
    draft_id: int,
    request: UpdateQuotationEmailRequest,
    session: Session = Depends(get_db),
):
    draft = session.scalar(
        _draft_query().where(
            QuotationDraft.id == draft_id
        )
    )

    if not draft:
        raise HTTPException(
            404,
            "견적서를 찾을 수 없습니다.",
        )

    if draft.status == DraftStatus.SENT:
        raise HTTPException(
            409,
            "이미 발송된 견적서의 제목은 수정할 수 없습니다.",
        )

    subject = (
        request.email_subject
        or ""
    ).strip()

    if not subject:
        raise HTTPException(
            400,
            "발송 제목을 입력해주세요.",
        )

    if len(subject) > 300:
        raise HTTPException(
            400,
            "발송 제목은 300자 이내로 입력해주세요.",
        )

    draft.email_subject = subject

    if request.email_body is not None:
        draft.email_body = request.email_body
    if request.email_recipients is not None:
        draft.email_recipients = request.email_recipients

    session.commit()

    return session.scalar(
        _draft_query().where(
            QuotationDraft.id == draft_id
        )
    )


@router.get("/{draft_id}", response_model=DraftOut)
def get_draft(draft_id: int, session: Session = Depends(get_db)):
    draft = session.scalar(_draft_query().where(QuotationDraft.id == draft_id))
    if not draft:
        raise HTTPException(404, "견적서를 찾을 수 없습니다.")
    return draft


@router.get("/{draft_id}/file")
def download_draft(draft_id: int, session: Session = Depends(get_db)):
    draft = session.get(QuotationDraft, draft_id)
    if not draft:
        raise HTTPException(404, "견적서를 찾을 수 없습니다.")
    path = Path(draft.file_path)
    if not path.exists():
        raise HTTPException(404, "견적서 파일이 없습니다.")
    return FileResponse(path, filename=path.name)


@router.get("/{draft_id}/customer-pdf")
def download_customer_pdf(
    draft_id: int,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    draft = session.get(
        QuotationDraft,
        draft_id,
    )

    if not draft:
        raise HTTPException(
            404,
            "견적서를 찾을 수 없습니다.",
        )

    path = customer_pdf_path(
        settings,
        draft,
    )

    if not path.exists():
        raise HTTPException(
            404,
            "고객용 PDF가 아직 생성되지 않았습니다. 견적서를 다시 생성해주세요.",
        )

    return FileResponse(
        path,
        media_type="application/pdf",
        filename=path.name,
    )


@router.get("/{draft_id}/email-preview", response_model=EmailPreview)
def email_preview(
    draft_id: int,
    employee_key: str = "kim_heejung",
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    draft = session.get(QuotationDraft, draft_id)
    if not draft:
        raise HTTPException(404, "견적서를 찾을 수 없습니다.")
    pdf_path = customer_pdf_path(
        settings,
        draft,
    )

    try:
        preview_body = _email_content(employee_key, draft.email_body)[0]
    except ValueError as error:
        raise HTTPException(400, str(error)) from error

    customer_recipient = draft.mail.customer_email or draft.mail.original_sender_email
    if settings.approval_test_mode:
        recipient = settings.approval_test_recipient.strip() or None
        delivery_mode = "approval_test"
    elif settings.allow_live_send and settings.send_test_to_self:
        login_id = settings.daum_login_id.strip()
        recipient = login_id if "@" in login_id else f"{login_id}@daum.net"
        delivery_mode = "self_test"
    else:
        recipient = ", ".join(draft.email_recipients) if draft.email_recipients is not None else customer_recipient
        delivery_mode = "customer" if settings.allow_live_send else "blocked"

    return EmailPreview(
        subject=draft.email_subject or "",
        body=preview_body,
        recipient=recipient,
        recipients=[address.strip() for address in (recipient or "").split(",") if address.strip()],
        customer_recipient=customer_recipient,
        delivery_mode=delivery_mode,
        attachment_path=str(pdf_path) if pdf_path.exists() else None,
        attachment_name=pdf_path.name if pdf_path.exists() else None,
    )


@router.post("/{draft_id}/approve", response_model=DraftOut)
def approve(
    draft_id: int,
    request: ApproveQuotationRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    draft = session.scalar(_draft_query().where(QuotationDraft.id == draft_id))
    if not draft:
        raise HTTPException(404, "견적서를 찾을 수 없습니다.")
    try:
        # 발송 준비가 안 된 경우 초안을 승인 상태로 바꾸지 않는다.
        validate_send_ready(settings, draft)
        if draft.status == DraftStatus.FAILED:
            draft.status = DraftStatus.DRAFT
            draft.error_message = None
        approve_draft(session, draft)
        send_draft(session, settings, draft, request.employee_key)
        return session.scalar(_draft_query().where(QuotationDraft.id == draft_id))
    except PermissionError as error:
        raise HTTPException(409, str(error)) from error
    except Exception as error:
        raise HTTPException(400, str(error)) from error


@router.post("/{draft_id}/send", response_model=DraftOut)
def send(
    draft_id: int,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    draft = session.scalar(_draft_query().where(QuotationDraft.id == draft_id))
    if not draft:
        raise HTTPException(404, "견적서를 찾을 수 없습니다.")
    try:
        send_draft(session, settings, draft)
        return session.scalar(_draft_query().where(QuotationDraft.id == draft_id))
    except PermissionError as error:
        raise HTTPException(409, str(error)) from error
    except Exception as error:
        raise HTTPException(400, str(error)) from error


@router.delete("/{draft_id}")
def delete_draft(
    draft_id: int,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    draft = session.scalar(
        _draft_query().where(QuotationDraft.id == draft_id)
    )
    if not draft:
        raise HTTPException(404, "견적서를 찾을 수 없습니다.")

    path = Path(draft.file_path).resolve()
    generated_root = settings.generated_quotes_dir.resolve()
    quotation_root = settings.quotation_files_path.resolve()
    removable = False
    try:
        path.relative_to(generated_root)
        removable = True
    except ValueError:
        try:
            path.relative_to(quotation_root)
            removable = path.name.startswith("견적서_")
        except ValueError as error:
            raise HTTPException(400, "견적서 폴더 밖의 파일은 삭제할 수 없습니다.") from error

    mail = draft.mail
    # 공용/담당자별 통합문서는 다른 견적 시트를 포함하므로 삭제하지 않는다.
    if removable and path.exists():
        path.unlink()

    session.delete(draft)
    session.flush()

    blocking = session.scalar(
        select(ReviewIssue.id).where(
            ReviewIssue.mail_id == mail.id,
            ReviewIssue.resolved.is_(False),
            ReviewIssue.severity == Severity.BLOCKING,
        )
    )
    mail.status = (
        MailStatus.REVIEW_REQUIRED
        if blocking
        else MailStatus.READY_FOR_QUOTE
    )
    session.commit()
    return {"deleted": draft_id}
