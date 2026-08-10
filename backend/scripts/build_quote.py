from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import re
import shutil
import sqlite3
import sys
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable


DEFAULT_FOLDER = Path(r"C:\Users\hk010\PycharmProjects\OPENMOON\quotation_files")
DEFAULT_DATABASE = Path("backend/data/source/quotation_history.db")
DEFAULT_OUTPUT = Path("backend/data/source/quotation_history_candidate.db")
DEFAULT_REPORT = Path("backend/data/quotation_history_audit.csv")
DEFAULT_LEGACY_PARSER = Path(r"C:\Users\hk010\PycharmProjects\OPENMOON\build_quote_db.py")

SUMMARY_PRODUCTS = {
    "소계",
    "합계",
    "총계",
    "총금액",
    "공급금액",
    "공급가액",
    "부가세",
    "vat",
}
EXCLUDED_FILE_PATTERNS = (
    re.compile(r"^!.*(?:미수|선수금)", re.IGNORECASE),
    re.compile(r"^~\$"),
)


def normalized_text(value: Any) -> str:
    return re.sub(r"[\s:：·ㆍ\-_()/\[\]{}]", "", str(value or "")).lower()


def is_excluded_file(path: Path) -> bool:
    return any(pattern.search(path.name) for pattern in EXCLUDED_FILE_PATTERNS)


