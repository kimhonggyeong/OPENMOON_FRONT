from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class Customer(TimestampMixin, Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)

    contacts: Mapped[list[CustomerContact]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
    mails: Mapped[list[Mail]] = relationship(back_populates="customer")
    quotations: Mapped[list[QuotationHistory]] = relationship(back_populates="customer")


class CustomerContact(TimestampMixin, Base):
    __tablename__ = "customer_contacts"
    __table_args__ = (UniqueConstraint("kind", "value", name="uq_contact_kind_value"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str | None] = mapped_column(String(100))

    customer: Mapped[Customer] = relationship(back_populates="contacts")


class Mail(TimestampMixin, Base):
    __tablename__ = "mails"
    __table_args__ = (
        UniqueConstraint("account", "uid", name="uq_mail_account_uid"),
        UniqueConstraint("message_id", name="uq_mail_message_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account: Mapped[str] = mapped_column(String(255), default="local")
    uid: Mapped[str] = mapped_column(String(100), default="")
    message_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    in_reply_to: Mapped[str | None] = mapped_column(String(500))
    references: Mapped[str | None] = mapped_column(Text)
    raw_path: Mapped[str | None] = mapped_column(Text)

    outer_sender_name: Mapped[str | None] = mapped_column(String(255))
    outer_sender_email: Mapped[str | None] = mapped_column(String(255))
    outer_recipient: Mapped[str | None] = mapped_column(Text)
    outer_subject: Mapped[str | None] = mapped_column(Text)
    outer_sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    outer_body: Mapped[str | None] = mapped_column(Text)

    original_sender_name: Mapped[str | None] = mapped_column(String(255))
    original_sender_email: Mapped[str | None] = mapped_column(String(255), index=True)
    original_recipient: Mapped[str | None] = mapped_column(Text)
    original_subject: Mapped[str | None] = mapped_column(Text)
    original_sent_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    original_body: Mapped[str | None] = mapped_column(Text)
    forward_depth: Mapped[int] = mapped_column(Integer, default=0)

    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)
    customer_organization: Mapped[str | None] = mapped_column(String(255))
    customer_department: Mapped[str | None] = mapped_column(String(255))
    customer_name: Mapped[str | None] = mapped_column(String(100))
    customer_phone: Mapped[str | None] = mapped_column(String(100))
    customer_email: Mapped[str | None] = mapped_column(String(255))
    delivery_place: Mapped[str | None] = mapped_column(Text)
    payment_terms: Mapped[str | None] = mapped_column(Text)
    requested_date: Mapped[str | None] = mapped_column(String(100))

    status: Mapped[str] = mapped_column(String(40), default="NEW", index=True)
    starred: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    request_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    commitment_status: Mapped[str | None] = mapped_column(String(30))
    confidence: Mapped[float | None] = mapped_column(Float)
    summary: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    missing_information: Mapped[list[str]] = mapped_column(JSON, default=list)
    analysis_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)

    customer: Mapped[Customer | None] = relationship(back_populates="mails")
    attachments: Mapped[list[Attachment]] = relationship(
        back_populates="mail", cascade="all, delete-orphan"
    )
    items: Mapped[list[MailItem]] = relationship(
        back_populates="mail", cascade="all, delete-orphan"
    )
    reviews: Mapped[list[ReviewIssue]] = relationship(
        back_populates="mail", cascade="all, delete-orphan"
    )
    drafts: Mapped[list[QuotationDraft]] = relationship(back_populates="mail")
    chat_messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="mail", cascade="all, delete-orphan"
    )
    learned_facts: Mapped[list[QuotationLearningFact]] = relationship(
        back_populates="mail", cascade="all, delete-orphan"
    )

    @property
    def heart_key(self) -> str:
        """모든 PC에서 동일한 메일을 가리키는 LAN 하트 식별값."""
        message_id = (self.message_id or "").strip()
        if message_id:
            return message_id
        return f"{self.account}:{self.uid}"


class Attachment(TimestampMixin, Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    mail_id: Mapped[int] = mapped_column(ForeignKey("mails.id"), index=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(255))
    saved_path: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(40), default="PENDING")
    extracted_text: Mapped[str | None] = mapped_column(Text)
    analysis_summary: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)

    mail: Mapped[Mail] = relationship(back_populates="attachments")


