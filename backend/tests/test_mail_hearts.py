from fastapi.testclient import TestClient

from backend.app.lan_heart import HeartStore, create_heart_app, normalize_heart_server_url


def test_heart_state_is_shared_and_persists_in_sqlite(tmp_path):
    database = tmp_path / "heart_sync.db"
    client_one = TestClient(create_heart_app(HeartStore(database)))

    updated = client_one.put(
        "/hearts",
        json={"mail_key": "<estimate-001@example.com>", "hearted": True},
    )
    assert updated.status_code == 200
    assert updated.json()["hearted"] is True

    client_two = TestClient(create_heart_app(HeartStore(database)))
    shared = client_two.get("/hearts")
    assert shared.status_code == 200
    assert shared.json()["<estimate-001@example.com>"] is True

    cleared = client_two.put(
        "/hearts",
        json={"mail_key": "<estimate-001@example.com>", "hearted": False},
    )
    assert cleared.status_code == 200
    assert client_one.get("/hearts").json() == {}


def test_heart_input_validation_and_url_normalization(tmp_path):
    client = TestClient(create_heart_app(HeartStore(tmp_path / "heart_sync.db")))
    assert client.put("/hearts", json={"mail_key": "", "hearted": True}).status_code == 422
    assert normalize_heart_server_url("192.168.0.10") == "http://192.168.0.10:54837"
    assert normalize_heart_server_url("http://192.168.0.10:54837/") == "http://192.168.0.10:54837"
