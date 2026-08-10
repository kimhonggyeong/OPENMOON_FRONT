from __future__ import annotations

import mimetypes
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import Settings
from ..enums import DraftStatus, MailStatus
from ..models import QuotationDraft


def send_draft(session: Session, settings: Settings, draft: QuotationDraft) -> QuotationDraft:
    if draft.status != DraftStatus.APPROVED:
        raise ValueError("승인된 견적서만 발송할 수 있습니다.")
    if not settings.allow_live_send:
        raise PermissionError("ALLOW_LIVE_SEND=false입니다. 실제 발송 전 테스트를 완료하세요.")
    if not settings.daum_login_id or not settings.daum_app_password:
        raise RuntimeError("메일 계정 정보가 설정되지 않았습니다.")

    recipient = draft.mail.customer_email or draft.mail.original_sender_email
    if not recipient:
        raise ValueError("고객 이메일 주소가 없습니다.")
    attachment_path = Path(draft.file_path)
    if not attachment_path.exists():
        raise FileNotFoundError(attachment_path)

    message = EmailMessage()
    message["From"] = settings.daum_login_id
    message["To"] = recipient
    message["Subject"] = draft.email_subject or "[열린문디자인] 견적서 송부"
    message.set_content(draft.email_body or "요청하신 견적서를 첨부합니다.")

    content_type, _ = mimetypes.guess_type(attachment_path.name)
    maintype, subtype = (content_type or "application/octet-stream").split("/", 1)
    message.add_attachment(
        attachment_path.read_bytes(),
        maintype=maintype,
        subtype=subtype,
        filename=attachment_path.name,
    )

    try:
        with smtplib.SMTP_SSL(settings.smtp_server, settings.smtp_port, timeout=30) as smtp:
            smtp.login(settings.daum_login_id, settings.daum_app_password)
            smtp.send_message(message)
        draft.status = DraftStatus.SENT
        draft.sent_at = datetime.now().astimezone().replace(tzinfo=None)
        draft.sent_to = recipient
        draft.mail.status = MailStatus.SENT
        draft.error_message = None
    except Exception as error:
        draft.status = DraftStatus.FAILED
        draft.error_message = f"{type(error).__name__}: {error}"
        raise
    finally:
        session.commit()
    return draft