def load_legacy_parser(path: Path) -> ModuleType:
    if not path.exists():
        raise FileNotFoundError(
            f"기존 파서가 없습니다: {path}\n"
            "--legacy-parser 옵션으로 build_quote_db.py 위치를 지정하세요."
        )
    spec = importlib.util.spec_from_file_location("yullinmoon_quote_parser", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"파서를 불러올 수 없습니다: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    install_parser_fixes(module)
    return module


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


def connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    if not readonly:
        connection.execute("PRAGMA journal_mode = WAL")
    return connection


def excel_files(folder: Path) -> list[Path]:
    return sorted(
        path
        for path in folder.rglob("*")
        if path.is_file()
        and path.suffix.lower() in {".xlsx", ".xlsm"}
        and not path.name.startswith("~$")
    )


def database_paths(connection: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    return {
        str(Path(row["file_path"]).resolve()).lower(): row
        for row in connection.execute("SELECT * FROM source_files")
    }


def suspicious_existing_paths(connection: sqlite3.Connection) -> set[str]:
    paths: set[str] = set()
    query = """
        SELECT DISTINCT sf.file_path
        FROM source_files sf
        JOIN quotations q ON q.source_file_id = sf.id
        LEFT JOIN quotation_items qi ON qi.quotation_id = q.id
        GROUP BY q.id
        HAVING COUNT(qi.id) = 0
    """
    paths.update(row[0] for row in connection.execute(query))

    for row in connection.execute(
        """
        SELECT DISTINCT sf.file_path, qi.product_name
        FROM quotation_items qi
        JOIN quotations q ON q.id = qi.quotation_id
        JOIN source_files sf ON sf.id = q.source_file_id
        """
    ):
        if normalized_text(row["product_name"]) in SUMMARY_PRODUCTS:
            paths.add(row["file_path"])
    return paths


def clean_quotation(quotation: Any) -> list[str]:
    warnings: list[str] = []
    cleaned_items = []
    for item in quotation.items:
        if normalized_text(item.product_name) in SUMMARY_PRODUCTS:
            warnings.append(f"요약행 제외: {item.product_name} (행 {item.source_row})")
            continue
        if item.quantity is not None and item.quantity <= 0:
            warnings.append(f"0 이하 수량: {item.product_name} (행 {item.source_row})")
        if (item.unit_price is not None and item.unit_price < 0) or (
            item.amount is not None and item.amount < 0
        ):
            warnings.append(f"음수 금액: {item.product_name} (행 {item.source_row})")
        if (
            item.quantity is not None
            and item.unit_price is not None
            and item.amount is not None
            and abs(item.amount - round(item.quantity * item.unit_price)) > 1
        ):
            warnings.append(f"수량×단가 불일치: {item.product_name} (행 {item.source_row})")
        cleaned_items.append(item)

    quotation.items = cleaned_items
    for index, item in enumerate(quotation.items, start=1):
        item.line_number = index
    quotation.total_amount = sum(
        item.amount for item in quotation.items if item.amount is not None
    ) or None
    if warnings:
        quotation.review_required = True
        if quotation.parse_status == "success":
            quotation.parse_status = "review"
        quotation.parse_error = " | ".join(warnings)
    return warnings


def remove_source_file(connection: sqlite3.Connection, file_path: Path) -> None:
    connection.execute("DELETE FROM source_files WHERE file_path = ?", (str(file_path.resolve()),))
    connection.commit()


def quotation_signature(connection: sqlite3.Connection, quotation_id: int) -> str | None:
    quotation = connection.execute(
        """
        SELECT quote_date, customer_organization
        FROM quotations WHERE id = ?
        """,
        (quotation_id,),
    ).fetchone()
    items = connection.execute(
        """
        SELECT product_name, specification_raw, width_mm, height_mm,
               quantity, unit, unit_price, amount
        FROM quotation_items
        WHERE quotation_id = ?
        ORDER BY line_number, id
        """,
        (quotation_id,),
    ).fetchall()
    if not items:
        return None
    payload = {
        "date": quotation["quote_date"],
        "customer": normalized_text(quotation["customer_organization"]),
        "items": [tuple(item) for item in items],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, default=str).encode()).hexdigest()


def deduplicate_quotations(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    groups: dict[str, list[sqlite3.Row]] = defaultdict(list)
    rows = connection.execute(
        """
        SELECT q.id, q.parse_confidence, q.review_required, q.block_index,
               sf.file_name, sf.file_path, q.sheet_name
        FROM quotations q JOIN source_files sf ON sf.id = q.source_file_id
        ORDER BY q.id
        """
    ).fetchall()
    for row in rows:
        signature = quotation_signature(connection, row["id"])
        if signature:
            groups[signature].append(row)

    removed: list[dict[str, Any]] = []
    for matches in groups.values():
        if len(matches) < 2:
            continue
        keep = max(
            matches,
            key=lambda row: (
                not row["review_required"],
                row["parse_confidence"],
                -row["block_index"],
                -row["id"],
            ),
        )
        for row in matches:
            if row["id"] == keep["id"]:
                continue
            connection.execute("DELETE FROM quotations WHERE id = ?", (row["id"],))
            removed.append(
                {
                    "category": "duplicate_quotation_removed",
                    "file_name": row["file_name"],
                    "file_path": row["file_path"],
                    "sheet_name": row["sheet_name"],
                    "detail": f"동일 견적 유지 위치: {keep['file_name']} / {keep['sheet_name']}",
                }
            )
    connection.commit()
    return removed


def audit_database(
    connection: sqlite3.Connection,
    folder: Path,
    files: list[Path],
) -> list[dict[str, Any]]:
    report: list[dict[str, Any]] = []
    indexed = database_paths(connection)
    disk_paths = {str(path.resolve()).lower() for path in files}

    for path in files:
        key = str(path.resolve()).lower()
        if is_excluded_file(path):
            report.append(
                {
                    "category": "excluded_non_quotation_file",
                    "file_name": path.name,
                    "file_path": str(path.resolve()),
                    "sheet_name": "",
                    "detail": "미수금·선수금 관리 파일",
                }
            )
        elif key not in indexed:
            report.append(
                {
                    "category": "missing_file",
                    "file_name": path.name,
                    "file_path": str(path.resolve()),
                    "sheet_name": "",
                    "detail": "원본 파일이 DB에 없음",
                }
            )

    for key, row in indexed.items():
        if key not in disk_paths:
            report.append(
                {
                    "category": "database_file_missing_on_disk",
                    "file_name": row["file_name"],
                    "file_path": row["file_path"],
                    "sheet_name": "",
                    "detail": "DB 경로에 원본 파일이 없음",
                }
            )

    anomaly_query = """
        SELECT sf.file_name, sf.file_path, q.sheet_name, q.id,
               q.parse_status, q.parse_confidence, q.parse_error,
               q.customer_organization, q.quote_date,
               COUNT(qi.id) AS item_count
        FROM quotations q
        JOIN source_files sf ON sf.id = q.source_file_id
        LEFT JOIN quotation_items qi ON qi.quotation_id = q.id
        GROUP BY q.id
    """
    for row in connection.execute(anomaly_query):
        issues = []
        if row["item_count"] == 0:
            issues.append("품목 0건")
        if not row["customer_organization"]:
            issues.append("고객기관 누락")
        if not row["quote_date"]:
            issues.append("견적일 누락")
        if row["parse_status"] != "success" or row["parse_error"]:
            issues.append(row["parse_error"] or row["parse_status"])
        if issues:
            report.append(
                {
                    "category": "quotation_review",
                    "file_name": row["file_name"],
                    "file_path": row["file_path"],
                    "sheet_name": row["sheet_name"],
                    "detail": " | ".join(dict.fromkeys(issues)),
                }
            )

    item_query = """
        SELECT sf.file_name, sf.file_path, q.sheet_name, qi.source_row,
               qi.product_name, qi.quantity, qi.unit_price, qi.amount
        FROM quotation_items qi
        JOIN quotations q ON q.id = qi.quotation_id
        JOIN source_files sf ON sf.id = q.source_file_id
    """
    for row in connection.execute(item_query):
        issue = None
        if normalized_text(row["product_name"]) in SUMMARY_PRODUCTS:
            issue = "소계·합계 행이 품목으로 저장됨"
        elif (row["unit_price"] is not None and row["unit_price"] < 0) or (
            row["amount"] is not None and row["amount"] < 0
        ):
            issue = "음수 단가 또는 금액"
        elif (
            row["quantity"] is not None
            and row["unit_price"] is not None
            and row["amount"] is not None
            and abs(row["amount"] - round(row["quantity"] * row["unit_price"])) > 1
        ):
            issue = "수량×단가와 금액 불일치(VAT·할인·반올림 여부 확인)"
        if issue:
            report.append(
                {
                    "category": "item_review",
                    "file_name": row["file_name"],
                    "file_path": row["file_path"],
                    "sheet_name": row["sheet_name"],
                    "detail": f"{issue}: {row['product_name']} / 행 {row['source_row']}",
                }
            )
    return report


def write_report(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["category", "file_name", "file_path", "sheet_name", "detail"]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def repair_candidate(
    parser: ModuleType,
    folder: Path,
    source_db: Path,
    output_db: Path,
    report_path: Path,
    *,
    full_rebuild: bool,
    deduplicate: bool,
    resume: bool,
) -> None:
    if not folder.exists():
        raise FileNotFoundError(folder)
    files = excel_files(folder)

    if not resume:
        if output_db.exists():
            output_db.unlink()
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(output_db) + suffix)
            if sidecar.exists():
                sidecar.unlink()

        if not full_rebuild and source_db.exists():
            shutil.copy2(source_db, output_db)
    elif not output_db.exists():
        raise FileNotFoundError(f"이어갈 후보 DB가 없습니다: {output_db}")

    connection = connect(output_db)
    parser.create_schema(connection)
    existing = database_paths(connection)
    suspicious = suspicious_existing_paths(connection)
    audit_rows: list[dict[str, Any]] = []

    # Remove files that are not quotation sources from the candidate database.
    for path in files:
        if is_excluded_file(path):
            remove_source_file(connection, path)
            audit_rows.append(
                {
                    "category": "excluded_non_quotation_file",
                    "file_name": path.name,
                    "file_path": str(path.resolve()),
                    "sheet_name": "",
                    "detail": "후보 DB에서 제외",
                }
            )

    targets = []
    for path in files:
        if is_excluded_file(path):
            continue
        key = str(path.resolve()).lower()
        row = existing.get(key)
        if full_rebuild or row is None or row["file_path"] in suspicious:
            targets.append(path)
            continue
        if row["file_size"] != path.stat().st_size or row["modified_time"] != path.stat().st_mtime:
            targets.append(path)

    print(f"원본 Excel: {len(files):,}개", flush=True)
    print(f"재처리 대상: {len(targets):,}개", flush=True)
    for index, path in enumerate(targets, start=1):
        try:
            file_hash = parser.calculate_file_hash(path)
            quotations = parser.parse_excel_file(path, file_hash)
            accepted = []
            for quotation in quotations:
                warnings = clean_quotation(quotation)
                if not quotation.items:
                    audit_rows.append(
                        {
                            "category": "empty_or_non_quotation_block",
                            "file_name": path.name,
                            "file_path": str(path.resolve()),
                            "sheet_name": quotation.sheet_name,
                            "detail": quotation.parse_error or "품목이 없는 블록 제외",
                        }
                    )
                    continue
                accepted.append(quotation)
                for warning in warnings:
                    audit_rows.append(
                        {
                            "category": "parsed_item_review",
                            "file_name": path.name,
                            "file_path": str(path.resolve()),
                            "sheet_name": quotation.sheet_name,
                            "detail": warning,
                        }
                    )
            parser.save_file_results(connection, path, file_hash, accepted)
        except Exception as error:
            audit_rows.append(
                {
                    "category": "file_parse_error",
                    "file_name": path.name,
                    "file_path": str(path.resolve()),
                    "sheet_name": "",
                    "detail": f"{type(error).__name__}: {error}",
                }
            )
        if index % 25 == 0 or index == len(targets):
            print(f"진행: {index:,}/{len(targets):,}", flush=True)

    if deduplicate:
        duplicate_rows = deduplicate_quotations(connection)
        audit_rows.extend(duplicate_rows)
        print(f"정확 중복 제거: {len(duplicate_rows):,}건")

    audit_rows.extend(audit_database(connection, folder, files))
    write_report(report_path, audit_rows)

    counts = {
        table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("source_files", "quotations", "quotation_items")
    }
    connection.close()
    print("후보 DB:", output_db.resolve())
    print("감사 보고서:", report_path.resolve())
    print("결과:", counts)


def audit_only(folder: Path, database: Path, report: Path) -> None:
    files = excel_files(folder)
    with connect(database, readonly=True) as connection:
        rows = audit_database(connection, folder, files)
    write_report(report, rows)
    category_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        category_counts[row["category"]] += 1
    print("원본 Excel:", len(files))
    print("감사 결과:", dict(sorted(category_counts.items())))
    print("보고서:", report.resolve())


def replace_live_database(candidate: Path, live: Path) -> Path:
    if not candidate.exists():
        raise FileNotFoundError(candidate)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = live.with_name(f"{live.stem}_backup_{timestamp}{live.suffix}")
    if live.exists():
        shutil.copy2(live, backup)
    shutil.copy2(candidate, live)
    return backup


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="견적 원본 Excel과 quotation_history.db를 감사하고 안전하게 재구축합니다."
    )
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER)
    parser.add_argument("--db", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output-db", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--legacy-parser", type=Path, default=DEFAULT_LEGACY_PARSER)
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--full-rebuild", action="store_true")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="기존 후보 DB를 삭제하지 않고 아직 누락되거나 문제가 남은 파일만 이어서 처리합니다.",
    )
    parser.add_argument("--no-deduplicate", action="store_true")
    parser.add_argument(
        "--replace-live",
        action="store_true",
        help="후보 DB를 검토한 뒤에만 사용하세요. 기존 DB를 타임스탬프 백업 후 교체합니다.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.audit_only:
        audit_only(args.folder, args.db, args.report)
        return

    parser = load_legacy_parser(args.legacy_parser)
    repair_candidate(
        parser,
        args.folder,
        args.db,
        args.output_db,
        args.report,
        full_rebuild=args.full_rebuild,
        deduplicate=not args.no_deduplicate,
        resume=args.resume,
    )
    if args.replace_live:
        backup = replace_live_database(args.output_db, args.db)
        print("기존 DB 백업:", backup.resolve())
        print("운영 DB 교체 완료:", args.db.resolve())


if __name__ == "__main__":
    main()
