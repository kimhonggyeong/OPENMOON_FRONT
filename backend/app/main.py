from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.concurrency import run_in_threadpool

from .config import PROJECT_ROOT, get_settings
from .database import init_db
from .routers import agent, chat, data_admin, general_chat, imports, lan_hearts, lan_presence, mails, products, quotations, reviews, settings
from .sync_state import sync_state

app_settings = get_settings()
server_stopping = threading.Event()
app = FastAPI(
    title=app_settings.app_name,
    version="0.1.0",
    description="메일·첨부파일·기존 견적·단가표 기반 견적 업무 보조 API",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def publish_lan_changes(request: Request, call_next):
    if server_stopping.is_set() and request.url.path.startswith("/api/") and request.method != "DELETE":
        return JSONResponse(status_code=410, content={"detail": "서버 연결이 종료되었습니다."})
    response = await call_next(request)
    if (
        request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and request.url.path.startswith("/api/")
        and response.status_code < 400
    ):
        # Hearts do not invalidate mail, pricing or chat data.
        payload = (
            {"type": "hearts"}
            if request.url.path == "/api/lan-hearts"
            else sync_state.publish(request.method, request.url.path)
        )
        await sync_state.broadcast(payload)
    return response

app.include_router(mails.router)
app.include_router(products.router)
app.include_router(reviews.router)
app.include_router(quotations.router)
app.include_router(imports.router)
app.include_router(settings.router)
app.include_router(chat.router)
app.include_router(general_chat.router)
app.include_router(agent.router)
app.include_router(lan_hearts.router)
app.include_router(lan_presence.router)
app.include_router(data_admin.router)


@app.on_event("startup")
async def startup() -> None:
    server_stopping.clear()
    init_db()
    from .services.history_refresh import start_history_refresh
    start_history_refresh(app_settings, server_stopping)


@app.get("/api/quotation-storage/history-status")
def history_refresh_status():
    from .services.history_refresh import refresh_status
    return refresh_status()


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/sync/state")
def get_sync_state():
    return sync_state.snapshot()


@app.get("/api/sync/events")
async def sync_events(request: Request):
    queue = sync_state.subscribe()

    async def event_stream():
        try:
            initial = json.dumps(sync_state.snapshot(), ensure_ascii=False)
            yield f"data: {initial}\n\n"
            hearts = await run_in_threadpool(lan_hearts.store.all)
            yield f"data: {json.dumps({'type': 'hearts', 'hearts': hearts}, ensure_ascii=False)}\n\n"
            while not await request.is_disconnected():
                if server_stopping.is_set():
                    yield 'data: {"type":"disconnected"}\n\n'
                    return
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=1)
                    if payload.get("type") == "hearts":
                        # Read current state at delivery time, including after queued changes.
                        payload = {"type": "hearts", "hearts": await run_in_threadpool(lan_hearts.store.all)}
                    data = json.dumps(payload, ensure_ascii=False)
                    yield f"data: {data}\n\n"
                except TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            sync_state.unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


frontend_dist = PROJECT_ROOT / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        candidate = frontend_dist / full_path
        if full_path and candidate.exists() and candidate.is_file():
            from fastapi.responses import FileResponse

            return FileResponse(candidate)
        return HTMLResponse((frontend_dist / "index.html").read_text(encoding="utf-8"))
else:

    @app.get("/", response_class=HTMLResponse)
    def root():
        return """
        <html><body style='font-family:sans-serif;padding:40px'>
        <h1>YullinMoon AI 백엔드 실행 중</h1>
        <p>프론트엔드가 아직 빌드되지 않았습니다.</p>
        <p><a href='/docs'>API 문서 열기</a></p>
        <p>frontend 폴더에서 <code>npm install && npm run build</code>를 실행하세요.</p>
        </body></html>
        """
