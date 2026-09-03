from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(
        from_attributes=True
    )


# =========================================================
# 첨부파일
# =========================================================

class AttachmentOut(ORMModel):
    id: int

    filename: str
    content_type: str | None

    size_bytes: int
    status: str

    extracted_text: str | None = None
    analysis_summary: str | None = None
    error_message: str | None = None


# =========================================================
# 메일 품목
# =========================================================

class MailItemBase(BaseModel):
    product_name: str

    normalized_product: str | None = None
    specification: str | None = None

    width_mm: float | None = None
    height_mm: float | None = None
    size_name: str | None = None

    quantity: float | None = None
    unit: str | None = None

    paper: str | None = None
    print_sides: str | None = None
    material: str | None = None

    # 품목별 동적 사양. 예: {"마감처리": "타공", "시공여부": "시공"}
    spec_attributes: dict[str, Any] = Field(default_factory=dict)

    # 내부 제작 원가. 판매 단가(unit_price)와 별도로 관리한다.
    cost_price: int | None = None

    unit_price: int | None = None
    amount: int | None = None

    detail_text: str | None = None
    schedule_note: str | None = None
    design_request: str | None = None

    evidence: dict[str, Any] = Field(
        default_factory=dict
    )

    confirmed: bool = False


class MailItemOut(
    MailItemBase,
    ORMModel,
):
    id: int
    position: int


class MailItemUpdate(
    MailItemBase
):
    id: int | None = None


# =========================================================
# 검토 항목
# =========================================================

class ReviewIssueOut(ORMModel):
    id: int

    code: str
    field_name: str | None

    message: str
    severity: str

    suggestions: list[Any] = Field(
        default_factory=list
    )

    resolved: bool

    resolution_value: Any | None = None


# =========================================================
# 메일 목록
# =========================================================

class MailListOut(ORMModel):
    id: int

    status: str
    starred: bool = False
    hearted: bool = False
    heart_key: str

    outer_subject: str | None
    original_subject: str | None

    original_sender_name: str | None
    original_sender_email: str | None

    customer_organization: str | None

    outer_sent_at: datetime | None
    original_sent_at: datetime | None

    summary: str | None

    created_at: datetime


class MailStarUpdate(BaseModel):
    starred: bool


# =========================================================
# 메일 상세
# =========================================================

class MailDetailOut(MailListOut):
    forward_depth: int

    outer_sender_name: str | None
    outer_sender_email: str | None
    outer_recipient: str | None
    outer_body: str | None

    original_recipient: str | None
    original_body: str | None

    customer_department: str | None
    customer_name: str | None
    customer_phone: str | None
    customer_email: str | None

    delivery_place: str | None
    payment_terms: str | None
    requested_date: str | None

    request_types: list[str] = Field(
        default_factory=list
    )

    commitment_status: str | None

    confidence: float | None

    reason: str | None

    missing_information: list[str] = Field(
        default_factory=list
    )

    analysis_payload: dict[str, Any] = Field(
        default_factory=dict,
        exclude=True,
    )

    attachments: list[AttachmentOut] = Field(
        default_factory=list
    )

    items: list[MailItemOut] = Field(
        default_factory=list
    )

    reviews: list[ReviewIssueOut] = Field(
        default_factory=list
    )

    # -----------------------------------------------------
    # analysis_payload 내부 값을 API 필드로 노출
    # -----------------------------------------------------

    @computed_field
    @property
    def category(self) -> str | None:
        value = self.analysis_payload.get(
            "category"
        )

        return (
            str(value)
            if value is not None
            else None
        )

    @computed_field
    @property
    def is_order_related(self) -> bool:
        value = self.analysis_payload.get(
            "is_order_related"
        )

        if isinstance(value, bool):
            return value

        # 이전 데이터처럼 값이 없으면
        # 현재 필드 구조를 이용해 보정한다.
        return bool(
            self.items
            and any(
                request_type
                in {
                    "production",
                    "quotation",
                    "inquiry",
                    "design_draft",
                    "revision",
                }
                for request_type
                in self.request_types
            )
        )

    @computed_field
    @property
    def total_amount(self) -> int | None:
        value = self.analysis_payload.get(
            "total_amount"
        )

        if value is not None:
            try:
                return int(value)
            except (
                TypeError,
                ValueError,
            ):
                pass

        # 분석 당시 총액이 없다면 현재 품목 금액으로 계산한다.
        if (
            self.items
            and all(
                item.amount is not None
                for item in self.items
            )
        ):
            return sum(
                int(item.amount or 0)
                for item in self.items
            )

        return None


# =========================================================
# 분석 수정
# =========================================================

class AnalysisUpdate(BaseModel):
    customer_organization: str | None = None
    customer_department: str | None = None

    customer_name: str | None = None
    customer_phone: str | None = None
    customer_email: str | None = None

    delivery_place: str | None = None
    payment_terms: str | None = None
    requested_date: str | None = None

    request_types: list[str] = Field(
        default_factory=list
    )

    commitment_status: str | None = None

    summary: str | None = None
    reason: str | None = None

    items: list[MailItemUpdate] = Field(
        default_factory=list
    )


