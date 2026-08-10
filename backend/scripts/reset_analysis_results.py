from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.app.config import get_settings


def main() -> None:
    settings = get_settings()
    database_path = Path(
        settings.resolved_database_url.removeprefix("sqlite:///")
    )

    with sqlite3.connect(database_path) as connection:
        counts = {
            table: connection.execute(
                f"SELECT count(1) FROM {table}"
            ).fetchone()[0]
            for table in (
                "mail_items",
                "review_issues",
                "quotation_draft_items",
                "quotation_drafts",
            )
        }

        connection.execute("DELETE FROM quotation_draft_items")
        connection.execute("DELETE FROM quotation_drafts")
        connection.execute("DELETE FROM review_issues")
        connection.execute("DELETE FROM mail_items")

        connection.execute(
            """
            UPDATE mails SET
                customer_id = NULL,
                customer_organization = NULL,
                customer_department = NULL,
                customer_name = NULL,
                customer_phone = NULL,
                customer_email = NULL,
                delivery_place = NULL,
                payment_terms = NULL,
                requested_date = NULL,
                status = 'NEW',
                request_types = '[]',
                commitment_status = NULL,
                confidence = NULL,
                summary = NULL,
                reason = NULL,
                missing_information = '[]',
                analysis_payload = '{}',
                error_message = NULL
            """
        )

        connection.commit()

        mail_count = connection.execute(
            "SELECT count(1) FROM mails WHERE status = 'NEW'"
        ).fetchone()[0]

    print(f"신규 상태 메일: {mail_count}개")
    for table, count in counts.items():
        print(f"초기화 {table}: {count}개")


if __name__ == "__main__":
    main()
