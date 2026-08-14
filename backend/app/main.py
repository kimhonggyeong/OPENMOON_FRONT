from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .config import PROJECT_ROOT, get_settings
from .database import init_db
from .routers import agent, chat, imports, mails, quotations, reviews, settings

app_settings = get_settings()
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

app.include_router(mails.router)
app.include_router(reviews.router)
app.include_router(quotations.router)
app.include_router(imports.router)
app.include_router(settings.router)
app.include_router(chat.router)
app.include_router(agent.router)


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/api/health")
def health():
    return {"status": "ok"}


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
