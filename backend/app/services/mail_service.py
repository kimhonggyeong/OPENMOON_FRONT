from __future__ import annotations

import email
import hashlib
import imaplib
from datetime import datetime
from email import policy
from email.message import Message
from email.parser import BytesParser
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..enums import MailStatus
from ..models import Attachment, Mail
from .attachment_service import process_attachment
from .forwarded_mail_parser import parse_forwarded_mail
from .utils import (
    decode_mime_text,
    html_to_text,
    parse_address,
    parse_email_date,
    sanitize_filename,
)


def get_message_body(message: Message) -> str:
    plain: list[str] = []
    html: list[str] = []
    parts = message.walk() if message.is_multipart() else [message]
    for part in parts:
        if part.get_content_disposition() == "attachment" or part.get_filename():
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        try:
            content = part.get_content()
        except Exception:
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            content = payload.decode(charset, errors="replace")
        if not isinstance(content, str):
            continue
        if content_type == "text/plain":
            plain.append(content.strip())
        else:
            html.append(html_to_text(content))
    if plain:
        return "\n\n".join(value for value in plain if value).strip()
    return "\n\n".join(value for value in html if value).strip()


def _save_raw_mail(settings: Settings, raw: bytes, key: str) -> Path:
    digest = hashlib.sha256(raw).hexdigest()[:12]
    filename = sanitize_filename(f"{key}_{digest}.eml", 120)
    path = settings.raw_mails_dir / filename
    path.write_bytes(raw)
    return path


def _save_attachments(
    session: Session,
    settings: Settings,
    mail: Mail,
    message: Message,
) -> None:
    mail_dir = settings.attachments_dir / str(mail.id)
    mail_dir.mkdir(parents=True, exist_ok=True)
    for index, part in enumerate(message.walk(), start=1):
        filename = part.get_filename()
        if not filename:
            continue
        filename = decode_mime_text(filename)
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        safe_name = sanitize_filename(filename, 150)
        target = mail_dir / safe_name
        if target.exists():
            target = mail_dir / f"{index:02d}_{safe_name}"
        target.write_bytes(payload)
        record = Attachment(
            mail_id=mail.id,
            filename=filename,
            content_type=part.get_content_type(),
            saved_path=str(target.resolve()),
            size_bytes=len(payload),
        )
        session.add(record)
        session.flush()
        process_attachment(session, record)


def import_eml_bytes(
    session: Session,
    settings: Settings,
    raw: bytes,
    account: str = "local",
    uid: str | None = None,
    starred: bool = False,
) -> Mail:
    message = BytesParser(policy=policy.default).parsebytes(raw)
    message_id = decode_mime_text(message.get("Message-ID")) or None
    uid = uid or hashlib.sha256(raw).hexdigest()[:24]

    existing = session.scalar(
        select(Mail).where(
            (Mail.message_id == message_id) if message_id else ((Mail.account == account) & (Mail.uid == uid))
        )
    )
    if existing:
        return existing

    outer_sender_name, outer_sender_email = parse_address(message.get("From"))
    body = get_message_body(message)
    forwarded = parse_forwarded_mail(
        body,
        seller_names=settings.seller_name_set,
        seller_emails={settings.daum_login_id.lower()} if settings.daum_login_id else set(),
    )
    raw_path = _save_raw_mail(settings, raw, uid)

    mail = Mail(
        account=account,
        uid=uid,
        message_id=message_id,
        in_reply_to=decode_mime_text(message.get("In-Reply-To")) or None,
        references=decode_mime_text(message.get("References")) or None,
        raw_path=str(raw_path.resolve()),
        outer_sender_name=outer_sender_name or None,
        outer_sender_email=outer_sender_email or None,
        outer_recipient=decode_mime_text(message.get("To")) or None,
        outer_subject=decode_mime_text(message.get("Subject")) or None,
        outer_sent_at=parse_email_date(message.get("Date")),
        outer_body=body,
        original_sender_name=(forwarded.sender_name if forwarded else outer_sender_name) or None,
        original_sender_email=(forwarded.sender_email if forwarded else outer_sender_email) or None,
        original_recipient=(forwarded.recipient if forwarded else decode_mime_text(message.get("To"))) or None,
        original_subject=(forwarded.subject if forwarded else decode_mime_text(message.get("Subject"))) or None,
        original_sent_at=forwarded.sent_at if forwarded else parse_email_date(message.get("Date")),
        original_body=(forwarded.body if forwarded else body) or None,
        forward_depth=forwarded.depth if forwarded else 0,
        status=MailStatus.NEW,
        starred=starred,
    )
    session.add(mail)
    session.flush()
    _save_attachments(session, settings, mail, message)
    session.commit()
    session.refresh(mail)
    return mail


