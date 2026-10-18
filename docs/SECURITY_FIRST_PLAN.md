# Security-first implementation order

From the Evecta security audit in [SECURITY_AND_EFFICIENCY_FIXED.md](./SECURITY_AND_EFFICIENCY_FIXED.md). That document is findings only. This plan is **security only** — efficiency, architecture, and database normalization stay out until the items below are closed.

| | |
|---|---|
| Critical findings | 3 |
| High findings | 10 |
| Current security rating | 6.5/10 |
| After these fixes | ~9/10 |

**Why this order:** authorization that does not revoke, forgeable SES webhooks, and stored XSS in Inbox are the items that show up in a breach post-mortem. SSRF, OAuth injection, and MIME-header injection are next because they are reachable from authenticated product flows. Auth polish, rate limits, and headers come after those doors are closed.

---

## Wave 0 — operations, today

No application change required. Do this even if the rest of the sprint slips.

- [ ] Rotate both historical Hunter.io keys (`4f7ed8f9…4952a6` and `d0aaaaad…5f243`). They are reachable on `dev`, `feature/campaign`, and `feature/source-changes`. Treat them as compromised. Confirm the live `HUNTER_API_KEY` in secrets is a new unused key. History rewriting is optional cleanup; rotation is mandatory.

---

## Wave 1 — close the breach-class bugs this week

Four defects. Two are authorization/integrity on the backend; two are session theft on the frontend. Fix them as one batch — the Inbox XSS is far more damaging while the access token still lives in `localStorage`.

| # | Status | Finding | Severity | Where | What to implement |
|---|---|---|---|---|---|
| 1 | **Done** | Permission revoke does not revoke | Critical | `require_permission` / `get_effective_permissions` | Honor `is_enabled=False`. Point the route guard at `calculate_final_permissions`. Implemented: `backend/app/services/permission_service.py`, `backend/app/dependencies/auth.py`, `backend/app/services/effective_permission_service.py`, `backend/tests/unit/test_permission_overrides.py`. Follow-up: the override write API still only stores `is_enabled=True`, so admins cannot persist a revoke through that endpoint. |
| 2 | **Done** | Forgeable SES/SNS webhooks | Critical + High | `webhook_ses.py`, `sns_trust.py` | `SigningCertURL` must be HTTPS `sns.<region>.amazonaws.com` plus the AWS cert filename. `SubscribeURL` uses the host check only. Empty `SNS_ALLOWED_TOPIC_ARNS` 403s all webhook traffic. Follow-up: replay/idempotency + topic/cert tests; signature failures emit `[SNS_SIGNATURE_FAILURE]` CRITICAL plus a Redis counter. |
| 3 | Open | Stored XSS from inbound email HTML | Critical | `Inbox.tsx` `MessageBody` | Sanitize with DOMPurify before `dangerouslySetInnerHTML`. Strip `script`, `on*` handlers, `javascript:` and `data:` URLs. Apply the same contract to other preview HTML sites. |
| 4 | **Done** | Access token in `localStorage` | High | `api.ts`, `PublicRoute.tsx`, `GoogleCallback.tsx` | Cookie-only session. Frontend no longer stores or sends a bearer access token; Google callback no longer reads tokens from the URL. |

**Suggested first PR slice:** Wave 0 + items 1–4. Item 1 is already in the working tree.

---

## Wave 2 — High: SSRF, OAuth, injection, cost abuse

These are reachable from real product features (mailbox setup, scraping, Google login, campaign generation). Implement after Wave 1; do not start architecture cleanup instead of these.

