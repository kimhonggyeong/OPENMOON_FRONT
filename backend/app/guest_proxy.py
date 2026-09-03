from __future__ import annotations

import asyncio
import json
import queue
import threading
import shutil
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Iterable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool

from .config import runtime_root
from .services.excel_open_service import open_excel_location


_upstream = ""
_session_stopped = threading.Event()
_session_user = ""
_presence_lock = threading.Lock()


def set_guest_upstream(url: str, user_id: str = "") -> None:
    global _upstream, _session_stopped, _session_user
    _session_stopped.set()
    _session_stopped = threading.Event()
    _session_user = user_id
    _upstream = url.rstrip("/")


def stop_guest_upstream() -> None:
    _session_stopped.set()
    # Finish an already accepted heartbeat before the launcher removes presence.
    with _presence_lock:
        pass


def guest_temp_dir() -> Path:
    return runtime_root() / "backend" / "data" / "guest_temp"


def clear_guest_temp() -> None:
    path = guest_temp_dir()
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _upstream_target(path: str, query: str = "") -> str:
    target = f"{_upstream}/{path.lstrip('/')}"
    return f"{target}?{query}" if query else target


def _forward(
    method: str,
    path: str,
    query: str,
    body: bytes,
    headers: Iterable[tuple[str, str]],
) -> Response:
    target = _upstream_target(path, query)
    forwarded_headers = {
        key: value for key, value in headers
        if key.lower() not in {"host", "content-length", "accept-encoding", "connection"}
    }
    request = urllib.request.Request(target, data=body or None, method=method, headers=forwarded_headers)
    try:
        with urllib.request.urlopen(request, timeout=5 if path.rstrip("/") == "api/lan-presence" else 120) as remote:
            data = remote.read()
            content_type = remote.headers.get("Content-Type", "application/octet-stream")
            response_headers = {}
            if disposition := remote.headers.get("Content-Disposition"):
                response_headers["Content-Disposition"] = disposition
            return Response(data, status_code=remote.status, media_type=content_type.split(";", 1)[0], headers=response_headers)
    except urllib.error.HTTPError as error:
        return Response(error.read(), status_code=error.code, media_type=error.headers.get_content_type())
    except (OSError, urllib.error.URLError) as error:
        return JSONResponse(
            status_code=502,
            content={"detail": "서버에 연결할 수 없습니다. 서버 PC와 사내 네트워크 연결을 확인해 주세요."},
        )


app = FastAPI(title="OPENMOON Guest Proxy")


@app.middleware("http")
async def check_session(request: Request, call_next):
    user = request.headers.get("X-Openmoon-User") or request.query_params.get("user_id")
    if request.url.path.startswith("/api/") and (
        _session_stopped.is_set() or (_session_user and user is not None and user != _session_user)
    ):
        return JSONResponse(status_code=410, content={"detail": "서버 연결이 종료되었습니다. 실행 창에서 웹을 다시 열어 주세요."})
    return await call_next(request)


@app.get("/api/sync/events")
def proxy_sync_events(request: Request):
    target = _upstream_target("api/sync/events", request.url.query)
    stopped = _session_stopped
    finished = threading.Event()
    lines: queue.Queue = queue.Queue(maxsize=100)

    def read_remote():
        upstream_request = urllib.request.Request(
            target,
            method="GET",
            headers={"Accept": "text/event-stream"},
        )
        try:
            with urllib.request.urlopen(upstream_request, timeout=30) as remote:
                while not stopped.is_set() and not finished.is_set():
                    line = remote.readline()
                    if not line:
                        break
                    while not stopped.is_set() and not finished.is_set():
                        try:
                            lines.put(line, timeout=0.2)
                            break
                        except queue.Full:
                            pass
        except (OSError, urllib.error.URLError):
            pass
        finally:
            finished.set()

    async def stream():
        threading.Thread(target=read_remote, daemon=True).start()
        try:
            while not stopped.is_set():
                try:
                    yield lines.get_nowait()
                except queue.Empty:
                    if finished.is_set():
                        return
                    await asyncio.sleep(0.1)
            yield b'data: {"type":"disconnected"}\n\n'
        finally:
            finished.set()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/mails/history/open-source")
async def open_history_on_guest(request: Request):
    payload = await request.body()
    return await run_in_threadpool(_open_history_on_guest, payload)


def _open_history_on_guest(payload: bytes):
    try:
        values = json.loads(payload.decode("utf-8"))
        sheet = str(values.get("source_sheet") or "")
    except (ValueError, UnicodeDecodeError):
        return JSONResponse(status_code=400, content={"detail": "파일 요청 정보가 올바르지 않습니다."})

    target = f"{_upstream}/api/mails/history/source-file"
    remote_request = urllib.request.Request(
        target,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(remote_request, timeout=120) as remote:
            file_bytes = remote.read()
            disposition = remote.headers.get("Content-Disposition", "")
            remote_suffix = remote.headers.get("X-Openmoon-Suffix", "").lower()
    except urllib.error.HTTPError as error:
        return Response(error.read(), status_code=error.code, media_type=error.headers.get_content_type())
    except (OSError, urllib.error.URLError):
        return JSONResponse(status_code=502, content={"detail": "서버 파일을 내려받을 수 없습니다."})

    allowed_suffixes = {".xlsx", ".xlsm", ".xls", ".csv"}
    suffix = remote_suffix if remote_suffix in allowed_suffixes else ".xlsx"
    if not remote_suffix and ".xls" in disposition.lower() and ".xlsx" not in disposition.lower():
        suffix = ".xls"
    folder = guest_temp_dir()
    folder.mkdir(parents=True, exist_ok=True)
    local_path = folder / f"history_{uuid.uuid4().hex}{suffix}"
    local_path.write_bytes(file_bytes)
    try:
        result = open_excel_location(local_path, sheet=sheet)
        result["temporary_guest_copy"] = True
        return result
    except Exception as error:
        return JSONResponse(status_code=400, content={"detail": f"게스트 임시 파일 열기 실패: {error}"})


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_all(path: str, request: Request):
    if path.rstrip("/") == "api/lan-presence" and request.method == "PUT":
        body = await request.body()
        stopped = _session_stopped
        try:
            profile = json.loads(body)
            user_id = profile.get("user_id") if isinstance(profile, dict) else None
        except (ValueError, UnicodeDecodeError):
            return JSONResponse(status_code=400, content={"detail": "접속자 정보가 올바르지 않습니다."})

        def heartbeat():
            with _presence_lock:
                if stopped.is_set() or (_session_user and user_id != _session_user):
                    return JSONResponse(status_code=410, content={"detail": "서버 연결이 종료되었습니다."})
                return _forward(request.method, path, request.url.query, body, request.headers.items())

        return await run_in_threadpool(heartbeat)
    return await run_in_threadpool(
        _forward,
        request.method,
        path,
        request.url.query,
        await request.body(),
        request.headers.items(),
    )
