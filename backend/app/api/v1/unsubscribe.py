import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Form

logger = logging.getLogger(__name__)
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database.session import get_session
from app.models.lead import Lead
from datetime import datetime, timezone
from app.utils.unsubscribe_token import generate_unsubscribe_token, verify_unsubscribe_token

router = APIRouter(prefix="/v1/unsubscribe", tags=["Email Subscription"])


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def unsubscribe_page(
    email: str = Query(..., description="Lead email address"),
    lead_id: str = Query(..., description="Lead ID"),
    token: str = Query(..., description="Unsubscribe token"),
    db: AsyncSession = Depends(get_session)
):
    """
    Shows a Gmail-style confirmation dialog before unsubscribing.
    """
    _base_style = """
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Google Sans', Roboto, Arial, sans-serif;
            background: #f1f3f4;
            display: flex; align-items: center; justify-content: center;
            min-height: 100vh; padding: 20px;
        }
        .dialog {
            background: #fff;
            border-radius: 28px;
            max-width: 480px; width: 100%;
            box-shadow: 0 8px 40px rgba(0,0,0,0.18);
            padding: 32px 32px 24px;
        }
        h2 { font-size: 22px; font-weight: 500; color: #202124; margin-bottom: 18px; }
        p  { font-size: 14px; color: #5f6368; line-height: 1.6; margin-bottom: 10px; }
        .actions {
            display: flex; justify-content: flex-end; gap: 8px; margin-top: 28px;
        }
        .btn {
            padding: 10px 24px; border-radius: 20px; font-size: 14px;
            font-weight: 500; cursor: pointer; border: none; outline: none;
            transition: background 0.15s;
        }
        .btn-cancel {
            background: transparent; color: #1a73e8;
        }
        .btn-cancel:hover { background: #e8f0fe; }
        .btn-unsub {
            background: #1a73e8; color: #fff;
        }
        .btn-unsub:hover { background: #1765cc; }
        .btn-unsub:disabled { background: #a8c7fa; cursor: default; }
        .success {
            display: none; text-align: center; padding: 8px 0 4px;
        }
        .success-icon { font-size: 44px; margin-bottom: 12px; }
        .success h2 { margin-bottom: 8px; }
    """

    if not verify_unsubscribe_token(token, lead_id, email):
        return HTMLResponse(content=f"""<!DOCTYPE html><html><head><title>Invalid Link</title>
        <meta name="viewport" content="width=device-width,initial-scale=1.0">
        <style>{_base_style}</style></head><body>
        <div class="dialog"><h2>Invalid Link</h2>
        <p>This unsubscribe link is invalid or has expired.</p></div>
        </body></html>""", status_code=400)

    lead = await db.get(Lead, lead_id)
    if not lead or lead.email != email:
        return HTMLResponse(content=f"""<!DOCTYPE html><html><head><title>Not Found</title>
        <meta name="viewport" content="width=device-width,initial-scale=1.0">
        <style>{_base_style}</style></head><body>
        <div class="dialog"><h2>Not Found</h2>
        <p>We couldn't find a subscription for this email address.</p></div>
        </body></html>""", status_code=404)

    already_unsubscribed = not lead.email_subscribed
    unsubscribe_action_url = f"/api/v1/unsubscribe/toggle?email={email}&lead_id={lead_id}&token={token}&action=unsubscribe"

    if already_unsubscribed:
        return HTMLResponse(content=f"""<!DOCTYPE html><html><head><title>Unsubscribed</title>
        <meta name="viewport" content="width=device-width,initial-scale=1.0">
        <style>{_base_style}</style></head><body>
        <div class="dialog" style="text-align:center;">
            <div style="font-size:44px;margin-bottom:16px;">✅</div>
            <h2>Already unsubscribed</h2>
            <p style="margin-top:8px;"><strong>{email}</strong> is already removed from this mailing list.</p>
        </div>
        </body></html>""")

    # Show Gmail-style confirmation dialog
    return HTMLResponse(content=f"""<!DOCTYPE html>
<html>
<head>
    <title>Unsubscribe</title>
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <style>{_base_style}</style>
</head>
<body>
<div class="dialog" id="dialog">

    <!-- Confirmation view -->
    <div id="confirm-view">
        <h2>Unsubscribe</h2>
        <p>Do you want to stop getting messages from this mailing list?</p>
        <div class="actions">
            <button class="btn btn-cancel" onclick="window.close()">Cancel</button>
            <button class="btn btn-unsub" id="unsub-btn" onclick="doUnsubscribe()">Unsubscribe</button>
        </div>
    </div>

    <!-- Success view (shown after unsubscribe) -->
    <div class="success" id="success-view">
        <div class="success-icon">✅</div>
        <h2>Unsubscribed</h2>
        <p><strong>{email}</strong> has been removed from this mailing list.<br>You will not receive any further emails.</p>
    </div>

</div>
<script>
async function doUnsubscribe() {{
    const btn = document.getElementById('unsub-btn');
    btn.disabled = true;
    btn.textContent = 'Unsubscribing...';
    try {{
        const res = await fetch('{unsubscribe_action_url}', {{ method: 'GET' }});
        if (!res.ok) throw new Error('Failed');
        document.getElementById('confirm-view').style.display = 'none';
        document.getElementById('success-view').style.display = 'block';
    }} catch (e) {{
        btn.disabled = false;
        btn.textContent = 'Unsubscribe';
        alert('Something went wrong. Please try again.');
    }}
}}
</script>
</body>
</html>""")


