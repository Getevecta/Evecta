"""Unit tests for Excel lead upload helpers."""
import asyncio
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import openpyxl

from fastapi import HTTPException
from app.services.lead_upload_service import (
    MAX_EXCEL_BYTES,
    _cell_email,
    _cell_str,
    _load_sheet_rows,
    _merge_cell,
    _row_is_blank,
    assert_xlsx_upload,
    import_leads_from_excel,
)


def test_row_is_blank_for_empty_and_whitespace():
    assert _row_is_blank(None) is True
    assert _row_is_blank(()) is True
    assert _row_is_blank((None, None, None)) is True
    assert _row_is_blank(("", "  ", None)) is True
    assert _row_is_blank(("Acme", None)) is False
    assert _row_is_blank((None, "=A1")) is False


def test_merge_cell_prefers_cached_then_raw():
    assert _merge_cell("cached@x.com", "=A1") == "cached@x.com"
    assert _merge_cell(None, "typed@x.com") == "typed@x.com"
    assert _merge_cell(None, "=VLOOKUP(A1)") is None
    assert _merge_cell("=A1", "typed@x.com") == "typed@x.com"


def test_cell_email_strips_mailto_and_angles():
    assert _cell_email("mailto:Ada@Example.com") == "ada@example.com"
    assert _cell_email("Ada Lovelace <ada@example.com>") == "ada@example.com"
    assert _cell_email(None) is None
    assert _cell_email("=A2") is None
    assert _cell_email("x@x.com\r\nBcc: attacker@evil.com") is None
    assert _cell_email("not-an-email") is None


def test_cell_str_integer_float():
    assert _cell_str(9801234567.0) == "9801234567"
    assert _cell_str("  Acme  ") == "Acme"
    assert _cell_str("=1+1") is None


def _xlsx_bytes(rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_load_sheet_rows_keeps_typed_values_when_data_only_empty():
    content = _xlsx_bytes(
        [
            ["business_name", "email", "industry"],
            ["Acme Co", "a@example.com", "Tech"],
            ["Beta LLC", "b@example.com", "Retail"],
            [None, None, None],
            ["", "", ""],
        ]
    )
    rows = _load_sheet_rows(content)
    assert len(rows) >= 3
    assert rows[0][0] == "business_name"
    assert rows[1][1] == "a@example.com"
    assert rows[2][0] == "Beta LLC"


def test_import_skips_blank_rows_not_as_failed():
    """Blank trailing rows must not inflate failed_rows or block import."""
    content = _xlsx_bytes(
        [
            ["Company Name", "Email", "Industry"],
            ["Acme Co", "a@example.com", "Tech"],
            ["Beta LLC", "b@example.com", "Retail"],
            [None, None, None],
            [None, None, None],
            ["Gamma", "a@example.com", "Tech"],  # in-file duplicate email
        ]
    )

    class _Result:
        def all(self):
            return []

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_Result())
    db.add_all = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    result = asyncio.run(import_leads_from_excel(content, "leads.xlsx", uuid4(), db))

    assert result.data["imported"] == 2
    assert result.data["blank_rows"] == 2
    assert result.data["failed_rows"] == 0
    assert result.data["skipped_duplicates_in_file"] == 1
    assert result.data["skipped_duplicates_existing"] == 0
    db.add_all.assert_called_once()
    assert len(db.add_all.call_args[0][0]) == 2


def test_import_counts_existing_db_duplicate_separately():
    content = _xlsx_bytes(
        [
            ["business_name", "email"],
            ["Acme Co", "existing@example.com"],
            ["New Co", "new@example.com"],
        ]
    )

    class _Row:
        def __init__(self, email, business_name):
            self.email = email
            self.business_name = business_name

    class _Result:
        def all(self):
            return [_Row("existing@example.com", "Old Acme")]

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_Result())
    db.add_all = MagicMock()
    db.commit = AsyncMock()

    result = asyncio.run(import_leads_from_excel(content, "leads.xlsx", uuid4(), db))

    assert result.data["imported"] == 1
    assert result.data["skipped_duplicates_existing"] == 1
    assert result.data["skipped_duplicates_in_file"] == 0


def test_xlsx_magic_and_size_cap():
    good = _xlsx_bytes([["business_name", "email"], ["Acme", "a@example.com"]])
    assert_xlsx_upload(good)
    try:
        assert_xlsx_upload(b"not-a-zip")
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 400
    try:
        assert_xlsx_upload(b"PK\x03\x04" + b"x" * MAX_EXCEL_BYTES)
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 413
