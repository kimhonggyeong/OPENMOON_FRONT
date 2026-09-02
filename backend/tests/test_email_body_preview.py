from backend.app.services.smtp_service import _email_content


def test_saved_review_body_is_used_in_text_and_html_email():
    body = "안녕하세요.\n\n수정한 최종 견적 내용을 확인해주세요."

    text, html, _signature = _email_content("kim_heejung", body)

    assert text == body
    assert "수정한 최종 견적 내용을 확인해주세요." in html
    assert "cid:employee-signature" in html

def test_legacy_short_body_is_upgraded_to_employee_template():
    short_body = (
        "안녕하세요. 충남사회경제네트워크 담당자님.\n\n"
        "요청하신 견적서를 첨부하여 보내드립니다.\n"
        "검토 후 문의사항이 있으시면 회신 부탁드립니다.\n\n"
        "감사합니다.\n열린문디자인"
    )

    text, _html, _signature = _email_content("kim_heejung", short_body)

    assert "♥주문 주셔서 진심으로 감사드립니다.♥" in text
    assert "관리부 김희정 과장" in text
    assert "☎ 041-548-5106" in text