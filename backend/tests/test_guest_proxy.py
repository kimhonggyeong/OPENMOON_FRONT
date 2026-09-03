from backend.app import guest_proxy


def test_download_keeps_original_filename_for_guest(monkeypatch):
    from io import BytesIO
    from urllib.parse import quote

    filename = "경남 견적서 고객용.pdf"
    disposition = f"attachment; filename*=utf-8''{quote(filename)}"

    class Remote(BytesIO):
        status = 200
        headers = {"Content-Type": "application/pdf", "Content-Disposition": disposition}

    monkeypatch.setattr(guest_proxy.urllib.request, "urlopen", lambda *args, **kwargs: Remote(b"pdf-content"))
    monkeypatch.setattr(guest_proxy, "_upstream", "http://unused")
    response = guest_proxy._forward("GET", "api/quotations/1/customer-pdf", "", b"", [])
    assert response.headers["content-disposition"] == disposition
    assert response.body == b"pdf-content"


def test_stopped_and_previous_session_requests_are_rejected(monkeypatch):
    from fastapi.testclient import TestClient
    from fastapi.responses import Response

    monkeypatch.setattr(guest_proxy, "_forward", lambda *args: Response("ok"))
    client = TestClient(guest_proxy.app)
    try:
        guest_proxy.set_guest_upstream("http://unused", "first")
        guest_proxy.stop_guest_upstream()
        assert client.get("/api/mails", headers={"X-Openmoon-User": "first"}).status_code == 410
        guest_proxy.set_guest_upstream("http://unused", "second")
        assert client.get("/api/mails", headers={"X-Openmoon-User": "first"}).status_code == 410
        assert client.put("/api/lan-presence", json={"user_id": "first"}).status_code == 410
        assert client.get("/api/mails", headers={"X-Openmoon-User": "second"}).status_code == 200
    finally:
        guest_proxy.set_guest_upstream("")


def test_shutdown_finishes_while_browser_stream_stays_open():
    import socket
    import threading
    import time
    import urllib.request
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import uvicorn

    finish = threading.Event()

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b'data: {"revision":1}\n\n')
            self.wfile.flush()
            finish.wait(5)  # Upstream remains silent and open during shutdown.

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    guest_proxy.set_guest_upstream(f"http://127.0.0.1:{upstream.server_port}")
    server = uvicorn.Server(uvicorn.Config(guest_proxy.app, log_config=None, access_log=False, timeout_graceful_shutdown=2))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    client = None
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        assert server.started
        client = urllib.request.urlopen(f"http://127.0.0.1:{sock.getsockname()[1]}/api/sync/events", timeout=3)
        assert b"revision" in client.readline()
        guest_proxy.stop_guest_upstream()
        server.should_exit = True
        thread.join(3)
        assert not thread.is_alive()
        assert b'"disconnected"' in client.read()
    finally:
        if client:
            client.close()
        finish.set()
        server.should_exit = True
        server.force_exit = True
        thread.join(3)
        upstream.shutdown()
        upstream.server_close()
        sock.close()
        guest_proxy.set_guest_upstream("")


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
