# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import shutil
from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH)

datas = [
    (str(root / "frontend" / "dist"), "frontend/dist"),
    (str(root / "backend" / "data" / "templates"), "backend/data/templates"),
    (str(root / "backend" / "data" / "source"), "backend/data/source"),
    (str(root / "backend" / "assets" / "email_signatures"), "backend/assets/email_signatures"),
    (str(root / "config"), "config"),
    (str(root / ".env.example"), "."),
]

hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    *collect_submodules("backend.app"),
]

a = Analysis(
    ["launcher.py"],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OPENMOON_AI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="OPENMOON_AI",
)

# Business data is intentionally external to _internal. The program resolves
# these paths from the directory containing OPENMOON_AI.exe, so the complete
# folder can be moved to another PC without changing user-specific paths.
portable_root = Path(DISTPATH) / "OPENMOON_AI"
shutil.copytree(
    root / "backend" / "data",
    portable_root / "backend" / "data",
    dirs_exist_ok=True,
)
