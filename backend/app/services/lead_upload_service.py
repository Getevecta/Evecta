import logging
import re
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any, Optional
from uuid import UUID

import openpyxl
from fastapi import HTTPException
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead
from app.schemas.response import BaseResponse
from app.utils.lead_dedup import (
    is_duplicate_lead,
    normalize_business_name,
    normalize_email,
    register_lead_keys,
)

logger = logging.getLogger(__name__)

# Accepted column name aliases (case-insensitive)
_COLUMN_ALIASES: dict[str, list[str]] = {
    "business_name":  ["business_name", "business name", "company", "company name", "name"],
    "industry":       ["industry", "sector", "category"],
    "email":          ["email", "email address", "e-mail"],
    "contact_number": ["contact_number", "contact number", "phone", "phone number", "mobile", "tel"],
    "address":        ["address", "location"],
    "website":        ["website", "web", "url", "website url"],
}

_MAX_ROWS = 1000  # safety cap per upload
MAX_EXCEL_BYTES = 5 * 1024 * 1024
_XLSX_MAGIC = b"PK\x03\x04"
_EMAIL_ADAPTER = TypeAdapter(EmailStr)

# User-facing copy for Excel import requirements
_REQUIRED_COMPANY_EMAIL_MSG = "Company Name and Email is required to upload the file."

_EMAIL_IN_ANGLES = re.compile(r"<([^>]+)>")
_FORMULA_PREFIX = "="


def _compute_lead_score(row: dict) -> int:
    """Simple score mirroring the enrichment scoring logic."""
    score = 0
    if row.get("email"):
        score += 40
    if row.get("website"):
        score += 30
    if row.get("contact_number"):
        score += 15
    if row.get("address"):
        score += 10
    if row.get("industry"):
        score += 5
    return min(score, 100)


def _resolve_headers(raw_headers: list[str]) -> dict[str, int]:
    """
    Map normalised field names → column index.
    Returns only the fields whose header was found in the sheet.
    """
    normalised = {h.strip().lower(): i for i, h in enumerate(raw_headers)}
    resolved: dict[str, int] = {}
    for field, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in normalised:
                resolved[field] = normalised[alias]
                break
    return resolved


