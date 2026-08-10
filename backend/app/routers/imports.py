from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..database import get_db
from ..schemas import ImportRequest, ImportResult

router = APIRouter(prefix="/api/import", tags=["import"])


@router.post("/price-table", response_model=ImportResult)
def import_prices(
    request: ImportRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    # YullinMoon_Ver3.py는 Excel을 실행 중에 다시 가져오지 않고
    # build_price_db.py가 만든 price_table.db를 직접 사용한다.
    path = settings.price_database_path
    try:
        if not path.exists():
            raise FileNotFoundError(f"단가표 DB를 찾을 수 없습니다: {path}")

        with sqlite3.connect(path) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }

        return ImportResult(
            processed=1,
            imported=len(tables),
            message="사용자 단가표 DB가 정상적으로 연결되었습니다.",
            details={"path": str(path), "tables": sorted(tables)},
        )
    except Exception as error:
        raise HTTPException(400, str(error)) from error


@router.post("/quotation-history", response_model=ImportResult)
def import_history(
    request: ImportRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    # YullinMoon_Ver3.py의 quotation_history.db를 그대로 사용한다.
    path = settings.quotation_database_path
    try:
        if not path.exists():
            raise FileNotFoundError(f"기존 견적 DB를 찾을 수 없습니다: {path}")

        with sqlite3.connect(path) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }

        return ImportResult(
            processed=1,
            imported=len(tables),
            message="사용자 견적 이력 DB가 정상적으로 연결되었습니다.",
            details={"path": str(path), "tables": sorted(tables)},
        )
    except Exception as error:
        raise HTTPException(400, str(error)) from error
