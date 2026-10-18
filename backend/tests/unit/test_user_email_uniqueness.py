"""Identity emails are unique case-insensitively at the database layer."""
from app.models.mailbox import Mailbox
from app.models.user import User
from app.models.waitlist import Waitlist


def _assert_lower_unique(model, column_name: str, index_name: str) -> None:
    email_col = model.__table__.c[column_name]
    assert not email_col.unique

    unique_indexes = {ix.name: ix for ix in model.__table__.indexes if ix.unique}
    assert index_name in unique_indexes
    assert unique_indexes[index_name].unique


def test_user_email_unique_on_lower_not_raw_column():
    _assert_lower_unique(User, "email", "ix_users_email_lower")


def test_mailbox_email_unique_on_lower_not_raw_column():
    _assert_lower_unique(Mailbox, "email", "ix_mailboxes_email_lower")


def test_waitlist_email_unique_on_lower_not_raw_column():
    _assert_lower_unique(Waitlist, "email", "ix_waitlist_email_lower")
