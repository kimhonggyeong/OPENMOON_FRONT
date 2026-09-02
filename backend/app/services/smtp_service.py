from __future__ import annotations

import imaplib
import mimetypes
import re
import smtplib
from datetime import datetime
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime, make_msgid, parseaddr
from html import escape
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import Settings
from ..enums import DraftStatus, MailStatus
from ..models import QuotationDraft
from .quotation_service import customer_pdf_path


SIGNATURE_ROOT = Path(__file__).resolve().parents[2] / "assets" / "email_signatures"
EMPLOYEES = {
    "moon_jeongseon": {
        "job": "업무총괄", "name": "문정선", "rank": "대표이사",
        "phone": "010-4420-5106", "image": "moon_jeongseon.png",
    },
    "shin_woohyun": {
        "job": "관리부서", "name": "신우현", "rank": "주임",
        "phone": "041-548-5106", "image": "shin_woohyun.png",
    },
    "kwon_jihye": {
        "job": "회계담당", "name": "권지혜", "rank": "대리",
        "phone": "070-8667-4730", "image": "kwon_jihye.png",
    },
    "kim_heejung": {
        "job": "관리부", "name": "김희정", "rank": "과장",
        "phone": "041-548-5106", "image": "kim_heejung.png",
    },
}


def _sender_address(login_id: str) -> str:
    """Daum accepts an account ID for login, but From must be a full address."""
    value = login_id.strip()
    return value if "@" in value else f"{value}@daum.net"


def _sent_mailboxes(imap: imaplib.IMAP4_SSL) -> list[str]:
    """Return the server's special-use Sent folder, followed by safe fallbacks."""
    candidates: list[str] = []
    status, rows = imap.list()
    if status == "OK":
        for raw in rows or []:
            if not raw:
                continue
            line = raw.decode("ascii", errors="replace")
            match = re.match(r"\((?P<flags>[^)]*)\)\s+\"[^\"]*\"\s+(?P<name>.+)$", line)
            if not match or "\\Sent" not in match.group("flags").split():
                continue
            name = match.group("name").strip()
            if name.startswith('"') and name.endswith('"'):
                name = name[1:-1].replace(r'\"', '"').replace(r"\\", "\\")
            candidates.append(name)
    for fallback in ("Sent", "Sent Messages", "INBOX.Sent"):
        if fallback not in candidates:
            candidates.append(fallback)
    return candidates


def _append_to_sent(settings: Settings, raw_message: bytes) -> None:
    imap = imaplib.IMAP4_SSL(settings.imap_server, settings.imap_port, timeout=120)
    try:
        imap.login(settings.daum_login_id, settings.daum_app_password)
        errors: list[str] = []
        for mailbox in _sent_mailboxes(imap):
            try:
                # Daum은 APPEND의 선택 인자(플래그·내부 날짜)를 거부하는 경우가 있어
                # 서버가 자체 처리하도록 최소 인자 형식으로 저장한다.
                status, response = imap.append(mailbox, None, None, raw_message)
                if status == "OK":
                    return
                errors.append(f"{mailbox}: {status} {response!r}")
            except imaplib.IMAP4.error as error:
                # 한 후보 폴더가 거부되어도 나머지 Sent 폴더 후보를 계속 확인한다.
                errors.append(f"{mailbox}: {error}")
        raise RuntimeError("보낸메일함을 찾거나 저장할 수 없습니다. " + " / ".join(errors))
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def _default_email_body(employee_key: str) -> str:
    employee = EMPLOYEES.get(employee_key)
    if not employee:
        raise ValueError("발송 담당 직원을 선택해주세요.")
    identity = f"{employee['job']} {employee['name']} {employee['rank']}"
    return f"""안녕하세요.
(주)열린문디자인 {identity}입니다.

♥주문 주셔서 진심으로 감사드립니다.♥

요청주신 건에 대한 견적서를 첨부하여 보내드립니다.
견적서 검토 후 제작 진행 여부를 알려주시면, 담당 디자이너를 배정하여 시안을 받아보실 수 있도록 신속히 진행하겠습니다.

견적 또는 제작 관련하여 문의사항이 있으시면 아래 연락처로 편하게 연락 주시기 바랍니다.

또한, 저희 회사는 사회적기업 및 여성기업 확인서를 보유하고 있으니 관련 서류가 필요하실 경우 요청해 주시면 메일로 송부드리겠습니다.

무더워지는 날씨에 건강 유의하시고, 시원하고 기분 좋은 하루 보내시길 바랍니다.

감사합니다.

(주)열린문디자인 {identity}
☎ {employee['phone']}"""


