import sqlite3
from pathlib import Path
from types import SimpleNamespace

from openpyxl import load_workbook

from backend.app.config import Settings
from backend.app.services import history_refresh as refresh
from backend.app.services.history_service import get_external_history_candidates, is_known_external_history_source
from backend.app.services.excel_open_service import resolve_quotation_source_path
from backend.app.quotation_storage import clear_source_cache


def example(path, price=10000):
    template = Path(__file__).parents[1] / "data/templates/quotation_template.xlsx"
    book = load_workbook(template)
    sheet = book.active
    sheet["B3"] = "테스트회사 귀하"
    sheet["D5"] = "2026-09-03"
    sheet["L5"] = "김담당"
    sheet["L7"] = "test@example.com"
    sheet["C14"] = "현수막 (5000x600mm)"
    sheet["F14"] = 1
    sheet["G14"] = price
    sheet["I14"] = price
    sheet["D10"] = price
    sheet["I10"] = price
    book.save(path)
    book.close()


def environment(tmp_path):
    root = tmp_path / "nas"
    (root / "2026").mkdir(parents=True)
    settings = Settings(quotation_files_path=root, quotation_database_path=tmp_path / "history.db")
    settings.quotation_year_folders = {"2026": "2026"}
    return settings, root / "2026" / "test.xlsx"


def test_refresh_indexes_selected_folders_and_updates_changed_workbook(tmp_path):
    settings, source = environment(tmp_path)
    example(source)
    assert refresh.refresh_history(settings)["status"] == "complete", refresh.refresh_status()
    with sqlite3.connect(settings.quotation_database_path) as db:
        assert db.execute("SELECT file_path FROM source_files").fetchone()[0] == str(source.resolve())
        assert db.execute("SELECT COUNT(*) FROM quotation_items").fetchone()[0] > 0
    example(source, 25000)
    assert refresh.refresh_history(settings)["status"] == "complete", refresh.refresh_status()
    with sqlite3.connect(settings.quotation_database_path) as db:
        assert db.execute("SELECT MAX(unit_price) FROM quotation_items").fetchone()[0] == 25000


def test_failure_keeps_existing_database_byte_for_byte(tmp_path):
    settings, source = environment(tmp_path)
    example(source)
    assert refresh.refresh_history(settings)["status"] == "complete"
    previous = settings.quotation_database_path.read_bytes()
    source.write_bytes(b"broken Excel")
    assert refresh.refresh_history(settings)["status"] == "failed"
    assert settings.quotation_database_path.read_bytes() == previous
    settings.quotation_year_folders = {"2027": "missing"}
    assert refresh.refresh_history(settings)["status"] == "failed"
    assert settings.quotation_database_path.read_bytes() == previous


def test_old_visible_and_open_paths_are_resolved_to_nas(tmp_path):
    settings, source = environment(tmp_path)
    example(source)
    assert refresh.refresh_history(settings)["status"] == "complete"
    old = tmp_path / "old-quotation_files" / source.name
    old.parent.mkdir()
    old.write_bytes(b"old local copy must never be opened")
    with sqlite3.connect(settings.quotation_database_path) as db:
        db.execute("UPDATE source_files SET file_path=?", (str(old),))
        sheet = db.execute("SELECT sheet_name FROM quotations LIMIT 1").fetchone()[0]
    clear_source_cache()
    assert resolve_quotation_source_path(old, settings.quotation_files_path, settings=settings) == source
    mail = SimpleNamespace(customer_organization="테스트회사", customer_name="김담당", customer_email="test@example.com", customer_phone="")
    rows = get_external_history_candidates(settings.quotation_database_path, mail, scope="company", settings=settings)
    assert rows
    assert all(row["source_file"] == str(source) for row in rows)
    assert is_known_external_history_source(settings.quotation_database_path, str(source), sheet, settings=settings)
    source.unlink()
    clear_source_cache()
    import pytest
    with pytest.raises(FileNotFoundError):
        resolve_quotation_source_path(old, settings.quotation_files_path, settings=settings)


def test_migration_removes_old_root_rows_without_touching_old_files(tmp_path):
    settings, source = environment(tmp_path)
    example(source)
    assert refresh.refresh_history(settings)["status"] == "complete"
    old = tmp_path / "local" / "old.xlsx"
    old.parent.mkdir()
    example(old)
    with sqlite3.connect(settings.quotation_database_path) as db:
        db.execute("UPDATE source_files SET file_path=?", (str(old),))
    assert refresh.refresh_history(settings)["status"] == "complete"
    with sqlite3.connect(settings.quotation_database_path) as db:
        assert db.execute("SELECT file_path FROM source_files").fetchall() == [(str(source),)]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert old.exists()


