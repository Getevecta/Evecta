from datetime import datetime, timezone
from sqlalchemy import select, func, distinct, Integer
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_activity import EmailActivity, EmailStatus
from app.models.mailbox import Mailbox, MailboxType


MONTHLY_LIMIT = 300
HEALTHY_THRESHOLD = 95.0


async def get_system_email_insights(
    *,
    user_id: str,
    db: AsyncSession,
) -> dict:
    """
    SYSTEM email insights for a user.
    - Monthly limit: 300 emails
    - Daily limit is enforced internally (not exposed here)
    """

    # 1️⃣ Fetch ALL active SYSTEM mailbox emails
    mailbox_stmt = (
        select(Mailbox.email)
        .where(
            Mailbox.mailbox_type == MailboxType.SYSTEM,
            Mailbox.is_active.is_(True),
        )
    )

    res = await db.execute(mailbox_stmt)
    system_emails = [row[0] for row in res.fetchall()]

    if not system_emails:
        return _empty_response()

    # 2️⃣ Monthly email stats (USER-SCOPED)
    # FAILED attempts are not sends — they must not consume the monthly
    # quota or deflate the delivery rate.
    stats_stmt = (
        select(
            func.count(EmailActivity.id).label("sent"),
            func.sum(func.cast(EmailActivity.delivered, Integer)).label("delivered"),
            func.sum(func.cast(EmailActivity.bounced, Integer)).label("bounced"),
        )
        .where(
            EmailActivity.user_id == user_id,
            EmailActivity.sent_from.in_(system_emails),
            EmailActivity.status != EmailStatus.FAILED,
            EmailActivity.sent_at >= func.date_trunc("month", func.now()),
        )
    )

    stats = (await db.execute(stats_stmt)).one()

    sent = stats.sent or 0
    delivered = stats.delivered or 0
    bounced = stats.bounced or 0

    # 3️⃣ Active SYSTEM mailboxes used
    active_accounts_stmt = (
        select(func.count(distinct(EmailActivity.sent_from)))
        .where(
            EmailActivity.user_id == user_id,
            EmailActivity.sent_from.in_(system_emails),
            EmailActivity.sent_at >= func.date_trunc("month", func.now()),
        )
    )

    active_accounts = (await db.execute(active_accounts_stmt)).scalar() or 0

    # 4️⃣ Derived metrics
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1)
    days_elapsed = max((now - month_start).days + 1, 1)

    delivery_rate = round((delivered / sent) * 100, 2) if sent else 0.0
    bounce_rate = round((bounced / sent) * 100, 2) if sent else 0.0
    avg_daily_sending = round(sent / days_elapsed)

    remaining = max(MONTHLY_LIMIT - sent, 0)
    monthly_usage_percent = round((sent / MONTHLY_LIMIT) * 100, 2)

    return {
        "total_sent": sent,
        "remaining": remaining,
        "delivery_rate": delivery_rate,
        "bounce_rate": bounce_rate,
        "active_accounts": active_accounts,
        "avg_daily_sending": avg_daily_sending,
        "monthly_usage_percent": monthly_usage_percent,
    }


def _empty_response() -> dict:
    return {
        "total_sent": 0,
        "remaining": MONTHLY_LIMIT,
        "delivery_rate": 0.0,
        "bounce_rate": 0.0,
        "active_accounts": 0,
        "avg_daily_sending": 0,
        "monthly_usage_percent": 0.0,
    }


