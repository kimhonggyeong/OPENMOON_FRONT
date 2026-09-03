from pathlib import Path
import pytest
from backend.app.services import quotation_service as q


def test_excel_export_does_not_require_pdf_template(monkeypatch):
    monkeypatch.setattr(q, "_export_customer_pdf_python", lambda *_a, **_k: pytest.fail("PDF template fallback must not run"))
    expected = Path("customer.pdf")
    monkeypatch.setattr(q, "_export_customer_pdf_with_excel", lambda *_: expected)
    assert q._export_customer_pdf(None, None, Path("quotation.xlsx"), None) == expected


def test_excel_failure_is_actionable_without_template_fallback(monkeypatch):
    def fail(*_):
        raise RuntimeError("Excel unavailable")
    monkeypatch.setattr(q, "_export_customer_pdf_with_excel", fail)
    monkeypatch.setattr(q, "_export_customer_pdf_python", lambda *_a, **_k: pytest.fail("PDF template fallback must not run"))
    with pytest.raises(RuntimeError, match="Microsoft Excel") as error:
        q._export_customer_pdf(None, None, Path("quotation.xlsx"), None)
    assert "quotation_customer_template.pdf" not in str(error.value)
