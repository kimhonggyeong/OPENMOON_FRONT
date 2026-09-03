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


def test_heart_mutation_does_not_invalidate_business_data(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.app.main import app
    from backend.app.routers import lan_hearts

    monkeypatch.setattr(
        lan_hearts.store,
        "set",
        lambda _mail_key, hearted, **kwargs: {"hearted": hearted, **kwargs},
    )
    events = []

    async def capture(payload):
        events.append(payload)

    monkeypatch.setattr("backend.app.main.sync_state.broadcast", capture)

    with TestClient(app) as client:
        before = client.get("/api/sync/state").json()["revision"]
        response = client.put(
            "/api/lan-hearts",
            json={"mail_key": "sync-test", "hearted": True},
        )
        after = client.get("/api/sync/state").json()

    assert response.status_code == 200
    assert after["revision"] == before
    assert events == [{"type": "hearts"}]


def test_heart_stream_updates_all_clients_and_restores_on_reconnect(monkeypatch):
    from backend.app import main

    state = SyncState()
    monkeypatch.setattr(main, "sync_state", state)
    hearts = {}
    monkeypatch.setattr(main.lan_hearts.store, "all", lambda: dict(hearts))

    class Connected:
        async def is_disconnected(self):
            return False

    async def scenario():
        streams = []
        try:
            for _ in range(2):
                response = await main.sync_events(Connected())
                stream = response.body_iterator
                streams.append(stream)
                await anext(stream)  # Business revision handshake.
                assert '"hearts": {}' in await anext(stream)
            hearts["mail-1"] = {"hearted": True, "user_name": "Alice", "color": "#123456"}
            await state.broadcast({"type": "hearts"})
            for stream in streams:
                event = await asyncio.wait_for(anext(stream), 1)
                assert '"Alice"' in event
                assert '"#123456"' in event
            response = await main.sync_events(Connected())
            streams.append(response.body_iterator)
            await anext(streams[-1])
            assert '"Alice"' in await anext(streams[-1])
            hearts.clear()
            await state.broadcast({"type": "hearts"})
            for stream in streams:
                assert '"hearts": {}' in await asyncio.wait_for(anext(stream), 1)
            assert state.snapshot()["revision"] == 0
        finally:
            for stream in streams:
                await stream.aclose()
        assert not state._subscribers

    asyncio.run(scenario())


def test_sync_event_is_broadcast_to_subscriber():
    state = SyncState()
    queue = state.subscribe()
    payload = state.publish("POST", "/api/mails/9/chat")

    asyncio.run(state.broadcast(payload))

    assert queue.get_nowait()["path"] == "/api/mails/9/chat"
    state.unsubscribe(queue)