@router.get("/toggle", response_class=HTMLResponse)
async def toggle_subscription(
    email: str = Query(..., description="Lead email address"),
    lead_id: str = Query(..., description="Lead ID"),
    token: str = Query(..., description="Unsubscribe token"),
    action: str = Query(..., description="Action: 'subscribe' or 'unsubscribe'"),
    db: AsyncSession = Depends(get_session)
):
    """
    Toggle email subscription status.
    """
    try:
        # Verify token
        if not verify_unsubscribe_token(token, lead_id, email):
            return HTMLResponse(content="""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Invalid Link</title>
                <style>
                    body { font-family: Arial, sans-serif; text-align: center; padding: 50px; background: #f5f5f5; }
                    .container { background: white; padding: 40px; border-radius: 8px; max-width: 500px; margin: 0 auto; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
                    h1 { color: #EF4444; }
                    p { color: #6B7280; }
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>Invalid Link</h1>
                    <p>This link is invalid or has expired.</p>
                </div>
            </body>
            </html>
            """, status_code=400)

        # Fetch lead
        lead = await db.get(Lead, lead_id)
        if not lead or lead.email != email:
            return HTMLResponse(content="""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Not Found</title>
                <style>
                    body { font-family: Arial, sans-serif; text-align: center; padding: 50px; background: #f5f5f5; }
                    .container { background: white; padding: 40px; border-radius: 8px; max-width: 500px; margin: 0 auto; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
                    h1 { color: #EF4444; }
                    p { color: #6B7280; }
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>Not Found</h1>
                    <p>We couldn't find your email subscription.</p>
                </div>
            </body>
            </html>
            """, status_code=404)

        # Update subscription status
        if action == "unsubscribe":
            lead.email_subscribed = False
            message = "You have been successfully unsubscribed. You will no longer receive emails from Evecta Outreach."
            new_status = "unsubscribed"
        elif action == "subscribe":
            lead.email_subscribed = True
            message = "You have been successfully subscribed. You will now receive emails from Evecta Outreach."
            new_status = "subscribed"
        else:
            raise HTTPException(status_code=400, detail="Invalid action")

        lead.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(lead)

        # Show success modal
        return HTMLResponse(content=f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Subscription Updated</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; min-height: 100vh; padding: 20px; }}
                .modal-overlay {{ position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.4); z-index: 1000; cursor: pointer; }}
                .modal {{ background: white; border-radius: 8px; max-width: 500px; width: 100%; box-shadow: 0 8px 32px rgba(0,0,0,0.2); z-index: 1001; position: relative; animation: slideIn 0.2s ease-out; }}
                @keyframes slideIn {{
                    from {{ transform: translateY(-20px); opacity: 0; }}
                    to {{ transform: translateY(0); opacity: 1; }}
                }}
                .modal-header {{ padding: 20px 24px; border-bottom: 1px solid #e5e7eb; }}
                .modal-title {{ font-size: 18px; font-weight: 600; color: #111827; display: flex; align-items: center; gap: 8px; }}
                .check-icon {{ color: #10b981; font-size: 20px; }}
                .modal-body {{ padding: 24px; }}
                .modal-message {{ color: #5f6368; font-size: 14px; line-height: 1.6; margin-bottom: 16px; }}
                .status-badge {{ display: inline-block; padding: 6px 12px; border-radius: 999px; font-size: 12px; font-weight: 600; }}
                .status-badge.subscribed {{ background: #D1FAE5; color: #065F46; }}
                .status-badge.unsubscribed {{ background: #FEE2E2; color: #991B1B; }}
                .modal-footer {{ padding: 16px 24px; border-top: 1px solid #e5e7eb; display: flex; justify-content: flex-end; gap: 12px; }}
                .btn {{ padding: 10px 24px; border-radius: 6px; font-size: 14px; font-weight: 500; cursor: pointer; border: none; transition: all 0.2s; min-width: 100px; }}
                .btn-primary {{ background: #1a73e8; color: white; }}
                .btn-primary:hover {{ background: #1765cc; }}
            </style>
        </head>
        <body>
            <div class="modal-overlay" onclick="window.close()"></div>
            <div class="modal" onclick="event.stopPropagation()">
                <div class="modal-header">
                    <div class="modal-title">
                        <span class="check-icon">✓</span>
                        Subscription Updated
                    </div>
                </div>
                <div class="modal-body">
                    <div class="modal-message">
                        {message}
                    </div>
                    <div style="margin-top: 12px; font-size: 13px; color: #5f6368;">
                        Current status: <span class="status-badge {new_status}">{new_status}</span>
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-primary" onclick="window.close()">Close</button>
                </div>
            </div>
            <script>
                function handleClose() {{
                    // Try to close the window (works if opened as popup or from email)
                    if (window.opener) {{
                        window.close();
                    }} else {{
                        // If can't close programmatically, try to go back
                        try {{
                            window.close();
                        }} catch(e) {{
                            // If that fails, redirect to a blank page or show message
                            document.body.innerHTML = '<div style="text-align:center;padding:50px;font-family:system-ui;"><h2>✓ Subscription Updated</h2><p>{message}</p><p style="color:#666;font-size:12px;margin-top:20px;">You can close this tab.</p></div>';
                        }}
                    }}
                }}
                
                // Auto-close after 2 seconds
                setTimeout(function() {{
                    handleClose();
                }}, 2000);
                
                // Close on Escape key
                document.addEventListener('keydown', function(e) {{
                    if (e.key === 'Escape') {{
                        handleClose();
                    }}
                }});
                
                // Update close button
                document.querySelector('.btn-primary').onclick = handleClose;
            </script>
        </body>
        </html>
        """)

    except HTTPException:
        raise
    except Exception as e:
        return HTMLResponse(content=f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Error</title>
            <style>
                body {{ font-family: Arial, sans-serif; text-align: center; padding: 50px; background: #f5f5f5; }}
                .container {{ background: white; padding: 40px; border-radius: 8px; max-width: 500px; margin: 0 auto; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
                h1 {{ color: #EF4444; }}
                p {{ color: #6B7280; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Error</h1>
                <p>An error occurred while updating your subscription. Please try again later.</p>
            </div>
        </body>
        </html>
        """, status_code=500)


async def _process_one_click_unsubscribe(request: Request, db: AsyncSession) -> Response:
    """
    RFC 8058 one-click unsubscribe handler used by Gmail/Outlook.
    Must return 200 quickly with no redirects or confirmation pages.
    """
    from urllib.parse import urlparse, parse_qs

    try:
        parsed = urlparse(str(request.url))
        params = parse_qs(parsed.query)

        email = params.get("email", [None])[0]
        lead_id = params.get("lead_id", [None])[0]
        token = params.get("token", [None])[0]

        body_text = ""
        if not email or not lead_id or not token:
            try:
                form_data = await request.form()
                if form_data:
                    # RFC 8058 POST body is "List-Unsubscribe=One-Click"; params live in URL.
                    one_click_flag = form_data.get("List-Unsubscribe", "")
                    if one_click_flag == "One-Click":
                        pass
                    else:
                        # Legacy clients may POST the full unsubscribe URL in the body.
                        unsubscribe_url = one_click_flag
                        if unsubscribe_url and unsubscribe_url.startswith("http"):
                            parsed = urlparse(unsubscribe_url)
                            params = parse_qs(parsed.query)
                            email = params.get("email", [None])[0] or email
                            lead_id = params.get("lead_id", [None])[0] or lead_id
                            token = params.get("token", [None])[0] or token
            except Exception as exc:
                logger.debug(
                    "One-click unsubscribe: unable to parse form body for fallback parameters: %s",
                    exc,
                    exc_info=True,
                )
                body = await request.body()
                body_text = body.decode("utf-8") if body else ""

        request_url = str(request.url)
        if not email or not lead_id or not token:
            logger.warning(
                f"⚠️ One-click unsubscribe: Missing parameters. URL: {request_url}, Body: {body_text[:200]}"
            )
            return Response(content="OK", status_code=200, headers={"Content-Type": "text/plain"})

        if not verify_unsubscribe_token(token, lead_id, email):
            logger.warning(f"⚠️ One-click unsubscribe: Invalid token for email {email}")
            return Response(content="OK", status_code=200, headers={"Content-Type": "text/plain"})

        lead = await db.get(Lead, lead_id)
        if not lead or lead.email != email:
            logger.warning(f"⚠️ One-click unsubscribe: Lead not found for email {email}")
            return Response(content="OK", status_code=200, headers={"Content-Type": "text/plain"})

        if lead.email_subscribed:
            lead.email_subscribed = False
            lead.updated_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info(f"✅ One-click unsubscribe: Successfully unsubscribed {email}")

        return Response(content="OK", status_code=200, headers={"Content-Type": "text/plain"})

    except Exception as e:
        logger.error(f"❌ One-click unsubscribe error: {str(e)}")
        import traceback
        traceback.print_exc()
        return Response(content="OK", status_code=200, headers={"Content-Type": "text/plain"})


@router.get("/one-click", status_code=200)
async def one_click_unsubscribe_get(
    email: str | None = Query(None),
    lead_id: str | None = Query(None),
    token: str | None = Query(None),
):
    """
    Gmail probes the List-Unsubscribe URL with GET before showing native
    header/inbox-hover Unsubscribe. Must return 200 with no redirects.
    """
    return Response(content="OK", status_code=200, headers={"Content-Type": "text/plain"})


@router.post("/one-click", status_code=200)
async def one_click_unsubscribe_post(
    request: Request,
    db: AsyncSession = Depends(get_session),
):
    """Dedicated one-click endpoint referenced in List-Unsubscribe email headers."""
    return await _process_one_click_unsubscribe(request, db)


@router.post("", status_code=200)
@router.post("/", status_code=200)
async def one_click_unsubscribe_post_legacy(
    request: Request,
    db: AsyncSession = Depends(get_session),
):
    """Legacy one-click POST target (kept for older sent emails)."""
    return await _process_one_click_unsubscribe(request, db)
