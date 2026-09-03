from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base, get_db
from backend.app.enums import DraftStatus
from backend.app.models import Mail, QuotationDraft
from backend.app.routers import quotations
from backend.app.config import get_settings
from types import SimpleNamespace


def _client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        mail = Mail(
            account="phase4b",
            uid="1",
            message_id="<phase4b@example.com>",
            original_sender_email="customer@example.com",
            original_subject="견적 요청",
        )
        session.add(mail)
        session.flush()

        draft = QuotationDraft(
            mail_id=mail.id,
            status=DraftStatus.DRAFT,
            file_path="internal.xlsx",
            customer_name="테스트 고객",
            email_subject="기존 제목",
            email_body="기존 본문",
        )
        session.add(draft)
        session.commit()
        draft_id = draft.id

    app = FastAPI()
    app.include_router(quotations.router)

    def override_db():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db

    return TestClient(app), SessionLocal, draft_id


def test_update_draft_subject_persists():
    client, SessionLocal, draft_id = _client()

    response = client.patch(
        f"/api/quotations/{draft_id}/email",
        json={
            "email_subject": "  수정된 고객 발송 제목  "
        },
    )

    assert response.status_code == 200
    assert response.json()["email_subject"] == "수정된 고객 발송 제목"

    with SessionLocal() as session:
        draft = session.get(
            QuotationDraft,
            draft_id,
        )
        assert draft.email_subject == "수정된 고객 발송 제목"


def test_blank_subject_is_rejected():
    client, _, draft_id = _client()

    response = client.patch(
        f"/api/quotations/{draft_id}/email",
        json={
            "email_subject": "   "
        },
    )

    assert response.status_code == 400


def test_sent_draft_subject_is_locked():
    client, SessionLocal, draft_id = _client()

    with SessionLocal() as session:
        draft = session.get(
            QuotationDraft,
            draft_id,
        )
        draft.status = DraftStatus.SENT
        session.commit()

    response = client.patch(
        f"/api/quotations/{draft_id}/email",
        json={
            "email_subject": "발송 후 변경"
        },
    )

    assert response.status_code == 409


def test_recipient_edits_persist_and_preview_matches(monkeypatch, tmp_path):
    client, sessions, draft_id = _client()
    client.app.dependency_overrides[get_settings] = lambda: SimpleNamespace(
        approval_test_mode=False, allow_live_send=True, send_test_to_self=False,
    )
    monkeypatch.setattr(quotations, "customer_pdf_path", lambda *_: tmp_path / "quote.pdf")
    response = client.patch(f"/api/quotations/{draft_id}/email", json={
        "email_subject": "견적", "email_recipients": [" first@example.com ", "second@example.com", "first@example.com"],
    })
    assert response.status_code == 200
    with sessions() as session:
        assert session.get(QuotationDraft, draft_id).email_recipients == ["first@example.com", "second@example.com"]
    preview = client.get(f"/api/quotations/{draft_id}/email-preview").json()
    assert preview["recipients"] == ["first@example.com", "second@example.com"]
    assert preview["recipient"] == "first@example.com, second@example.com"
    response = client.patch(f"/api/quotations/{draft_id}/email", json={
        "email_subject": "견적", "email_recipients": ["second@example.com"],
    })
    assert response.status_code == 200
    assert client.get(f"/api/quotations/{draft_id}/email-preview").json()["recipients"] == ["second@example.com"]


def test_invalid_or_empty_recipients_are_not_saved():
    client, sessions, draft_id = _client()
    for addresses in ([], [""], ["invalid"], ["a@example.com\r\nBcc: b@example.com"], ["a@example.com,b@example.com"]):
        response = client.patch(f"/api/quotations/{draft_id}/email", json={
            "email_subject": "견적", "email_recipients": addresses,
        })
        assert response.status_code == 422
    with sessions() as session:
        assert session.get(QuotationDraft, draft_id).email_recipients is None
