import zipfile
from backend.app.services.quotation_service import _normalize_excel_text_whitespace


def test_preserves_legacy_linebreaks_without_rewriting_other_parts(tmp_path):
    path = tmp_path / "legacy.xlsx"
    sheet = b'<worksheet><is><r><t>Product</t></r><r><t>\n</t></r><r><t>(Size)</t></r></is></worksheet>'
    shared = b'<sst><si><r><t> </t></r></si></sst>'
    with zipfile.ZipFile(path, "w") as archive:
        archive.comment = b"original comment"
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
        archive.writestr("xl/sharedStrings.xml", shared)
        archive.writestr("xl/media/image1.png", b"unchanged image")
        archive.writestr("xl/styles.xml", b"unchanged styles")
    assert _normalize_excel_text_whitespace(path)
    with zipfile.ZipFile(path) as archive:
        assert archive.comment == b"original comment"
        assert archive.read("xl/worksheets/sheet1.xml") == sheet.replace(b'<t>\n</t>', b'<t xml:space="preserve">\n</t>')
        assert archive.read("xl/sharedStrings.xml") == shared.replace(b'<t> </t>', b'<t xml:space="preserve"> </t>')
        assert archive.read("xl/media/image1.png") == b"unchanged image"
        assert archive.read("xl/styles.xml") == b"unchanged styles"
    before = path.read_bytes()
    assert not _normalize_excel_text_whitespace(path)
    assert path.read_bytes() == before


def test_leaves_non_xml_workbooks_untouched(tmp_path):
    path = tmp_path / "old.xls"
    path.write_bytes(b"legacy binary workbook")
    assert not _normalize_excel_text_whitespace(path)
    assert path.read_bytes() == b"legacy binary workbook"
