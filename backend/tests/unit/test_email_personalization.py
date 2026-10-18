from app.utils.email_personalization import replace_placeholders


class _Lead:
    def __init__(self):
        self.business_name = "Acme"
        self.email = "a@acme.test"
        self._sa_instance_state = object()


def test_replace_placeholders_from_lead_object():
    out = replace_placeholders("Hi {{ business_name }} at {{ email }}", _Lead())
    assert out == "Hi Acme at a@acme.test"


def test_replace_placeholders_uses_sample_when_no_lead():
    out = replace_placeholders("Hello {{ business_name }}")
    assert "Sample Company" in out


def test_replace_placeholders_from_dict():
    out = replace_placeholders("{{ industry }}", {"industry": "SaaS"})
    assert out == "SaaS"
