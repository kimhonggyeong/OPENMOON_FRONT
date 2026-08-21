from __future__ import annotations

import subprocess
import shutil

import pytest

from backend.app.services.quotation_service import (
    CUSTOMER_PDF_EXPORT_SCRIPT,
    CUSTOMER_PRIVATE_CELLS,
)


def test_customer_private_cells_are_removed():
    assert CUSTOMER_PRIVATE_CELLS == (
        "L5",
        "L6",
        "L7",
    )
    for cell in CUSTOMER_PRIVATE_CELLS:
        assert f'"{cell}"' in CUSTOMER_PDF_EXPORT_SCRIPT


def test_customer_pdf_clears_internal_column():
    assert "Columns.Item(20).ClearContents()" in CUSTOMER_PDF_EXPORT_SCRIPT
    assert "Columns.Item(20).Hidden = $true" in CUSTOMER_PDF_EXPORT_SCRIPT


def test_customer_pdf_exports_single_sheet():
    assert "ExportAsFixedFormat" in CUSTOMER_PDF_EXPORT_SCRIPT
    assert "$sheet.ExportAsFixedFormat" in CUSTOMER_PDF_EXPORT_SCRIPT


def test_customer_pdf_export_script_is_valid_powershell():
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is not available")

    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "$scriptText = $input | Out-String; $errors=$null; "
            "[void][System.Management.Automation.Language.Parser]::ParseInput(" 
            "$scriptText, [ref]$null, [ref]$errors); "
            "if ($errors.Count) { $errors | ForEach-Object Message; exit 1 }",
        ],
        input=CUSTOMER_PDF_EXPORT_SCRIPT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0, result.stdout or result.stderr