def _is_formula(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(_FORMULA_PREFIX)


def _cell_str(value: Any) -> Optional[str]:
    """Convert a cell value to a stripped string, or None if empty/formula."""
    if value is None or _is_formula(value):
        return None
    # Excel may store phones/ids as floats; avoid "9801234567.0"
    if isinstance(value, float) and value.is_integer():
        s = str(int(value))
    else:
        s = str(value).strip()
    return s if s else None


def assert_xlsx_upload(file_bytes: bytes) -> None:
    if len(file_bytes) > MAX_EXCEL_BYTES:
        raise HTTPException(
            status_code=413,
            detail="File is too large. Maximum size is 5 MB.",
        )
    if not file_bytes.startswith(_XLSX_MAGIC):
        raise HTTPException(
            status_code=400,
            detail="Only Excel files (.xlsx) are accepted.",
        )


def _cell_email(value: Any) -> Optional[str]:
    """Extract and validate an email from a cell (mailto:, Name <email>, plain)."""
    s = _cell_str(value)
    if not s:
        return None
    if any(ch in s for ch in ("\r", "\n", "\x00")):
        return None
    lower = s.lower()
    if lower.startswith("mailto:"):
        s = s[7:].strip()
    angled = _EMAIL_IN_ANGLES.search(s)
    if angled:
        s = angled.group(1).strip()
    if any(ch in s for ch in ("\r", "\n", "\x00", " ", "\t")):
        return None
    try:
        return str(_EMAIL_ADAPTER.validate_python(s)).lower()
    except ValidationError:
        return None


def _row_is_blank(raw: Any) -> bool:
    """True when the Excel row has no meaningful values (common trailing used-range empties)."""
    if raw is None:
        return True
    for value in raw:
        if value is None:
            continue
        if _is_formula(value):
            return False
        if isinstance(value, str) and not value.strip():
            continue
        return False
    return True


def _merge_cell(cached: Any, raw: Any) -> Any:
    """
    Prefer cached calculated value (data_only). Fall back to the typed raw value when
    data_only is None — that happens for uncached formulas AND sometimes for plain
    values depending on how the file was saved. Never return an unevaluated formula.
    """
    if cached is not None and not _is_formula(cached):
        return cached
    if raw is not None and not _is_formula(raw):
        return raw
    return None


def _load_sheet_rows(file_bytes: bytes) -> list[tuple]:
    """
    Load the active sheet, merging data_only + raw workbooks so formula cells without
    a cached result do not wipe otherwise-valid typed values in the same file.
    """
    try:
        wb_raw = openpyxl.load_workbook(BytesIO(file_bytes), read_only=True, data_only=False)
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read this file. Use a valid .xlsx file.")

    try:
        ws_raw = wb_raw.active
        raw_rows = [tuple(r) for r in ws_raw.iter_rows(values_only=True)]
    finally:
        wb_raw.close()

    cached_rows: list[tuple] = []
    try:
        wb_cached = openpyxl.load_workbook(BytesIO(file_bytes), read_only=True, data_only=True)
        try:
            ws_cached = wb_cached.active
            cached_rows = [tuple(r) for r in ws_cached.iter_rows(values_only=True)]
        finally:
            wb_cached.close()
    except Exception:
        logger.warning("data_only workbook load failed; using raw cell values only")
        cached_rows = []

    if not cached_rows:
        return raw_rows

    merged: list[tuple] = []
    row_count = max(len(raw_rows), len(cached_rows))
    for i in range(row_count):
        raw = raw_rows[i] if i < len(raw_rows) else ()
        cached = cached_rows[i] if i < len(cached_rows) else ()
        width = max(len(raw), len(cached))
        merged.append(
            tuple(
                _merge_cell(
                    cached[j] if j < len(cached) else None,
                    raw[j] if j < len(raw) else None,
                )
                for j in range(width)
            )
        )
    return merged


async def import_leads_from_excel(
    file_bytes: bytes,
    filename: str,
    user_id: UUID,
    db: AsyncSession,
) -> BaseResponse:
    """
    Parse an .xlsx / .xls file and import leads directly into the Lead table.

    Rules
    -----
    - Header row must include mappable ``business_name`` and ``email`` columns.
    - Completely blank rows are ignored (not counted as failures).
    - Each non-blank data row must have non-empty company name and email; otherwise skipped (failed).
    - Duplicate detection: same email as an existing lead or earlier row in this file.
    - Rows beyond ``_MAX_ROWS`` are ignored and reported.
    - Returns a summary: imported, skipped (duplicates), failed (bad rows), blank ignored.
    """
    assert_xlsx_upload(file_bytes)
    rows = _load_sheet_rows(file_bytes)

    if not rows:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    # ── 2. Resolve headers ─────────────────────────────────────────────────────
    header_row = [str(c).strip() if c is not None else "" for c in rows[0]]
    col_map = _resolve_headers(header_row)

    if "business_name" not in col_map:
        raise HTTPException(
            status_code=400,
            detail=f"{_REQUIRED_COMPANY_EMAIL_MSG} Add a Company Name column.",
        )

    if "email" not in col_map:
        raise HTTPException(
            status_code=400,
            detail=f"{_REQUIRED_COMPANY_EMAIL_MSG} Add an Email column.",
        )

    data_rows = rows[1:]
    if not data_rows:
        raise HTTPException(status_code=400, detail="The file has a header but no data rows.")

    truncated = 0
    blank_rows = 0
    # Drop trailing/mid blank rows before applying the row cap so empties don't eat the quota
    non_blank_rows = []
    for raw in data_rows:
        if _row_is_blank(raw):
            blank_rows += 1
            continue
        non_blank_rows.append(raw)

    if len(non_blank_rows) > _MAX_ROWS:
        truncated = len(non_blank_rows) - _MAX_ROWS
        non_blank_rows = non_blank_rows[:_MAX_ROWS]

    if not non_blank_rows:
        raise HTTPException(status_code=400, detail="The file has a header but no data rows.")

    # ── 3. Parse each row into a dict ──────────────────────────────────────────
    parsed: list[dict] = []
    failed = 0

    for raw in non_blank_rows:
        def get(field: str) -> Optional[str]:
            idx = col_map.get(field)
            if idx is None or idx >= len(raw):
                return None
            if field == "email":
                return _cell_email(raw[idx])
            return _cell_str(raw[idx])

        business_name = get("business_name")
        email = get("email")
        if not business_name or not email:
            failed += 1
            continue

        parsed.append({
            "business_name": business_name,
            "industry":       get("industry"),
            "email":          email,
            "contact_number": get("contact_number"),
            "address":        get("address"),
            "website":        get("website"),
        })

    if not parsed:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{_REQUIRED_COMPANY_EMAIL_MSG} "
                f"{failed} row{'s' if failed != 1 else ''} skipped."
            ),
        )

    # ── 4. Bulk duplicate check ────────────────────────────────────────────────
    existing_emails: set[str] = set()
    existing_names_no_email: set[str] = set()

    existing_rows = await db.execute(
        select(Lead.email, Lead.business_name).where(Lead.user_id == user_id)
    )
    for row in existing_rows.all():
        norm_email = normalize_email(row.email)
        if norm_email:
            existing_emails.add(norm_email)
        elif row.business_name:
            norm_name = normalize_business_name(row.business_name)
            if norm_name:
                existing_names_no_email.add(norm_name)

    # Snapshot DB emails before in-file register so we can split duplicate reasons
    db_emails = set(existing_emails)

    # ── 5. Build new Lead records ──────────────────────────────────────────────
    # Unique created_at per row keeps offset pagination stable even if Lead.id
    # ordering differs across environments (same-timestamp batches used to drop rows).
    base_time = datetime.now(timezone.utc)
    new_leads: list[Lead] = []
    skipped_existing = 0
    skipped_in_file = 0

    for index, r in enumerate(parsed):
        norm_email = normalize_email(r["email"])
        if norm_email and norm_email in db_emails:
            skipped_existing += 1
            continue
        if is_duplicate_lead(r["email"], r["business_name"], existing_emails, existing_names_no_email):
            skipped_in_file += 1
            continue

        stored_email = norm_email
        row_time = base_time - timedelta(microseconds=index)
        new_leads.append(
            Lead(
                business_name=r["business_name"],
                industry=r["industry"],
                email=stored_email,
                contact_number=r["contact_number"],
                address=r["address"],
                website=r["website"],
                lead_score=_compute_lead_score(r),
                starred=False,
                email_subscribed=True,
                user_id=user_id,
                created_at=row_time,
                updated_at=row_time,
            )
        )
        register_lead_keys(r["email"], r["business_name"], existing_emails, existing_names_no_email)

    imported = len(new_leads)
    skipped = skipped_existing + skipped_in_file

    if new_leads:
        try:
            db.add_all(new_leads)
            await db.commit()
        except SQLAlchemyError as e:
            await db.rollback()
            logger.exception("DB error during Excel lead import for user %s", user_id)
            raise HTTPException(status_code=500, detail="A database error occurred. Please try again.")

    # ── 6. Build summary ───────────────────────────────────────────────────────
    parts = [f"{imported} imported."]
    if skipped_existing:
        parts.append(f"{skipped_existing} duplicate(s) already in Lead Database.")
    if skipped_in_file:
        parts.append(f"{skipped_in_file} duplicate email(s) in the file skipped.")
    if failed:
        parts.append(f"{failed} row(s) skipped (missing company or email).")
    if blank_rows:
        parts.append(f"{blank_rows} blank row(s) ignored.")
    if truncated:
        parts.append(f"{truncated} row(s) past {_MAX_ROWS}-row limit ignored.")

    return BaseResponse(
        status="success",
        message=" ".join(parts),
        data={
            "imported": imported,
            "skipped_duplicates": skipped,
            "skipped_duplicates_existing": skipped_existing,
            "skipped_duplicates_in_file": skipped_in_file,
            "failed_rows": failed,
            "blank_rows": blank_rows,
            "truncated_rows": truncated,
            "total_processed": len(parsed),
            "rows_in_file": len(non_blank_rows) + blank_rows + truncated,
        },
    )
