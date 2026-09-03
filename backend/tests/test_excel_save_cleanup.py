import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

from backend.app.services import quotation_service as q


def make_saved_file(path, marker="OPENMOON:7"):
    book = Workbook()
    book.active.title = "견적"
    book.active["T1"] = marker
    book.save(path)
    book.close()
    Path(str(path) + ".saved.json").write_text(
        json.dumps({"sheet": "견적", "marker": marker}), encoding="utf-8-sig"
    )


def test_saved_workbook_must_match_receipt(tmp_path):
    path = tmp_path / "quote.xlsx"
    make_saved_file(path)
    q._verify_native_excel_save(path, "OPENMOON:7")
    with pytest.raises(RuntimeError, match="저장 결과 확인"):
        q._verify_native_excel_save(path, "OPENMOON:8")
    Path(str(path) + ".saved.json").unlink()
    with pytest.raises(RuntimeError, match="저장 결과 확인"):
        q._verify_native_excel_save(path, "OPENMOON:7")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Excel wrapper")
@pytest.mark.parametrize("outcome", ["cleanup_warning", "save_failure", "unverified_save"])
def test_only_verified_save_is_published(tmp_path, monkeypatch, outcome):
    target = tmp_path / "target.xlsx"
    target.write_bytes(b"original unchanged")
    template = tmp_path / "template.xlsx"
    Workbook().save(template)
    settings = SimpleNamespace(quotation_template_path=template, quotation_template_sheet="Sheet",
                               default_delivery_place="", default_payment_terms="", default_validity="")
    mail = SimpleNamespace(id=7, customer_organization="", customer_name="고객", customer_department="",
                           delivery_place="", payment_terms="", customer_phone="", customer_email="",
                           original_sender_email="", items=[])
    monkeypatch.setattr(q, "_sheet_base_name", lambda *_: "견적")

    def fake_excel(args, **kwargs):
        native = Path(args[args.index("-TargetPath") + 1])
        make_saved_file(native, f"{q.MAIL_MARKER_PREFIX}7")
        if outcome == "unverified_save":
            Path(str(native) + ".saved.json").unlink()
        return subprocess.CompletedProcess(args, 1 if outcome == "save_failure" else 0, "",
                                           "[견적 파일 저장] failed" if outcome == "save_failure" else "Excel cleanup warning")

    monkeypatch.setattr(q.subprocess, "run", fake_excel)
    if outcome == "cleanup_warning":
        q._save_with_native_excel(target, settings, mail, [], 0, True, datetime.now())
        assert target.read_bytes().startswith(b"PK")
    else:
        with pytest.raises(RuntimeError):
            q._save_with_native_excel(target, settings, mail, [], 0, True, datetime.now())
        assert target.read_bytes() == b"original unchanged"


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell COM error handling")
def test_powershell_retry_and_cleanup_preserve_primary_error(tmp_path):
    helpers = q.EXCEL_COM_SCRIPT.split("function Set-ExcelValue", 1)[0].split("$ErrorActionPreference", 1)[1]
    script = '$ErrorActionPreference' + helpers + r'''
function Start-Sleep { param($Milliseconds) }
$script:attempts = 0
$result = Invoke-ExcelCall {
    $script:attempts++
    if ($script:attempts -lt 3) {
        throw [Runtime.InteropServices.COMException]::new("busy", -2147418111)
    }
    return "saved"
}
if ($result -ne "saved" -or $script:attempts -ne 3) { throw "retry failed" }
$script:attempts = 0
$script:quitAttempted = $false
try {
    try { throw "original save failure" }
    finally {
        Invoke-ExcelCleanup "close" {
            $script:attempts++
            throw [Runtime.InteropServices.COMException]::new("busy", -2147418111)
        }
        Invoke-ExcelCleanup "quit" { $script:quitAttempted = $true }
    }
} catch {
    if ($_.Exception.Message -ne "original save failure") { throw "primary error replaced" }
}
if (-not $script:quitAttempted -or $script:attempts -ne 21) { throw "cleanup failed" }
$script:attempts = 0
try {
    Invoke-ExcelCall { $script:attempts++; throw "ordinary failure" }
} catch { }
if ($script:attempts -ne 1) { throw "unexpected retry" }
Write-Output "OK"
'''
    path = tmp_path / "test.ps1"
    path.write_text(script, encoding="utf-8-sig")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-File", str(path)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
