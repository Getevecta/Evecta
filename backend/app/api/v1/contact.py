import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request, status

from app.core.limiter import limiter
from app.schemas.contact import ContactFormRequest, ContactFormResponse
from app.services.contact_form_service import send_contact_form_email

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Contact"])


@router.post("/contact", response_model=ContactFormResponse)
@limiter.limit("5/hour")
async def submit_contact_form(
    request: Request,
    body: ContactFormRequest,
):
    """
    Public contact form — delivers submissions to   via SMTP (APP_SMTP_*).
    """
    ok = await asyncio.to_thread(
        send_contact_form_email,
        body.full_name.strip(),
        str(body.email).strip(),
        body.company_name.strip() if body.company_name else None,
        body.subject.strip(),
        body.message.strip(),
    )

    if not ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Mail could not be sent right now. Please try again later or email us directly at mail@evecta.io.",
        )

    return ContactFormResponse(
        message="Thanks — your message has been sent. We'll get back to you soon."
    )
