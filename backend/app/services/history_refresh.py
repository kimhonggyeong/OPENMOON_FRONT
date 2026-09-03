"""Refresh the local search DB from the host's selected source folders."""
from __future__ import annotations

import logging
import asyncio
import sqlite3
import tempfile
import threading
from contextlib import closing
from pathlib import Path
from collections import defaultdict

from ..quotation_storage import storage_lock, selected_roots, clear_source_cache
from . import quotation_history_parser as parser
from .quotation_history_parser_fixes import install_parser_fixes

install_parser_fixes(parser)
_running = threading.Lock()
_event_loop = None
_state = {"status": "idle", "message": "과거 견적 갱신 대기", "processed": 0, "total": 0}


def refresh_status():
    state = dict(_state)
    completed = sum(state.get(key, 0) for key in ("parsed", "relocated", "unchanged", "metadata_updated"))
    state["completed"] = completed
    state["percent"] = round(100 * completed / state["total"], 1) if state.get("total") else None
    return state


def _version(path):
    stat = path.stat()
    return stat.st_mtime, stat.st_size


def refresh_history(settings, stopping=None, excluded_mail_ids=()):
    if not _running.acquire(blocking=False):
        return refresh_status()
    try:
        with storage_lock:
            _state.update(status="running", message="과거 견적 폴더 확인 중", processed=0, total=0,
                          parsed=0, relocated=0, unchanged=0, metadata_updated=0, removed=0,
                          phase="scanning", discovered=0, current_file="")
            roots = selected_roots(settings)
            parser.excluded_markers = {f"OPENMOON_MAIL_ID:{value}" for value in excluded_mail_ids}
            files = []
            for root in roots:
                if not root.is_dir():
                    raise FileNotFoundError(f"견적서 폴더에 연결할 수 없습니다: {root}")
                # os.walk propagates access errors instead of treating an unreadable folder as empty.
                import os
                def fail(error):
                    raise error
                for directory, _, names in os.walk(root, onerror=fail, followlinks=False):
                    for name in names:
                        path = Path(directory) / name
                        if path.suffix.lower() in {".xlsx", ".xlsm"} and not name.startswith(("~$", ".", "!")):
                            if path.resolve().is_relative_to(root.resolve()):
                                files.append(path.resolve())
                                _state["discovered"] = len(files)
            files = sorted(set(files))
            if not files:
                raise ValueError("지정된 폴더에서 견적 Excel을 찾지 못했습니다.")
            _state.update(total=len(files), phase="preparing", message="기존 검색 DB 준비 중")
            database = settings.quotation_database_path
            database.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="om-history-") as temporary:
                candidate = Path(temporary) / "history.db"
                with closing(sqlite3.connect(candidate)) as work:
                    if database.exists():
                        with closing(sqlite3.connect(database)) as original:
                            original.backup(work)
                    work.execute("PRAGMA foreign_keys=ON")
                    parser.create_schema(work)
                    work.row_factory = sqlite3.Row
                    existing = {row["file_path"]: row for row in work.execute("SELECT * FROM source_files")}
                    selected = {str(path) for path in files}
                    movable = defaultdict(list)
                    for old_path, row in existing.items():
                        # A copy that still exists in the selected folders must keep its own records.
                        if old_path not in selected and row["file_hash"]:
                            movable[(row["file_hash"], row["file_size"])].append(row)
                    moved_ids = set()
                    changed = not database.exists()
                    _state.update(total=len(files))
                    versions = {}
                    for index, path in enumerate(files, 1):
                        if stopping is not None and stopping.is_set():
                            raise RuntimeError("서버 종료로 갱신을 중단했습니다.")
                        _state.update(processed=index, phase="checking", current_file=path.name,
                                      message=f"과거 견적 확인 중 {index}/{len(files)} · {path.name}")
                        version = _version(path)
                        versions[path] = version
                        previous = existing.get(str(path))
                        if previous and (previous["modified_time"], previous["file_size"]) == version:
                            _state["unchanged"] += 1
                            continue
                        _state["message"] = f"기존 DB와 파일 내용 비교 중 {index}/{len(files)} · {path.name}"
                        digest = parser.calculate_file_hash(path)
                        if _version(path) != version:
                            raise ValueError(f"내용 비교 중 파일이 변경되었습니다: {path.name}")
                        if previous and previous["file_hash"] == digest:
                            work.execute("UPDATE source_files SET modified_time=?, file_size=? WHERE id=?",
                                         (*version, previous["id"]))
                            changed = True
                            _state["metadata_updated"] += 1
                            continue
                        matches = movable.get((digest, version[1]), [])
                        if previous is None and len(matches) == 1 and matches[0]["id"] not in moved_ids:
                            old = matches[0]
                            # Preserve quotation/item IDs and parsed content; only the source location changed.
                            work.execute("UPDATE source_files SET file_path=?, file_name=?, modified_time=?, file_size=? WHERE id=?",
                                         (str(path), path.name, *version, old["id"]))
                            moved_ids.add(old["id"])
                            changed = True
                            _state["relocated"] += 1
                            continue
                        _state["message"] = f"새 파일·변경 파일 분석 중 {index}/{len(files)} · {path.name}"
                        _state["phase"] = "analyzing"
                        quotations = parser.parse_excel_file(path, digest)
                        if any(q.parse_status == "error" for q in quotations):
                            raise ValueError(f"견적 해석 실패: {path.name}: " + "; ".join(q.parse_error or "" for q in quotations if q.parse_status == "error"))
                        accepted = [q for q in quotations if q.items]
                        if previous and not accepted:
                            raise ValueError(f"기존 견적의 품목을 읽지 못했습니다: {path.name}")
                        parser.save_file_results(work, path, digest, accepted)
                        changed = True
                        _state["parsed"] += 1
                        if _version(path) != version:
                            raise ValueError(f"갱신 중 파일이 변경되었습니다: {path.name}")
                    _state.update(phase="validating", current_file="", message="파일 확인 완료 · 갱신 결과 검증 중")
                    for old_path, row in existing.items():
                        if old_path not in selected and row["id"] not in moved_ids:
                            work.execute("DELETE FROM source_files WHERE id=?", (row["id"],))
                            changed = True
                            _state["removed"] += 1
                    work.commit()
                    if any(_version(path) != version for path, version in versions.items()):
                        raise ValueError("갱신 중 견적 파일이 변경되었습니다. 다시 갱신해주세요.")
                    if stopping is not None and stopping.is_set():
                        raise RuntimeError("서버 종료로 갱신을 중단했습니다.")
                    if work.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise ValueError("갱신 DB 검증에 실패했습니다.")
                    if not work.execute("SELECT COUNT(*) FROM quotations").fetchone()[0]:
                        raise ValueError("읽을 수 있는 견적이 없어 기존 검색 DB를 유지합니다.")
                    # SQLite backup publishes transactionally, including on Windows with readers open.
                    if changed:
                        _state.update(phase="publishing", message="파일 확인 완료 · 최종 DB 반영 중")
                        with closing(sqlite3.connect(database, timeout=30)) as live:
                            work.backup(live)
            clear_source_cache()
            _state.update(status="complete", phase="complete", current_file="", message=(
                f"과거 견적 갱신 완료 · 새로 분석 {_state['parsed']}개 / 경로만 변경 {_state['relocated']}개 / "
                f"내용 유지 {_state['unchanged'] + _state['metadata_updated']}개 / 목록 제외 {_state['removed']}개"))
            if _event_loop is not None and not _event_loop.is_closed():
                try:
                    from ..sync_state import sync_state
                    payload = sync_state.publish("POST", "/api/import/quotation-history")
                    _event_loop.call_soon_threadsafe(lambda: asyncio.create_task(sync_state.broadcast(payload)))
                except RuntimeError:
                    logging.getLogger(__name__).warning("History updated after server event loop stopped")
    except Exception as error:
        _state.update(status="failed", message=f"과거 견적 갱신 실패 · 기존 DB 유지: {error}")
        logging.getLogger(__name__).exception("History refresh failed")
    finally:
        _running.release()
    return refresh_status()


def start_history_refresh(settings, stopping=None):
    global _event_loop
    try:
        _event_loop = asyncio.get_running_loop()
    except RuntimeError:
        pass
    def run():
        from ..database import SessionLocal
        from ..models import QuotationDraft
        from sqlalchemy import select
        try:
            with SessionLocal() as session:
                excluded = session.scalars(select(QuotationDraft.mail_id).where(QuotationDraft.status != "SENT")).all()
            refresh_history(settings, stopping, excluded)
        except Exception as error:
            _state.update(status="failed", message=f"과거 견적 갱신 실패 · 기존 DB 유지: {error}")
            logging.getLogger(__name__).exception("Unable to start history refresh")
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread
