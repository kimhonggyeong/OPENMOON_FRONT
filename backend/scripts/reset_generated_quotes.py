from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.app.config import get_settings


def main() -> None:
    settings = get_settings()
    generated_root = settings.generated_quotes_dir.resolve()

    removed_files = 0
    for path in generated_root.iterdir():
        if not path.is_file():
            continue
        path.resolve().relative_to(generated_root)
        path.unlink()
        removed_files += 1

    database_path = Path(
        settings.resolved_database_url.removeprefix("sqlite:///")
    )
    with sqlite3.connect(database_path) as connection:
        mail_ids = [
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT mail_id FROM quotation_drafts"
            )
        ]
        draft_count = connection.execute(
            "SELECT count(1) FROM quotation_drafts"
        ).fetchone()[0]

        connection.execute("DELETE FROM quotation_draft_items")
        connection.execute("DELETE FROM quotation_drafts")

        status_sql = """
            UPDATE mails
            SET status = CASE
                WHEN EXISTS (
                    SELECT 1 FROM review_issues r
                    WHERE r.mail_id = mails.id
                      AND r.resolved = 0
                      AND r.severity = 'blocking'
                ) THEN 'REVIEW_REQUIRED'
                ELSE 'READY_FOR_QUOTE'
            END
            WHERE id = ?
        """
        for mail_id in mail_ids:
            connection.execute(status_sql, (mail_id,))

        connection.commit()

    print(f"생성 견적 파일 {removed_files}개 삭제")
    print(f"견적서 DB 기록 {draft_count}개 삭제")


if __name__ == "__main__":
    main()
