import threading
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app import quotation_storage as storage
from backend.app.config import Settings
from backend.app.services.quotation_service import get_storage_options, _new_file_candidates


def configured(root):
    return Settings(quotation_files_path=root)


def test_roundtrip_permissions_and_relocation(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "settings_path", lambda: tmp_path / "config.json")
    old, new = tmp_path / "old", tmp_path / "new"
    for root in (old, new):
        (root / "@@26-견적서@@").mkdir(parents=True)
    settings = configured(old)
    settings.quotation_year_folders = {"2026": "@@26-견적서@@"}
    storage.save_storage(settings, str(new), {"2026": "@@26-견적서@@"})
    loaded = configured(old)
    storage.load_storage(loaded)
    assert loaded.quotation_files_path == new
    assert storage.year_root(loaded, 2026) == new / "@@26-견적서@@"
    assert storage.relocated_path(loaded, old / "@@26-견적서@@" / "a.xlsx") == new / "@@26-견적서@@" / "a.xlsx"
    assert not list(new.rglob("*.tmp"))
    storage.save_storage(settings, str(old), {"2026": "@@26-견적서@@"})
    assert storage.relocated_path(settings, new / "@@26-견적서@@" / "a.xlsx") == old / "@@26-견적서@@" / "a.xlsx"


def test_missing_folder_and_invalid_mapping_leave_settings_unchanged(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    monkeypatch.setattr(storage, "settings_path", lambda: config)
    settings = configured(tmp_path)
    for years in ({"2026": "missing"}, {"2026": "../escape"}, {"bad": "year"}, {"2026": "same", "2027": "same"}):
        with pytest.raises(ValueError):
            storage.save_storage(settings, str(tmp_path), years)
        assert not config.exists()
        assert settings.quotation_year_folders == {}


def test_busy_generation_prevents_settings_change(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "settings_path", lambda: tmp_path / "config.json")
    ready, finish = threading.Event(), threading.Event()
    def generation():
        with storage.storage_lock:
            ready.set()
            finish.wait(5)
    worker = threading.Thread(target=generation)
    worker.start()
    assert ready.wait(2)
    try:
        with pytest.raises(ValueError, match="처리 중"):
            storage.save_storage(configured(tmp_path), str(tmp_path), {})
    finally:
        finish.set()
        worker.join()


def test_year_selection_search_and_missing_new_year(tmp_path):
    settings = configured(tmp_path)
    settings.quotation_year_folders = {"2025": "2025", "2026": "2026"}
    for year in ("2025", "2026"):
        (tmp_path / year / "부서").mkdir(parents=True)
        (tmp_path / year / "부서" / "고객.xlsx").touch()
    (tmp_path / "2026" / "~$고객.xlsx").touch()
    mail = SimpleNamespace(customer_organization="고객", customer_name="담당자", customer_department="", drafts=[])
    options = get_storage_options(settings, mail, now=datetime(2026, 9, 3))
    assert len(options["existing_files"]) == 2
    assert "2026" in options["existing_files"][0]["path"]
    assert all(Path(row["path"]).parent == tmp_path / "2026" for row in options["new_files"])
    future = get_storage_options(settings, mail, now=datetime(2027, 1, 1))
    assert len(future["existing_files"]) == 2
    assert future["new_files"] == []
    assert "2027" in future["storage_notice"]
    with pytest.raises(ValueError, match="2027"):
        _new_file_candidates(settings, mail, datetime(2027, 1, 1))


def test_frozen_exe_keeps_nas_path(monkeypatch):
    import sys
    if sys.platform != "win32":
        pytest.skip("Windows UNC path")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    path = Path(r"\\192.168.0.29\backup-1\1. 견적서")
    assert Settings(quotation_files_path=path).quotation_files_path == path
