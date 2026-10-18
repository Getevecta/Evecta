from sqlalchemy import select, func, Integer, Date, cast
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException
from datetime import datetime, timedelta, timezone, date

from app.core.email_limits import DAILY_EMAIL_LIMIT
from app.enums.email_sending_mode import EmailSendingMode
from app.models.email_activity import EmailActivity, EmailStatus
from app.models.campaign import Campaign, CampaignStatus
from app.models.campaign_lead import CampaignLead
from app.models.email_job import EmailJob, EmailJobStatus
from app.models.mailbox import Mailbox, MailboxType


def _sent_activity_conditions(campaign_id: str):
    return (
        EmailActivity.campaign_id == campaign_id,
        # Failed send attempts keep sent_at for audit/history, but they are not
        # successful outreach and must not drive sent counters or charts.
        EmailActivity.status != EmailStatus.FAILED,
    )


def _build_daily_stats_stmt(campaign_id: str, from_date: date, to_date: date):
    return (
        select(
            cast(EmailActivity.sent_at, Date).label("date"),
            func.count().label("sent"),
            func.sum(cast(EmailActivity.opened, Integer)).label("opened"),
            func.sum(cast(EmailActivity.clicked, Integer)).label("clicked"),
            func.sum(cast(EmailActivity.bounced, Integer)).label("bounced"),
            func.sum(cast(EmailActivity.replied, Integer)).label("total_replied"),
        )
        .where(
            *_sent_activity_conditions(campaign_id),
            cast(EmailActivity.sent_at, Date) >= from_date,
            cast(EmailActivity.sent_at, Date) <= to_date,
        )
        .group_by(cast(EmailActivity.sent_at, Date))
        .order_by(cast(EmailActivity.sent_at, Date))
    )


def _build_failed_leads_stmt(campaign_id: str, user_id: str):
    # A lead only counts as failed if it has NO successful send in this
    # campaign. Failed attempts keep their FAILED activity row forever, so a
    # lead that failed once and succeeded on retry would otherwise be counted
    # in BOTH total_sent and total_failed — double-subtracting it from
    # `remaining`.
    succeeded_leads = select(EmailActivity.lead_id).where(
        EmailActivity.campaign_id == campaign_id,
        EmailActivity.status != EmailStatus.FAILED,
        EmailActivity.lead_id.isnot(None),
    )
    failed_activity_leads = select(EmailActivity.lead_id).where(
        EmailActivity.campaign_id == campaign_id,
        EmailActivity.status == EmailStatus.FAILED,
        EmailActivity.lead_id.isnot(None),
        EmailActivity.lead_id.notin_(succeeded_leads),
    )
    failed_job_leads = select(EmailJob.lead_id).where(
        EmailJob.campaign_id == campaign_id,
        EmailJob.user_id == user_id,
        EmailJob.status == EmailJobStatus.FAILED,
        EmailJob.lead_id.isnot(None),
        EmailJob.lead_id.notin_(succeeded_leads),
    )
    failed_leads = failed_activity_leads.union(failed_job_leads).subquery()
    return select(func.count()).select_from(failed_leads)


