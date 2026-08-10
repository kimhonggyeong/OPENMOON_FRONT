from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Literal

try:
    from openai import OpenAI
except ImportError:
    # OpenAI 키 없이 규칙 기반 분석만 사용하는 경우를 지원한다.
    OpenAI = None  # type: ignore[assignment]

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..config import Settings
from ..enums import AttachmentStatus, EvidenceSource, MailStatus
from ..models import Mail, MailItem
from .attachment_service import IMAGE_EXTENSIONS, compact_attachment_context
from .customer_matcher import find_or_create_customer
from .price_service import load_alias_map, resolve_standard_product
from .utils import (
    DEFAULT_ALIASES,
    extract_phone,
    extract_quantity,
    parse_dimensions,
)


# =========================================================
# 분석 분류 타입
# =========================================================

MailCategory = Literal[
    "order",
    "quotation_request",
    "advertisement",
    "inquiry",
    "shipping",
    "payment",
    "other",
]


# =========================================================
# 내부 분석 결과 모델
# =========================================================

class LLMOrderItem(BaseModel):
    product_name: str

    specification: str | None = None

    width_mm: float | None = None
    height_mm: float | None = None
    size_name: str | None = None

    quantity: float | None = None
    unit: str | None = None

    paper: str | None = None
    print_sides: str | None = None
    material: str | None = None

    unit_price: int | None = None
    amount: int | None = None

    detail_text: str | None = None
    schedule_note: str | None = None
    design_request: str | None = None

    evidence: dict[str, str] = Field(
        default_factory=dict
    )


class LLMMailAnalysis(BaseModel):
    # 기존 YullinMoon_Ver3.py 방식의 단일 분류
    category: MailCategory

    # 주문·견적·시안 등 견적 업무 대상으로 볼 것인지
    is_order_related: bool

    confidence: float = Field(
        ge=0,
        le=1,
    )

    customer_organization: str | None = None
    customer_department: str | None = None
    customer_name: str | None = None
    customer_phone: str | None = None
    customer_email: str | None = None

    delivery_place: str | None = None
    payment_terms: str | None = None
    requested_date: str | None = None

    total_amount: int | None = None

    items: list[LLMOrderItem] = Field(
        default_factory=list
    )

    summary: str
    reason: str

    missing_information: list[str] = Field(
        default_factory=list
    )


# =========================================================
# OpenAI Structured Output 전용 모델
# =========================================================

class StructuredEvidence(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )

    field_name: str

    source: Literal[
        "CURRENT_MAIL",
        "ATTACHMENT",
        "UNKNOWN",
    ]


class StructuredLLMOrderItem(BaseModel):
    """
    OpenAI strict JSON Schema에서는 모든 필드를 required로 두고,
    값이 없을 수 있는 필드는 nullable로 선언한다.
    """

    model_config = ConfigDict(
        extra="forbid"
    )

    product_name: str

    specification: str | None

    width_mm: float | None
    height_mm: float | None
    size_name: str | None

    quantity: float | None
    unit: str | None

    paper: str | None
    print_sides: str | None
    material: str | None

    unit_price: int | None
    amount: int | None

    detail_text: str | None
    schedule_note: str | None
    design_request: str | None

    evidence: list[StructuredEvidence]


class StructuredLLMMailAnalysis(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )

    category: MailCategory

    is_order_related: bool

    confidence: float = Field(
        ge=0,
        le=1,
    )

    customer_organization: str | None
    customer_department: str | None
    customer_name: str | None
    customer_phone: str | None
    customer_email: str | None

    delivery_place: str | None
    payment_terms: str | None
    requested_date: str | None

    total_amount: int | None

    items: list[StructuredLLMOrderItem]

    summary: str
    reason: str

    missing_information: list[str]


# =========================================================
# Structured Output → 내부 모델 변환
# =========================================================