def test_server_start_schedules_refresh_without_waiting_for_nas(monkeypatch):
    import asyncio
    from backend.app import main
    calls = []
    monkeypatch.setattr(main, "init_db", lambda: calls.append("init"))
    monkeypatch.setattr(refresh, "start_history_refresh", lambda settings, stopping: calls.append((settings, stopping)))
    asyncio.run(main.startup())
    assert calls == ["init", (main.app_settings, main.server_stopping)]


def test_unchanged_sources_are_not_parsed_again(tmp_path, monkeypatch):
    settings, source = environment(tmp_path)
    example(source)
    assert refresh.refresh_history(settings)["status"] == "complete"
    def unexpected(*args):
        raise AssertionError("unchanged workbook should not be reparsed")
    monkeypatch.setattr(refresh.parser, "parse_excel_file", unexpected)
    assert refresh.refresh_history(settings)["status"] == "complete"


def test_moved_identical_file_preserves_records_without_parsing(tmp_path, monkeypatch):
    import shutil
    settings, source = environment(tmp_path)
    example(source)
    assert refresh.refresh_history(settings)["status"] == "complete"
    with sqlite3.connect(settings.quotation_database_path) as db:
        before = db.execute("SELECT * FROM quotations").fetchall()
        items_before = db.execute("SELECT * FROM quotation_items").fetchall()
    new_root = tmp_path / "different-nas"
    (new_root / "2026").mkdir(parents=True)
    destination = new_root / "2026" / "renamed.xlsx"
    shutil.copyfile(source, destination)
    settings.quotation_files_path = new_root
    monkeypatch.setattr(refresh.parser, "parse_excel_file", lambda *_: (_ for _ in ()).throw(AssertionError("must not parse moved content")))
    result = refresh.refresh_history(settings)
    assert result["status"] == "complete", result
    assert result["relocated"] == 1 and result["parsed"] == 0
    with sqlite3.connect(settings.quotation_database_path) as db:
        assert db.execute("SELECT * FROM quotations").fetchall() == before
        assert db.execute("SELECT * FROM quotation_items").fetchall() == items_before
        assert db.execute("SELECT file_path FROM source_files").fetchall() == [(str(destination),)]
    assert source.exists()


def test_timestamp_only_change_is_remembered(tmp_path, monkeypatch):
    import os
    settings, source = environment(tmp_path)
    example(source)
    assert refresh.refresh_history(settings)["status"] == "complete"
    stat = source.stat()
    os.utime(source, (stat.st_atime, stat.st_mtime + 10))
    result = refresh.refresh_history(settings)
    assert result["metadata_updated"] == 1 and result["parsed"] == 0
    monkeypatch.setattr(refresh.parser, "calculate_file_hash", lambda *_: (_ for _ in ()).throw(AssertionError("unchanged file should not be read")))
    snapshot = settings.quotation_database_path.read_bytes()
    modified = settings.quotation_database_path.stat().st_mtime_ns
    result = refresh.refresh_history(settings)
    assert result["status"] == "complete" and result["unchanged"] == 1
    assert settings.quotation_database_path.read_bytes() == snapshot
    assert settings.quotation_database_path.stat().st_mtime_ns == modified


def test_identical_copy_does_not_steal_existing_source(tmp_path):
    import shutil
    settings, source = environment(tmp_path)
    example(source)
    assert refresh.refresh_history(settings)["status"] == "complete"
    copy = source.with_name("copy.xlsx")
    shutil.copyfile(source, copy)
    result = refresh.refresh_history(settings)
    assert result["status"] == "complete"
    assert result["relocated"] == 0 and result["parsed"] == 1
    with sqlite3.connect(settings.quotation_database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM source_files").fetchone()[0] == 2


def test_same_name_different_content_after_move_is_parsed(tmp_path):
    settings, source = environment(tmp_path)
    example(source)
    assert refresh.refresh_history(settings)["status"] == "complete"
    new_root = tmp_path / "new-nas"
    (new_root / "2026").mkdir(parents=True)
    example(new_root / "2026" / source.name, 35000)
    settings.quotation_files_path = new_root
    result = refresh.refresh_history(settings)
    assert result["status"] == "complete"
    assert result["relocated"] == 0 and result["parsed"] == 1
    with sqlite3.connect(settings.quotation_database_path) as db:
        assert db.execute("SELECT MAX(unit_price) FROM quotation_items").fetchone()[0] == 35000