# USER EMAIL OVERVIEW (TOP CARDS)
async def get_user_email_overview_service(
    *,
    user_id: str,
    db: AsyncSession,
) -> dict:
    """
    USER email accounts overview (cards section).

    Delivery rate = average of per-mailbox delivery rates (used mailboxes only).
    Health = count of healthy mailboxes:
             - sent == 0  → healthy
             - sent > 0 and rate >= HEALTHY_THRESHOLD → healthy
    Active accounts = count of accounts where is_active == True
    """

    # Fetch USER mailboxes
    mailbox_stmt = (
        select(Mailbox.email, Mailbox.is_active)
        .where(
            Mailbox.user_id == user_id,
            Mailbox.mailbox_type == MailboxType.USER,
        )
    )

    res = await db.execute(mailbox_stmt)
    user_mailboxes = res.fetchall()

    user_emails = [row[0] for row in user_mailboxes]
    active_accounts = sum(1 for row in user_mailboxes if row[1])  # count active mailboxes

    total_accounts = len(user_emails)

    if not user_emails:
        return {
            "total_accounts": 0,
            "sent_today": 0,
            "delivery_rate": 0.0,
            "healthy_accounts": 0,
            "active_accounts": 0,
        }

    # Sent today (USER mail only, successful sends)
    sent_today_stmt = (
        select(func.count(EmailActivity.id))
        .where(
            EmailActivity.user_id == user_id,
            EmailActivity.sent_from.in_(user_emails),
            EmailActivity.status != EmailStatus.FAILED,
            EmailActivity.sent_at >= func.date_trunc("day", func.now()),
        )
    )

    sent_today = (await db.execute(sent_today_stmt)).scalar() or 0

    # Single GROUP BY query replaces the per-mailbox loop (was N queries → 1 query)
    delivery_rates: list[float] = []
    healthy_accounts = 0

    # USER mailboxes (Gmail/SMTP) receive no SES Delivery events, so the
    # `delivered` flag stays False even for perfectly delivered mail.
    # Delivery is therefore approximated as sent − bounced.
    bulk_stats_stmt = (
        select(
            EmailActivity.sent_from,
            func.count(EmailActivity.id).label("sent"),
            func.sum(func.cast(EmailActivity.bounced, Integer)).label("bounced"),
        )
        .where(
            EmailActivity.user_id == user_id,
            EmailActivity.sent_from.in_(user_emails),
            EmailActivity.status != EmailStatus.FAILED,
        )
        .group_by(EmailActivity.sent_from)
    )
    stats_map = {
        row.sent_from: (row.sent or 0, row.bounced or 0)
        for row in (await db.execute(bulk_stats_stmt)).all()
    }

    for email in user_emails:
        sent, bounced = stats_map.get(email, (0, 0))

        if sent == 0:
            healthy_accounts += 1
            continue

        rate = ((sent - bounced) / sent) * 100
        delivery_rates.append(rate)

        if rate >= HEALTHY_THRESHOLD:
            healthy_accounts += 1

    # Average delivery rate (used mailboxes only)
    avg_delivery_rate = (
        round(sum(delivery_rates) / len(delivery_rates), 2)
        if delivery_rates
        else 0.0
    )

    return {
        "total_accounts": total_accounts,
        "sent_today": sent_today,
        "delivery_rate": avg_delivery_rate,
        "healthy_accounts": healthy_accounts,
        "active_accounts": active_accounts,  
    }

# USER EMAIL ACCOUNTS TABLE
async def get_user_email_accounts_service(
    *,
    user_id: str,
    db: AsyncSession,
) -> list[dict]:
    """
    USER connected email accounts table.
    """

    mailboxes_stmt = (
        select(Mailbox)
        .where(
            Mailbox.user_id == user_id,
            Mailbox.mailbox_type == MailboxType.USER,
        )
    )

    mailboxes = (await db.execute(mailboxes_stmt)).scalars().all()

    # Single GROUP BY query for all mailboxes (was N queries → 1 query)
    # Same delivery approximation as the overview: USER mailboxes get no
    # SES Delivery events, so delivered ≈ sent − bounced.
    mailbox_emails = [m.email for m in mailboxes]
    bulk_stmt = (
        select(
            EmailActivity.sent_from,
            func.count(EmailActivity.id).label("sent"),
            func.sum(func.cast(EmailActivity.bounced, Integer)).label("bounced"),
        )
        .where(
            EmailActivity.user_id == user_id,
            EmailActivity.sent_from.in_(mailbox_emails),
            EmailActivity.status != EmailStatus.FAILED,
        )
        .group_by(EmailActivity.sent_from)
    )
    mailbox_stats_map = {
        row.sent_from: (row.sent or 0, row.bounced or 0)
        for row in (await db.execute(bulk_stmt)).all()
    }

    results: list[dict] = []

    for mailbox in mailboxes:
        sent, bounced = mailbox_stats_map.get(mailbox.email, (0, 0))

        delivery_rate = round(((sent - bounced) / sent) * 100, 2) if sent else 0.0

        results.append({
            "email": mailbox.email,
            "provider": mailbox.provider.value,
            "status": "Active" if mailbox.is_active else "Inactive",
            # Unused mailbox (sent == 0) is healthy — same rule as the overview cards
            "health": "Healthy" if sent == 0 or delivery_rate >= HEALTHY_THRESHOLD else "Warning",
            "delivery_rate": delivery_rate,
            "total_sent": sent,
        })

    return results
