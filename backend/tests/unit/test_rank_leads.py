from app.services.chat_service import rank_leads


def _names(leads):
    return [l["business_name"] for l in leads]


def test_completeness_ranks_higher_within_tier():
    leads = [
        {"business_name": "Bare Co", "address": "Sydney", "email": None, "website": "N/A", "contact_number": "N/A"},
        {"business_name": "Full Co", "address": "Sydney", "email": "a@b.com", "website": "b.com", "contact_number": "123"},
    ]
    assert _names(rank_leads(leads, "hotel", [], "Sydney"))[0] == "Full Co"


def test_name_keyword_match_boosts():
    leads = [
        {"business_name": "Generic Shop", "address": "Sydney", "email": "a@b.com", "website": "b.com", "contact_number": "1"},
        {"business_name": "Apple Reseller", "address": "Sydney", "email": "a@b.com", "website": "b.com", "contact_number": "1"},
    ]
    assert _names(rank_leads(leads, "apple store", ["apple store"], "Sydney"))[0] == "Apple Reseller"


def test_location_priority_preserved():
    # A city-matching lead ranks first even if it's less complete than a faraway one.
    leads = [
        {"business_name": "Full Faraway", "address": "Melbourne", "email": "a@b.com", "website": "b.com", "contact_number": "1"},
        {"business_name": "Bare Sydney", "address": "Sydney", "email": None, "website": "N/A", "contact_number": "N/A"},
    ]
    assert _names(rank_leads(leads, "hotel", [], "Sydney"))[0] == "Bare Sydney"


def test_empty_and_single_are_safe():
    assert rank_leads([], "hotel", [], "Sydney") == []
    one = [{"business_name": "Solo", "address": "X", "email": None, "website": "N/A", "contact_number": "N/A"}]
    assert _names(rank_leads(one, "hotel", [], "Sydney")) == ["Solo"]
