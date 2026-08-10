import sqlite3
from pathlib import Path
from types import SimpleNamespace

from backend.app.services.quantity_suggestion_service import suggest_quantity_from_history


def _database(path: Path, quantities: list[float]) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE source_files (id INTEGER PRIMARY KEY, file_name TEXT);
            CREATE TABLE quotations (
                id INTEGER PRIMARY KEY, source_file_id INTEGER, sheet_name TEXT,
                quote_date TEXT, customer_organization TEXT
            );
            CREATE TABLE quotation_items (
                id INTEGER PRIMARY KEY, quotation_id INTEGER, product_name TEXT,
                normalized_product TEXT, specification_raw TEXT,
                width_mm REAL, height_mm REAL, quantity REAL, unit TEXT
            );
            """
        )
        for index, quantity in enumerate(quantities, start=1):
            connection.execute(
                "INSERT INTO source_files VALUES (?, ?)",
                (index, f"quote-{index}.xlsx"),
            )
            connection.execute(
                "INSERT INTO quotations VALUES (?, ?, ?, ?, ?)",
                (index, index, "견적서", f"2026-0{index}-01", "테스트기관"),
            )
            connection.execute(
                "INSERT INTO quotation_items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (index, index, "현수막", "현수막", "4000mm x 600mm", 4000, 600, quantity, "장"),
            )


def test_suggests_only_when_three_recent_quantities_match(tmp_path: Path):
    database = tmp_path / "history.db"
    _database(database, [2, 2, 2])
    mail = SimpleNamespace(customer_organization="테스트기관", customer_name=None)
    item = SimpleNamespace(
        product_name="현수막", specification="4000 x 600mm",
        width_mm=4000, height_mm=600, unit=None,
    )

    suggestions = suggest_quantity_from_history(database, mail, item)

    assert suggestions[0]["value"] == 2
    assert suggestions[0]["recent_count"] == 3
    assert "최근 동일 회사·품목·규격 3회" in suggestions[0]["message"]


def test_does_not_suggest_when_recent_quantities_differ(tmp_path: Path):
    database = tmp_path / "history.db"
    _database(database, [2, 3, 2])
    mail = SimpleNamespace(customer_organization="테스트기관", customer_name=None)
    item = SimpleNamespace(
        product_name="현수막", specification="4000mm x 600mm",
        width_mm=4000, height_mm=600, unit=None,
    )

    assert suggest_quantity_from_history(database, mail, item) == []


def test_matches_shorter_company_name_and_majority_quantity(tmp_path: Path):
    database = tmp_path / "history.db"
    _database(database, [1, 2, 1, 1, 6])
    mail = SimpleNamespace(customer_organization="아산시 테스트기관", customer_name=None)
    item = SimpleNamespace(
        product_name="명함", specification=None,
        width_mm=None, height_mm=None, unit=None,
    )

    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE quotations SET customer_organization = '테스트기관'")
        connection.execute(
            "UPDATE quotation_items SET product_name = '명함', normalized_product = '명함', "
            "specification_raw = '90*50, 양면, 고급지, 200매', width_mm = NULL, height_mm = NULL"
        )

    suggestions = suggest_quantity_from_history(database, mail, item)

    assert suggestions[0]["value"] == 1
    assert suggestions[0]["recent_count"] == 5
    assert suggestions[0]["repeat_count"] == 3
    assert "5회 중 3회" in suggestions[0]["message"]
