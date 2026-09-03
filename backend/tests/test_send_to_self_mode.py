from types import SimpleNamespace

from backend.app.services.smtp_service import validate_send_ready


def test_test_mode_routes_to_logged_in_account(monkeypatch, tmp_path):
    pdf = tmp_path / "견적서.pdf"
    pdf.write_bytes(b"%PDF-test")

    xlsx = tmp_path / "견적서.xlsx"
    xlsx.write_bytes(b"xlsx")

    settings = SimpleNamespace(
        allow_live_send=True,
        approval_test_mode=False,
        approval_test_recipient="",
        daum_login_id="openmoon-test",
        daum_app_password="secret",
        send_test_to_self=True,
        generated_quotes_dir=tmp_path,
    )

    mail = SimpleNamespace(
        customer_email="real-customer@example.com",
        original_sender_email="real-customer@example.com",
    )
    draft = SimpleNamespace(
        id=1,
        customer_name="고객",
        mail=mail,
        file_path=str(xlsx),
    )

    monkeypatch.setattr(
        "backend.app.services.smtp_service.customer_pdf_path",
        lambda settings, draft: pdf,
    )

    draft.email_recipients = ["custom@example.com", "another@example.com"]
    recipient, attachment = validate_send_ready(settings, draft)

    assert recipient == "openmoon-test@daum.net"
    assert attachment == pdf


def test_approval_test_mode_routes_to_configured_recipient_with_live_send_disabled(
    monkeypatch,
    tmp_path,
):
    pdf = tmp_path / "견적서.pdf"
    pdf.write_bytes(b"%PDF-test")
    xlsx = tmp_path / "견적서.xlsx"
    xlsx.write_bytes(b"xlsx")

    settings = SimpleNamespace(
        allow_live_send=False,
        approval_test_mode=True,
        approval_test_recipient="hk010626@naver.com",
        daum_login_id="openmoon-test",
        daum_app_password="secret",
        send_test_to_self=True,
        generated_quotes_dir=tmp_path,
    )
    draft = SimpleNamespace(
        id=1,
        customer_name="고객",
        mail=SimpleNamespace(
            customer_email="real-customer@example.com",
            original_sender_email="real-customer@example.com",
        ),
        file_path=str(xlsx),
    )
    monkeypatch.setattr(
        "backend.app.services.smtp_service.customer_pdf_path",
        lambda settings, draft: pdf,
    )

    draft.email_recipients = ["custom@example.com", "another@example.com"]
    recipient, attachment = validate_send_ready(settings, draft)

    assert recipient == "hk010626@naver.com"
    assert attachment == pdf