def _is_legacy_short_body(body: str | None) -> bool:
    value = (body or "").strip()
    return (
        value.startswith("안녕하세요.")
        and "요청하신 견적서를 첨부하여 보내드립니다." in value
        and "검토 후 문의사항이 있으시면 회신 부탁드립니다." in value
        and value.endswith("열린문디자인")
    )


def _email_content(employee_key: str, body: str | None = None) -> tuple[str, str, Path]:
    employee = EMPLOYEES.get(employee_key)
    if not employee:
        raise ValueError("발송 담당 직원을 선택해주세요.")
    text = _default_email_body(employee_key)
    if body is not None and body.strip() and not _is_legacy_short_body(body):
        text = body.strip()
    html = "".join(
        f"<p style=\"margin:0 0 16px;line-height:1.65\">{escape(block).replace(chr(10), '<br>')}</p>"
        for block in text.split("\n\n")
    )
    html = (
        '<div style="font-family:Arial,\'Malgun Gothic\',sans-serif;font-size:14px;color:#111">'
        f"{html}<p style=\"margin-top:18px\"><img src=\"cid:employee-signature\" "
        'alt="직원 안내 이미지" style="display:block;max-width:100%;height:auto"></p></div>'
    )
    return text, html, SIGNATURE_ROOT / str(employee["image"])
def _validate_customer_pdf_attachment(
    pdf_path: Path,
    internal_xlsx_path: Path | None = None,
) -> None:
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(
            "고객 발송 첨부파일이 PDF 형식이 아닙니다."
        )

    try:
        header = pdf_path.read_bytes()[:5]
    except OSError as error:
        raise FileNotFoundError(
            f"고객용 PDF를 읽을 수 없습니다: {pdf_path}"
        ) from error

    if header != b"%PDF-":
        raise ValueError(
            "고객용 PDF 파일 형식이 올바르지 않습니다. "
            "견적서를 다시 생성해주세요."
        )

    if (
        internal_xlsx_path is not None
        and internal_xlsx_path.exists()
    ):
        try:
            pdf_mtime = pdf_path.stat().st_mtime
            xlsx_mtime = internal_xlsx_path.stat().st_mtime

            # 파일시스템 타임스탬프 오차를 감안하여 1초 여유.
            if pdf_mtime + 1 < xlsx_mtime:
                raise ValueError(
                    "고객용 PDF가 내부 견적서보다 오래된 버전입니다. "
                    "견적서를 다시 생성한 뒤 발송해주세요."
                )
        except OSError:
            pass


def validate_send_ready(settings: Settings, draft: QuotationDraft) -> tuple[str, Path]:
    """Validate all local prerequisites before approval changes the draft state."""
    if not settings.daum_login_id or not settings.daum_app_password:
        raise RuntimeError("메일 계정 정보가 설정되지 않았습니다.")

    customer_recipient = (
        draft.mail.customer_email
        or draft.mail.original_sender_email
    )

    approval_test_mode = bool(
        getattr(settings, "approval_test_mode", False)
    )

    if approval_test_mode:
        recipient = str(
            getattr(settings, "approval_test_recipient", "")
        ).strip()
        _, parsed_recipient = parseaddr(recipient)
        if not recipient or parsed_recipient != recipient or "@" not in parsed_recipient:
            raise ValueError(
                "APPROVAL_TEST_MODE=true일 때 유효한 "
                "APPROVAL_TEST_RECIPIENT를 설정해야 합니다."
            )
    elif not settings.allow_live_send:
        raise PermissionError(
            "ALLOW_LIVE_SEND=false입니다. 실제 발송 전 테스트를 완료하세요."
        )
    elif bool(getattr(settings, "send_test_to_self", False)):
        recipient = _sender_address(settings.daum_login_id)
    else:
        recipient = customer_recipient
        if not recipient:
            raise ValueError("고객 이메일 주소가 없습니다.")

    # 고객에게는 내부 XLSX가 아니라 4-A에서 생성한 고객용 PDF만 보낸다.
    attachment_path = customer_pdf_path(
        settings,
        draft,
    )

    if not attachment_path.exists():
        raise FileNotFoundError(
            "고객용 PDF가 없습니다. "
            "견적서를 다시 생성하여 최신 고객용 PDF를 만든 뒤 발송해주세요."
        )

    _validate_customer_pdf_attachment(
        attachment_path,
        Path(draft.file_path)
        if draft.file_path
        else None,
    )

    return recipient, attachment_path


