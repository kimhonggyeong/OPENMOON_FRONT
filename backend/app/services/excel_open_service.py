from __future__ import annotations

import base64
import json
import os
import subprocess
from pathlib import Path
from typing import Any


def _ps_quote(value: str) -> str:
    return value.replace("'", "''")


def _open_in_file_explorer(path: Path) -> dict[str, Any]:
    subprocess.Popen(
        ["explorer.exe", f'/select,"{path}"'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {
        "opened": False,
        "mode": "file_explorer",
        "navigation_supported": False,
        "file_path": str(path),
        "sheet": None,
        "cell": None,
        "warning": (
            "Microsoft Excel 또는 XLSX 기본 연결 프로그램으로 파일을 열 수 없어 "
            "파일 위치를 탐색기에서 표시했습니다."
        ),
    }


def _open_with_default_app(path: Path) -> dict[str, Any]:
    try:
        os.startfile(str(path))  # type: ignore[attr-defined]
        return {
            "opened": True,
            "mode": "default_viewer",
            "navigation_supported": False,
            "file_path": str(path),
            "sheet": None,
            "cell": None,
            "warning": (
                "Microsoft Excel이 없어 기본 XLSX 연결 프로그램으로 열었습니다. "
                "이 모드에서는 지정 시트/셀 자동 이동을 보장할 수 없습니다."
            ),
        }
    except OSError:
        return _open_in_file_explorer(path)


def _run_excel_com(
    path: Path,
    *,
    sheet: str,
    cell: str,
) -> dict[str, Any] | None:
    script = f"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$path = '{_ps_quote(str(path))}'
$sheetName = '{_ps_quote(sheet)}'
$cellAddress = '{_ps_quote(cell)}'

try {{
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $true
    $workbook = $excel.Workbooks.Open($path)

    $resolvedSheet = $null
    $resolvedCell = $null

    if ($sheetName) {{
        try {{
            $worksheet = $workbook.Worksheets.Item($sheetName)
            $worksheet.Activate()
            $resolvedSheet = $sheetName

            if ($cellAddress) {{
                try {{
                    $worksheet.Range($cellAddress).Select()
                    $resolvedCell = $cellAddress
                }} catch {{
                }}
            }}
        }} catch {{
        }}
    }}

    @{{
        ok = $true
        mode = 'excel_com'
        navigation_supported = $true
        sheet = $resolvedSheet
        cell = $resolvedCell
    }} | ConvertTo-Json -Compress
}} catch {{
    @{{
        ok = $false
        mode = 'excel_com_unavailable'
        navigation_supported = $false
        error = $_.Exception.Message
    }} | ConvertTo-Json -Compress
}}
""".strip()

    encoded = base64.b64encode(
        script.encode("utf-16le")
    ).decode("ascii")

    creationflags = getattr(
        subprocess,
        "CREATE_NO_WINDOW",
        0,
    )

    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                encoded,
            ],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            creationflags=creationflags,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    output = (completed.stdout or "").strip()
    if not output:
        return None

    candidate = output.splitlines()[-1].strip()
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return None

    if not payload.get("ok"):
        return None

    return {
        "opened": True,
        "mode": "excel_com",
        "navigation_supported": True,
        "file_path": str(path),
        "sheet": payload.get("sheet"),
        "cell": payload.get("cell"),
        "warning": None,
    }


def open_excel_location(
    file_path: Path | str,
    *,
    sheet: str | None = None,
    cell: str | None = None,
) -> dict[str, object]:
    path = Path(file_path).expanduser().resolve()

    if not path.exists() or not path.is_file():
        raise FileNotFoundError(
            f"Excel 파일을 찾을 수 없습니다: {path}"
        )

    if os.name != "nt":
        raise RuntimeError(
            "가격표 열기는 Windows 회사 PC에서만 지원합니다."
        )

    normalized_sheet = (sheet or "").strip()
    normalized_cell = (cell or "").strip()

    if normalized_sheet or normalized_cell:
        excel_result = _run_excel_com(
            path,
            sheet=normalized_sheet,
            cell=normalized_cell,
        )
        if excel_result is not None:
            if normalized_sheet and not excel_result.get("sheet"):
                excel_result["warning"] = (
                    f"가격표는 Excel에서 열었지만 '{normalized_sheet}' 시트를 "
                    "자동으로 찾지 못했습니다."
                )
            elif normalized_cell and not excel_result.get("cell"):
                excel_result["warning"] = (
                    f"가격표와 '{normalized_sheet}' 시트는 열었지만 "
                    f"'{normalized_cell}' 셀을 자동 선택하지 못했습니다."
                )
            return excel_result

    viewer_result = _open_with_default_app(path)

    if viewer_result["mode"] == "default_viewer":
        viewer_result["sheet"] = normalized_sheet or None
        viewer_result["cell"] = normalized_cell or None
        if normalized_sheet or normalized_cell:
            viewer_result["warning"] = (
                "Microsoft Excel이 설치되어 있지 않아 기본 XLSX 뷰어로 "
                "가격표 파일을 열었습니다. "
                f"요청 위치: {normalized_sheet or '-'}"
                + (
                    f" / {normalized_cell}"
                    if normalized_cell
                    else ""
                )
                + ". 뷰어에서는 시트/셀 자동 이동이 지원되지 않을 수 있습니다."
            )

    return viewer_result