async def get_campaign_insight(
    campaign_id: str,
    user_id: str,
    db: AsyncSession,
    range_days: int = 7,
    start_date: date | None = None,
    end_date: date | None = None,
):
    try:
        #  Campaign validation
        campaign = await db.get(Campaign, campaign_id)
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        if campaign.user_id != user_id:
            raise HTTPException(status_code=403, detail="Unauthorized access")

        #  Get total leads count for the campaign
        total_leads_stmt = select(func.count(CampaignLead.id)).where(
            CampaignLead.campaign_id == campaign_id
        )
        total_leads = (await db.scalar(total_leads_stmt)) or 0

        #  Resolve date range
        now = datetime.now(timezone.utc)
        today = now.date()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

        if start_date and end_date:
            if start_date > end_date:
                raise HTTPException(status_code=400, detail="start_date cannot be after end_date")
            from_date = start_date
            to_date = end_date

        elif start_date or end_date:
            raise HTTPException(
                status_code=400,
                detail="Both start_date and end_date are required for custom range",
            )
        else:
            # Default / range-based
            from_date = today - timedelta(days=range_days - 1)
            to_date = today

        #  Aggregate totals
        totals_stmt = (
            select(
                func.count().label("total_sent"),
                func.sum(cast(EmailActivity.opened, Integer)).label("total_opened"),
                func.sum(cast(EmailActivity.clicked, Integer)).label("total_clicked"),
                func.sum(cast(EmailActivity.bounced, Integer)).label("total_bounced"),
                func.sum(cast(EmailActivity.delivered, Integer)).label("total_delivered"),
                func.sum(cast(EmailActivity.replied, Integer)).label("total_replied"),
            )
            .where(
                *_sent_activity_conditions(campaign_id),
                cast(EmailActivity.sent_at, Date) >= from_date,
                cast(EmailActivity.sent_at, Date) <= to_date,
            )
        )

        totals = (await db.execute(totals_stmt)).first() or {}

        total_sent = totals.total_sent or 0
        total_opened = totals.total_opened or 0
        total_clicked = totals.total_clicked or 0
        total_bounced = totals.total_bounced or 0
        total_delivered = totals.total_delivered or 0
        total_replied = totals.total_replied or 0

        #  Tracking metrics are LEAD-based (distinct leads), not email-based.
        #  Analytics totals above stay email-based (open/reply rates are per
        #  email sent). Once follow-up sequences exist, one lead will have
        #  several activities — counting rows here would overstate outreach
        #  and understate `remaining`.
        #  Exclude FAILED only — emails that progress to OPENED/CLICKED/BOUNCED
        #  have their status updated away from SENT, so we must NOT filter by status == SENT
        leads_outreached_stmt = select(
            func.count(func.distinct(EmailActivity.lead_id))
        ).where(*_sent_activity_conditions(campaign_id))
        leads_outreached = (await db.scalar(leads_outreached_stmt)) or 0
        total_failed = (await db.scalar(_build_failed_leads_stmt(campaign_id, user_id))) or 0

        #  Leads contacted today (distinct — a follow-up to an already
        #  contacted lead is not a newly contacted lead)
        today_sent_stmt = select(
            func.count(func.distinct(EmailActivity.lead_id))
        ).where(
            *_sent_activity_conditions(campaign_id),
            EmailActivity.sent_at >= today_start,
            EmailActivity.sent_at <= today_end
        )
        outreached_today = (await db.scalar(today_sent_stmt)) or 0

        #  Remaining = leads never successfully contacted and not failed.
        #  All three terms are lead counts, so they are mutually exclusive.
        remaining = max(0, total_leads - leads_outreached - total_failed)

        #  Effective daily sending capacity — mirrors the two send-time gates
        #  in app.tasks.mail_job: the per-user DAILY_EMAIL_LIMIT (counted
        #  across ALL campaigns) and the per-mailbox daily limits enforced by
        #  the mailbox selector. The estimate projects from these caps rather
        #  than from historical averages, because they are what actually
        #  throttles sending.
        sending_mode = campaign.email_sending_mode or EmailSendingMode.USER
        mailbox_filters = [Mailbox.is_active.is_(True)]
        if sending_mode == EmailSendingMode.SYSTEM:
            mailbox_filters.append(Mailbox.mailbox_type == MailboxType.SYSTEM)
        else:
            mailbox_filters.append(Mailbox.mailbox_type == MailboxType.USER)
            mailbox_filters.append(Mailbox.user_id == user_id)

        mailbox_caps = (
            await db.execute(
                select(
                    func.coalesce(func.sum(Mailbox.daily_limit), 0),
                    func.coalesce(
                        func.sum(func.greatest(Mailbox.daily_limit - Mailbox.sent_today, 0)),
                        0,
                    ),
                ).where(*mailbox_filters)
            )
        ).first()
        mailbox_daily_capacity = int(mailbox_caps[0] or 0)
        mailbox_left_today = int(mailbox_caps[1] or 0)

        daily_outreach_rate = min(DAILY_EMAIL_LIMIT, mailbox_daily_capacity)

        #  Capacity still available today: the user-level cap counts today's
        #  successful sends across all campaigns (same query mail_job uses),
        #  and the mailbox side counts what the active mailboxes have left.
        user_sent_today = (
            await db.scalar(
                select(func.count(EmailActivity.id)).where(
                    EmailActivity.user_id == user_id,
                    EmailActivity.status != EmailStatus.FAILED,
                    EmailActivity.sent_at >= today_start,
                    EmailActivity.sent_at <= today_end,
                )
            )
        ) or 0
        today_capacity = max(0, min(DAILY_EMAIL_LIMIT - user_sent_today, mailbox_left_today))

        #  The user's other campaigns drain the same daily quota. Jobs are
        #  processed roughly FIFO, so this campaign's last send lands after
        #  the whole currently queued workload drains, not just its own.
        other_campaigns_queued = (
            await db.scalar(
                select(func.count(EmailJob.id)).where(
                    EmailJob.user_id == user_id,
                    EmailJob.campaign_id != campaign_id,
                    EmailJob.status.in_([EmailJobStatus.QUEUED, EmailJobStatus.SENDING]),
                )
            )
        ) or 0

        #  Days/date stay None when no honest estimate exists (campaign not
        #  ongoing, or zero mailbox capacity) — the UI shows that as-is
        #  instead of a made-up number.
        estimated_completion_days = None
        estimated_completion_date = None
        if remaining <= 0:
            estimated_completion_days = 0
            estimated_completion_date = today.isoformat()
        elif campaign.status == CampaignStatus.ONGOING and daily_outreach_rate > 0:
            workload = remaining + other_campaigns_queued
            if workload <= today_capacity:
                estimated_completion_days = 0
            else:
                overflow = workload - today_capacity
                estimated_completion_days = 1 + (
                    (overflow + daily_outreach_rate - 1) // daily_outreach_rate  # Ceiling division
                )
            estimated_completion_date = (
                today + timedelta(days=estimated_completion_days)
            ).isoformat()

        # Rates
        def rate(value: int) -> float:
            return round((value / total_sent) * 100, 2) if total_sent else 0.0

        # Daily breakdown
        daily_stmt = _build_daily_stats_stmt(campaign_id, from_date, to_date)

        rows = (await db.execute(daily_stmt)).all()

        stats_map = {
            row.date.isoformat(): {
                "sent": row.sent or 0,
                "opened": row.opened or 0,
                "clicked": row.clicked or 0,
                "bounced": row.bounced or 0,
                "replied": row.total_replied or 0,

            }
            for row in rows
            if row.date
        }

        daily_stats = []
        total_days = (to_date - from_date).days + 1

        for i in range(total_days):
            d = from_date + timedelta(days=i)
            daily_stats.append({
                "date": d.isoformat(),
                "day": f"Day {i + 1}",
                **stats_map.get(d.isoformat(), {
                    "sent": 0,
                    "opened": 0,
                    "clicked": 0,
                    "bounced": 0,
                    "replied": 0,
                }),
            })

        # Final response
        return {
            "campaign_id": str(campaign.id),
            "campaign_name": campaign.name,
            "status": campaign.status.value,
            "range": {
                "from": from_date.isoformat(),
                "to": to_date.isoformat(),
                "days": total_days,
            },
            "total_sent": total_sent,
            "total_opened": total_opened,
            "total_clicked": total_clicked,
            "total_bounced": total_bounced,
            "total_delivered": total_delivered,
            "total_replied": total_replied,
            "total_failed": total_failed,
            "open_rate": rate(total_opened),
            "click_rate": rate(total_clicked),
            "bounce_rate": rate(total_bounced),
            "delivery_rate": rate(total_delivered),
            "reply_rate": rate(total_replied),
            "daily_stats": daily_stats,
            # Tracking metrics for Campaign Outreach Progress
            "tracking": {
                "total_leads": total_leads,
                "outreached_today": outreached_today,
                "total_outreached": leads_outreached,
                "failed": total_failed,
                "remaining": remaining,
                "estimated_completion_days": estimated_completion_days,
                "estimated_completion_date": estimated_completion_date,
                "daily_outreach_rate": daily_outreach_rate,
            },
        }

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve campaign insights",
        )