def _convert_structured_analysis(
    parsed: StructuredLLMMailAnalysis,
) -> LLMMailAnalysis:
    items: list[LLMOrderItem] = []

    for item in parsed.items:
        evidence = {
            entry.field_name: entry.source
            for entry in item.evidence
        }

        items.append(
            LLMOrderItem(
                product_name=item.product_name,
                specification=item.specification,
                width_mm=item.width_mm,
                height_mm=item.height_mm,
                size_name=item.size_name,
                quantity=item.quantity,
                unit=item.unit,
                paper=item.paper,
                print_sides=item.print_sides,
                material=item.material,
                unit_price=item.unit_price,
                amount=item.amount,
                detail_text=item.detail_text,
                schedule_note=item.schedule_note,
                design_request=item.design_request,
                evidence=evidence,
            )
        )

    analysis = LLMMailAnalysis(
        category=parsed.category,
        is_order_related=parsed.is_order_related,
        confidence=parsed.confidence,
        customer_organization=parsed.customer_organization,
        customer_department=parsed.customer_department,
        customer_name=parsed.customer_name,
        customer_phone=parsed.customer_phone,
        customer_email=parsed.customer_email,
        delivery_place=parsed.delivery_place,
        payment_terms=parsed.payment_terms,
        requested_date=parsed.requested_date,
        total_amount=parsed.total_amount,
        items=items,
        summary=parsed.summary,
        reason=parsed.reason,
        missing_information=list(
            parsed.missing_information
        ),
    )

    normalize_order_related(analysis)

    return analysis


# =========================================================
# category → 현재 웹 프로젝트 필드 변환
# =========================================================

def category_to_request_types(
    analysis: LLMMailAnalysis,
) -> list[str]:
    """
    기존 프로그램의 category를 현재 웹 프로젝트의
    request_types 형식으로 변환한다.
    """

    mapping: dict[str, list[str]] = {
        "order": ["production"],
        "quotation_request": ["quotation"],
        "advertisement": ["advertisement"],
        "inquiry": ["inquiry"],
        "shipping": ["delivery"],
        "payment": ["payment"],
        "other": ["other"],
    }

    request_types = list(
        mapping.get(
            analysis.category,
            ["other"],
        )
    )

    # 메일에 시안 관련 요청이 명확하면 추가한다.
    combined_text = " ".join(
        filter(
            None,
            [
                analysis.summary,
                analysis.reason,
                *[
                    item.detail_text
                    for item in analysis.items
                    if item.detail_text
                ],
                *[
                    item.design_request
                    for item in analysis.items
                    if item.design_request
                ],
            ],
        )
    )

    if "시안" in combined_text:
        request_types.append("design_draft")

    if any(
        word in combined_text
        for word in (
            "수정",
            "변경",
            "교체",
        )
    ):
        request_types.append("revision")

    return list(
        dict.fromkeys(request_types)
    )


def category_to_commitment_status(
    analysis: LLMMailAnalysis,
) -> str:
    """
    기존 category를 현재 웹 프로젝트의
    commitment_status 형식으로 변환한다.
    """

    if analysis.category == "order":
        return "confirmed"

    if analysis.category == "quotation_request":
        return "unconfirmed"

    return "unclear"


# =========================================================
# 주문 관련 여부 보정
# =========================================================

def normalize_order_related(
    analysis: LLMMailAnalysis,
) -> None:
    """
    GPT가 category와 is_order_related를 서로 모순되게
    반환했을 때 프로그램 규칙으로 보정한다.

    견적 요청, 제작 문의, 시안 요청도 품목이 있으면
    견적 업무 대상으로 본다.
    """

    excluded_categories = {
        "advertisement",
        "shipping",
        "payment",
        "other",
    }

    if analysis.category in excluded_categories:
        analysis.is_order_related = False
        return

    if (
        analysis.category
        in {
            "order",
            "quotation_request",
            "inquiry",
        }
        and analysis.items
    ):
        analysis.is_order_related = True