# =========================================================
# 검토 해결
# =========================================================

class ReviewResolveRequest(BaseModel):
    resolution_value: Any | None = None

    apply_to_field: bool = True


# =========================================================
# 현재 단가 후보
# =========================================================

class PriceCandidateOut(BaseModel):
    item_id: int
    item_index: int = 0

    product_name: str

    unit_price: int | None = None
    amount: int | None = None

    source: str = "unresolved"
    reference: str | None = None

    score: float = 0.0

    reason: str

    needs_review: bool = True

    # 기존 프론트 및 API 호환용 필드
    exact: bool = False

    source_sheet: str = ""
    source_cell: str = ""

    context: str | None = None
    vat: str | None = None

    automation_status: str | None = None

# =========================================================
# 과거 견적 후보
# =========================================================

class HistoryCandidateOut(BaseModel):
    quotation_id: int
    quotation_date: date | None

    customer_name: str

    product_name: str
    specification: str | None

    width_mm: float | None
    height_mm: float | None

    quantity: float | None

    unit_price: int | None
    amount: int | None

    source_file: str
    source_sheet: str


# =========================================================
# 견적서 초안
# =========================================================

class DraftItemOut(ORMModel):
    id: int
    position: int

    product_name: str
    specification: str | None
    spec_attributes: dict[str, Any] = Field(default_factory=dict)

    quantity: float | None
    unit: str | None

    cost_price: int | None
    unit_price: int | None
    amount: int | None

    note: str | None

    price_source: dict[str, Any] = Field(
        default_factory=dict
    )


class DraftOut(ORMModel):
    id: int
    mail_id: int

    status: str
    file_path: str

    customer_name: str

    total_amount: int | None

    email_subject: str | None
    email_body: str | None

    approved_at: datetime | None
    sent_at: datetime | None
    sent_to: str | None

    error_message: str | None

    items: list[DraftItemOut] = Field(
        default_factory=list
    )


class QuotationStorageCandidate(BaseModel):
    mode: Literal["existing", "department", "person", "separate"]
    filename: str
    file_type: str
    exists: bool
    path: str
    related: bool = True


class QuotationStorageOptions(BaseModel):
    root_path: str
    storage_notice: str | None = None
    selected_file: str | None = None
    existing_files: list[QuotationStorageCandidate] = Field(default_factory=list)
    new_files: list[QuotationStorageCandidate] = Field(default_factory=list)


class CreateQuotationRequest(BaseModel):
    mode: Literal["existing", "department", "person", "separate"]
    file_path: str


class UpdateQuotationEmailRequest(BaseModel):
    email_subject: str
    email_body: str | None = None
    email_recipients: list[str] | None = None

    @field_validator("email_recipients")
    @classmethod
    def validate_recipients(cls, value):
        from .services.email_recipients import normalize_recipients
        return normalize_recipients(value) if value is not None else None


class ApproveQuotationRequest(BaseModel):
    employee_key: Literal[
        "moon_jeongseon",
        "shin_woohyun",
        "kwon_jihye",
        "kim_heejung",
    ]


# =========================================================
# 가져오기
# =========================================================

class ImportRequest(BaseModel):
    path: str | None = None


class ImportResult(BaseModel):
    processed: int = 0
    imported: int = 0
    review_required: int = 0
    failed: int = 0

    message: str

    details: dict[str, Any] = Field(
        default_factory=dict
    )


# =========================================================
# 메일 동기화
# =========================================================

class MailSyncRequest(BaseModel):
    limit: int = Field(
        default=50,
        ge=1,
        le=500,
    )

    include_existing: bool = False


# =========================================================
# 이메일 미리보기
# =========================================================

class EmailPreview(BaseModel):
    subject: str
    body: str

    recipient: str | None
    recipients: list[str] = Field(default_factory=list)
    customer_recipient: str | None = None
    delivery_mode: str = "customer"
    attachment_path: str | None
    attachment_name: str | None = None


class OpenHistorySourceRequest(BaseModel):
    source_file: str
    source_sheet: str


# =========================================================
# 상태 확인
# =========================================================

class HealthOut(BaseModel):
    status: Literal["ok"] = "ok"

    database: str

    openai_configured: bool
    ai_configured: bool
    ai_provider: Literal["openai", "anthropic"]
    ai_model: str
    mail_configured: bool
    live_send_enabled: bool


class ChatMessageOut(ORMModel):
    id: int
    mail_id: int
    role: str
    content: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    action_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    user_message: ChatMessageOut
    assistant_message: ChatMessageOut
    mail: MailDetailOut
    draft_updated: bool = False


class GeneralChatMessageOut(ORMModel):
    id: int
    role: str
    content: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime


class GeneralChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class GeneralChatResponse(BaseModel):
    user_message: GeneralChatMessageOut
    assistant_message: GeneralChatMessageOut
