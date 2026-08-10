from __future__ import annotations

import argparse
from pathlib import Path

from backend.app.config import get_settings
from backend.app.database import SessionLocal, init_db
from backend.app.services.history_service import import_quotation_history


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="2025·2026 견적서 상위 폴더")
    parser.add_argument("--replace", action="store_true", help="기존 이력을 삭제하고 다시 가져오기")
    args = parser.parse_args()

    init_db()
    settings = get_settings()
    with SessionLocal() as session:
        stats = import_quotation_history(
            session,
            Path(args.input),
            settings.data_dir / "import_summary.csv",
            settings.data_dir / "import_errors.csv",
            replace_existing=args.replace,
        )
    print(stats)


if __name__ == "__main__":
    main()
