from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from ..config import Settings, get_settings
from ..schemas import HealthOut

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/status", response_model=HealthOut)
def status(settings: Settings = Depends(get_settings)):
    return HealthOut(
        database=settings.resolved_database_url,
        openai_configured=bool(settings.openai_api_key),
        mail_configured=bool(settings.daum_login_id and settings.daum_app_password),
        live_send_enabled=settings.allow_live_send,
    )


@router.get("/paths")
def paths(settings: Settings = Depends(get_settings)):
    return {
        "project_root": str(Path(__file__).resolve().parents[3]),
        "database": settings.resolved_database_url,
        "price_database": str(settings.price_database_path),
        "quotation_database": str(settings.quotation_database_path),
        "quotation_template": str(settings.quotation_template_path),
        "attachments": str(settings.attachments_dir),
        "generated_quotes": str(settings.generated_quotes_dir),
        "source_program": "YullinMoon_Ver3.py / price_engine.py",
    }