def resolve_customer_organization(
    analysis: LLMMailAnalysis,
    subject: str,
    seller_names: set[str],
) -> str | None:
    """YullinMoon_Ver3.py의 견적서 수신 기관 보정 규칙을 웹 저장 전에 적용한다."""
    organization = (
        analysis.customer_organization or ""
    ).strip()

    normalized_sellers = {
        name.replace(" ", "").replace("(주)", "").replace("주식회사", "")
        for name in seller_names
    }

    if organization:
        normalized = organization.replace(" ", "").replace("(주)", "").replace("주식회사", "")
        if normalized not in normalized_sellers:
            department = (analysis.customer_department or "").strip()
            if department and department not in organization and organization in {"아산시", "아산시청"}:
                return f"{organization} {department}"
            return organization

    bracket = re.search(r"\[([^\]]+)\]", subject)
    if bracket:
        candidate = bracket.group(1).strip()
        normalized = candidate.replace(" ", "").replace("(주)", "").replace("주식회사", "")
        if normalized not in normalized_sellers:
            return candidate

    # 관공서 메일은 기관 대신 '여성복지과' 같은 부서만 반환되는 경우가 많다.
    # 원본 프로그램이 견적서 수신처로 사용하던 값을 기관 필드에도 보존한다.
    if analysis.customer_department:
        return analysis.customer_department.strip()

    return analysis.customer_name


def normalize_products_for_original_engine(
    analysis: LLMMailAnalysis,
    subject: str,
) -> None:
    """원본 Python이 사용한 품목 표현으로 최소한의 결정적 보정을 한다."""
    for item in analysis.items:
        product = item.product_name.strip()
        if product in {"출력물", "출력", "대형 출력물"}:
            item.product_name = "인쇄물"
        elif (
            "부스" in subject
            and "그래픽" in subject
            and product.lower() in {"tower", "counter", "타워", "카운터", "타워 하단 전시대"}
        ):
            item.product_name = f"박람회 부스 그래픽 디자인 - {product}"


# =========================================================
# 이미지 데이터 URL 생성
# =========================================================

def _image_data_url(
    path: Path,
) -> str:
    media_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(
        path.suffix.lower(),
        "image/png",
    )

    encoded = base64.b64encode(
        path.read_bytes()
    ).decode("ascii")

    return (
        f"data:{media_type};"
        f"base64,{encoded}"
    )


def _pdf_page_data_urls(
    path: Path,
    max_pages: int = 2,
) -> list[str]:
    """
    텍스트가 없는 스캔 PDF의 앞쪽 페이지를
    이미지로 변환해 OpenAI Vision에 전달한다.
    """

    try:
        import fitz
    except ImportError:
        return []

    urls: list[str] = []

    document = fitz.open(path)

    try:
        for page_index in range(
            min(
                len(document),
                max_pages,
            )
        ):
            page = document.load_page(
                page_index
            )

            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(
                    1.5,
                    1.5,
                ),
                alpha=False,
            )

            encoded = base64.b64encode(
                pixmap.tobytes("png")
            ).decode("ascii")

            urls.append(
                "data:image/png;base64,"
                + encoded
            )

    finally:
        document.close()

    return urls


# =========================================================
# GPT 시스템 프롬프트
# =========================================================

