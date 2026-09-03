from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.services import smtp_service


def _draft(tmp_path: Path):
    mail = SimpleNamespace(
        customer_email="customer@example.com",
        original_sender_email="sender@example.com",
        original_subject="원본 견적 요청",
        outer_subject=None,
        forward_depth=1,
        message_id=None,
        references=None,
        status=None,
    )

    return SimpleNamespace(
        id=17,
        mail=mail,
        email_subject="직접 수정한 발송 제목",
        file_path=str(tmp_path / "internal.xlsx"),
        status=smtp_service.DraftStatus.APPROVED,
    )


def _settings():
    return SimpleNamespace(
        allow_live_send=True,
        daum_login_id="sender@example.com",
        daum_app_password="secret",
        smtp_server="smtp.example.com",
        smtp_port=465,
    )


def test_validate_send_ready_requires_customer_pdf(tmp_path, monkeypatch):
    draft = _draft(tmp_path)
    pdf = tmp_path / "customer.pdf"

    monkeypatch.setattr(
        smtp_service,
        "customer_pdf_path",
        lambda settings, row: pdf,
    )

    with pytest.raises(
        FileNotFoundError,
        match="고객용 PDF",
    ):
        smtp_service.validate_send_ready(
            _settings(),
            draft,
        )


def test_validate_send_ready_returns_pdf_only(tmp_path, monkeypatch):
    draft = _draft(tmp_path)
    internal = Path(draft.file_path)
    internal.write_bytes(b"INTERNAL XLSX")

    pdf = tmp_path / "customer.pdf"
    pdf.write_bytes(b"%PDF-test")

    monkeypatch.setattr(
        smtp_service,
        "customer_pdf_path",
        lambda settings, row: pdf,
    )

    recipient, attachment = (
        smtp_service.validate_send_ready(
            _settings(),
            draft,
        )
    )

    assert recipient == "customer@example.com"
    assert attachment == pdf
    assert attachment != internal
    assert attachment.suffix == ".pdf"


def test_saved_subject_is_preferred_in_source():
    source = Path(
        smtp_service.__file__
    ).read_text(
        encoding="utf-8"
    )

    assert "saved_subject = (" in source
    assert 'message["Subject"] = saved_subject' in source
    assert "draft.email_subject" in source


def test_send_uses_all_saved_recipients(monkeypatch, tmp_path):
    from email.utils import getaddresses

    draft = _draft(tmp_path)
    draft.email_body = "견적서를 보내드립니다."
    draft.email_recipients = ["first@example.com", "second@example.com"]
    pdf = tmp_path / "customer.pdf"
    pdf.write_bytes(b"%PDF-test")
    signature = tmp_path / "signature.png"
    signature.write_bytes(b"test signature")
    monkeypatch.setattr(smtp_service, "customer_pdf_path", lambda *_: pdf)
    monkeypatch.setattr(smtp_service, "_email_content", lambda *_: ("body", "<p>body</p>", signature))
    monkeypatch.setattr(smtp_service, "_append_to_sent", lambda *_: None)
    monkeypatch.setattr("backend.app.services.external_db_admin.sync_draft_to_history", lambda *_: None)
    captured = []

    class FakeSMTP:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def login(self, *args): pass
        def send_message(self, message): captured.append(message)

    monkeypatch.setattr(smtp_service.smtplib, "SMTP_SSL", FakeSMTP)
    settings = _settings()
    settings.quotation_database_path = tmp_path / "history.db"
    smtp_service.send_draft(SimpleNamespace(commit=lambda: None), settings, draft)
    assert getaddresses(captured[0].get_all("To")) == [("", "first@example.com"), ("", "second@example.com")]
    assert draft.sent_to == "first@example.com, second@example.com"
    assert draft.status == smtp_service.DraftStatus.SENT
