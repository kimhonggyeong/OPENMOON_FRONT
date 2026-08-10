from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


IGNORED_COLUMNS = {"id", "indexed_at", "file_path"}


def table_names(connection: sqlite3.Connection) -> list[str]:
    return [
        row[0]
        for row in connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        )
    ]


def comparable_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [
        row[1]
        for row in connection.execute(f'PRAGMA table_info("{table}")')
        if row[1] not in IGNORED_COLUMNS
    ]


def rows_as_tuples(
    connection: sqlite3.Connection, table: str, columns: list[str]
) -> list[tuple[Any, ...]]:
    quoted = ", ".join(f'"{column}"' for column in columns)
    return list(connection.execute(f'SELECT {quoted} FROM "{table}"'))


def compare_databases(live_path: Path, candidate_path: Path) -> dict[str, Any]:
    with sqlite3.connect(live_path) as live, sqlite3.connect(candidate_path) as candidate:
        live_tables = table_names(live)
        candidate_tables = table_names(candidate)
        report: dict[str, Any] = {
            "live_db": str(live_path.resolve()),
            "candidate_db": str(candidate_path.resolve()),
            "missing_tables": sorted(set(candidate_tables) - set(live_tables)),
            "unexpected_tables": sorted(set(live_tables) - set(candidate_tables)),
            "tables": {},
            "integrity": {
                "sqlite": live.execute("PRAGMA integrity_check").fetchone()[0],
                "foreign_key_errors": len(live.execute("PRAGMA foreign_key_check").fetchall()),
                "nonpositive_prices": live.execute(
                    "SELECT COUNT(*) FROM price_items WHERE COALESCE(unit_price, total_price, 0) <= 0"
                ).fetchone()[0],
                "missing_names": live.execute(
                    "SELECT COUNT(*) FROM price_items WHERE TRIM(product_name) = '' OR TRIM(normalized_name) = ''"
                ).fetchone()[0],
                "invalid_confidence": live.execute(
                    "SELECT COUNT(*) FROM price_items WHERE confidence < 0 OR confidence > 1"
                ).fetchone()[0],
                "review_required": live.execute(
                    "SELECT COUNT(*) FROM price_items WHERE review_required <> 0"
                ).fetchone()[0],
                "missing_source_coordinates": live.execute(
                    "SELECT COUNT(*) FROM price_items WHERE row_number IS NULL OR column_number IS NULL"
                ).fetchone()[0],
                "minimum_price": live.execute(
                    "SELECT MIN(COALESCE(unit_price, total_price)) FROM price_items"
                ).fetchone()[0],
                "maximum_price": live.execute(
                    "SELECT MAX(COALESCE(unit_price, total_price)) FROM price_items"
                ).fetchone()[0],
                "maximum_total_price": live.execute(
                    "SELECT MAX(total_price) FROM price_items"
                ).fetchone()[0],
                "unitless_quantity_over_100000": live.execute(
                    "SELECT COUNT(*) FROM price_items WHERE unit IS NULL AND quantity > 100000"
                ).fetchone()[0],
                "total_price_over_100000000": live.execute(
                    "SELECT COUNT(*) FROM price_items WHERE total_price > 100000000"
                ).fetchone()[0],
                "excel_formula_errors_in_source_text": live.execute(
                    "SELECT COUNT(*) FROM price_items WHERE original_text LIKE '%#REF!%' OR original_text LIKE '%#VALUE!%' OR original_text LIKE '%#DIV/0!%'"
                ).fetchone()[0],
                "target_sheets_missing_quantity": live.execute(
                    "SELECT COUNT(*) FROM price_items WHERE TRIM(sheet_name) IN ('리플릿', '카다로그', '옵셋봉투') AND quantity IS NULL"
                ).fetchone()[0],
            },
        }

        for table in sorted(set(live_tables) & set(candidate_tables)):
            live_columns = comparable_columns(live, table)
            candidate_columns = comparable_columns(candidate, table)
            if live_columns != candidate_columns:
                report["tables"][table] = {
                    "column_mismatch": True,
                    "live_columns": live_columns,
                    "candidate_columns": candidate_columns,
                }
                continue

            live_rows = rows_as_tuples(live, table, live_columns)
            candidate_rows = rows_as_tuples(candidate, table, candidate_columns)
            live_set = set(live_rows)
            candidate_set = set(candidate_rows)
            report["tables"][table] = {
                "live_rows": len(live_rows),
                "candidate_rows": len(candidate_rows),
                "live_duplicates": len(live_rows) - len(live_set),
                "candidate_duplicates": len(candidate_rows) - len(candidate_set),
                "live_only": len(live_set - candidate_set),
                "candidate_only": len(candidate_set - live_set),
                "live_only_samples": [list(row) for row in list(live_set - candidate_set)[:5]],
                "candidate_only_samples": [list(row) for row in list(candidate_set - live_set)[:5]],
            }

        report["matches"] = not (
            report["missing_tables"]
            or report["unexpected_tables"]
            or any(
                details.get("column_mismatch")
                or details.get("live_only")
                or details.get("candidate_only")
                or details.get("live_duplicates")
                or details.get("candidate_duplicates")
                for details in report["tables"].values()
            )
        )
        report["target_missing_quantity_by_sheet"] = dict(
            live.execute(
                "SELECT TRIM(sheet_name), COUNT(*) FROM price_items "
                "WHERE TRIM(sheet_name) IN ('리플릿', '카다로그', '옵셋봉투') AND quantity IS NULL "
                "GROUP BY TRIM(sheet_name) ORDER BY TRIM(sheet_name)"
            ).fetchall()
        )
        report["target_missing_quantity_samples"] = [
            list(row)
            for row in live.execute(
                "SELECT sheet_name, row_number, column_number, specification, total_price "
                "FROM price_items WHERE TRIM(sheet_name) IN ('리플릿', '카다로그', '옵셋봉투') "
                "AND quantity IS NULL ORDER BY sheet_name, row_number, column_number LIMIT 30"
            ).fetchall()
        ]
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare a live price DB with a rebuilt candidate DB.")
    parser.add_argument("--live", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    report = compare_databases(args.live, args.candidate)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload, encoding="utf-8")
    raise SystemExit(0 if report["matches"] else 1)


if __name__ == "__main__":
    main()