def _system_prompt() -> str:
    return """
당신은 디자인·인쇄 업체 "(주)열린문디자인"의 주문 메일 분석 AI입니다.

메일 본문, 전달된 원본 고객 메일, 첨부파일 내용을 구분하여 분석합니다.

판매자는 다음 명칭을 사용합니다.

- 열린문디자인
- (주)열린문디자인
- 주식회사 열린문디자인

위 판매자 명칭은 고객 기관으로 반환하지 마세요.

반드시 메일이나 첨부파일에서 직접 확인되는 내용만 반환하세요.
메일에 없는 규격, 수량, 단가, 금액, 기관명, 담당자 정보는 추측하지 마세요.

분류 기준은 다음과 같습니다.

order:
- 고객이 제작, 발주 또는 주문 진행을 확정적으로 요청함
- "제작해주세요", "진행해주세요", "주문합니다", "발주합니다" 등이 확인됨
- 단순 견적 문의가 아니라 실제 작업 진행 의사가 확인됨

quotation_request:
- 견적, 가격 또는 단가를 요청함
- 제작 진행이 아직 확정되지 않음

advertisement:
- 할인, 프로모션, 이벤트, 뉴스레터, 가입 유도 등 광고성 메일
- 광고는 절대 주문이나 견적 요청으로 분류하지 않음

inquiry:
- 제작 가능 여부, 인쇄 가능 여부, 시안 가능 여부 등 일반 문의
- 주문 확정이나 견적 요청 여부가 명확하지 않음

shipping:
- 배송, 출고, 운송장, 납품 상태와 관련된 메일

payment:
- 결제, 입금, 세금계산서, 영수증과 관련된 메일

other:
- 위 분류에 해당하지 않는 메일

is_order_related 규칙:

1. order이면서 품목이 있으면 true
2. quotation_request이면서 품목이 있으면 true
3. 제작·인쇄·시안 관련 inquiry이면서 품목이 있으면 true
4. advertisement, shipping, payment, other는 false
5. 확정 주문만 true라는 뜻이 아님
6. 견적서 초안 작성 대상으로 검토할 수 있는 메일이면 true

품목 분석 규칙:

1. 여러 품목은 하나로 합치지 말고 각각 분리합니다.
2. 제품명은 product_name에 입력합니다.
3. 크기·규격·용지·재질·색상·후가공은 specification에 입력합니다.
4. 가로·세로가 확인되면 mm로 변환하여 width_mm와 height_mm에 입력합니다.
5. 수량을 확인할 수 없으면 quantity는 null입니다.
6. 단가와 금액은 메일에 직접 적혀 있을 때만 반환합니다.
7. 단가표 또는 과거 견적 가격을 추측하여 넣지 않습니다.
8. 현수막 문구, 인쇄 문구 등은 detail_text에 입력합니다.
9. 디자인 변경 및 시안 요구는 design_request에 입력합니다.
10. 납품·배송·시공·철거·방문수령 일정은 schedule_note에 입력합니다.
11. "지난번처럼", "작년 것처럼"은 현재 규격이 아니므로 누락 정보에 기록합니다.
12. 품목별 evidence에는 각 필드의 근거 출처를 기록합니다.

evidence 형식:

[
  {
    "field_name": "product_name",
    "source": "CURRENT_MAIL"
  }
]

source는 다음 값만 사용합니다.

- CURRENT_MAIL
- ATTACHMENT
- UNKNOWN

고객 정보 규칙:

1. customer_organization은 주문을 보낸 고객 측 회사·기관입니다.
2. 메일 제목의 "[충남연구원]" 같은 대괄호 기관명을 우선 확인합니다.
3. 발신자 서명, 부서, 이메일 도메인도 참고할 수 있습니다.
4. customer_email은 실제 고객 발신자 이메일을 사용할 수 있습니다.
5. 수신자에 있는 열린문디자인은 고객 기관이 아닙니다.
6. 기관명을 확정할 수 없으면 null로 반환합니다.

reason은 반드시 메일 원문의 어떤 표현을 근거로 판단했는지 구체적으로 작성합니다.
summary는 메일의 핵심 요청을 간결하게 작성합니다.
missing_information에는 견적 작성에 필요하지만 확인되지 않은 정보를 기록합니다.
""".strip()


# =========================================================
# GPT 사용자 프롬프트
# =========================================================

def _user_prompt(
    mail: Mail,
    attachment_context: str,
    max_length: int,
) -> str:
    return f"""
다음 고객 이메일을 분석하세요.

[실제 고객 메일]

보낸 사람:
{mail.original_sender_name or ""} <{mail.original_sender_email or ""}>

받는 사람:
{mail.original_recipient or ""}

발송 시각:
{mail.original_sent_at or ""}

제목:
{mail.original_subject or mail.outer_subject or ""}

본문:
{(mail.original_body or "")[:max_length]}

[첨부파일에서 추출한 내용]

{attachment_context or "텍스트로 추출된 내용 없음"}

[분석 목표]

1. order, quotation_request, advertisement, inquiry, shipping, payment, other 중 하나로 분류
2. 견적 업무 검토 대상인지 is_order_related 판단
3. 고객 기관, 부서, 담당자, 연락처 식별
4. 여러 품목이 있으면 각각 분리
5. 품목별 규격, 크기, 수량, 재질, 용지, 인쇄면 분석
6. 디자인 문구와 일정 정보를 별도 필드로 분리
7. 누락 정보를 명확하게 기록
8. 원문에 없는 가격은 절대 생성하지 않기
""".strip()


