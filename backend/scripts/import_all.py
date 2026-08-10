from __future__ import annotations

import argparse
from pathlib import Path

from backend.app.config import get_settings
from backend.app.database import SessionLocal, init_db
from backend.app.services.history_service import import_quotation_history
from backend.app.services.price_service import import_price_table


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", help="기존 견적서 폴더")
    args = parser.parse_args()
    settings = get_settings()
    init_db()
    with SessionLocal() as session:
        print("가격표:", import_price_table(session, settings.price_table_path))
        if args.history:
            print(
                "견적 이력:",
                import_quotation_history(
                    session,
                    Path(args.history),
                    settings.data_dir / "import_summary.csv",
                    settings.data_dir / "import_errors.csv",
                ),
            )


if __name__ == "__main__":
    main()
