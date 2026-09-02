from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.routers import lan_presence


def test_presence_lists_every_connected_user():
    lan_presence._users.clear()
    client = TestClient(app)

    first = client.put(
        "/api/lan-presence",
        json={"user_id": "host-1", "user_name": "서버장", "color": "#DF7134"},
    )
    second = client.put(
        "/api/lan-presence",
        json={"user_id": "guest-1", "user_name": "게스트", "color": "#1E88E5"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    users = client.get("/api/lan-presence").json()
    assert {user["user_id"] for user in users} == {"host-1", "guest-1"}

    removed = client.delete("/api/lan-presence/guest-1")
    assert removed.status_code == 200
    assert [user["user_id"] for user in removed.json()] == ["host-1"]