# =========================================================
# OpenAI 호출
# =========================================================

def _call_openai(
    settings: Settings,
    mail: Mail,
    attachment_context: str,
) -> LLMMailAnalysis:
    if OpenAI is None:
        raise RuntimeError(
            "openai 패키지가 설치되지 않았습니다. "
            "pip install -r requirements.txt를 실행하세요."
        )

    client = OpenAI(
        api_key=settings.openai_api_key
    )

    content: list[dict] = [
        {
            "type": "input_text",
            "text": _user_prompt(
                mail,
                attachment_context,
                settings.max_llm_body_length,
            ),
        }
    ]

    vision_attachments = []

    if settings.analyze_images:
        for attachment in mail.attachments:
            path = Path(
                attachment.saved_path
            )

            if not path.exists():
                continue

            urls: list[str] = []

            if (
                path.suffix.lower()
                in IMAGE_EXTENSIONS
            ):
                urls = [
                    _image_data_url(path)
                ]

            elif (
                path.suffix.lower() == ".pdf"
                and attachment.status
                == AttachmentStatus.IMAGE_PENDING
            ):
                urls = _pdf_page_data_urls(
                    path
                )

            for url in urls:
                content.append(
                    {
                        "type": "input_image",
                        "image_url": url,
                    }
                )

                if (
                    attachment
                    not in vision_attachments
                ):
                    vision_attachments.append(
                        attachment
                    )

                # 텍스트 1개 + 이미지 최대 4개
                if len(content) >= 5:
                    break

            if len(content) >= 5:
                break

    try:
        # 최신 Responses API
        response = client.responses.parse(
            model=settings.openai_model,
            input=[
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": _system_prompt(),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": content,
                },
            ],
            text_format=StructuredLLMMailAnalysis,
        )

        parsed = response.output_parsed

        if parsed is None:
            raise RuntimeError(
                "OpenAI structured output이 비어 있습니다."
            )

        for attachment in vision_attachments:
            attachment.status = (
                AttachmentStatus.EXTRACTED
            )

            attachment.analysis_summary = (
                "OpenAI 비전 분석에 반영됨"
            )

        return _convert_structured_analysis(
            parsed
        )

    except (AttributeError, TypeError):
        # 구버전 SDK용 Chat Completions 폴백
        response = (
            client
            .beta
            .chat
            .completions
            .parse(
                model=settings.openai_model,
                temperature=0,
                messages=[
                    {
                        "role": "system",
                        "content": _system_prompt(),
                    },
                    {
                        "role": "user",
                        "content": _user_prompt(
                            mail,
                            attachment_context,
                            settings.max_llm_body_length,
                        ),
                    },
                ],
                response_format=(
                    StructuredLLMMailAnalysis
                ),
            )
        )

        parsed = (
            response
            .choices[0]
            .message
            .parsed
        )

        if parsed is None:
            raise RuntimeError(
                "OpenAI structured output이 비어 있습니다."
            )

        return _convert_structured_analysis(
            parsed
        )


# =========================================================
# OpenAI 미사용 또는 실패 시 규칙 기반 분석
# =========================================================

