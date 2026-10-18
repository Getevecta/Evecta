import re

PLACEHOLDER_PATTERN = re.compile(r"\[([a-zA-Z0-9_ ]+)\]")


def check_unmodified_placeholders(content: str) -> list[str]:
    """Return square-bracket placeholders still present in content."""
    return PLACEHOLDER_PATTERN.findall(content)