class MailItem(TimestampMixin, Base):
    __tablename__ = "mail_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    mail_id: Mapped[int] = mapped_column(ForeignKey("mails.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_product: Mapped[str | None] = mapped_column(String(255), index=True)
    specification: Mapped[str | None] = mapped_column(Text)
    width_mm: Mapped[float | None] = mapped_column(Float)
    height_mm: Mapped[float | None] = mapped_column(Float)
    size_name: Mapped[str | None] = mapped_column(String(100))
    quantity: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(50))
    paper: Mapped[str | None] = mapped_column(String(255))
    print_sides: Mapped[str | None] = mapped_column(String(100))
    material: Mapped[str | None] = mapped_column(String(255))
    spec_attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    cost_price: Mapped[int | None] = mapped_column(Integer)
    unit_price: Mapped[int | None] = mapped_column(Integer)
    amount: Mapped[int | None] = mapped_column(Integer)
    detail_text: Mapped[str | None] = mapped_column(Text)
    schedule_note: Mapped[str | None] = mapped_column(Text)
    design_request: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)

    mail: Mapped[Mail] = relationship(back_populates="items")


class ReviewIssue(TimestampMixin, Base):
    __tablename__ = "review_issues"

    id: Mapped[int] = mapped_column(primary_key=True)
    mail_id: Mapped[int] = mapped_column(ForeignKey("mails.id"), index=True)
    code: Mapped[str] = mapped_column(String(100), index=True)
    field_name: Mapped[str | None] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(20), default="blocking")
    suggestions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    resolution_value: Mapped[Any | None] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(30), default="AUTO")

    mail: Mapped[Mail] = relationship(back_populates="reviews")


class ProductAlias(TimestampMixin, Base):
    __tablename__ = "product_aliases"
    __table_args__ = (UniqueConstraint("alias", name="uq_product_alias"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    standard_name: Mapped[str] = mapped_column(String(255), index=True)
    alias: Mapped[str] = mapped_column(String(255), index=True)
    priority: Mapped[int] = mapped_column(Integer, default=1)
    note: Mapped[str | None] = mapped_column(Text)


class PriceRule(TimestampMixin, Base):
    __tablename__ = "price_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_name: Mapped[str] = mapped_column(String(255), index=True)
    rule_type: Mapped[str] = mapped_column(String(50), index=True)
    amount: Mapped[int | None] = mapped_column(Integer)
    min_amount: Mapped[int | None] = mapped_column(Integer)
    max_amount: Mapped[int | None] = mapped_column(Integer)
    width_cm: Mapped[float | None] = mapped_column(Float, index=True)
    height_min_cm: Mapped[float | None] = mapped_column(Float)
    height_max_cm: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(100))
    vat: Mapped[str | None] = mapped_column(String(50))
    confidence: Mapped[str | None] = mapped_column(String(50))
    automation_status: Mapped[str | None] = mapped_column(String(100))
    source_sheet: Mapped[str] = mapped_column(String(255))
    source_cell: Mapped[str] = mapped_column(String(50))
    section_context: Mapped[str | None] = mapped_column(Text)
    full_context: Mapped[str | None] = mapped_column(Text)
    formula: Mapped[str | None] = mapped_column(Text)


class SourceReviewFlag(TimestampMixin, Base):
    __tablename__ = "source_review_flags"

    id: Mapped[int] = mapped_column(primary_key=True)
    review_key: Mapped[str] = mapped_column(String(100), unique=True)
    review_type: Mapped[str] = mapped_column(String(100))
    source_sheet: Mapped[str] = mapped_column(String(255), index=True)
    source_cell: Mapped[str] = mapped_column(String(50), index=True)
    current_value: Mapped[str | None] = mapped_column(Text)
    formula: Mapped[str | None] = mapped_column(Text)
    check_message: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(100))


