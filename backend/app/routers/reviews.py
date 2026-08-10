from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import Settings, get_settings
from ..database import get_db
from ..models import Mail, ReviewIssue
from ..schemas import MailDetailOut, ReviewIssueOut, ReviewResolveRequest
from ..services.review_service import apply_review_resolution, evaluate_mail_readiness

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


@router.get("", response_model=list[ReviewIssueOut])
def list_unresolved(session: Session = Depends(get_db)):
    return session.scalars(
        select(ReviewIssue)
        .where(ReviewIssue.resolved.is_(False))
        .order_by(ReviewIssue.created_at.desc())
    ).all()


@router.post("/{issue_id}/resolve", response_model=MailDetailOut)
def resolve_issue(
    issue_id: int,
    request: ReviewResolveRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    issue = session.get(ReviewIssue, issue_id)
    if not issue:
        raise HTTPException(404, "검토 항목을 찾을 수 없습니다.")
    apply_review_resolution(session, issue, request.resolution_value)
    mail = session.scalar(
        select(Mail)
        .where(Mail.id == issue.mail_id)
        .options(
            selectinload(Mail.attachments),
            selectinload(Mail.items),
            selectinload(Mail.reviews),
        )
    )
    evaluate_mail_readiness(session, settings, mail)
    return session.scalar(
        select(Mail)
        .where(Mail.id == issue.mail_id)
        .options(
            selectinload(Mail.attachments),
            selectinload(Mail.items),
            selectinload(Mail.reviews),
        )
    )
