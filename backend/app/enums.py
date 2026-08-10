from __future__ import annotations

from enum import StrEnum


class MailStatus(StrEnum):
    NEW = "NEW"
    ANALYZING = "ANALYZING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    READY_FOR_QUOTE = "READY_FOR_QUOTE"
    QUOTE_CREATED = "QUOTE_CREATED"
    APPROVED = "APPROVED"
    SENT = "SENT"
    FAILED = "FAILED"
    NOT_RELEVANT = "NOT_RELEVANT"


class AttachmentStatus(StrEnum):
    PENDING = "PENDING"
    EXTRACTED = "EXTRACTED"
    IMAGE_PENDING = "IMAGE_PENDING"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    FAILED = "FAILED"


class DraftStatus(StrEnum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SENT = "SENT"
    FAILED = "FAILED"


class Severity(StrEnum):
    WARNING = "warning"
    BLOCKING = "blocking"


class EvidenceSource(StrEnum):
    CURRENT_MAIL = "CURRENT_MAIL"
    ATTACHMENT = "ATTACHMENT"
    MAIL_THREAD = "MAIL_THREAD"
    CUSTOMER_HISTORY = "CUSTOMER_HISTORY"
    PRICE_TABLE = "PRICE_TABLE"
    PRODUCT_DEFAULT = "PRODUCT_DEFAULT"
    MANUAL_INPUT = "MANUAL_INPUT"
    UNKNOWN = "UNKNOWN"