class QuotationHistory(TimestampMixin, Base):
    __tablename__ = "quotation_history"
    __table_args__ = (
        UniqueConstraint("source_file", "source_sheet", name="uq_quote_source_sheet"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)
    customer_name: Mapped[str] = mapped_column(String(255), index=True)
    quotation_date: Mapped[date | None] = mapped_column(Date, index=True)
    recipient_department: Mapped[str | None] = mapped_column(String(255))
    delivery_place: Mapped[str | None] = mapped_column(Text)
    payment_terms: Mapped[str | None] = mapped_column(Text)
    vat_type: Mapped[str | None] = mapped_column(String(100))
    displayed_total: Mapped[int | None] = mapped_column(Integer)
    calculated_total: Mapped[int | None] = mapped_column(Integer)
    extract_status: Mapped[str] = mapped_column(String(50), default="OK")
    source_file: Mapped[str] = mapped_column(Text, nullable=False)
    source_sheet: Mapped[str] = mapped_column(String(255), nullable=False)
    source_modified_at: Mapped[datetime | None] = mapped_column(DateTime)
    extraction_notes: Mapped[list[str]] = mapped_column(JSON, default=list)

    customer: Mapped[Customer | None] = relationship(back_populates="quotations")
    items: Mapped[list[QuotationHistoryItem]] = relationship(
        back_populates="quotation", cascade="all, delete-orphan"
    )


class QuotationHistoryItem(TimestampMixin, Base):
    __tablename__ = "quotation_history_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    quotation_id: Mapped[int] = mapped_column(ForeignKey("quotation_history.id"), index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    product_name: Mapped[str] = mapped_column(String(255), index=True)
    normalized_product: Mapped[str | None] = mapped_column(String(255), index=True)
    specification: Mapped[str | None] = mapped_column(Text)
    width_mm: Mapped[float | None] = mapped_column(Float)
    height_mm: Mapped[float | None] = mapped_column(Float)
    quantity: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(50))
    unit_price: Mapped[int | None] = mapped_column(Integer)
    amount: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    internal_note: Mapped[str | None] = mapped_column(Text)

    quotation: Mapped[QuotationHistory] = relationship(back_populates="items")


class QuotationDraft(TimestampMixin, Base):
    __tablename__ = "quotation_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    mail_id: Mapped[int] = mapped_column(ForeignKey("mails.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    file_path: Mapped[str] = mapped_column(Text)
    customer_name: Mapped[str] = mapped_column(String(255))
    total_amount: Mapped[int | None] = mapped_column(Integer)
    email_subject: Mapped[str | None] = mapped_column(Text)
    email_body: Mapped[str | None] = mapped_column(Text)
    email_recipients: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    sent_to: Mapped[str | None] = mapped_column(String(255))
    error_message: Mapped[str | None] = mapped_column(Text)

    mail: Mapped[Mail] = relationship(back_populates="drafts")
    items: Mapped[list[QuotationDraftItem]] = relationship(
        back_populates="draft", cascade="all, delete-orphan"
    )


class QuotationDraftItem(TimestampMixin, Base):
    __tablename__ = "quotation_draft_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("quotation_drafts.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    product_name: Mapped[str] = mapped_column(String(255))
    specification: Mapped[str | None] = mapped_column(Text)
    spec_attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    quantity: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(50))
    cost_price: Mapped[int | None] = mapped_column(Integer)
    unit_price: Mapped[int | None] = mapped_column(Integer)
    amount: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    price_source: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    draft: Mapped[QuotationDraft] = relationship(back_populates="items")


class AppSetting(TimestampMixin, Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)


class ChatMessage(TimestampMixin, Base):
    """메일별 상담 대화. evidence에는 답변에 사용한 DB 근거를 저장한다."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    mail_id: Mapped[int] = mapped_column(ForeignKey("mails.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    action_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    mail: Mapped[Mail] = relationship(back_populates="chat_messages")


class QuotationLearningFact(TimestampMixin, Base):
    """사람이 대화/화면에서 확정한 견적 판단 사례와 변경 전후 값."""

    __tablename__ = "quotation_learning_facts"

    id: Mapped[int] = mapped_column(primary_key=True)
    mail_id: Mapped[int] = mapped_column(ForeignKey("mails.id"), index=True)
    chat_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_messages.id"), index=True
    )
    item_id: Mapped[int | None] = mapped_column(ForeignKey("mail_items.id"), index=True)
    fact_type: Mapped[str] = mapped_column(String(50), index=True)
    field_name: Mapped[str] = mapped_column(String(100), index=True)
    old_value: Mapped[Any | None] = mapped_column(JSON)
    new_value: Mapped[Any | None] = mapped_column(JSON)
    customer_name: Mapped[str | None] = mapped_column(String(255), index=True)
    product_name: Mapped[str | None] = mapped_column(String(255), index=True)
    specification: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(30), default="chat_user")
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    applied: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    confidence: Mapped[float | None] = mapped_column(Float)

    mail: Mapped[Mail] = relationship(back_populates="learned_facts")
