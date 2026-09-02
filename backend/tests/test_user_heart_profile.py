import sqlite3

from backend.app.lan_heart import HeartStore


def test_existing_boolean_heart_database_is_migrated(tmp_path):
    database = tmp_path / "heart_sync.db"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE mail_hearts(mail_key TEXT PRIMARY KEY, hearted INTEGER NOT NULL, updated_at TEXT NOT NULL)"
    )
    connection.execute("INSERT INTO mail_hearts VALUES('old-mail', 1, '2026-01-01')")
    connection.commit()
    connection.close()

    state = HeartStore(database).all()["old-mail"]
    assert state["hearted"] is True
    assert state["user_name"] == "기존 사용자"
    assert state["color"] == "#DF7134"


def test_another_user_replaces_heart_owner_and_color(tmp_path):
    store = HeartStore(tmp_path / "heart_sync.db")
    store.set("mail-1", True, user_id="a", user_name="김대리", color="#E53935")
    store.set("mail-1", True, user_id="b", user_name="이과장", color="#1E88E5")

    state = store.all()["mail-1"]
    assert state["user_id"] == "b"
    assert state["user_name"] == "이과장"
    assert state["color"] == "#1E88E5"
