"""Reject control characters and enforce max lengths on user-supplied text."""
from __future__ import annotations

_UNSAFE = {"\r", "\n", "\x00"}
SUBJECT_MAX_LENGTH = 255
NAME_MAX_LENGTH = 255
CONTENT_MAX_LENGTH = 50_000
PROMPT_MAX_LENGTH = 8_000
DESCRIPTION_MAX_LENGTH = 8_000


def header_value_is_safe(value: str | None) -> bool:
    if value is None:
        return True
    return not any(ch in value for ch in _UNSAFE)


def text_value_is_safe(value: str | None, *, allow_newlines: bool = True) -> bool:
    if value is None:
        return True
    for ch in value:
        code = ord(ch)
        if code == 0 or code == 127:
            return False
        if code < 32:
            if ch == "\t":
                continue
            if allow_newlines and ch in "\n\r":
                continue
            return False
    return True


def require_safe_header(value: str, *, name: str, max_length: int | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required.")
    if not header_value_is_safe(value):
        raise ValueError(f"{name} contains invalid characters.")
    if max_length is not None and len(value) > max_length:
        raise ValueError(f"{name} is too long.")
    return value


def require_safe_text(
    value: str,
    *,
    name: str,
    max_length: int,
    allow_newlines: bool = True,
    required: bool = True,
    strip: bool = True,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} is required.")
    cleaned = value.strip() if strip else value
    if not cleaned:
        if required:
            raise ValueError(f"{name} is required.")
        return cleaned
    if not text_value_is_safe(cleaned, allow_newlines=allow_newlines):
        raise ValueError(f"{name} contains invalid characters.")
    if len(cleaned) > max_length:
        raise ValueError(f"{name} is too long.")
    return cleaned


def optional_safe_text(
    value: str | None,
    *,
    name: str,
    max_length: int,
    allow_newlines: bool = True,
    strip: bool = True,
) -> str | None:
    if value is None:
        return None
    cleaned = require_safe_text(
        value,
        name=name,
        max_length=max_length,
        allow_newlines=allow_newlines,
        required=False,
        strip=strip,
    )
    return cleaned or None