def _fallback_analysis(
    session: Session,
    mail: Mail,
    attachment_context: str,
) -> LLMMailAnalysis:
    subject = (
        mail.original_subject
        or mail.outer_subject
        or ""
    )

    body = (
        mail.original_body
        or ""
    )

    text = (
        f"{subject}\n"
        f"{body}\n"
        f"{attachment_context}"
    )

    alias_map = (
        load_alias_map(session)
        or DEFAULT_ALIASES
    )

    detected: list[str] = []

    for standard, aliases in alias_map.items():
        if any(
            alias.lower() in text.lower()
            for alias in aliases
        ):
            detected.append(
                standard
            )

    detected = list(
        dict.fromkeys(detected)
    )

    dimension_pattern = re.compile(
        r"\d+(?:\.\d+)?\s*"
        r"(?:mm|cm|m|㎜|㎝)?\s*"
        r"[x×*]\s*"
        r"\d+(?:\.\d+)?\s*"
        r"(?:mm|cm|m|㎜|㎝)?",
        re.I,
    )

    dimension_matches = list(
        dimension_pattern.finditer(text)
    )

    items: list[LLMOrderItem] = []

    # 한 품목에 여러 규격이 존재하는 경우
    if (
        len(detected) == 1
        and dimension_matches
    ):
        product = detected[0]

        seen: set[
            tuple[
                float | None,
                float | None,
                float | None,
            ]
        ] = set()

        lines = text.splitlines()

        for line_index, line in enumerate(
            lines
        ):
            for match in dimension_pattern.finditer(
                line
            ):
                dimension_text = match.group(0)

                width, height, size_name = (
                    parse_dimensions(
                        dimension_text
                    )
                )

                trailing = line[
                    match.end():
                ]

                if (
                    line_index + 1 < len(lines)
                    and lines[
                        line_index + 1
                    ].strip()
                    in {
                        "개",
                        "장",
                        "부",
                        "매",
                        "세트",
                        "곽",
                    }
                ):
                    trailing += (
                        " "
                        + lines[
                            line_index + 1
                        ].strip()
                    )

                quantity_match = re.search(
                    r"(?:[x×*]\s*)?"
                    r"(\d+(?:\.\d+)?)\s*"
                    r"(개|장|부|매|세트|곽)",
                    trailing,
                    re.I,
                )

                quantity = (
                    float(
                        quantity_match.group(1)
                    )
                    if quantity_match
                    else None
                )

                unit = (
                    quantity_match.group(2)
                    if quantity_match
                    else None
                )

                key = (
                    width,
                    height,
                    quantity,
                )

                if key in seen:
                    continue

                seen.add(key)

                items.append(
                    LLMOrderItem(
                        product_name=product,
                        specification=dimension_text,
                        width_mm=width,
                        height_mm=height,
                        size_name=size_name,
                        quantity=quantity,
                        unit=unit,
                        evidence={
                            "product_name": (
                                EvidenceSource
                                .CURRENT_MAIL
                            ),
                            "specification": (
                                EvidenceSource
                                .CURRENT_MAIL
                            ),
                            "quantity": (
                                EvidenceSource
                                .CURRENT_MAIL
                                if quantity is not None
                                else EvidenceSource.UNKNOWN
                            ),
                        },
                    )
                )

    else:
        for index, product in enumerate(
            detected
        ):
            dimension_text = (
                dimension_matches[index].group(0)
                if index < len(
                    dimension_matches
                )
                else None
            )

            width, height, size_name = (
                parse_dimensions(
                    dimension_text or text
                )
            )

            quantity, unit = (
                extract_quantity(text)
            )

            items.append(
                LLMOrderItem(
                    product_name=product,
                    specification=dimension_text,
                    width_mm=width,
                    height_mm=height,
                    size_name=size_name,
                    quantity=quantity,
                    unit=unit,
                    evidence={
                        "product_name": (
                            EvidenceSource
                            .CURRENT_MAIL
                        ),
                        "specification": (
                            EvidenceSource
                            .CURRENT_MAIL
                            if dimension_text
                            else EvidenceSource.UNKNOWN
                        ),
                        "quantity": (
                            EvidenceSource
                            .CURRENT_MAIL
                            if quantity is not None
                            else EvidenceSource.UNKNOWN
                        ),
                    },
                )
            )

    lowered = text.lower()

    advertisement_words = (
        "광고",
        "프로모션",
        "이벤트",
        "할인",
        "뉴스레터",
        "수신거부",
        "무료체험",
        "가입",
    )

    payment_words = (
        "입금",
        "결제",
        "세금계산서",
        "영수증",
    )

    shipping_words = (
        "운송장",
        "배송조회",
        "출고",
        "배송 상태",
    )

    order_words = (
        "제작해주세요",
        "제작해 주세요",
        "진행해주세요",
        "진행해 주세요",
        "주문합니다",
        "발주합니다",
        "제작 요청드립니다",
        "제작 부탁드립니다",
    )

    quotation_words = (
        "견적",
        "단가",
        "가격",
        "금액",
    )

    production_words = (
        "제작",
        "인쇄",
        "시안",
        "출력",
    )

    category: MailCategory

    if any(
        word in lowered
        for word in advertisement_words
    ):
        category = "advertisement"

    elif any(
        word in lowered
        for word in payment_words
    ):
        category = "payment"

    elif any(
        word in lowered
        for word in shipping_words
    ):
        category = "shipping"

    elif any(
        word in lowered
        for word in order_words
    ):
        category = "order"

    elif any(
        word in lowered
        for word in quotation_words
    ):
        category = "quotation_request"

    elif any(
        word in lowered
        for word in production_words
    ):
        category = "inquiry"

    else:
        category = "other"

    organization = None

    bracket_match = re.search(
        r"\[([^\]]+)\]",
        subject,
    )

    if bracket_match:
        candidate = (
            bracket_match
            .group(1)
            .strip()
        )

        if candidate not in {
            "열린문디자인",
            "(주)열린문디자인",
            "주식회사 열린문디자인",
        }:
            organization = candidate

    missing: list[str] = []

    for item in items:
        if item.quantity is None:
            missing.append(
                f"{item.product_name} 수량"
            )

        if (
            item.product_name
            in {
                "현수막",
                "육교현수막",
                "배너",
                "친환경배너",
                "포맥스,아크릴",
                "골지,허니콤보드",
            }
            and (
                item.width_mm is None
                or item.height_mm is None
            )
        ):
            missing.append(
                f"{item.product_name} 규격"
            )

    if not items:
        missing.append("품목")

    reference_words = (
        "지난번",
        "저번",
        "작년",
        "이전처럼",
        "전에 했던",
        "그때처럼",
    )

    if any(
        word in text
        for word in reference_words
    ):
        missing.append(
            "이전 제작 이력 확인"
        )

    is_order_related = (
        bool(items)
        and category
        in {
            "order",
            "quotation_request",
            "inquiry",
        }
    )

    return LLMMailAnalysis(
        category=category,
        is_order_related=is_order_related,
        confidence=0.55,
        customer_organization=organization,
        customer_name=(
            mail.original_sender_name
        ),
        customer_email=(
            mail.original_sender_email
        ),
        customer_phone=extract_phone(
            body
        ),
        total_amount=None,
        items=items,
        summary=(
            subject[:200]
            or "메일 내용 분석"
        ),
        reason=(
            "OpenAI를 사용하지 못해 "
            "제목·본문의 키워드와 정규식으로 "
            "분류 및 품목 분석을 수행했습니다."
        ),
        missing_information=list(
            dict.fromkeys(missing)
        ),
    )


