from types import SimpleNamespace

import sqlite3
from openpyxl import Workbook

from backend.app.services.external_db_admin import (
    delete_price,
    list_prices,
    save_price,
    sync_draft_to_history,
)


def test_price_crud(tmp_path):
    database = tmp_path / "price_table.db"
    created = save_price(database, {"product_name": "현수막", "specification": "5000x600", "unit_price": 50000})
    assert created["normalized_name"] == "현수막"
    assert list_prices(database, "현수막")[0]["unit_price"] == 50000

    updated = save_price(database, {"product_name": "현수막", "specification": "5000x600", "unit_price": 55000}, created["id"])
    assert updated["unit_price"] == 55000
    delete_price(database, created["id"])
    assert list_prices(database, "현수막") == []


def test_draft_sync_upserts_without_duplicates(tmp_path):
    workbook_path = tmp_path / "quotation_files" / "26-test.xlsx"
    workbook_path.parent.mkdir()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "0831"
    sheet.cell(1, 20).value = "OPENMOON_MAIL_ID:7"
    workbook.save(workbook_path)
    workbook.close()

    item = SimpleNamespace(position=1, product_name="현수막", specification="5000x600", quantity=1, unit="장", unit_price=50000, amount=50000, note=None)
    draft = SimpleNamespace(id=3, file_path=str(workbook_path), total_amount=50000, items=[item])
    mail = SimpleNamespace(id=7, customer_organization="테스트기관", customer_name="홍길동", customer_phone=None, customer_email="test@example.com", original_sender_email=None)
    database = tmp_path / "quotation_history.db"

    sync_draft_to_history(database, draft, mail)
    item.unit_price = 60000
    item.amount = 60000
    draft.total_amount = 60000
    sync_draft_to_history(database, draft, mail)

    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT COUNT(*) FROM quotations").fetchone()[0] == 1
        assert connection.execute("SELECT unit_price FROM quotation_items").fetchone()[0] == 60000
    finally:
        connection.close()
