from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, selectinload

from backend.app.database import Base
from backend.app.models import Mail
from backend.app.services.llm_service import analyze_mail
from backend.app.services.mail_service import import_eml_bytes
from backend.app.services.review_service import evaluate_mail_readiness


def test_eml_to_analysis_and_price_review(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    project_root = Path(__file__).resolve().parents[2]
    for name in ("raw", "attachments", "quotes"):
        (tmp_path / name).mkdir()
    settings = SimpleNamespace(
        seller_name_set={"열린문디자인", "(주)열린문디자인", "주식회사 열린문디자인"},
        daum_login_id="",
        raw_mails_dir=tmp_path / "raw",
        attachments_dir=tmp_path / "attachments",
        generated_quotes_dir=tmp_path / "quotes",
        openai_api_key="",
        openai_model="gpt-4.1-mini",
        max_llm_body_length=20_000,
        analyze_images=False,
        low_confidence_threshold=0.72,
        use_external_price_engine=True,
        price_database_path=project_root / "backend/data/source/price_table.db",
        quotation_database_path=project_root / "backend/data/source/quotation_history.db",
        history_minimum_score=65.0,
        price_review_score=80.0,
    )

    message = EmailMessage()
    message["From"] = "홍길동 <hong@example.com>"
    message["To"] = "yullin-moon@daum.net"
    message["Subject"] = "[테스트기관] 현수막 견적 요청"
    message["Message-ID"] = "<integration-test@example.com>"
    message.set_content("현수막 4000mm x 600mm 1개 제작 견적 부탁드립니다.")

    with Session(engine) as session:
        mail = import_eml_bytes(session, settings, message.as_bytes(), account="test", uid="1")
        analyze_mail(session, settings, mail)
        session.expire_all()
        mail = session.scalar(
            select(Mail)
            .where(Mail.id == mail.id)
            .options(selectinload(Mail.items), selectinload(Mail.attachments), selectinload(Mail.reviews))
        )
        evaluate_mail_readiness(session, settings, mail)
        assert mail.customer_organization == "테스트기관"
        assert len(mail.items) == 1
        assert mail.items[0].width_mm == 4000
        assert mail.items[0].height_mm == 600
        # 원본 YullinMoon_Ver3.py처럼 가격 후보의 검토 표시는
        # 참고 사항이며 견적서 초안 생성을 차단하지 않는다.
        assert mail.status == "READY_FOR_QUOTE"