| # | Status | Finding | Where | What to implement |
|---|---|---|---|---|
| 5 | **Done** | Authenticated SSRF via custom SMTP/IMAP | `mailbox.py`, `mailbox_service.py` | Resolve and pin the IP immediately before connect. Reject loopback, private, link-local, multicast, reserved, and cloud-metadata ranges (IPv4 and IPv6). Restrict ports. Re-run the same validation on mailbox **update**. Implemented: `backend/app/utils/outbound_host.py`, `backend/app/services/mailbox_service.py`. |
| 6 | **Done** | Gmail mailbox OAuth trusts unsigned `user_id` | `mailbox.py` callback | Redis `mailbox_oauth_state:{state}` stores `{user_id, campaign_id}` with TTL 600 and GETDEL once. Cookie holds the state token only. Implemented: `backend/app/services/mailbox_oauth_state.py`, `backend/app/api/v1/mailbox.py`. |
| 7 | **Done** | Scraper SSRF via DNS rebinding | `company_scraper_service.py`, `email_scraper.py` | Resolve once, pin the IP on the request URL, set `Host` + TLS SNI to the original hostname. `follow_redirects=False`; each Location hop is re-validated the same way. Ports limited to 80/443. Implemented: `backend/app/utils/safe_http.py`. |
| 8 | **Done** | MIME header / CRLF injection | `email_mime_builder.py`, `lead_upload_service.py` | Header values go through `EmailMessage` and `require_safe_header` (rejects CR/LF/NUL). Subject capped at 255. Excel emails validated as `EmailStr` after CR/LF rejection. |
| 9 | **Done** | Google login skips `email_verified` | `google_auth_service.py` | Require `email_verified is True` before treating the Google email as account proof. Email is normalized to lowercase before lookup. |
| 10 | **Done** | Free-credits `simulate-renewal` in non-dev | `billing.py` `simulate_renewal` | Single environment policy in `config.py`: `is_production` / `is_local_dev` / `allows_dev_only_routes`. Cookies, Google OAuth (`cookie_secure`), OTP logging, URL generation, and simulate-renewal all use it. Fail closed unless explicit `development`/`local`/`dev`/`test`. |
| 11 | Open | Ungated campaign email generation | `campaign_emails.py` `/generate`, `/resume` | Add `@limiter.limit` (for example 10/hour) matching campaign_draft `/ai`. Credit checks are billing, not rate control. |
| 12 | **Done** | Gmail access tokens stored plaintext | mailbox model, `google_*` token services | Access tokens are Fernet-encrypted at rest (`store_google_access_token`); decrypted only at the API-call boundary (`google_access_token_plain`). Legacy plaintext rows still decrypt via `decrypt_secret_compat`. Gmail HTTP calls reuse `get_http_client()`. |

---

## Wave 3 — Medium security, after the High list

Real defects, but they do not forge webhooks, steal sessions, or reach internal networks on their own. Ship them as a hardening pass once Waves 0–2 are in production.

### Auth / OTP — account abuse and enumeration

- **Done:** OTP verify sets the same HttpOnly cookie session as login.
- **Done:** `/otp/status/{user_id}` requires matching `email` and is rate-limited.
- **Done:** Password-reset verify and reset return one generic 400 (`Invalid or expired code.`).
- **Done:** Login lockout is keyed by email + client IP.
- **Done:** OTP hashes use HMAC-SHA256 keyed with `SECRET_KEY` (legacy unsalted SHA-256 still accepted for in-flight codes).
- **Done:** Dev OTP plaintext logging is gated on explicit local/dev (`development` / `local` / `dev` / `test`). Unset environment does not log codes.
- **Done:** Password fields have `max_length=128`.
- **Done:** Google email is normalized in application code. `User.email`, `Mailbox.email`, and `Waitlist.email` have unique indexes on `lower(email)` (`ix_users_email_lower`, `ix_mailboxes_email_lower`, `ix_waitlist_email_lower`). Migrations fail loudly on existing case-collisions, then store emails lowercase. Lead email stays out of scope (not globally unique).
- **Done:** Session orchestration lives in `session_service`: `issue_session` / `establish_session` mint+persist tokens, `set_auth_cookies` writes them, `clear_auth_cookies` clears logout. JWT crypto stays in `utils/jwt.py`; refresh-token rows stay in `token_service.py`.

### Authorization / RBAC / administration

