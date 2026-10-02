"""Parsing and validating competency files (task 2.2). Pure functions: nothing here touches the database."""

import csv
import io
import zipfile
from dataclasses import dataclass, field

from django.conf import settings
from rest_framework.exceptions import APIException

COLUMNS = ("code", "title", "description", "level", "requirement")
REQUIRED_COLUMNS = ("code", "title")
MAX_LENGTHS = {"code": 50, "title": 500, "level": 50}

HEADER_ALIASES = {
    "code": {"code", "الرمز", "رمز", "رمز الكفاية"},
    "title": {"title", "العنوان", "عنوان", "اسم الكفاية", "الكفاية"},
    "description": {"description", "الوصف", "وصف"},
    "level": {"level", "المستوى", "مستوى"},
    "requirement": {"requirement", "type", "النوع", "نوع الكفاية", "الإلزامية", "الالزامية"},
}

REQUIREMENT_VALUES = {
    "required": {
        "",
        "required",
        "mandatory",
        "core",
        "إلزامية",
        "إلزامي",
        "الزامية",
        "الزامي",
        "أساسية",
        "أساسي",
        "كفاية",
    },
    "optional": {"optional", "elective", "اختيارية", "اختياري"},
}


class ImportRejected(APIException):
    """The file as a whole cannot be read; nothing is previewed."""

    status_code = 400
    default_code = "import_rejected"
    default_detail = "the file cannot be imported"

    def __init__(self, code: str, message: str):
        super().__init__(detail=message, code=code)


@dataclass
class ParsedRow:
    row: int
    values: dict[str, str]
    errors: list[str] = field(default_factory=list)
    action: str = "create"


def _normalize_header(value) -> str:
    return " ".join(str(value or "").replace("﻿", "").split()).lower()


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _read_csv(data: bytes) -> list[list[str]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportRejected("file_encoding", "the CSV file must be saved as UTF-8") from exc
    return [list(row) for row in csv.reader(io.StringIO(text, newline=""))]


def _read_xlsx(data: bytes) -> list[list[str]]:
    import openpyxl
    from openpyxl.utils.exceptions import InvalidFileException

    try:
        book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (zipfile.BadZipFile, InvalidFileException, KeyError, OSError, ValueError) as exc:
        raise ImportRejected("unreadable_file", "the Excel file cannot be read") from exc
    try:
        sheet = book.worksheets[0]
        return [[_cell(value) for value in row] for row in sheet.iter_rows(values_only=True)]
    finally:
        book.close()


def read_table(file_name: str, data: bytes) -> list[list[str]]:
    if len(data) > settings.COMPETENCY_IMPORT_MAX_BYTES:
        raise ImportRejected("file_too_large", f"the file is larger than {settings.COMPETENCY_IMPORT_MAX_BYTES} bytes")
    if not data:
        raise ImportRejected("empty_file", "the file is empty")
    extension = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    if extension == "csv":
        return _read_csv(data)
    if extension == "xlsx":
        return _read_xlsx(data)
    raise ImportRejected("unsupported_file_type", "only .csv and .xlsx files are supported")


def parse(file_name: str, data: bytes) -> list[ParsedRow]:
    table = read_table(file_name, data)
    if not table or not any(_cell(v) for v in table[0]):
        raise ImportRejected("empty_file", "the file has no header row")

    headers = [_normalize_header(h) for h in table[0]]
    positions: dict[str, int] = {}
    for column, aliases in HEADER_ALIASES.items():
        for index, header in enumerate(headers):
            if header in aliases and column not in positions:
                positions[column] = index
    missing = [c for c in REQUIRED_COLUMNS if c not in positions]
    if missing:
        raise ImportRejected("missing_columns", f"missing required columns: {', '.join(missing)}")

    data_rows = [(number, row) for number, row in enumerate(table[1:], start=2) if any(_cell(v) for v in row)]
    if len(data_rows) > settings.COMPETENCY_IMPORT_MAX_ROWS:
        raise ImportRejected("too_many_rows", f"the file has more than {settings.COMPETENCY_IMPORT_MAX_ROWS} rows")

    parsed = []
    for number, row in data_rows:
        values = {c: (_cell(row[positions[c]]) if c in positions and positions[c] < len(row) else "") for c in COLUMNS}
        parsed.append(ParsedRow(row=number, values=values))
    return parsed


def validate(rows: list[ParsedRow], existing: dict[str, dict[str, str]]) -> list[ParsedRow]:
    """Fills errors and the action of each row. `existing` maps code -> current values in the target version."""
    seen: set[str] = set()
    for row in rows:
        row.errors = []
        values = row.values
        raw_requirement = values["requirement"].strip().lower()
        requirement = next((k for k, allowed in REQUIREMENT_VALUES.items() if raw_requirement in allowed), None)
        if not values["code"]:
            row.errors.append("missing_code")
        if not values["title"]:
            row.errors.append("missing_title")
        if requirement is None:
            row.errors.append("invalid_requirement")
        else:
            values["requirement"] = requirement
        for column, limit in MAX_LENGTHS.items():
            if len(values[column]) > limit:
                row.errors.append(f"{column}_too_long")
        if values["code"]:
            if values["code"] in seen:
                row.errors.append("duplicate_code_in_file")
            seen.add(values["code"])

        if row.errors:
            row.action = "error"
        elif values["code"] in existing:
            current = existing[values["code"]]
            row.action = "unchanged" if all(current[c] == values[c] for c in COLUMNS) else "update"
        else:
            row.action = "create"
    return rows


def summarize(rows: list[ParsedRow]) -> dict[str, int]:
    summary = {"create": 0, "update": 0, "unchanged": 0, "errors": 0}
    for row in rows:
        summary["errors" if row.action == "error" else row.action] += 1
    return summary
