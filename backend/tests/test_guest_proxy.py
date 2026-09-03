from backend.app import guest_proxy


def test_slow_forward_does_not_block_realtime_events(monkeypatch):
    import asyncio
    import threading
    from types import SimpleNamespace
    from fastapi.responses import Response

    started = threading.Event()
    release = threading.Event()

    def slow_forward(*args):
        started.set()
        release.wait(2)
        return Response("ok")

    monkeypatch.setattr(guest_proxy, "_forward", slow_forward)

    class Request:
        method = "GET"
        url = SimpleNamespace(query="")
        headers = {}

        async def body(self):
            return b""

    async def scenario():
        task = asyncio.create_task(guest_proxy.proxy_all("api/mails", Request()))
        try:
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(0.01)
            assert started.is_set()
            # SSE delivery must be able to run while forwarding is still waiting.
            assert not task.done()
        finally:
            release.set()
            await task

    asyncio.run(scenario())


def test_upstream_target_preserves_company_scope_query():
    guest_proxy.set_guest_upstream("http://192.168.0.10:54837")

    target = guest_proxy._upstream_target(
        "/api/mails/31/history",
        "scope=company",
    )

    assert target == (
        "http://192.168.0.10:54837/"
        "api/mails/31/history?scope=company"
    )


def test_upstream_target_preserves_encoded_search_and_filter():
    guest_proxy.set_guest_upstream("http://192.168.0.10:54837/")

    target = guest_proxy._upstream_target(
        "api/mails",
        "status=REVIEW_REQUIRED&search=%EC%B6%A9%EB%82%A8",
    )

    assert target.endswith(
        "/api/mails?status=REVIEW_REQUIRED&search=%EC%B6%A9%EB%82%A8"
    )
