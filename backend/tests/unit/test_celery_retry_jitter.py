from app.tasks.generate_campaign_emails import generate_campaign_emails_task
from app.tasks.enrich_leads import enrich_leads_task
from app.tasks.overture_tasks import load_overture_area_task, load_and_fill_overture_task


def test_generation_and_enrichment_retries_use_jitter():
    for task in (
        generate_campaign_emails_task,
        enrich_leads_task,
        load_overture_area_task,
        load_and_fill_overture_task,
    ):
        assert task.retry_jitter is True
        assert task.retry_backoff
        countdown = (task.retry_kwargs or {}).get("countdown")
        assert countdown is None, f"{task.name} still uses a fixed countdown"
