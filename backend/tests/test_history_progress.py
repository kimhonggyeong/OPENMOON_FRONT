from backend.app.services import history_refresh as refresh
from backend.app.history_progress import progress_text


def test_current_file_does_not_count_as_completed(monkeypatch):
    monkeypatch.setattr(refresh, "_state", dict(status="running", phase="analyzing", total=10,
                       processed=4, parsed=1, relocated=1, unchanged=1, metadata_updated=0))
    status = refresh.refresh_status()
    assert status["completed"] == 3
    assert status["percent"] == 30
    assert "3 / 10" in progress_text(status)[0]


def test_scanning_does_not_invent_a_total():
    text, _ = progress_text(dict(status="running", phase="scanning", discovered=85))
    assert "85" in text and "%" not in text


def test_file_completion_is_distinct_from_database_publication(monkeypatch):
    state = dict(status="running", phase="publishing", total=10, parsed=2, relocated=3, unchanged=5)
    monkeypatch.setattr(refresh, "_state", state)
    headline, counts = progress_text(refresh.refresh_status())
    assert "100%" in headline and "DB 반영 완료" not in headline
    assert "경로만 변경 3개" in counts
    state["status"] = "complete"
    assert "DB 반영 완료" in progress_text(refresh.refresh_status())[0]
    state["status"] = "failed"
    assert "기존 DB 유지" in progress_text(refresh.refresh_status())[0]
