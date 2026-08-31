from __future__ import annotations

import json
import shutil
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Iterable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .config import runtime_root
from .services.excel_open_service import open_excel_location


_upstream = ""


def set_guest_upstream(url: str) -> None:
    global _upstream
    _upstream = url.rstrip("/")


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
        with urllib.request.urlopen(request, timeout=120) as remote:
            data = remote.read()
            content_type = remote.headers.get("Content-Type", "application/octet-stream")
            return Response(data, status_code=remote.status, media_type=content_type.split(";", 1)[0])
    except urllib.error.HTTPError as error:
        return Response(error.read(), status_code=error.code, media_type=error.headers.get_content_type())
    except (OSError, urllib.error.URLError) as error:
        return JSONResponse(
            status_code=502,
            content={"detail": "서버에 연결할 수 없습니다. 서버 PC와 사내 네트워크 연결을 확인해 주세요."},
        )


app = FastAPI(title="OPENMOON Guest Proxy")


@app.get("/api/sync/events")
def proxy_sync_events(request: Request):
    target = _upstream_target("api/sync/events", request.url.query)

    def stream():
        upstream_request = urllib.request.Request(
            target,
            method="GET",
            headers={"Accept": "text/event-stream"},
        )
        while True:
            try:
                with urllib.request.urlopen(upstream_request, timeout=30) as remote:
                    while True:
                        line = remote.readline()
                        if not line:
                            break
                        yield line
            except (OSError, urllib.error.URLError):
                return

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
    return _forward(
        request.method,
        path,
        request.url.query,
        await request.body(),
        request.headers.items(),
    )
