from types import SimpleNamespace

import sqlite3
from openpyxl import Workbook

from backend.app.services.external_db_admin import remove_draft_from_history, sync_draft_to_history


def test_unapproved_draft_history_can_be_removed(tmp_path):
    workbook_path = tmp_path / "quotation_files" / "draft.xlsx"
    workbook_path.parent.mkdir()
    workbook = Workbook()
    workbook.active.cell(1, 20).value = "OPENMOON_MAIL_ID:10"
    workbook.save(workbook_path)
    workbook.close()

    item = SimpleNamespace(position=1, product_name="배너", specification="600x1800", quantity=1, unit="개", unit_price=33000, amount=33000, note=None)
    draft = SimpleNamespace(id=5, file_path=str(workbook_path), total_amount=33000, items=[item])
    mail = SimpleNamespace(id=10, customer_organization="테스트기관", customer_name="담당자", customer_phone=None, customer_email="test@example.com", original_sender_email=None)
    database = tmp_path / "quotation_history.db"

    sync_draft_to_history(database, draft, mail)
    assert remove_draft_from_history(database, draft.id) == 1

    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT COUNT(*) FROM quotations").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM quotation_items").fetchone()[0] == 0
    finally:
        connection.close()
