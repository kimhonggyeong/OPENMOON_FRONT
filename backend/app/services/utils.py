from __future__ import annotations

import math
import re
from datetime import datetime
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

COMPANY_PREFIX_PATTERN = re.compile(r"^(?:\(주\)|㈜|주식회사|\(재\)|재단법인|\(영\)|영농조합법인)\s*")
PHONE_PATTERN = re.compile(r"(?:0\d{1,2}[-. ]?\d{3,4}[-. ]?\d{4})")
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
MONEY_PATTERN = re.compile(r"(?<!\d)(\d{1,3}(?:,\d{3})+|\d{4,})\s*원?")

DEFAULT_ALIASES: dict[str, list[str]] = {
    "현수막": ["현수막", "플래카드", "게릴라 현수막", "게시대 현수막"],
    "육교현수막": ["육교 현수막", "육교 광고", "대형 현수막"],
    "배너": ["배너", "배너기", "x배너", "롤업배너", "실내용 배너"],
    "친환경배너": ["친환경 배너", "에코 배너", "무독성 배너"],
    "어깨띠": ["어깨띠", "행사용 어깨띠", "선거 어깨띠"],
    "사원증": ["사원증", "id카드", "아이디카드", "출입증", "명찰"],
    "인포그래픽": ["인포그래픽", "정보그래픽", "시각화 패널"],
    "책제본": ["책제본", "제본", "무선제본", "중철제본", "책자"],
    "명함": ["명함", "비즈니스카드", "네임카드"],
    "전단지": ["전단지", "전단", "낱장 홍보물", "leaflet"],
    "포스터": ["포스터", "벽보", "홍보 포스터"],
    "리플릿": ["리플릿", "리플렛", "접지물", "2단접지", "3단접지", "브로슈어"],
    "카다로그": ["카다로그", "카탈로그", "브로셔", "제품책자", "홍보책자"],
    "옵셋봉투": ["옵셋봉투", "봉투", "대봉투", "소봉투", "각대봉투", "서류봉투"],
    "상장지": ["상장지", "상장용지", "수료증 용지", "인증서 용지"],
    "양식지": ["양식지", "서식지", "신청서", "전표", "ncr지"],
    "골지,허니콤보드": ["골지", "허니콤보드", "허니컴보드", "보드패널", "전시보드"],
    "포맥스,아크릴": ["포맥스", "폼보드", "아크릴", "아크릴판", "안내판"],
}


def decode_mime_text(value: str | None) -> str:
    if not value:
        return ""
    parts: list[str] = []
    for fragment, charset in decode_header(value):
        if isinstance(fragment, bytes):
            for encoding in (charset, "utf-8", "cp949", "euc-kr"):
                if not encoding:
                    continue
                try:
                    parts.append(fragment.decode(encoding))
                    break
                except (LookupError, UnicodeDecodeError):
                    continue
            else:
                parts.append(fragment.decode("utf-8", errors="replace"))
        else:
            parts.append(fragment)
    return "".join(parts).strip()


def parse_address(value: str | None) -> tuple[str, str]:
    name, address = parseaddr(decode_mime_text(value))
    return decode_mime_text(name), address.strip().lower()


def parse_email_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed
    except (TypeError, ValueError, OverflowError):
        return None


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "head", "meta", "link", "noscript", "svg"]):
        tag.decompose()
    lines: list[str] = []
    last = None
    for raw in soup.get_text(separator="\n").splitlines():
        cleaned = " ".join(raw.strip().split())
        if cleaned and cleaned != last:
            lines.append(cleaned)
            last = cleaned
    return "\n".join(lines)


def sanitize_filename(value: str, max_length: int = 80) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", value or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(". ")
    return (cleaned or "unnamed")[:max_length]


def normalize_customer_name(value: str | None) -> str:
    if not value:
        return ""
    text = value.replace("귀하", "").strip()
    previous = None
    while previous != text:
        previous = text
        text = COMPANY_PREFIX_PATTERN.sub("", text).strip()
    text = re.sub(r"[\s()（）·ㆍ.,_-]+", "", text).lower()
    return text


def normalize_product_name(value: str | None, aliases: dict[str, list[str]] | None = None) -> str:
    if not value:
        return ""
    aliases = aliases or DEFAULT_ALIASES
    lowered = re.sub(r"\s+", " ", value.strip().lower())
    matches: list[tuple[int, str]] = []
    for standard, terms in aliases.items():
        for term in terms:
            term_l = term.lower()
            if term_l in lowered:
                matches.append((len(term_l), standard))
    if matches:
        return max(matches)[1]
    first = re.split(r"[\n(/,]", value.strip(), maxsplit=1)[0]
    return first[:100]


def extract_email(value: str | None) -> str | None:
    if not value:
        return None
    match = EMAIL_PATTERN.search(value)
    return match.group(0).lower() if match else None


def extract_phone(value: str | None) -> str | None:
    if not value:
        return None
    match = PHONE_PATTERN.search(value)
    return re.sub(r"[. ]", "-", match.group(0)) if match else None


def safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if math.isnan(value) if isinstance(value, float) else False:
            return None
        return int(round(value))
    text = str(value).replace(",", "").replace("원", "").strip()
    try:
        return int(float(text))
    except ValueError:
        return None


def safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


def parse_dimensions(text: str | None) -> tuple[float | None, float | None, str | None]:
    if not text:
        return None, None, None
    normalized = (
        text.lower()
        .replace("㎜", "mm")
        .replace("㎝", "cm")
        .replace("×", "x")
        .replace("*", "x")
        .replace("Ｘ", "x")
    )
    size_match = re.search(r"\b(a[0-9]|b[0-9])\b", normalized, re.I)
    size_name = size_match.group(1).upper() if size_match else None

    pattern = re.compile(
        r"(?P<w>\d+(?:\.\d+)?)\s*(?P<wu>mm|cm|m)?\s*x\s*"
        r"(?P<h>\d+(?:\.\d+)?)\s*(?P<hu>mm|cm|m)?",
        re.I,
    )
    match = pattern.search(normalized)
    if not match:
        return None, None, size_name

    def to_mm(number: str, unit: str | None, paired_unit: str | None) -> float:
        actual = unit or paired_unit or "mm"
        value = float(number)
        if actual == "m":
            return value * 1000
        if actual == "cm":
            return value * 10
        return value

    width = to_mm(match.group("w"), match.group("wu"), match.group("hu"))
    height = to_mm(match.group("h"), match.group("hu"), match.group("wu"))
    return width, height, size_name


def extract_quantity(text: str | None) -> tuple[float | None, str | None]:
    if not text:
        return None, None
    patterns = [
        r"(?:수량\s*[:：]?\s*)?(\d+(?:\.\d+)?)\s*(개|장|부|매|갑|곽|세트|권|조)",
        r"(\d+(?:\.\d+)?)\s*(개|장|부|매|갑|곽|세트|권|조)\s*(?:제작|인쇄|요청)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return float(match.group(1)), match.group(2)
    return None, None


def compact_text(value: str | None, limit: int = 500) -> str:
    if not value:
        return ""
    text = re.sub(r"\s+", " ", value).strip()
    return text[:limit]


def relative_path(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path.resolve())
