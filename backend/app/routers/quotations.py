from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import Settings, get_settings
from ..database import get_db
from ..enums import MailStatus, Severity
from ..models import Mail, QuotationDraft, ReviewIssue
from ..schemas import DraftOut, EmailPreview
from ..services.quotation_service import approve_draft, create_quotation
from ..services.smtp_service import send_draft

router = APIRouter(prefix="/api/quotations", tags=["quotations"])


def _draft_query():
    return select(QuotationDraft).options(selectinload(QuotationDraft.items))


@router.get("", response_model=list[DraftOut])
def list_drafts(session: Session = Depends(get_db)):
    return session.scalars(_draft_query().order_by(QuotationDraft.id.desc())).all()


@router.post("/from-mail/{mail_id}", response_model=DraftOut)
def create_from_mail(
    mail_id: int,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    mail = session.scalar(
        select(Mail)
        .where(Mail.id == mail_id)
        .options(
            selectinload(Mail.items),
            selectinload(Mail.reviews),
            selectinload(Mail.attachments),
        )
    )
    if not mail:
        raise HTTPException(404, "메일을 찾을 수 없습니다.")
    try:
        draft = create_quotation(session, settings, mail)
        return session.scalar(_draft_query().where(QuotationDraft.id == draft.id))
    except Exception as error:
        raise HTTPException(400, str(error)) from error


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


@router.get("/{draft_id}/email-preview", response_model=EmailPreview)
def email_preview(draft_id: int, session: Session = Depends(get_db)):
    draft = session.get(QuotationDraft, draft_id)
    if not draft:
        raise HTTPException(404, "견적서를 찾을 수 없습니다.")
    return EmailPreview(
        subject=draft.email_subject or "",
        body=draft.email_body or "",
        recipient=draft.mail.customer_email or draft.mail.original_sender_email,
        attachment_path=draft.file_path,
    )


@router.post("/{draft_id}/approve", response_model=DraftOut)
def approve(draft_id: int, session: Session = Depends(get_db)):
    draft = session.scalar(_draft_query().where(QuotationDraft.id == draft_id))
    if not draft:
        raise HTTPException(404, "견적서를 찾을 수 없습니다.")
    return approve_draft(session, draft)


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
    try:
        path.relative_to(generated_root)
    except ValueError as error:
        raise HTTPException(400, "생성 견적서 폴더 밖의 파일은 삭제할 수 없습니다.") from error

    mail = draft.mail
    if path.exists():
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