def sync_imap(
    session: Session,
    settings: Settings,
    limit: int = 50,
    include_existing: bool = False,
) -> dict[str, int]:
    if not settings.daum_login_id or not settings.daum_app_password:
        raise RuntimeError("DAUM_LOGIN_ID와 DAUM_APP_PASSWORD를 .env에 입력하세요.")

    imported = 0
    skipped = 0
    failed = 0
    imap = imaplib.IMAP4_SSL(settings.imap_server, settings.imap_port)
    try:
        imap.login(settings.daum_login_id, settings.daum_app_password)
        status, _ = imap.select("INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError("받은편지함을 열 수 없습니다.")
        status, data = imap.uid("search", None, "ALL")
        if status != "OK":
            raise RuntimeError("메일 UID 검색에 실패했습니다.")

        # Daum's important/star state is the standard IMAP \Flagged flag.
        flagged_status, flagged_data = imap.uid("search", None, "FLAGGED")
        if flagged_status != "OK":
            raise RuntimeError("중요 메일 상태를 가져오지 못했습니다.")
        flagged_uids = {
            value.decode()
            for value in (flagged_data[0].split() if flagged_data and flagged_data[0] else [])
        }
        existing_mails = session.scalars(
            select(Mail).where(Mail.account == settings.daum_login_id)
        ).all()
        for existing_mail in existing_mails:
            existing_mail.starred = existing_mail.uid in flagged_uids
        session.commit()

        uids = (data[0].split() if data and data[0] else [])[-limit:]
        for uid_bytes in uids:
            uid = uid_bytes.decode()
            if not include_existing:
                exists = session.scalar(
                    select(Mail.id).where(Mail.account == settings.daum_login_id, Mail.uid == uid)
                )
                if exists:
                    skipped += 1
                    continue
            try:
                status, message_data = imap.uid("fetch", uid_bytes, "(BODY.PEEK[])")
                if status != "OK":
                    failed += 1
                    continue
                raw = next(
                    (part[1] for part in message_data if isinstance(part, tuple) and part[1]),
                    None,
                )
                if not raw:
                    failed += 1
                    continue
                before = session.scalar(
                    select(Mail.id).where(Mail.account == settings.daum_login_id, Mail.uid == uid)
                )
                import_eml_bytes(
                    session,
                    settings,
                    raw,
                    account=settings.daum_login_id,
                    uid=uid,
                    starred=uid in flagged_uids,
                )
                imported += 0 if before else 1
            except Exception:
                session.rollback()
                failed += 1
        return {"imported": imported, "skipped": skipped, "failed": failed}
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def set_imap_star(settings: Settings, mail: Mail, starred: bool) -> None:
    """Mirror a local star change to the corresponding Daum INBOX message."""
    if mail.account != settings.daum_login_id:
        return
    if not settings.daum_login_id or not settings.daum_app_password:
        raise RuntimeError("DAUM_LOGIN_ID와 DAUM_APP_PASSWORD를 .env에 입력하세요.")

    imap = imaplib.IMAP4_SSL(settings.imap_server, settings.imap_port)
    try:
        imap.login(settings.daum_login_id, settings.daum_app_password)
        status, _ = imap.select("INBOX", readonly=False)
        if status != "OK":
            raise RuntimeError("받은편지함을 열 수 없습니다.")

        operation = "+FLAGS.SILENT" if starred else "-FLAGS.SILENT"
        status, _ = imap.uid("store", mail.uid, operation, "(\\Flagged)")
        if status != "OK":
            raise RuntimeError("다음 메일의 중요 표시를 변경하지 못했습니다.")
    finally:
        try:
            imap.logout()
        except Exception:
            pass
