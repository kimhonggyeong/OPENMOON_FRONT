from backend.app.services.forwarded_mail_parser import parse_forwarded_mail


def test_parses_daum_split_header_lines():
    body = """
--------- 원본 메일 ---------
보낸사람
: "임희정" <heejeong25@korea.kr>
받는사람
: "열린문디자인" <yullin-moon@daum.net>
날짜
: 26.08.03 13:13 GMT +0900
제목
: [아산시청 축산과] 현수막 시안 의뢰
첨부파일
: 동물유기 현수막 시안.hwpx
현수막 제작을 의뢰드립니다.
"""
    parsed = parse_forwarded_mail(
        body,
        {"열린문디자인", "(주)열린문디자인"},
        {"yullin-moon@daum.net"},
    )
    assert parsed is not None
    assert parsed.sender_name == "임희정"
    assert parsed.sender_email == "heejeong25@korea.kr"
    assert parsed.subject == "[아산시청 축산과] 현수막 시안 의뢰"
    assert parsed.sent_at.year == 2026
    assert parsed.attachment_names == ["동물유기 현수막 시안.hwpx"]
