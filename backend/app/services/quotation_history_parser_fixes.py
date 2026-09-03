from __future__ import annotations
import re
from pathlib import Path
from types import ModuleType
from typing import Any
SUMMARY_PRODUCTS = {"소계", "합계", "총계", "총금액", "공급금액", "공급가액", "부가세", "vat"}

def normalized_text(value):
    return re.sub(r'[\s:：·ㆍ\-_()/\[\]{}]', '', str(value or '')).lower()

def install_parser_fixes(parser: ModuleType) -> None:
    """Patch known extraction defects without modifying the old source file."""
    original_split = parser.split_product_specification
    original_find_header = parser.find_item_header

    def meaningful_cells(sheet, max_row: int):
        # Some files have formatting extended to XFD/XEB even though their real
        # data ends near column Z. Iterating sheet.max_column makes one small
        # workbook take minutes. Non-read-only openpyxl sheets keep real cells
        # in _cells, so use that sparse collection when available.
        sparse = getattr(sheet, "_cells", None)
        if isinstance(sparse, dict):
            return [
                cell
                for cell in sparse.values()
                if cell.row <= max_row
                and not isinstance(cell, parser.MergedCell)
                and parser.normalize_text(cell.value)
            ]
        return list(parser.iter_real_cells(sheet, min_row=1, max_row=max_row))

    def find_quotation_blocks(sheet):
        cells = meaningful_cells(sheet, min(sheet.max_row, parser.MAX_SCAN_ROW))
        title_columns = sorted(
            {
                cell.column
                for cell in cells
                if cell.row <= 8 and parser.compact_text(cell.value) in parser.TITLE_LABELS
            }
        )
        if title_columns:
            starts = title_columns
        else:
            product_columns = sorted(
                {
                    cell.column
                    for cell in cells
                    if cell.row <= 30
                    and parser.compact_text(cell.value) in parser.PRODUCT_HEADER_LABELS
                }
            )
            starts = [max(1, column - 2) for column in product_columns]
        starts = sorted(set(starts))
        if not starts:
            return []
        effective_end = max((cell.column for cell in cells), default=max(starts))
        return [
            (start, starts[index + 1] - 1 if index + 1 < len(starts) else effective_end)
            for index, start in enumerate(starts)
            if start <= effective_end
        ]

    def split_product_specification(raw_text: str) -> tuple[str, str | None]:
        lines = [line.strip() for line in re.split(r"[\r\n]+", raw_text) if line.strip()]
        if not lines:
            return "", None

        # The old parser treated a leading [product] as an empty product name.
        leading_bracket = re.fullmatch(r"[\[（(](.+?)[\]）)]", lines[0])
        if leading_bracket:
            product = leading_bracket.group(1).strip()
            specification = "\n".join(lines[1:]).strip() or None
            return product, specification

        return original_split(raw_text)

    def find_item_header(sheet, start_column: int, end_column: int):
        header_row, columns = original_find_header(sheet, start_column, end_column)
        if header_row is None or "product" not in columns:
            return header_row, columns

        detected = columns["product"]
        reserved = {value for key, value in columns.items() if key != "product"}
        candidates = range(max(start_column, detected - 2), min(end_column, detected + 2) + 1)

        def score(column: int) -> tuple[int, int]:
            text_rows = 0
            number_only_rows = 0
            for row in range(header_row + 1, min(sheet.max_row, header_row + 20) + 1):
                value = parser.get_real_cell_value(sheet, row, column)
                text = parser.normalize_text(value)
                if not text or text.startswith("="):
                    continue
                if parser.parse_number(value) is not None:
                    number_only_rows += 1
                elif normalized_text(text) not in SUMMARY_PRODUCTS:
                    text_rows += 1
            return text_rows * 5 - number_only_rows * 2, -abs(column - detected)

        viable = [column for column in candidates if column not in reserved]
        if viable:
            best = max(viable, key=score)
            if score(best)[0] > score(detected)[0]:
                columns["product"] = best
        return header_row, columns

    parser.split_product_specification = split_product_specification
    parser.find_item_header = find_item_header
    parser.find_quotation_blocks = find_quotation_blocks

    def parse_excel_file(file_path: Path, file_hash: str):
        """Legacy parser equivalent with external-link loading disabled."""
        keep_vba = file_path.suffix.lower() == ".xlsm"
        common = {
            "filename": file_path,
            "read_only": False,
            "keep_vba": keep_vba,
            "keep_links": False,
        }
        workbook_values = parser.load_workbook(data_only=True, **common)
        workbook_formulas = parser.load_workbook(data_only=False, **common)
        results = []
        try:
            for sheet_values in workbook_values.worksheets:
                sheet_formulas = workbook_formulas[sheet_values.title]
                if str(sheet_formulas["T1"].value) in getattr(parser, "excluded_markers", set()):
                    continue
                for block_index, (start_column, end_column) in enumerate(
                    parser.find_quotation_blocks(sheet_values), start=1
                ):
                    results.append(
                        parser.parse_quotation_block(
                            sheet_values=sheet_values,
                            sheet_formulas=sheet_formulas,
                            file_path=file_path,
                            file_hash=file_hash,
                            block_index=block_index,
                            start_column=start_column,
                            end_column=end_column,
                        )
                    )
        finally:
            workbook_values.close()
            workbook_formulas.close()
        return results

    parser.parse_excel_file = parse_excel_file



