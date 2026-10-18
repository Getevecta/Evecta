from app.utils.lead_dedup import (
    is_duplicate_lead,
    normalize_email,
    register_lead_keys,
)


def test_normalize_email_treats_placeholders_as_missing():
    assert normalize_email("N/A") is None
    assert normalize_email("  ") is None
    assert normalize_email("Lead@example.com") == "lead@example.com"


def test_in_batch_duplicate_by_company_without_email():
    emails: set[str] = set()
    names: set[str] = set()

    assert not is_duplicate_lead("N/A", "The Taj Hotel", emails, names)
    register_lead_keys("N/A", "The Taj Hotel", emails, names)
    assert is_duplicate_lead("N/A", "The Taj Hotel", emails, names)


def test_in_batch_duplicate_by_email():
    emails: set[str] = set()
    names: set[str] = set()

    assert not is_duplicate_lead("same@hotel.com", "Hotel A", emails, names)
    register_lead_keys("same@hotel.com", "Hotel A", emails, names)
    assert is_duplicate_lead("same@hotel.com", "Hotel B", emails, names)
