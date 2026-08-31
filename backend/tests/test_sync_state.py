import asyncio

from backend.app.sync_state import SyncState


def test_sync_state_revision_and_metadata():
    state = SyncState()

    assert state.snapshot() == {
        "revision": 0,
        "changed_at": None,
        "method": None,
        "path": None,
    }

    first = state.publish("PATCH", "/api/mails/7/analysis")
    second = state.publish("POST", "/api/quotations/from-mail/7")

    assert first["revision"] == 1
    assert second["revision"] == 2
    assert second["method"] == "POST"
    assert second["path"] == "/api/quotations/from-mail/7"
    assert second["changed_at"]


def test_successful_mutation_is_visible_to_all_clients(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.app.main import app
    from backend.app.routers import lan_hearts

    monkeypatch.setattr(
        lan_hearts.store,
        "set",
        lambda _mail_key, hearted: hearted,
    )

    with TestClient(app) as client:
        before = client.get("/api/sync/state").json()["revision"]
        response = client.put(
            "/api/lan-hearts",
            json={"mail_key": "sync-test", "hearted": True},
        )
        after = client.get("/api/sync/state").json()

    assert response.status_code == 200
    assert after["revision"] == before + 1
    assert after["method"] == "PUT"
    assert after["path"] == "/api/lan-hearts"


def test_sync_event_is_broadcast_to_subscriber():
    state = SyncState()
    queue = state.subscribe()
    payload = state.publish("POST", "/api/mails/9/chat")

    asyncio.run(state.broadcast(payload))

    assert queue.get_nowait()["path"] == "/api/mails/9/chat"
    state.unsubscribe(queue)
