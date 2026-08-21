from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def runtime_root() -> Path:
    """Return the stable base directory used for portable EXE paths."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return PROJECT_ROOT


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # =====================================================
    # 애플리케이션
    # =====================================================

    app_name: str = "YullinMoon AI 견적 업무 보조"

    database_url: str = (
        "sqlite:///backend/data/openmoon.db"
    )

    # =====================================================
    # Daum 메일
    # =====================================================

    daum_login_id: str = ""
    daum_app_password: str = ""

    imap_server: str = "imap.daum.net"
    imap_port: int = 993

    smtp_server: str = "smtp.daum.net"
    smtp_port: int = 465

    # =====================================================
    # OpenAI
    # =====================================================

    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"

    max_llm_body_length: int = 20_000

    analyze_images: bool = True

    low_confidence_threshold: float = 0.72

    # =====================================================
    # 실제 메일 발송 안전장치
    # =====================================================

    allow_live_send: bool = False

    # 승인 버튼의 전체 발송 흐름을 실제 고객 대신 지정 주소로 검증한다.
    # 이 모드에서는 ALLOW_LIVE_SEND=false여도 지정된 테스트 주소로만 발송한다.
    approval_test_mode: bool = False
    approval_test_recipient: str = ""

    # 테스트 중에는 실제 고객 대신 현재 로그인한 Daum 계정 자신에게 발송
    send_test_to_self: bool = True

    # =====================================================
    # 열린문디자인 기본정보
    # =====================================================

    seller_names: str = (
        "열린문디자인|"
        "(주)열린문디자인|"
        "주식회사 열린문디자인"
    )

    default_delivery_place: str = "지정장소"

    default_payment_terms: str = (
        "현금 또는 카드결제"
    )

    default_validity: str = "견적일로부터"

    # =====================================================
    # 기존 웹 프로젝트용 Excel 원본
    # =====================================================

    price_table_path: Path = Field(
        default=Path(
            "backend/data/source/"
            "price_table.xlsx"
        )
    )

    quotation_template_path: Path = Field(
        default=Path(
            "backend/data/templates/"
            "quotation_template.xlsx"
        )
    )

    quotation_template_sheet: str = "Main_Sheet"

    quotation_files_path: Path = Field(
        default=Path("backend/data/quotation_files")
    )

    quotation_history_dir: str = ""

    # =====================================================
    # 새 가격 엔진용 SQLite DB
    # =====================================================

    price_database_path: Path = Field(
        default=Path(
            "backend/data/source/"
            "price_table.db"
        )
    )

    quotation_database_path: Path = Field(
        default=Path(
            "backend/data/source/"
            "quotation_history.db"
        )
    )

    # 새 가격 엔진을 사용할지 여부
    use_external_price_engine: bool = True

    # 과거 견적 검색 최소 점수
    history_minimum_score: float = 65.0

    # 결과가 이 점수 미만이면 담당자 검토
    price_review_score: float = 80.0

    # =====================================================
    # 상대 경로 → 프로젝트 절대 경로 변환
    # =====================================================

    @field_validator(
        "price_table_path",
        "quotation_template_path",
        "price_database_path",
        "quotation_database_path",
        mode="before",
    )
    @classmethod
    def resolve_project_path(
        cls,
        value: str | Path,
    ) -> Path:
        path = Path(value)

        if path.is_absolute():
            return path

        return PROJECT_ROOT / path

    @field_validator("quotation_files_path", mode="before")
    @classmethod
    def resolve_quotation_files_path(cls, value: str | Path) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return (runtime_root() / path).resolve()

    # =====================================================
    # 데이터 폴더
    # =====================================================

    @property
    def data_dir(self) -> Path:
        return (
            PROJECT_ROOT
            / "backend"
            / "data"
        )

    @property
    def attachments_dir(self) -> Path:
        return (
            self.data_dir
            / "attachments"
        )

    @property
    def raw_mails_dir(self) -> Path:
        return (
            self.data_dir
            / "raw_mails"
        )

    @property
    def generated_quotes_dir(self) -> Path:
        return (
            self.data_dir
            / "generated_quotes"
        )

    # =====================================================
    # 판매자 이름
    # =====================================================

    @property
    def seller_name_set(self) -> set[str]:
        return {
            part.strip()
            for part
            in self.seller_names.split("|")
            if part.strip()
        }

    # =====================================================
    # DB URL
    # =====================================================

    @property
    def resolved_database_url(self) -> str:
        if not self.database_url.startswith(
            "sqlite:///"
        ):
            return self.database_url

        raw = self.database_url.removeprefix(
            "sqlite:///"
        )

        path = Path(raw)

        if not path.is_absolute():
            path = PROJECT_ROOT / path

        return (
            "sqlite:///"
            f"{path.as_posix()}"
        )

    # =====================================================
    # 가격 DB 상태
    # =====================================================

    @property
    def external_price_database_ready(
        self,
    ) -> bool:
        return (
            self.price_database_path.exists()
            and self.quotation_database_path.exists()
        )

    # =====================================================
    # 폴더 생성
    # =====================================================

    def ensure_directories(self) -> None:
        directories = (
            self.data_dir,
            self.attachments_dir,
            self.raw_mails_dir,
            self.generated_quotes_dir,
            self.quotation_template_path.parent,
            self.price_table_path.parent,
            self.price_database_path.parent,
            self.quotation_database_path.parent,
            self.quotation_files_path,
        )

        for path in directories:
            path.mkdir(
                parents=True,
                exist_ok=True,
            )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()

    settings.ensure_directories()

    if settings.openai_api_key:
        os.environ.setdefault(
            "OPENAI_API_KEY",
            settings.openai_api_key,
        )

    return settings