def send_draft(
    session: Session,
    settings: Settings,
    draft: QuotationDraft,
    employee_key: str = "kim_heejung",
) -> QuotationDraft:
    if draft.status != DraftStatus.APPROVED:
        raise ValueError("승인된 견적서만 발송할 수 있습니다.")
    recipient, attachment_path = validate_send_ready(settings, draft)

    message = EmailMessage()
    message["From"] = _sender_address(settings.daum_login_id)
    message["To"] = recipient
    message["Date"] = format_datetime(datetime.now().astimezone())
    message["Message-ID"] = make_msgid(domain=_sender_address(settings.daum_login_id).split("@", 1)[1])
    text_body, html_body, signature_path = _email_content(employee_key, draft.email_body)
    if not signature_path.exists():
        raise FileNotFoundError(f"직원 서명 이미지를 찾을 수 없습니다: {signature_path}")
    saved_subject = (
        draft.email_subject
        or ""
    ).strip()

    if saved_subject:
        message["Subject"] = saved_subject
    else:
        original_subject = (
            draft.mail.original_subject
            or draft.mail.outer_subject
            or "견적 문의"
        ).strip()

        message["Subject"] = (
            original_subject
            if original_subject.lower().startswith("re:")
            else f"Re: {original_subject}"
        )
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")
    html_part = message.get_payload()[-1]
    html_part.add_related(
        signature_path.read_bytes(),
        maintype="image",
        subtype="png",
        cid="<employee-signature>",
        filename=signature_path.name,
        disposition="inline",
    )

    # 전달 메일의 Message-ID는 전달자와의 바깥 스레드이므로 직접 수신 메일에만 연결한다.
    if (
        not bool(getattr(settings, "approval_test_mode", False))
        and draft.mail.forward_depth == 0
        and draft.mail.message_id
    ):
        message["In-Reply-To"] = draft.mail.message_id
        references = (draft.mail.references or "").strip()
        message["References"] = f"{references} {draft.mail.message_id}".strip()

    content_type, _ = mimetypes.guess_type(attachment_path.name)
    maintype, subtype = (content_type or "application/octet-stream").split("/", 1)
    message.add_attachment(
        attachment_path.read_bytes(),
        maintype=maintype,
        subtype=subtype,
        filename=attachment_path.name,
    )

    try:
        # 견적서와 고해상도 서명 이미지를 함께 전송하므로 느린 회선도 허용한다.
        with smtplib.SMTP_SSL(settings.smtp_server, settings.smtp_port, timeout=120) as smtp:
            smtp.login(settings.daum_login_id, settings.daum_app_password)
            smtp.send_message(message)
        draft.status = DraftStatus.SENT
        draft.sent_at = datetime.now().astimezone().replace(tzinfo=None)
        draft.sent_to = recipient
        draft.mail.status = MailStatus.SENT
        draft.error_message = None
        try:
            _append_to_sent(settings, message.as_bytes(policy=SMTP))
        except Exception as append_error:
            # SMTP 발송은 이미 성공했으므로 재발송으로 인한 중복 메일을 막는다.
            draft.error_message = f"메일은 발송됐지만 보낸메일함 저장에 실패했습니다: {append_error}"
    except Exception as error:
        draft.status = DraftStatus.FAILED
        draft.error_message = f"{type(error).__name__}: {error}"
        raise
    finally:
        session.commit()
    if draft.status == DraftStatus.SENT:
        from .external_db_admin import sync_draft_to_history

        try:
            sync_draft_to_history(settings.quotation_database_path, draft, draft.mail)
        except Exception:
            import logging

            # 메일은 이미 발송됐으므로 재발송을 유발하지 않는다.
            # 설정의 수동 업데이트 버튼으로 안전하게 재시도할 수 있다.
            logging.getLogger(__name__).exception("발송 완료 견적의 이력 DB 갱신 실패")
    return draft
