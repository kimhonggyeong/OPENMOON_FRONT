from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from email.utils import parseaddr

from .utils import decode_mime_text, extract_email, parse_email_date

MARKER_PATTERN = re.compile(r"[-—_\s]*원본\s*메일[-—_\s]*", re.I)
HEADER_PATTERN = re.compile(
    r"^(?P<label>보낸사람|받는사람|날짜|제목|첨부파일)\s*[:：]\s*(?P<value>.*)$",
    re.I,
)
HEADER_LABELS = {"보낸사람", "받는사람", "날짜", "제목", "첨부파일"}


@dataclass(slots=True)
class ForwardedMail:
    sender_name: str | None
    sender_email: str | None
    recipient: str | None
    sent_at: datetime | None
    subject: str | None
    body: str
    attachment_names: list[str]
    depth: int


def _parse_sender(value: str) -> tuple[str | None, str | None]:
    value = value.replace('\\"', '"').strip()
    name, address = parseaddr(value)
    if not address:
        address = extract_email(value) or ""
        if address:
            name = value.replace(address, "").strip(" <>\"'")
    return decode_mime_text(name) or None, address.lower() or None


def _parse_forward_date(value: str) -> datetime | None:
    parsed = parse_email_date(value)
    if parsed:
        return parsed
    cleaned = value.strip()
    # Daum 전달 본문 예: 26.08.03 13:13 GMT +0900
    match = re.search(
        r"(?P<y>\d{2,4})[./-](?P<m>\d{1,2})[./-](?P<d>\d{1,2})\s+"
        r"(?P<h>\d{1,2}):(?P<min>\d{2})",
        cleaned,
    )
    if not match:
        return None
    year = int(match.group("y"))
    if year < 100:
        year += 2000
    try:
        return datetime(
            year,
            int(match.group("m")),
            int(match.group("d")),
            int(match.group("h")),
            int(match.group("min")),
        )
    except ValueError:
        return None


def _parse_block(block: str, depth: int) -> ForwardedMail | None:
    lines = [line.rstrip() for line in block.replace("\r", "").split("\n")]
    headers: dict[str, str] = {}
    attachment_names: list[str] = []
    body_start = 0
    header_count = 0
    index = 0

    while index < len(lines):
        stripped = lines[index].strip()
        label: str | None = None
        value: str | None = None

        inline = HEADER_PATTERN.match(stripped)
        if inline:
            label = inline.group("label")
            value = inline.group("value").strip()
        elif stripped in HEADER_LABELS:
            label = stripped
            # Daum HTML->텍스트 변환 시 라벨과 ': 값'이 별도 줄로 분리됨.
            if index + 1 < len(lines):
                next_line = lines[index + 1].strip()
                if next_line.startswith((":", "：")):
                    value = next_line[1:].strip()
                    index += 1
                else:
                    value = next_line
                    index += 1
            else:
                value = ""

        if label is not None:
            if label == "첨부파일":
                attachment_names.extend(
                    [part.strip() for part in re.split(r"[,;]", value or "") if part.strip()]
                )
            else:
                headers[label] = value or ""
            header_count += 1
            body_start = index + 1
            index += 1
            continue

        if header_count:
            if not stripped:
                body_start = index + 1
                index += 1
                continue
            body_start = index
            break
        index += 1

    if not header_count or "보낸사람" not in headers:
        return None

    sender_name, sender_email = _parse_sender(headers.get("보낸사람", ""))
    body = "\n".join(lines[body_start:]).strip()
    return ForwardedMail(
        sender_name=sender_name,
        sender_email=sender_email,
        recipient=headers.get("받는사람"),
        sent_at=_parse_forward_date(headers.get("날짜", "")),
        subject=headers.get("제목"),
        body=body,
        attachment_names=attachment_names,
        depth=depth,
    )


def parse_forwarded_mail(
    body: str,
    seller_names: set[str],
    seller_emails: set[str] | None = None,
) -> ForwardedMail | None:
    """전달 본문에서 가장 안쪽의 실제 고객 메일을 선택한다."""

    seller_emails = {value.lower() for value in (seller_emails or set())}
    matches = list(MARKER_PATTERN.finditer(body))
    blocks: list[ForwardedMail] = []

    if matches:
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
            parsed = _parse_block(body[match.end() : end], index + 1)
            if parsed:
                blocks.append(parsed)
    else:
        parsed = _parse_block(body, 1)
        if parsed:
            blocks.append(parsed)

    if not blocks:
        return None

    normalized_sellers = {re.sub(r"\s+", "", name) for name in seller_names}
    external: list[ForwardedMail] = []
    for candidate in blocks:
        name_norm = re.sub(r"\s+", "", candidate.sender_name or "")
        email = (candidate.sender_email or "").lower()
        if name_norm in normalized_sellers or email in seller_emails:
            continue
        external.append(candidate)

    return external[-1] if external else blocks[-1]