# =========================================================
# 메일 분석 실행 및 DB 저장
# =========================================================

def analyze_mail(
    session: Session,
    settings: Settings,
    mail: Mail,
) -> Mail:
    mail.status = MailStatus.ANALYZING
    mail.error_message = None

    session.commit()

    attachment_context = (
        compact_attachment_context(
            mail.attachments
        )
    )

    # 대화에서 사람이 확정한 동일 고객의 과거 판단을 다음 분석의
    # 참고 자료로 제공한다. 현재 메일의 명시적 내용보다 우선하지 않는다.
    from .learning_service import learning_context
    learned_context = learning_context(session, mail)
    if learned_context:
        attachment_context = "\n\n".join(
            part for part in (attachment_context, learned_context) if part
        )

    try:
        if settings.openai_api_key:
            try:
                analysis = _call_openai(
                    settings,
                    mail,
                    attachment_context,
                )

            except Exception as openai_error:
                analysis = _fallback_analysis(
                    session,
                    mail,
                    attachment_context,
                )

                analysis.reason = (
                    "OpenAI 분석 실패"
                    f"({type(openai_error).__name__})로 "
                    "규칙 기반 분석을 사용했습니다. "
                    + analysis.reason
                )

                analysis.missing_information = list(
                    dict.fromkeys(
                        [
                            *analysis.missing_information,
                            "AI 분석 결과 수동 검토",
                        ]
                    )
                )

                mail.error_message = (
                    "OpenAI warning: "
                    f"{type(openai_error).__name__}: "
                    f"{openai_error}"
                )[:2000]

        else:
            analysis = _fallback_analysis(
                session,
                mail,
                attachment_context,
            )

        normalize_order_related(
            analysis
        )

        analysis.customer_organization = resolve_customer_organization(
            analysis,
            mail.original_subject or mail.outer_subject or "",
            settings.seller_name_set,
        )
        normalize_products_for_original_engine(
            analysis,
            mail.original_subject or mail.outer_subject or "",
        )

        request_types = (
            category_to_request_types(
                analysis
            )
        )

        commitment_status = (
            category_to_commitment_status(
                analysis
            )
        )

        # -------------------------------------------------
        # Mail 기본 분석 정보 저장
        # -------------------------------------------------

        mail.customer_organization = (
            analysis.customer_organization
        )

        mail.customer_department = (
            analysis.customer_department
        )

        mail.customer_name = (
            analysis.customer_name
        )

        mail.customer_phone = (
            analysis.customer_phone
        )

        mail.customer_email = (
            analysis.customer_email
            or mail.original_sender_email
        )

        mail.delivery_place = (
            analysis.delivery_place
        )

        mail.payment_terms = (
            analysis.payment_terms
        )

        mail.requested_date = (
            analysis.requested_date
        )

        mail.request_types = (
            request_types
        )

        mail.commitment_status = (
            commitment_status
        )

        mail.confidence = (
            analysis.confidence
        )

        mail.summary = (
            analysis.summary
        )

        mail.reason = (
            analysis.reason
        )

        mail.missing_information = (
            analysis.missing_information
        )

        # category, is_order_related, total_amount는
        # 별도 DB 컬럼을 추가하지 않고 JSON에 보존한다.
        mail.analysis_payload = {
            **analysis.model_dump(
                mode="json"
            ),
            "request_types": request_types,
            "commitment_status": (
                commitment_status
            ),
        }

        # -------------------------------------------------
        # 고객 정보 연결
        # -------------------------------------------------

        customer = find_or_create_customer(
            session,
            analysis.customer_organization,
            email=mail.customer_email,
            phone=mail.customer_phone,
            contact_name=mail.customer_name,
        )

        mail.customer_id = (
            customer.id
            if customer
            else None
        )

        # -------------------------------------------------
        # 기존 품목 삭제 후 새 분석 품목 저장
        # -------------------------------------------------

        session.execute(
            delete(MailItem).where(
                MailItem.mail_id == mail.id
            )
        )

        for index, item in enumerate(
            analysis.items,
            start=1,
        ):
            normalized = (
                resolve_standard_product(
                    session,
                    item.product_name,
                )
            )

            width = item.width_mm
            height = item.height_mm
            size_name = item.size_name

            if (
                width is None
                or height is None
            ):
                (
                    parsed_width,
                    parsed_height,
                    parsed_size,
                ) = parse_dimensions(
                    item.specification
                )

                width = (
                    width
                    if width is not None
                    else parsed_width
                )

                height = (
                    height
                    if height is not None
                    else parsed_height
                )

                size_name = (
                    size_name
                    or parsed_size
                )

            session.add(
                MailItem(
                    mail_id=mail.id,
                    position=index,
                    product_name=(
                        item.product_name
                    ),
                    normalized_product=(
                        normalized
                    ),
                    specification=(
                        item.specification
                    ),
                    width_mm=width,
                    height_mm=height,
                    size_name=size_name,
                    quantity=item.quantity,
                    unit=item.unit,
                    paper=item.paper,
                    print_sides=(
                        item.print_sides
                    ),
                    material=item.material,
                    unit_price=(
                        item.unit_price
                    ),
                    amount=item.amount,
                    detail_text=(
                        item.detail_text
                    ),
                    schedule_note=(
                        item.schedule_note
                    ),
                    design_request=(
                        item.design_request
                    ),
                    evidence=(
                        item.evidence
                    ),
                )
            )

        session.commit()
        session.refresh(mail)

        return mail

    except Exception as error:
        session.rollback()

        failed_mail = session.get(
            Mail,
            mail.id,
        )

        if failed_mail is not None:
            failed_mail.status = (
                MailStatus.FAILED
            )

            failed_mail.error_message = (
                f"{type(error).__name__}: "
                f"{error}"
            )

            session.commit()

        raise
