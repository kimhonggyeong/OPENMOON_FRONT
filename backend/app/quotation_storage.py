"""Host-only storage configuration; business databases stay local."""
from __future__ import annotations

import json
import os
import threading
import uuid
from functools import wraps
from functools import lru_cache
import time
from pathlib import Path

storage_lock = threading.RLock()


def selected_roots(settings):
    root = settings.quotation_files_path.resolve()
    years = getattr(settings, "quotation_year_folders", {})
    return [root / folder for folder in years.values()] if years else [root]


@lru_cache(maxsize=4)
def _source_catalog(roots, time_bucket):
    import os
    catalog = {}
    for text in roots:
        root = Path(text)
        if not root.is_dir():
            raise FileNotFoundError(f"견적서 저장소에 연결할 수 없습니다: {root}")
        def fail(error):
            raise error
        for directory, _, names in os.walk(root, onerror=fail, followlinks=False):
            for name in names:
                path = Path(directory) / name
                if path.suffix.lower() not in {".xlsx", ".xlsm"} or name.startswith(("~$", ".")):
                    continue
                if path.resolve().is_relative_to(root):
                    catalog.setdefault(name.casefold(), []).append(path.resolve())
    return catalog


def clear_source_cache():
    _source_catalog.cache_clear()


def selected_source_path(settings, original):
    """Resolve only within the host-selected folders, never fall back to an old local copy."""
    roots = selected_roots(settings)
    mapped = relocated_path(settings, original).resolve()
    if any(mapped.is_relative_to(root) for root in roots) and mapped.is_file():
        return mapped
    catalog = _source_catalog(tuple(str(root) for root in roots), int(time.monotonic() // 30))
    matches = [path for path in catalog.get(Path(original).name.casefold(), []) if path.is_file()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise FileNotFoundError(f"설정된 저장소에 같은 이름의 파일이 여러 개 있습니다: {Path(original).name}")
    raise FileNotFoundError(f"설정된 견적서 저장소에서 파일을 찾을 수 없습니다: {Path(original).name}")


def storage_operation(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        with storage_lock:
            return function(*args, **kwargs)
    return guarded


def settings_path():
    from .config import runtime_root
    return runtime_root() / "backend" / "data" / "quotation_storage.json"


def load_storage(settings):
    path = settings_path()
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        root, years = validate_storage(data["root"], data["years"])
        settings.quotation_files_path = root
        settings.quotation_year_folders = years
        settings.quotation_path_aliases = data.get("aliases", {})


def validate_storage(root_text, years):
    if not str(root_text).strip():
        raise ValueError("NAS 또는 견적서 기본 폴더를 입력해주세요.")
    root = Path(str(root_text).strip()).expanduser()
    if not root.is_absolute():
        raise ValueError("전체 폴더 경로를 입력해주세요. 예: \\\\192.168.0.29\\backup-1\\1. 견적서")
    root = root.resolve()
    cleaned = {}
    for year, folder in years.items():
        if not str(year).isdigit() or not 1900 <= int(year) <= 2199:
            raise ValueError("연도는 1900~2199 범위의 네 자리 숫자로 입력해주세요.")
        relative = Path(str(folder).strip())
        if not str(folder).strip() or relative.is_absolute() or ".." in relative.parts or relative == Path("."):
            raise ValueError(f"{year}년 폴더는 기본 폴더 안의 하위 폴더로 지정해주세요.")
        (root / relative).resolve().relative_to(root)
        cleaned[str(int(year))] = str(relative)
    if len(set(value.casefold() for value in cleaned.values())) != len(cleaned):
        raise ValueError("서로 다른 연도에 같은 폴더를 지정할 수 없습니다.")
    return root, cleaned


def check_storage(root_text, years):
    root, years = validate_storage(root_text, years)
    for folder in [root, *(root / name for name in years.values())]:
        if not folder.is_dir():
            raise ValueError(f"폴더가 없거나 연결할 수 없습니다: {folder}\n폴더 찾아보기에서 폴더를 만들거나 선택해주세요.")
        # Actually enumerate and create/read/delete a unique probe; os.access is insufficient on SMB.
        next(folder.iterdir(), None)
        probe = folder / f".openmoon-check-{uuid.uuid4().hex}.tmp"
        try:
            with probe.open("xb") as stream:
                stream.write(b"OPENMOON")
            if probe.read_bytes() != b"OPENMOON":
                raise OSError("쓰기 확인에 실패했습니다.")
        finally:
            probe.unlink(missing_ok=True)
    return root, years


def save_storage(settings, root_text, years):
    if not storage_lock.acquire(blocking=False):
        raise ValueError("견적서를 처리 중입니다. 처리가 끝난 뒤 다시 적용해주세요.")
    try:
        root, years = check_storage(root_text, years)
        aliases = dict(settings.quotation_path_aliases)
        changes = {}
        old_root = settings.quotation_files_path
        if old_root != root:
            changes[str(old_root)] = str(root)
        for year, folder in settings.quotation_year_folders.items():
            if year in years:
                old, new = old_root / folder, root / years[year]
                if old != new:
                    changes[str(old)] = str(new)
        for source, destination in list(aliases.items()):
            for old, new in sorted(changes.items(), key=lambda row: -len(row[0])):
                try:
                    aliases[source] = str(Path(new) / Path(destination).relative_to(Path(old)))
                    break
                except ValueError:
                    continue
        aliases.update(changes)
        aliases = {old: new for old, new in aliases.items() if old != new}
        data = {"root": str(root), "years": years, "aliases": aliases}
        path = settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
        settings.quotation_files_path = root
        settings.quotation_year_folders = years
        settings.quotation_path_aliases = aliases
        clear_source_cache()
    finally:
        storage_lock.release()


def year_root(settings, year):
    years = getattr(settings, "quotation_year_folders", {})
    if not years:
        return settings.quotation_files_path
    folder = years.get(str(year))
    if folder is None:
        raise ValueError(f"{year}년 견적서 폴더가 없습니다. 서버장의 저장소 설정에서 연도를 추가해주세요.")
    result = settings.quotation_files_path / folder
    if not result.is_dir():
        raise ValueError(f"{year}년 저장 폴더에 연결할 수 없습니다: {result}")
    return result


def relocated_path(settings, original):
    path = Path(original)
    visited = set()
    while str(path) not in visited:
        visited.add(str(path))
        for old, new in sorted(getattr(settings, "quotation_path_aliases", {}).items(), key=lambda row: -len(row[0])):
            try:
                relative = path.relative_to(Path(old))
            except ValueError:
                continue
            candidate = Path(new) / relative
            if candidate == path:
                continue
            path = candidate
            break
        else:
            break
    return path