- **Done:** Permission revoke honors `is_enabled=False`; route guard and admin UI both use `calculate_final_permissions`.
- **Done:** `GET /domains/` and `GET /domains/{id}` require admin, matching writes and `/system/domains`.
- **Done:** Disabling a user revokes all refresh tokens and admin device-trust keys; hard-delete also drops device trust.
- **Done:** `GET /users/` is paginated (`limit` max 200, `offset`) and returns `{ items, total, limit, offset }`.
- **Open:** Override write API still only stores `is_enabled=True` (cannot persist a revoke through that endpoint).

### IDOR / secrets — ownership and secret leakage

- **Done:** Remove `receive_password` from the system-mailbox read schema (`SystemMailboxRead` + `GET /system/mailboxes/` `response_model`).
- Scope both reply/conversation lead lookups with `Lead.user_id == user_id`.
- Stop logging Redis URLs with credentials and unsubscribe addresses in plaintext.

### Uploads / DoS — input size and scraping leftovers

- **Done:** Cap spreadsheet upload at 5 MB before reading past that; require ZIP magic bytes (`PK\x03\x04`). Do not trust filename/content-type.
- Add a global request-body limit (`nginx client_max_body_size` and/or ASGI middleware).
- **Done:** Deleted unused Playwright scraper (`playwright_scrape_email`, `hunter_fallback`, `scrape_company_email`) and dropped `playwright` from `requirements.txt`.

### Chat / conversational workflow

- **Done:** Stored transcript capped at 40 turns; LLM prompts use the last 12 (500 chars per message). Implemented: `backend/app/utils/chat_history.py`, `chat_graph.py`, `chat_service.py`, `chat_helper.py`, `understanding.py`.
- **Done:** Sync Redis helpers called from async code run off the event loop via `arun` (`asyncio.to_thread`). Helpers stay sync for Celery and tests.
- **Done:** `/ready` calls sync `get_redis()` then `await redis.ping()` (it previously `await`ed a non-coroutine and reported Redis down).
- **Done:** Insufficient-credits chat paths use `build_insufficient_credits_recovery` (`open_billing` action). Enrichment-timeout recovery is used when the chat graph times out after a LeadLog was saved, when enrichment enqueue fails, and when `/enrichment-status` still shows processing after 180s.
- **Done:** Enrichment Hunter/HTTP/Maps/Gemini caps are process-local *and* cluster-wide: `RedisBoundedSemaphore` takes a Redis ZSET slot (Lua acquire/release) so multiple Celery workers share one limit. Local `asyncio.Semaphore` remains the in-process bound and the fallback if Redis is down.
- **Skipped:** Splitting `chat_service.py` (architecture).

### Platform — headers, TLS, docs, CORS

- Add CSP (`default-src 'self'`, explicit `script-src`, `object-src 'none'`).
- Put `X-Frame-Options` / `frame-ancestors 'none'` on the nginx SPA.
- Require Postgres SSL except localhost.
- Hide `/docs` in production.
- Split CORS so localhost never ships to staging/prod.
- Fail startup if launch-critical secrets are empty in production.

---

## Do not start these for “security first”

They are in the same audit document, but they are efficiency, correctness, or schema work. They do not close a security door.

| Item | Why it waits |
|---|---|
| Campaign DRAFT guard consolidation, god-file splits, favorite-toggle queries | Architecture. No attacker path. |
| EmailActivity / EmailMessage canonical model, UserProfile split, credit CHECK constraints | Normalization. Do after the security writers are stable. |
| N+1 reply matching, Float→Numeric money, pool sizing, Celery jitter | Efficiency and reliability. Schedule after Wave 2. |
| Scheduler shutdown | Correctness. Still waits. |

---

## Notes

Ratings after a full fix assume tests, dependency scanning, and a penetration test still happen. The audit did not run those.

Source: [SECURITY_AND_EFFICIENCY_FIXED.md](./SECURITY_AND_EFFICIENCY_FIXED.md) · read-only code review · 2026-08-13 re-audit included.
