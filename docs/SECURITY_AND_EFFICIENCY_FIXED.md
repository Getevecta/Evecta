# Security & Efficiency Audit — Evecta

**Status: findings only — nothing in this document has been fixed yet.** Every item below was identified via read-only code review (no files were edited during the audit). Treat this as a punch list, not a changelog.

**Scope:** Backend (`backend/app/`) fully, for both passes. Frontend (`Frontend/src/`) covered only for the security checklist (XSS, Vite/build config) — frontend efficiency/architecture (bundle size, React re-renders, component structure) was explicitly not reviewed.

---

## Table of contents

1. [Feature-grouped master audit](#feature-grouped-master-audit)
2. [Overall ratings](#1-overall-ratings)
3. [Security findings and detailed evidence](#2-security-findings)
4. [Reply-tracking & email-threading deep dive](#3-reply-tracking--email-threading-deep-dive)
5. [Backend efficiency & architecture findings](#4-backend-efficiency--architecture-findings)
6. [Out of scope / not yet reviewed](#5-out-of-scope--not-yet-reviewed)
7. [Additional findings from senior backend re-audit](#6-additional-findings-from-senior-backend-re-audit-2026-08-13)

---

## Feature-grouped master audit

This is the ownership-oriented view of the audit. It groups every finding by the product feature or platform subsystem that should own the fix. The full evidence, affected lines, descriptions, and proposed fixes remain in the detailed sections below.

Status labels used here:

- **Confirmed defect** — the incorrect or unsafe behavior is directly present in source.
- **Confirmed risk** — the risky structure is present, but production impact requires runtime/load/infrastructure validation.
- **Improvement** — maintainability, consistency, normalization, or future-scale work; not proof of a current failure.
- **Historical verification required** — the claim concerns repository history or external state and cannot be proven from the current working tree alone.

### A. Authentication, sessions, OTP and password recovery

**Security and correctness**

- **Confirmed defect — High:** Google login consumes the email claim without requiring `email_verified is True`.
- **Confirmed defect — Medium:** OTP verification auto-login returns an access token in JSON but does not establish the same cookie session as the standard login flow.
- **Confirmed defect — Medium:** `/otp/status/{user_id}` is unauthenticated and unrate-limited, exposing OTP/account state.
- **Confirmed defect — Medium:** password-reset verification and reset endpoints return `User not found`, reintroducing account enumeration after the generic forgot-password response.
- **Confirmed risk — Medium:** login lockout is keyed only by normalized email, allowing a third party to lock a known account by repeatedly submitting a bad password.
- **Confirmed risk — Low:** OTP values use unsalted, single-round SHA-256 over a six-digit search space; use keyed HMAC instead.
- **Confirmed risk — Low:** development OTP logging is controlled by heuristic configuration checks rather than one canonical environment policy.
- **Confirmed risk — Low:** password inputs have minimum lengths but no consistent pre-hash maximum length.
- **Improvement:** normalize Google email before lookup and enforce case-insensitive uniqueness at the database layer.
- **Improvement:** consolidate cookie creation, token delivery, refresh rotation, logout, and OAuth completion into one session service.

**Frontend session handling**

- **Confirmed risk — High:** the frontend persists bearer access tokens in `localStorage`, making them readable by any successful XSS.
- **Confirmed risk — Medium:** the Google callback frontend still accepts access tokens from URL query parameters or fragments. Confirm whether any current backend redirect still sends them; otherwise remove the legacy path.

### B. Authorization, RBAC, permissions and administration

**Security and correctness**

- **Confirmed defect — Critical:** the route permission guard treats the existence of an override row as enabled and ignores `is_enabled=False`; the UI and enforced permissions can disagree.
- **Confirmed risk — Low:** global Domain read routes are not protected consistently with Domain writes and the `/system/domains` administration API.
- **Improvement:** permission calculation exists in two implementations (`calculate_final_permissions` and `get_effective_permissions`); replace them with one authoritative function used by both UI responses and route enforcement.
- **Improvement:** security-sensitive cleanup functions such as token revocation and admin-device-trust revocation exist but are not consistently wired into account-disable/delete workflows.
- **Improvement:** admin user listing is unbounded and will increasingly hydrate sensitive user records as the account table grows.

### C. Google OAuth mailbox connection and mailbox management

**Security and correctness**

- **Confirmed defect — High:** custom SMTP/IMAP validation connects to user-controlled hosts and ports without private/reserved-address protection, enabling authenticated SSRF and internal-port probing.
- **Confirmed defect — High:** Gmail mailbox OAuth callback trusts an unsigned user ID stored in a client-controlled cookie; state correlation is not stored or authenticated server-side.
- **Confirmed risk — Medium:** Gmail access tokens are stored as plaintext in the database while refresh tokens are encrypted.
- **Confirmed defect — Medium:** mailbox updates can change SMTP/IMAP destinations and credentials without repeating validation, bypassing creation-time checks.
- **Confirmed defect — High correctness:** `MailboxUpdate.smtp_port` is assigned to a transient `smtp_port` Python attribute while the mapped database column is `Mailbox.port`; the endpoint can report success without persisting the new SMTP port.
- **Confirmed defect — Medium:** encrypted `receive_password` is included in the system-mailbox read schema and can be returned through the admin API.
- **Confirmed risk:** several Gmail calls create a new HTTP client per operation instead of reusing a lifespan-managed connection pool.
- **Improvement:** explicitly map API field names to ORM columns instead of generic `setattr`, validate update ports, and re-read persisted values in tests.

### D. Lead generation, search, enrichment and lead library

**Security and correctness**

- **Confirmed defect — High:** website scraping performs DNS validation separately from the HTTP connection, leaving a DNS-rebinding check/connect gap.
- **Confirmed defect — Medium:** redirects are followed before the final destination is rejected; validation happens after the redirected request has already reached its target.
- **Confirmed defect — Medium:** spreadsheet lead upload reads the entire body with no maximum size and trusts filename/content-type indicators before parser execution.
- **Confirmed defect — High:** raw imported recipient data can reach manually constructed MIME headers without consistent CR/LF rejection.
- **Confirmed risk — Low:** an unused Playwright scraper has no equivalent SSRF protection; delete it or secure it before it becomes reachable.
- **Confirmed risk:** enrichment concurrency semaphores are created per operation and are not shared across worker processes, so configured limits are not global limits.
- **Confirmed risk:** Hunter `429` responses can be collapsed into “no email found,” hiding rate-limit exhaustion and preventing correct retry/backoff behavior.
- **Improvement:** add shared enrichment-result caching for repeated businesses outside the master Overture path.
- **Improvement:** remove confirmed-unused scraping entry points and separate Overture catalog lookup, external enrichment, scoring, persistence, and UI orchestration from the lead-generation god-service.
- **Improvement:** retain deterministic database-driven duplicate/exhaustion decisions and do not delegate catalog membership or user-consumption decisions to the LLM.

### E. Chat, conversational lead workflow and chat memory

**Correctness and efficiency**

- **Confirmed risk:** chat prompts can resend uncapped conversation history, causing context cost and latency to grow throughout long sessions.
- **Confirmed risk:** intended enrichment concurrency limits are local to individual operations rather than shared across API/Celery processes.
- **Confirmed defect:** Redis context helpers use the synchronous Redis client from `async def` functions, blocking the event loop during network operations.
- **Confirmed defect:** `/ready` incorrectly does `await get_redis()` even though `get_redis()` is synchronous, causing Redis readiness to be reported incorrectly.
- **Improvement:** `chat_service.py` combines orchestration, search, recovery, ranking, persistence, and response construction; split by responsibility while preserving graph state contracts.
- **Improvement:** completed enrichment-timeout and insufficient-credit recovery builders are not wired into the conversational failure paths.
- **Improvement:** define explicit history compaction/summarization rules rather than passing the full conversation indefinitely.

### F. Campaign creation, drafts, personalization, generation, review and launch

**Security and correctness**

- **Confirmed defect — High:** campaign email generation and resume endpoints lack request-rate limits despite triggering expensive AI/background work.
- **Confirmed risk — High:** campaign generation can hold a database connection while polling enrichment for as long as the shared 180-second wait budget.
- **Confirmed risk — High:** one campaign generation run is a large sequential unit; work is not chunked for distribution or bounded concurrency.
- **Confirmed risk:** a worker/task crash can leave the remaining generation run unfinished and recovery semantics are limited.
- **Improvement — High:** the “campaign must be DRAFT” business rule is duplicated across generation, review, draft, launch, lead, and campaign services.
- **Improvement — High:** `CampaignLeadResponse` emits much of the lead representation twice through nested and flattened fields.
- **Improvement:** campaign status polling hydrates rows that could be counted using grouped aggregate queries.
- **Improvement:** launch/review consumers require several endpoints that are always requested together; consider a composed read model.
- **Improvement:** standardize pagination and enforce bounds on campaign list parameters.

### G. Email generation engine, templates, personalization and spam checking

**Correctness and efficiency**

- **Confirmed defect:** raw MIME construction interpolates subject/from/to/reply-to values into header lines instead of using safe structured header APIs.
- **Confirmed defect:** the AI email generator contains a retry configuration whose default values cannot execute an actual retry.
- **Confirmed risk:** a compliance attempt can invoke multiple Gemini calls per lead and repeat several times, producing high worst-case cost.
- **Confirmed risk:** stricter “try harder” spam remediation paths appear unreachable, reducing intended recovery behavior.
- **Improvement — High:** favorite-template toggling performs repeated schema introspection and several database round trips for one boolean update.
- **Improvement:** template-formatting helpers are located in the Celery task layer and imported back into services, reversing the intended dependency direction.
- **Improvement:** apply maximum lengths and control-character validation consistently to template names, subjects, content, prompts, and generated fields.

### H. Campaign sending, mailbox rotation and email dispatch

**Correctness and reliability**

- **Confirmed risk:** reply and some send paths keep an open database session/transaction while waiting on SMTP or Gmail network operations.
- **Confirmed risk:** Celery remains at-least-once; sending tasks require explicit idempotency/deduplication for retries, worker loss, and late acknowledgements.
- **Confirmed risk:** fixed retry countdowns without jitter can cause synchronized retry bursts during shared-provider incidents.
- **Confirmed risk:** Redis broker/result URLs are logged without credential redaction.
- **Improvement:** the old mailbox-rotation functions are unused and race-prone; the `FOR UPDATE SKIP LOCKED` selector is the correct active implementation.
- **Improvement:** remove `mailbox_usage.py` and unused rotation functions after confirming deployment has no out-of-repository callers.

### I. Inbox, reply fetching, email threads and manual replies

**Security and correctness**

- **Confirmed defect — Critical frontend impact:** inbound email HTML is rendered with `dangerouslySetInnerHTML` without sanitization, allowing stored XSS from an external email reply.
- **Confirmed defect — Medium:** two reply/conversation paths fetch a lead only by ID without including its owner in the query.
- **Confirmed correctness defect:** `EmailActivity` and `EmailMessage` maintain overlapping reply state; some ingest paths update one representation without reliably creating/updating the other.
- **Confirmed risk:** IMAP/Gmail reply matching performs repeated per-message database queries, creating N+1 query bursts as unread volume grows.
- **Confirmed risk:** Gmail reply fetching creates a new HTTP client for individual API operations rather than reusing one client per mailbox cycle.
- **Confirmed risk:** manual reply paths keep database connections checked out during external sends.
- **Improvement:** establish one canonical thread/message model and derive activity summaries rather than independently mutating duplicate reply truth.
- **Improvement:** combine sequential ownership lookups into joined, ownership-scoped queries.

### J. Email tracking, SES/SNS webhooks and unsubscribe compliance

**Security and correctness**

- **Confirmed defect — Critical:** SNS signature verification accepts certificates from any matching AWS parent-domain suffix rather than the documented SNS certificate-host pattern.
- **Confirmed defect — High:** SNS TopicArn verification is skipped when the configured allowlist is empty.
- **Confirmed risk:** email-open accuracy is inherently limited by proxying, image blocking, scanners, and privacy prefetch; this is an industry limitation, not entirely an application bug.
- **Confirmed risk:** unsubscribe processing logs full recipient addresses and, on malformed requests, portions of URLs/bodies that may contain long-lived unsubscribe tokens.
- **Improvement:** keep one canonical event-state transition service for delivery, bounce, complaint, open, click, and reply changes.
- **Improvement:** add webhook replay/idempotency tests, strict topic/certificate validation tests, and operational alerts for signature failures.

### K. Billing, subscriptions, Stripe and credits

**Security and correctness**

- **Confirmed defect — High:** the credit-granting simulate-renewal endpoint blocks only exact `production`, remains documented, and is reachable by any authenticated user in other production-like environment spellings.
- **Confirmed risk:** environment detection differs between billing, authentication cookies, Google OAuth, and URL generation.
- **Confirmed risk:** free-text credit `pool`, `action`, and status values lack database CHECK constraints even though credit arithmetic depends on valid categories.
- **Confirmed risk:** the credit history query filters by user and orders by creation time without a matching `(user_id, created_at)` index.
- **Improvement:** credit balance reads repeat queries that can be consolidated.
- **Improvement:** `billing.py` contains routing, Stripe orchestration, webhook processing, plan transitions, feedback email, and credit policy in one large module.
- **Improvement:** usage/cost money fields should use exact `Numeric`/`Decimal` storage instead of binary Float where totals inform financial reporting.

### L. Insights, analytics, AI usage and external API cost tracking

**Efficiency and data modeling**

- **Confirmed risk:** status/usage analytics contain repeated schemas and queries that differ mainly by grouping dimension.
- **Confirmed risk:** several usage tables have individual indexes but should be validated against real multi-column filter/order patterns with query plans.
- **Confirmed risk:** synchronous pricing refresh can run inside an async cost-tracking path and block the event loop.
- **Confirmed risk:** monthly Overture refresh may pull cached areas again without first proving the upstream release changed.
- **Improvement:** consolidate analytics grouping into shared query builders/read models.
- **Improvement:** retain integer token/unit counts and use exact decimal rates/costs.
- **Improvement:** add retention/aggregation policies so high-volume raw usage-event tables do not grow indefinitely.

### M. Database models, normalization, indexes and migrations

**Correctness and design**

- **Confirmed risk:** three historical migrations add non-null columns without a safe default/backfill transition for populated tables.
- **Confirmed risk:** older enum columns persist enum member names differently from newer value-based enums, complicating raw SQL/reporting.
- **Confirmed risk:** several business-state fields are free text without database constraints.
- **Confirmed risk:** email uniqueness relies on application normalization rather than a database-enforced case-insensitive invariant.
- **Confirmed risk:** user/created-time and functional-index shapes do not always match active filters and ordering.
- **Improvement:** use normalized/reference tables or constrained enums for finite business states; do not normalize genuinely flexible content such as campaign copy, scraped descriptions, or LLM context into unnecessary tables.
- **Improvement:** validate proposed indexes using `EXPLAIN (ANALYZE, BUFFERS)` on production-shaped data before adding write overhead.
- **Improvement:** test every migration from both an empty database and a representative previous production revision.

### N. API platform, configuration, observability and deployment readiness

**Security and reliability**

- **Confirmed risk:** application-wide request-body size limits are absent; upload-specific validation alone does not protect every endpoint.
- **Confirmed risk:** API documentation is enabled in every environment.
- **Confirmed risk:** CORS configuration includes localhost alongside staging and production origins.
- **Confirmed risk:** several launch-critical secrets default to empty strings and only produce warnings.
- **Confirmed risk:** PostgreSQL TLS is not enforced by the constructed connection configuration.
- **Confirmed risk:** no Content-Security-Policy is defined for the application/static frontend configuration.
- **Confirmed risk:** static frontend delivery lacks the clickjacking headers applied by FastAPI to API responses.
- **Confirmed risk:** Sentry is installed but not initialized, leaving exception monitoring incomplete.
- **Confirmed risk:** database pool capacity is hard-coded per process and must be sized against worker count and PostgreSQL limits.
- **Confirmed defect:** reply scheduler task is created without retaining/cancelling it before shared resources close; its fixed Redis lock TTL is not renewed during long cycles.
- **Improvement:** create one typed environment policy (`local`, `test`, `staging`, `production`) and make security-sensitive features fail closed.
- **Improvement:** make CORS, docs exposure, cookies, TLS, dev routes, and external URLs derive from that one policy.
- **Improvement:** resolve `.env` intentionally rather than relying silently on the process working directory.

### O. Frontend security directly coupled to backend data

- **Confirmed defect — Critical:** unsanitized inbound email HTML can execute in the authenticated Inbox.
- **Confirmed risk — High:** `localStorage` access tokens make any frontend XSS significantly more damaging.
- **Confirmed risk:** multiple other `dangerouslySetInnerHTML` sites exist for campaign/template previews; each helper producing those strings needs an explicit sanitization/escaping contract.
- **Confirmed risk:** production API base URL can be overridden from a URL parameter and persisted in local storage unless deployment restrictions prevent it.
- **Confirmed risk:** CSP and static clickjacking protections are absent from the in-repository frontend-serving configuration.

### P. Tests, dependencies and repository hygiene

- **Confirmed risk:** no completed dependency vulnerability scan is documented.
- **Confirmed risk:** the full test suite was not completed during this audit, so runtime correctness is not certified.
- **Confirmed risk:** configuration loading is working-directory sensitive, complicating tests and tooling invoked from the repository root.
- **Improvement:** add regression tests for every Critical/High finding, especially authorization overrides, OAuth state, SSRF, webhook verification, stored XSS boundaries, MIME headers, credits, and Celery idempotency.
- **Improvement:** add migration tests, database integration tests, query-plan checks for critical reads, and controlled concurrency tests.
- **Improvement:** migrate deprecated Pydantic class-based configuration and `Field(example=...)` usage before Pydantic v3.
- **Improvement:** remove duplicate utilities, bytecode/cache artifacts, and checked-in virtual environments from the maintained project surface.
- **Historical verification required — Critical:** Hunter.io keys reportedly exist in Git history. Confirm independently, rotate regardless if still valid, and treat history rewriting as cleanup rather than a substitute for rotation.

### Feature-level fix order

1. **Authorization and webhooks:** permission override enforcement; SNS certificate and TopicArn validation.
2. **Inbox and sessions:** sanitize inbound HTML; remove access tokens from `localStorage` and legacy URL-token handling.
3. **Mailbox/OAuth security:** block SMTP/IMAP SSRF; make OAuth state server-side/signed; encrypt Gmail access tokens; validate updates.
4. **Authentication:** require verified Google email; close OTP status/enumeration gaps; unify cookie/session handling.
5. **Campaign and lead cost controls:** rate-limit generation; release DB connections during long waits; enforce upload and text limits.
6. **Correctness:** fix `smtp_port`, lead ownership, reply-state duplication, `/ready`, and scheduler shutdown.
7. **Database and async efficiency:** eliminate N+1 reply matching, blocking Redis/HTTP paths, missing query-aligned indexes, and Float money storage.
8. **Architecture cleanup:** split billing/chat/lead-generation responsibilities and centralize duplicated business rules.
9. **Validation:** complete tests, dependency scanning, migration rehearsal, query profiling, load testing, and penetration testing.

---

## 1. Overall ratings

| | Current | After fixing everything found |
|---|---|---|
| Security | 6.5/10 | ~9/10 |
| Efficiency / Architecture | 6/10 | ~8.5/10 |
| **Overall** | **6/10** | **~9/10** |

**Why not lower:** nothing here is "no auth" or "SQL injection everywhere" territory. Ownership checks, RBAC, credit-locking, rate limiting, and cost tracking are implemented correctly almost everywhere — the hard parts of a system like this are mostly done right.

**Why not higher:** a stored XSS reachable by an external party, a forgeable webhook, a leaked API key, and a permission-revoke that doesn't actually revoke are the kind of findings that show up in a breach post-mortem, not just a hardening checklist.

**Why the ceiling is ~9, not 10, even fully fixed:**
- No load testing or live query-plan verification — findings were diagnosed by reading code, not watching it run under real concurrent traffic.
- No real `pip-audit`/`npm audit` run against the lockfiles (manual pattern-matching only).
- No penetration test; no monitoring/alerting pipeline live (Sentry is a dependency but never initialized).
- Frontend efficiency/architecture was never reviewed — an unknown, not a verified "fine."

**The one lever that moves both scores at once:** the codebase doesn't yet have a habit of extracting shared logic *before* it forks. The same failure mode — two implementations of one rule, kept in sync by hand — shows up three separate times across both audits: `EmailActivity`/`EmailMessage` reply-state duplication, the permission-check bug (`calculate_final_permissions` vs `get_effective_permissions`), and the 9-way duplicated "campaign must be DRAFT" guard. Fixing the specific instances helps; establishing "extract before duplicating" as a habit prevents the next ten.

---

## 2. Security findings

**Method:** 6 parallel deep-dives covering the full checklist — injection/input validation, auth, authorization/IDOR/CSRF, CORS/secrets/FastAPI hardening, frontend XSS/Vite config, and DB/deps/infra/DoS/compliance. Every route file (34) and service file were read, not sampled. Critical/High findings were independently re-verified against the actual source.

### Summary

| Severity | Count |
|---|---|
| Critical | 3 |
| High | 7 |
| Medium | 15 |
| Low | 16 |
| Info (no action / documented tradeoff) | 11 |

### Fix-first shortlist

1. **Rotate the leaked Hunter.io API key** — real key committed to git history, reachable on `dev`/`feature/campaign`/`feature/source-changes`.
2. **Close the SES/SNS webhook trust chain** — two independent bypasses (cert-domain check, optional TopicArn allowlist) let anyone forge delivery/bounce/complaint events.
3. **Sanitize inbound email HTML before rendering in Inbox** — unsanitized `dangerouslySetInnerHTML` is a stored-XSS vector any external party can trigger by replying to a campaign; compounded by the access token sitting in `localStorage`.
4. **Fix SSRF DNS-rebinding gap in the website scrapers** — the core lead-gen scraping feature validates a hostname once, then lets httpx re-resolve independently at connect time.
5. **Unify "is production" detection and rate-limit the two ungated endpoints** — `/billing/test/simulate-renewal` (free credits) and `/campaigns/{id}/emails/generate` (unmetered Gemini cost) have no request-rate limiting, and three different files each implement their own inconsistent prod-environment check.

### Critical

```
[SEVERITY: Critical] SNS webhook signature check trusts any *.amazonaws.com subdomain (forgeable via S3)
File: backend/app/api/v1/webhook_ses.py:27,30-36,58-72
Category: Confidentiality/Integrity — Improper Certificate Validation (CWE-347)
Description: verify_sns_signature() fetches the cert used to verify the SNS signature from an
attacker-supplied SigningCertURL, gated only by _is_trusted_aws_url(), which accepts any hostname
ending in "amazonaws.com" or "aws.amazon.com". A public S3 bucket (e.g. attacker-bucket.s3.amazonaws.com)
satisfies that suffix check and is fully attacker-controlled — upload a self-signed cert there, sign a
forged SNS payload with the matching key, and the handler "verifies" it successfully.
Evidence:
    _ALLOWED_CERT_DOMAINS = {"amazonaws.com", "aws.amazon.com"}
    def _is_trusted_aws_url(url):
        host = urlparse(url).hostname or ""
        return any(host == d or host.endswith(f".{d}") for d in _ALLOWED_CERT_DOMAINS)
Fix: Anchor to AWS's documented SNS hostname pattern, e.g. `^sns\.[a-z0-9-]+\.amazonaws\.com$`
(regex-anchored, not endswith) — excludes S3 and every other multi-tenant *.amazonaws.com service.
```

```
[SEVERITY: Critical] Real Hunter.io API keys hardcoded and preserved in git history
File: backend/app/utils/email_scraper.py (historical) — reachable via `git log --all` on remote
branches dev, feature/campaign, feature/source-changes
Category: Confidentiality — Secrets Exposure
Description: Multiple historical commits assigned a literal Hunter.io key directly in source
(`HUNTER_API_KEY = "4f7ed8f9…4952a6"`, later rotated to a second literal key, then finally moved to
`get_settings().HUNTER_API_KEY`). The working tree is clean today, but git history is immutable —
anyone who clones the repo can retrieve both keys from history regardless of the current code state.
Evidence (redacted): `HUNTER_API_KEY = "4f7ed8f9…4952a6"` and `HUNTER_API_KEY = "d0aaaaad…5f243"` —
confirmed present across 10+ commits via `git log --all -p`.
Fix: Rotate both Hunter.io keys immediately — treat as compromised regardless of whether abuse has
been observed. Optionally rewrite history (git filter-repo/BFG) on all affected branches afterward;
rotation is the mandatory part, history-scrubbing is just cleanup.
```

```
[SEVERITY: Critical] Unsanitized rendering of inbound email HTML in the Inbox — stored XSS
File: Frontend/src/features/dashboard/components/Inbox/Inbox.tsx:131-150, 788
Category: Integrity/Confidentiality — Stored XSS (OWASP A03:2021)
Description: MessageBody renders a thread message's `body` via `dangerouslySetInnerHTML` whenever a
regex thinks it "looks like HTML" — no DOMPurify or any sanitizer is used (confirmed: no DOMPurify
or equivalent listed in Frontend/package.json). `body` is the raw content of an inbound email reply —
attacker-controlled by anyone who replies into a campaign thread. A crafted reply containing
`<img src=x onerror=...>` executes in the dashboard user's session the moment the thread is opened.
This compounds directly with the next finding (access token in localStorage) into full session theft.
Evidence:
    function messageBodyLooksHtml(body) { return /<[a-z][\s\S]*>/i.test(body); }
    if (messageBodyLooksHtml(body)) {
      return <div dangerouslySetInnerHTML={{ __html: body }} />;
    }
Fix: Sanitize with DOMPurify before rendering: `DOMPurify.sanitize(body, { ALLOWED_TAGS: [...],
ALLOWED_ATTR: [...] })`. Strip `<script>`, `on*` handlers, and `javascript:`/`data:` URLs at minimum.
```

### High

```
[SEVERITY: High] SSRF guard bypassable via DNS rebinding (check-then-connect TOCTOU)
File: backend/app/services/company_scraper_service.py:26-31,80-105; backend/app/utils/email_scraper.py:32-38,400-449
Category: Integrity/Confidentiality — SSRF (CWE-918/CWE-367)
Description: Both scrapers resolve a hostname once via socket.gethostbyname() to check it isn't
private/metadata-range, then hand the URL to httpx, which re-resolves DNS independently at connect
time. An attacker who controls DNS for a scraped domain (any company website entered by a user) can
answer the check-time lookup with a public IP and the connect-time lookup with 169.254.169.254 or an
internal IP a moment later — a textbook SSRF bypass, and directly reachable through this product's
core lead-generation scraping feature.
Fix: Resolve once, validate, then connect to the pinned IP directly (custom httpx transport hook or
per-request IP pinning) so validation and connection use the same address.
```

```
[SEVERITY: High] Unsanitized fields flow into hand-built raw MIME headers — SMTP header/CRLF injection
File: backend/app/utils/email_mime_builder.py:36-76; backend/app/services/lead_upload_service.py:91-102
Category: Integrity — Email Header Injection (CWE-93)
Description: build_campaign_mime_bytes() f-string-interpolates subject/from/to/reply-to directly into
raw header lines with no CR/LF stripping, sent via aiosmtplib/Gmail API for most mailbox types. The
`subject` schema field has no max_length or control-character validation, and Excel-imported lead
emails (`_cell_email`) skip the EmailStr-style validation used elsewhere — a crafted spreadsheet cell
like `x@x.com\r\nBcc: attacker@evil.com` is stored verbatim and later used as a raw header value.
Fix: Reject/strip `\r`/`\n` from subject/from/to/reply-to before building headers, or better, build
headers via Python's `email.message.EmailMessage` (rejects embedded newlines natively).
```

```
[SEVERITY: High] Google OAuth login trusts the email claim without checking `email_verified`
File: backend/app/services/google_auth_service.py:101-123
Category: Confidentiality/Integrity — Broken Authentication (OWASP A07:2021)
Description: handle_google_callback() looks up and logs into an existing account by `email_info.get("email")`
alone, never checking Google's accompanying `email_verified` flag. If an attacker can complete Google
sign-in with an unverified matching email, they receive the victim's session tokens without a password.
Fix: Require `email_verified is True` before treating the Google email as account-linking proof;
prefer matching on Google's stable `sub` subject ID stored on the User record.
```

```
[SEVERITY: High] AWS SNS TopicArn allowlist is optional and empty by default
File: backend/app/api/v1/webhook_ses.py:141-146; backend/app/core/config.py:109
Category: Confidentiality/Integrity — Broken Access Control (OWASP A01)
Description: Compounds the cert-domain bypass above: even where signature verification held, the
extra check that the message actually came from *this app's* SNS topic (`SNS_ALLOWED_TOPIC_ARNS`)
is skipped entirely when unset — and it ships unset in `.env.example`/`backend/.env`. Combined with
the cert bypass, an attacker can subscribe the public endpoint to their own AWS topic and publish
forged bounce/complaint/open/click events, falsifying campaign engagement/compliance data.
Fix: Make SNS_ALLOWED_TOPIC_ARNS mandatory — fail closed (403 everything) if empty, and raise on
app boot if unset outside local dev.
```

```
[SEVERITY: High] Inconsistent "is production" detection creates a reachable free-credits endpoint and a fragile cookie Secure flag
File: backend/app/api/v1/billing.py:863 (simulate_renewal); backend/app/api/v1/auth.py:58-64 (is_production);
backend/app/core/config.py:196 (get_base_url)
Category: Integrity/Availability — Security Misconfiguration (OWASP A05)
Description: Three different files each reimplement "are we in production" with different accepted
values: billing.py's dev-only `/test/simulate-renewal` (grants a full plan's credits with no payment,
`include_in_schema=True`, gated only by `Depends(get_current_user)` — any authenticated user) blocks
only the exact string `"production"`; auth.py's `is_production()` (controls the cookie `Secure` flag)
accepts `"production"/"prod"/"staging"/"stage"`; config.py's `get_base_url()` checks `"production"/"prod"`.
`ENVIRONMENT` is never set in `.env`/`.env.example`, so behavior depends entirely on what each
deployment happens to export — one misconfigured/misspelled value and either free credits become
mintable in prod, or auth cookies silently lose the Secure flag.
Fix: Consolidate into one `settings.is_production` property used everywhere; fail closed (block unless
explicitly `development`/`local`) rather than fail open (block only on exact `"production"`); consider
not registering the simulate-renewal route at all outside dev, and set `include_in_schema=False`.
```

```
[SEVERITY: High] JWT access token stored in localStorage — full stealability via the Inbox XSS above
File: Frontend/src/shared/services/api.ts:1394-1395,1509-1518; Frontend/src/shared/components/PublicRoute/PublicRoute.tsx:25
Category: Confidentiality — Sensitive Data Exposure (OWASP A02/A07)
Description: The bearer access token is read from/written to `localStorage['access_token']` and
manually attached to every request. localStorage has no XSS protection — combined with the Critical
Inbox finding above, this turns a single malicious email reply into full API session takeover. (The
refresh token does appear to live in an httpOnly cookie already — the access token is the weak link.)
Fix: Move the access token to an httpOnly Secure SameSite cookie set by the backend, mirroring the
refresh token, so the frontend never touches it directly.
```

```
[SEVERITY: High] AI email-generation endpoint has no rate limit, unlike every sibling AI endpoint
File: backend/app/api/v1/campaign_emails.py:106,164,212 (/generate, /cancel, /resume)
Category: Availability — Unrestricted Resource Consumption / cost-based DoS (OWASP API4:2023)
Description: This is the highest-cost AI path in the app — per-lead Gemini generation across an entire
campaign — yet unlike `chat.py` (60/hour) and `campaign_draft.py`'s `/ai` (20/hour), it carries no
`@limiter.limit(...)` decorator at all (confirmed by direct read). Credit-gating is a billing control,
not a rate control: a user can rapidly re-trigger generation as long as credits remain, and each call
cancels+restarts any in-flight generation task, so rapid-fire requests keep re-launching full regeneration.
Fix: Add `@limiter.limit("10/hour")` (or similar) to `/generate` and `/resume`, matching the pattern
already used on `campaign_draft.py`'s `/ai` route.
```

### Medium

```
[SEVERITY: Medium] SSRF check runs only after the full redirect chain has already been followed
File: backend/app/services/company_scraper_service.py:48-61; backend/app/utils/email_scraper.py:411-423
Fix: Disable follow_redirects; validate each Location host (with the DNS-pinning fix above) one hop at a time.
```

```
[SEVERITY: Medium] Lead Excel upload has no size cap and only client-spoofable type checks
File: backend/app/api/v1/lead.py:293-319; backend/app/services/lead_upload_service.py:133-179
Fix: Enforce a hard size cap before reading the body; check the ZIP magic bytes (`PK\x03\x04`) before parsing.
```

```
[SEVERITY: Medium] Login lockout is keyed only by email — anyone can lock out any known account
File: backend/app/services/auth_service.py:27-33,108-140
Fix: Add a per-IP dimension to the counter, or step-up friction (CAPTCHA) instead of a hard lock.
```

```
[SEVERITY: Medium] OTP-based auto-login endpoint returns the bearer token only in the JSON body
File: backend/app/api/v1/otp.py:93-137
Fix: Call `_set_auth_cookies` here too, matching /auth/login and the Google callback.
```

```
[SEVERITY: Medium] User enumeration reintroduced between forgot-password and verify/reset steps
File: backend/app/api/v1/auth.py:407-494
Fix: Return the same generic 400 "invalid or expired code" for both cases.
```

```
[SEVERITY: Medium] Unauthenticated, unrate-limited OTP status endpoint leaks account/OTP state
File: backend/app/api/v1/otp.py:147-176
Fix: Require the caller to prove ownership (as /otp/verify/{user_id} already does), add rate limiting.
```

```
[SEVERITY: Medium] IDOR: Lead fetched by ID with no ownership check inside two otherwise-scoped endpoints
File: backend/app/api/v1/inbox.py:444 (get_lead_conversation); backend/app/services/thread_reply_service.py:189
Fix: Change both to `select(Lead).where(Lead.id == lead_id, Lead.user_id == user_id)`.
```

```
[SEVERITY: Medium] Encrypted mailbox secret returned verbatim in an admin API response
File: backend/app/schemas/system_mailbox.py:27-48 (receive_password); backend/app/api/v1/system_mailbox.py:19-71
Fix: Remove `receive_password` from the read schema, mirroring the existing `smtp_pass` omission.
```

```
[SEVERITY: Medium] OAuth access token passed through the URL query string/hash
File: Frontend/src/features/auth/GoogleCallback.tsx:21-28
Fix: Deliver only via URL fragment or a one-time-code exchange; strip the URL with history.replaceState immediately after reading it.
```

```
[SEVERITY: Medium] No Content-Security-Policy anywhere in the stack
File: backend/app/main.py:161-171 (sets other headers, no CSP); Frontend/index.html; Frontend/deployment/nginx-cache-headers.conf
Description: The backend sets X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy,
and conditional HSTS via middleware — but no CSP anywhere in the stack, on the API or the frontend.
Fix: Add a CSP header (nginx `add_header` or the backend middleware) — `default-src 'self'`, explicit
`script-src` allowlist for PostHog/GTM/Fonts, `object-src 'none'`.
```

```
[SEVERITY: Medium] Static frontend HTML has no clickjacking protection despite the API being protected
File: Frontend/deployment/nginx-cache-headers.conf (only cache headers, no X-Frame-Options)
Description: The backend's security_headers_middleware sets X-Frame-Options: DENY on every FastAPI
response — but the actual SPA (login page, dashboard shell) is static HTML served separately by
nginx, which carries no such header.
Fix: Add `X-Frame-Options: DENY` / `frame-ancestors 'none'` to the nginx config that serves the built frontend.
```

```
[SEVERITY: Medium] Sentry is a declared dependency but never initialized
File: backend/requirements.txt:111 (sentry-sdk==2.38.0); no sentry_sdk.init() anywhere in backend/
Fix: Either wire up `sentry_sdk.init(dsn=..., before_send=<PII-scrub>)` in main.py's startup, or drop the unused dependency.
```

```
[SEVERITY: Medium] Redis broker/result URLs (may carry embedded credentials) logged in plaintext
File: backend/app/core/celery_app.py:54-55
Fix: Strip userinfo before logging, or drop the lines entirely.
```

```
[SEVERITY: Medium] No SSL/TLS enforced on PostgreSQL connection strings
File: backend/app/core/config.py:158-168; backend/app/database/session.py:14-23
Fix: Default to `ssl=True`/`sslmode=require` unless the host is localhost/a Unix socket.
```

```
[SEVERITY: Medium] No request body size limit anywhere (app or the one nginx config in-repo)
File: backend/app/main.py (no such middleware); Frontend/deployment/nginx-cache-headers.conf (cache headers only)
Fix: Add `client_max_body_size` on whatever nginx vhost fronts the API, and/or a lightweight ASGI size-check middleware.
```

### Low

```
[SEVERITY: Low] Dead code: playwright_scrape_email() has no SSRF guard (currently unreachable)
File: backend/app/utils/email_scraper.py:292-296 — no callers found repo-wide
Fix: Add the same _is_internal_host() guard used elsewhere in this file, or delete if truly unused.
```

```
[SEVERITY: Low] OTP hashed with unsalted single-round SHA-256 — trivially reversible offline for a 6-digit space
File: backend/app/services/otp_service.py:27-29
Fix: HMAC with the app secret instead of bare SHA-256.
```

```
[SEVERITY: Low] Dev-only OTP plaintext logging gated by a string-match heuristic, not an environment flag
File: backend/app/services/otp_service.py:145-158
Fix: Gate on `settings.ENVIRONMENT in ("development","local",None)` instead.
```

```
[SEVERITY: Low] Password fields have min_length but no max_length before bcrypt hashing
File: backend/app/schemas/user.py:13-17; backend/app/schemas/auth.py:41-45
Fix: Add max_length=128.
```

```
[SEVERITY: Low] GET /system/mailboxes/ has no response_model — returns raw ORM rows
File: backend/app/api/v1/system_mailbox.py:85-107
Fix: Add response_model=list[SystemMailboxRead] after removing receive_password from that schema.
```

```
[SEVERITY: Low] /docs, /redoc, /openapi.json exposed unconditionally in every environment
File: backend/app/main.py:152 (FastAPI() with no docs_url/redoc_url/openapi_url override)
Fix: `docs_url=None if is_prod else "/docs"` (and same for redoc/openapi).
```

```
[SEVERITY: Low] Inconsistent RBAC on the global Domain resource — GETs are not admin-gated, writes are
File: backend/app/api/v1/domain.py:24-34
Fix: Gate the two GET routes with require_role("admin") to match writes and the sibling /system/domains pattern.
```

```
[SEVERITY: Low] CORS allowlist mixes the local dev origin into the same list served to staging/prod
File: backend/app/main.py:176-186
Fix: Source allow_origins from settings, split per-deployment so localhost:5173 never ships to staging/prod.
```

```
[SEVERITY: Low] Several secret-bearing settings default to empty string rather than failing startup
File: backend/app/core/config.py:64-101 (SMTP_*, HUNTER_API_KEY, STRIPE_*)
Fix: Make launch-critical secrets required in production via a startup check keyed on ENVIRONMENT.
```

```
[SEVERITY: Low] API base URL overridable via a ?api= URL parameter, persisted to localStorage
File: Frontend/src/config/api.ts:38-63,85-89
Description: A crafted link with ?api=https://attacker.example (on a non-canonical hostname) persists
the override, silently redirecting all future bearer-token-bearing API calls.
Fix: Remove the override in production builds, or restrict to an explicit allowlist of known API origins.
```

```
[SEVERITY: Low] Connection pool sizing risk under multi-worker scale-out
File: backend/app/database/session.py:14-23
Fix: Size pool_size × workers against Postgres max_connections; consider PgBouncer.
```

```
[SEVERITY: Low] Unbounded in-process spam-check cache — grows for the life of the worker process
File: backend/app/utils/spam_checker.py:32
Fix: Replace with a bounded/TTL cache (cachetools is already a dependency).
```

```
[SEVERITY: Low] Several list endpoints have no pagination cap
File: backend/app/api/v1/campaign_lead.py:53-63 and others (email_template.py, campaign_goal.py, campaign_category.py, chat_memory.py, domain.py)
Fix: Add capped limit/offset query params, consistent with lead.py's existing le=200 pattern.
```

```
[SEVERITY: Low] duckdb/geoalchemy2 are the only two unpinned dependencies in requirements.txt
File: backend/requirements.txt:26,36 (>= instead of ==)
Fix: Pin exact versions matching what's actually deployed.
```

### Info (documented, mitigated, or requires infra access to confirm)

- No `extra="forbid"` on Pydantic schemas — not currently exploitable (service layer whitelists fields explicitly) but worth adding as defense-in-depth.
- Access token returned both as an HttpOnly cookie and in the JSON login response body — redundant once the frontend fully migrates to cookie-only auth.
- No explicit CSRF token — acceptable given SameSite=Strict/Lax cookies + a fixed CORS allowlist; confirm the Lax choice on the refresh-token cookie is intentional.
- Unsubscribe token design (HMAC over lead_id+email+expiry) independently verified sound — no finding.
- DB user privilege level (superuser vs. least-privilege) — not verifiable from the repo; confirm on the actual Postgres instance.
- No self-service "delete my account"/"export my data" endpoint — only an admin-only hard-delete exists.
- Staging vs. production OAuth callback routing (`/mailboxes/google/callback`) — the actual nginx server blocks aren't in the repo; check directly on the Lightsail host.
- python-jose has a known algorithm-confusion class of issue in the ecosystem, but every decode call site here explicitly pins `algorithms=["HS256"]` — not exploitable as used.
- Third-party scripts (PostHog, GTM, Google Fonts) load without SRI — acceptable given they're frequently-updated analytics snippets.

---

## 3. Reply-tracking & email-threading deep dive

*(Recap of a follow-up investigation into how inbound replies are detected, matched, and stored — relevant background for the Inbox XSS finding above.)*

### How a reply is detected
A scheduler (`backend/app/core/scheduler.py`) runs every ~500 seconds, takes a Redis lock, and polls every active mailbox's inbox via IMAP (`reply_fetch_service.py`) or the Gmail API (`gmail_reply_fetch_service.py`) for unread messages. An on-demand API path can also trigger a fetch immediately.

### How a reply is matched to the right campaign + lead
Every outbound email embeds a custom `Message-ID`:
```
<EV-{random-uuid}-{campaign_id}-{lead_id}@evecta>
```
When the lead replies, their client's `In-Reply-To`/`References` headers point back at it. Matching is tried in priority order: (1) regex the IDs straight out of `In-Reply-To`, (2) DB lookup by stored Message-ID if a provider rewrote it, (3) walk the full `References` chain, (4) last resort — scan the body for a hidden fallback token. If none match, the message is dropped.

### The hidden-token mechanism
Two things are hidden in outbound HTML via `display:none; opacity:0; font-size:1px`:
1. A **legacy tracking token** (`ev=campaign_id|lead_id|user_id`) — the priority-4 fallback for reply matching (`email_sender.py:76-89`, `reply_sender_service.py:69-78`).
2. A **1×1 open-tracking pixel** — unrelated to reply matching, used only for open analytics (`email_sender.py:82`).

This pattern (Message-ID header + hidden-div fallback token) is standard industry practice, comparable to Marketo's "email homing beacon" technique — not itself a security issue. One secondary, non-security note: the same CSS pattern (`display:none`/`opacity:0`) is also the signature of "hidden text salting," a technique spam filters increasingly flag — a deliverability risk, not a security one.

### Why opens sometimes aren't tracked (industry-wide, not a bug)
- Apple Mail Privacy Protection preloads all images (including tracking pixels) through Apple's own proxy, often before the user opens the message — this actually causes false positives, not false negatives.
- Many clients (Outlook, various webmail) block remote images by default until the user clicks "show images" — if they never click it, the pixel never fires even though they read the email.
- This is a property of pixel-based tracking industry-wide; there's no code fix for it.

### Why replies sometimes don't show up (a real, confirmed bug)
`reply_fetch_service.py` fetches each unread message with `client.fetch(msg_id, "(RFC822)")`. Per the IMAP protocol, `RFC822` (unlike `RFC822.PEEK`/`BODY.PEEK[]`) **implicitly marks the message `\Seen`** as a side effect of fetching it — confirmed against the IMAP spec. Sequence for any reply that fails all four matching attempts:
1. Fetched once → marked `\Seen`, regardless of match success.
2. Matching fails → logged and skipped.
3. Next poll only searches `UNSEEN` mail → this message no longer qualifies → **never looked at again.**

There's no dead-letter queue, retry, "unmatched replies" view, or alerting — a reply that fails to match simply vanishes, with only a warning line in server logs as a trace.

**Fix:** switch the fetch to `RFC822.PEEK` (or `BODY.PEEK[]`) so unmatched messages stay unseen and get retried next cycle; add a fallback path (e.g. a small "needs review" table surfaced in the UI) instead of dropping unmatched mail outright.

### The EmailActivity / EmailMessage schema duplication

`EmailActivity` (legacy, per-send analytics: opens/clicks/bounces/delivery) and `EmailMessage`/`EmailThread` (newer, proper conversation threading) independently store the same fact — "did this lead reply, and what did they say" (`EmailActivity.replied/replied_at/reply_text` vs. an `EmailMessage` row with `direction=INBOUND`). Three separate services each hand-roll the same "update both" sequence:
- `reply_fetch_service.py:433-435`
- `gmail_reply_fetch_service.py:276-296`
- `reply_sender_service.py:103` / `thread_reply_service.py`

This has already drifted in production — `thread_reconcile_service.py` exists specifically as a backfill job because "some deployments... recorded SENT activities without creating thread rows."

**Fix (not a rewrite):**
1. Consolidate the "reply received" write sequence into one shared function all three paths call.
2. Treat `EmailMessage` as the source of truth; derive `EmailActivity`'s reply fields from it rather than writing them independently.
3. Keep the reconciliation job as a one-time safety net for old data, not a permanent patch for new drift.

Note: `EmailMessage.campaign_id` is *also* technically derivable via `thread_id → EmailThread.campaign_id`, but that duplication is a deliberate, reasonable query-performance tradeoff (avoids a join on hot paths) — not the same class of problem as the reply-state duplication above.

---

## 4. Backend efficiency & architecture findings

**Method:** 5 parallel deep-dives — DB/queries, service-layer duplication, async/Celery, external API cost, API endpoint design. Every service file (~90), route file (34), model (35), and Celery task was read.

### ⚠ The one correctness bug found during this pass

```
[IMPACT: Critical — correctness/authorization, not efficiency] Permission override "disable" is silently ignored by the actual route guard
File: backend/app/dependencies/auth.py:152; backend/app/services/effective_permission_service.py:92-93;
      correct logic exists but is unused for enforcement: backend/app/services/permission_service.py (calculate_final_permissions)
Description: require_permission() — the dependency that gates every permission-protected route — calls
get_effective_permissions(), which grants a permission the instant an override row exists, without ever
checking whether that override's is_enabled is True or False. The correct check (respecting is_enabled)
exists in calculate_final_permissions, but that's only wired to user.final_permissions — the value shown
in the UI. Net effect: if an admin explicitly revokes a permission for a user via an override, the UI
shows it revoked, but the user can still use it.
Evidence:
    # effective_permission_service.py:92-93 — used by require_permission
    if perm_id in override_ids:
        final_enabled = True          # never checks is_enabled
Fix: Point require_permission at calculate_final_permissions (or make get_effective_permissions check
is_enabled). One-line-scale fix, but fix it before anything else in this section.
```

### Database & Queries

**High**
```
[IMPACT: High] DB connection held checked-out for up to 180s per lead during campaign email generation
File: backend/app/services/campaign_email_generation_service.py:72-106 (_await_business_enriched), 835-935
Problem: Polls the DB every 5s waiting for enrichment with no commit between polls — the connection
stays checked out from the API's small pool (pool_size=5, max_overflow=10) for the whole wait, per lead.
A handful of concurrent generations can exhaust the pool and stall unrelated API requests.
Fix: Commit/release between polls (or use a short-lived session per poll); run this loop against its
own engine rather than the API's shared pool, even in the in-process fallback path.
```

**Medium**
```
[IMPACT: Medium-High] DB session held open across slow SMTP/Gmail network sends (reply paths)
File: backend/app/services/thread_reply_service.py:157-303; backend/app/services/reply_sender_service.py:23-135
Problem: Several SELECTs open a transaction, then the code sends the email over the network (up to a
90s timeout) with the session still checked out, committing only afterward. The main campaign-send path
explicitly enforces "no DB writes/commits during send" — this discipline wasn't carried into reply paths.
Fix: Commit/close read queries before sending; send with no open session; open a fresh short session to persist afterward.
```
```
[IMPACT: Medium] DB connection held across website scrape + LLM extraction call
File: backend/app/services/company_scraper_worker.py:16-85
Fix: Fetch what's needed with a short-lived session, close it, scrape+LLM with no open session, then open a fresh session just for the write.
```
```
[IMPACT: Medium] Per-message N+1 query bursts inside IMAP/Gmail reply-matching loops
File: backend/app/services/reply_fetch_service.py:169-450; backend/app/services/gmail_reply_fetch_service.py:92-322
Problem: Up to 6+ sequential DB round trips per unread message before moving to the next one.
Fix: Pre-fetch outbound message_ids/EmailActivity/EmailThread for the batch in 1-2 queries, match in-memory.
```
```
[IMPACT: Medium] Missing composite index on credit_transactions(user_id, created_at)
File: backend/app/models/credit.py:35-48; backend/app/services/credit_service.py:671-682
Problem: Every credit-consuming action writes a row here; the history query filters+sorts on both columns with only a single-column index.
Fix: Add Index("idx_credit_transactions_user_created", "user_id", "created_at") via migration.
```
```
[IMPACT: Low-Medium] Three Alembic migrations add NOT NULL columns with no default/backfill
File: backend/alembic/versions/37bffb41df78_added_user_id_in_email_activity_model.py:24,
      27e4f993493b_add_promoted_flag_to_lead_log_leads.py:24, e409b5cf5595_add_promoted_flag_to_lead_log_leads.py:24
Problem: On Postgres, ADD COLUMN ... NOT NULL with no default fails outright against a table with
existing rows. Other migrations in the same history handle this correctly (server_default, or an
explicit TRUNCATE with a comment) — these three didn't follow that pattern.
Fix: Always add nullable=True with a server_default (or a backfill UPDATE), then a follow-up SET NOT NULL step.
```

**Low**
- Older enum columns (`CampaignStatus`, `EmailStatus`, `MessageDirection`) store the uppercase member name, not `.value`, inconsistent with newer models using `values_callable` — a landmine for a future raw-SQL report.
- Free-text `pool`/`status`/`action` columns backing credit math have no DB-level CHECK constraint (`normalize_pool()` already has defensive coercion because bad values do get in).
- `GET /credits/balance` re-fetches the same 3 pool rows twice (6-9 round trips for one balance read).
- A functional-index mismatch on `lower(coalesce(industry,''))` in `chat_service.py` won't use the plain `industry` index.

### Service-Layer Architecture & Dead Code

**High**
```
[IMPACT: High] "Campaign must be DRAFT" guard duplicated ~9 times, including two identically-named separate functions
File: campaign_email_generation_service.py:490-498, campaign_email_review_service.py:54-59 (both define
      _get_campaign_or_404 independently), campaign_draft_service.py:152-156/249-253/331-335,
      campaign_launch_service.py:40-44/78-82, campaign_lead_service.py:42-44, campaign_service.py:524-528/613-617
Fix: Extract one ensure_campaign_editable(campaign, action) helper; have all call sites use it.
```
```
[IMPACT: High] Entire legacy mailbox-selection module is dead and was race-prone
File: email_rotation_service.py:14-92 (get_available_domain/get_available_mailbox/get_available_user_mailbox),
      mailbox_usage.py:1-6 (mark_mailbox_used) — zero callers, superseded by mailbox_selector_service.py's
      correct FOR UPDATE SKIP LOCKED version
Fix: Delete the dead functions and mailbox_usage.py; keep only reset_daily_counters from email_rotation_service.py.
```

**Medium**
- Byte-identical duplicate file `app/utils/unsubscribe_url 2.py` — never imported, safe to delete.
- ~200 lines of dead scraping code in `email_scraper.py` (`hunter_fallback`, `playwright_scrape_email`, `scrape_company_email`) — `playwright_scrape_email` is the only reason this file (and possibly `requirements.txt`) still depends on Playwright.
- Two god-files: `chat_service.py` (2891 lines, one 624-line function) and `lead_generation_service.py` (3227 lines, 5 unrelated subsystems).
- `billing.py` (1333 lines) never got a `*_service.py` extracted, unlike every other feature area.
- Two recovery-message builders in `chat_recovery.py` (enrichment-timeout, insufficient-credits) are fully written but never called — plausibly the concrete cause of the "no retry escalation" gap from the earlier chat-design audit.
- The sanctioned `raise_safe()` helper in `http_errors.py` has zero callers; services still hand-roll `HTTPException` everywhere.

**Low**
- Dead revoke/cleanup functions that sound security-relevant but are wired to nothing: `revoke_admin_device_trust`, `revoke_all_user_tokens`, `cleanup_expired_otps`.
- ~55 unused imports across ~34 files (25% of reviewed set) — add `ruff check --select F401` to CI.
- A retry loop in `ai_email_generator.py` that can mathematically never retry (`max_retries=1`, guard is always `0 < 0`).
- Template-formatting helpers live inside the Celery task module `mail_job.py`, forcing two services to import from the tasks layer (backwards dependency direction).

### Async / Celery / Caching

**High**
```
[IMPACT: High] Campaign email generation is one giant sequential, non-distributable task
File: campaign_email_generation_service.py:835-935
Problem: A whole campaign's leads are generated one at a time in one task/asyncio task, each optionally
blocked up to 180s on the enrichment poll above. No work distribution across workers; a crash loses the
entire remaining run.
Fix: Process small concurrent batches (semaphore of 3-5), or fan out into small per-chunk Celery sub-tasks.
```
```
[IMPACT: High] Enrichment concurrency semaphores aren't actually shared across calls or workers
File: backend/app/utils/enrichment_semaphores.py; instantiated fresh per call in lead_generation_service.py:2970, chat_service.py:2218
Problem: The intended Hunter/HTTP/Playwright/Maps concurrency caps only hold within one task. With
multiple Celery worker processes running concurrently (confirmed in deploy-staging.yml), real concurrent
Hunter calls can be several times the intended ceiling.
Fix: Module-level singleton for per-process bounding; a Redis-backed token limiter for a true cross-process cap.
```

**Medium**
- No shared cache for Hunter lookups / Gemini context-extraction outside the Overture-sourced lead path — same company re-scraped/re-queried every time it appears in a different campaign or user's search.
- Hunter.io `429` responses are silently treated as "no email found" — no distinction, no backoff, no retry.
- Campaign status-polling endpoints hydrate every row just to count statuses on every UI poll tick — should be a `GROUP BY` aggregate.
- All Celery auto-retries use a fixed countdown, not `retry_backoff`/`retry_jitter` — a shared-dependency blip causes synchronized retry bursts.
- Gmail reply-fetch opens a brand-new `httpx.AsyncClient` for every single API call (up to ~40 per mailbox per cycle) instead of reusing one.

**Low-Medium**
- `redis_context.py` uses the synchronous redis client directly from `async def` functions with no `asyncio.to_thread` — blocks the event loop on every cache/lock check.
- Bonus correctness bug: `main.py:255` does `redis = await get_redis()`, but `get_redis()` is a plain sync function — awaiting it raises `TypeError`, silently swallowed, so `/ready` may report Redis "unreachable" even when healthy.

### External API Cost (Gemini / Maps / Hunter)

**Medium**
- Chat prompts resend the **entire conversation history**, uncapped, on every Gemini call — cost grows linearly per call, roughly quadratically per session.
- Campaign email generation makes up to 2 Gemini calls per compliance attempt (generate + spam-score), up to 10 per lead worst-case — and the intended "try harder after 3 failures" escalation is dead code (the stricter spam-check path is unreachable).
- The monthly Overture refresh unconditionally re-pulls every cached area from S3 regardless of whether that area's release actually changed.

**Low-Medium**
- The Google-Maps geocoding path (dormant behind `LEAD_SOURCE=overture` but still the code default) fires a second, uncached Geocode API call on every search even on a cache hit for the first call.
- The Gemini pricing-cache refresh does a synchronous blocking HTTP call from inside the async cost-tracking path — blocks the event loop for that request every ~6 hours.

**What's already good:** master-catalog enrichment dedup (`overture_id`-keyed atomic claim) means a given business is scraped/Gemini-enriched at most once across all users; every paid call site goes through a tracked wrapper (no cost-visibility gaps); no retry-without-checking-success risk on any paid API.

### API Endpoint Design

**High**
```
[IMPACT: High] "Toggle favorite" endpoint runs 5-6 round trips (including a duplicate schema-introspection query) to flip one boolean
File: backend/app/api/v1/email_template.py:129-166; backend/app/services/email_template_service.py:294-337,385-400
Fix: Drop the runtime information_schema check entirely (reference the column directly); make the toggle a single UPDATE ... RETURNING.
```
```
[IMPACT: High] CampaignLeadResponse emits every lead field twice (nested + flattened) — roughly doubles payload size
File: backend/app/schemas/campaign_lead.py:28-118
Fix: Pick one representation, or compute the flat fields as pydantic computed properties reading from the nested object.
```

**Medium**
- Pagination style inconsistent across the API: `page`+`per_page`, `page`+`limit`, `limit`+`offset` all coexist.
- A few more unbounded list endpoints beyond the ones already flagged — notably `GET /users/` (every user, no pagination — the one that will actually grow unbounded).
- `manual_fetch_replies` re-derives the user ID from a second, independent token-decode path even though `get_current_user` already did that work.

**Low**
- Sequential ownership-check queries in `email_replies.py`/`inbox.py` that could be one joined query.
- Campaign launch/review screen needs 2-3 separate GETs that are always consumed together.
- `gemini_purchases.py` has two byte-for-byte identical endpoints (`/track`, `/summary`).
- Usage-analytics endpoints have 6-8 near-duplicate schemas/queries differing only by group-by dimension.

### Punch list — fix first

1. Fix `require_permission` to respect `is_enabled=False` — the one actual bug in this section.
2. Release the DB connection during the 180s enrichment poll, and share the enrichment semaphores — these compound each other under load.
3. Delete the confirmed-dead code (duplicate file, dead mailbox-selection module, dead scraping functions, dead recovery-message builders) — zero risk, immediate clarity win.
4. Consolidate the 9-way duplicated "campaign must be DRAFT" check into one helper.
5. Fix the toggle-favorite endpoint and the doubled `CampaignLeadResponse` payload — cheap, high-value wins on frequently-hit paths.

---

## 5. Out of scope / not yet reviewed

- **Frontend efficiency/architecture** — React re-render patterns, bundle size, code-splitting, component structure. Frontend was covered for security (XSS, Vite config) but not performance/architecture.
- **Test suite quality/coverage** — `backend/tests/` exists but hasn't been assessed for what's actually covered.
- **Real dependency CVE scanning** — no actual `pip-audit`/`npm audit` run against the lockfiles; findings here are manual pattern-matching only.
- **Live/runtime verification** — no query EXPLAIN plans, no load testing, no confirming any finding under real traffic.
- **Nothing in this document has been fixed.** This is a diagnosis, not a changelog.

---

## 6. Additional findings from senior backend re-audit (2026-08-13)

**Important:** These are additional, source-verified findings appended after the original audit. No application code was changed. Generated files, `__pycache__`, `.pytest_cache`, and the checked-in `venv`/`myenv` third-party packages were excluded from the code review.

### Security

```text
[SEVERITY: High] Authenticated SSRF and internal-port probing through custom mailbox validation
File: backend/app/api/v1/mailbox.py:147-157; backend/app/schemas/mailbox.py:24-36;
      backend/app/services/mailbox_service.py:22-59,98-127
Category: Server-Side Request Forgery (OWASP API7:2023 / CWE-918)
Description: Any authenticated user can supply arbitrary `smtp_host`, `smtp_port`, `imap_host`, and
`imap_port` values. The backend then opens SMTP and IMAP connections to those destinations. There is
no private, loopback, link-local, metadata-address, or DNS-rebinding protection. The different curated
connection/authentication errors also provide a useful internal port-scanning oracle. This path is
separate from the website-scraper SSRF already documented above.
Fix: Resolve and validate every address immediately before connection; reject loopback, private,
link-local, multicast, reserved, and cloud-metadata ranges for both IPv4 and IPv6; pin the validated
address for the connection; restrict ports to the supported SMTP/IMAP set where practical; and apply
an outbound network policy that prevents API workers from reaching metadata and internal networks.
```

```text
[SEVERITY: High] Gmail mailbox OAuth callback trusts an unsigned, client-controlled user_id
File: backend/app/api/v1/mailbox.py:31-70,76-110
Category: Broken Authentication / OAuth account-injection
Description: The code comment says `mailbox_oauth_state` is signed, but its value is only
`<random-state>:<user_id>|<campaign_id>`. The unauthenticated callback verifies that the query-string
state matches the prefix in that same client-supplied cookie, then trusts the cookie's user_id. There
is no server-side state record, HMAC/signature, or authenticated-current-user comparison. A caller who
can construct the callback request and cookie can choose the victim user_id to which the Google
mailbox is attached.
Fix: Store `{state -> authenticated user_id, campaign_id, created_at}` server-side in Redis with a
short TTL and consume it atomically once, or use an authenticated-encryption/signed state token with
expiry and nonce. Do not accept identity/ownership data merely because it appears beside a matching
client-controlled state value.
```

```text
[SEVERITY: Medium] Gmail access tokens are stored in plaintext while refresh tokens are encrypted
File: backend/app/models/mailbox.py:68-70; backend/app/services/google_mailbox_service.py:103-106,140-154;
      backend/app/services/google_gmail_token_service.py:40-48
Category: Sensitive Data Exposure
Description: `google_refresh_token` is protected with Fernet, but `google_access_token` is written
directly to the database on initial connection and every refresh. A database read leak therefore
immediately exposes currently valid Gmail API bearer tokens. Their shorter lifetime reduces impact
but does not make plaintext storage appropriate.
Fix: Encrypt access tokens at rest too, decrypt only at the API-call boundary, and plan key rotation
with key identifiers/versioning instead of one process-global unversioned Fernet key.
```

```text
[SEVERITY: Medium] Mailbox update can redirect future SMTP/IMAP traffic without re-validation
File: backend/app/schemas/mailbox.py:64-74; backend/app/services/mailbox_service.py:253-285
Category: SSRF / Validation Bypass
Description: Creation validates SMTP and IMAP credentials, but update writes changed hosts and
credentials directly. Even after the creation-time SSRF issue is fixed, this update path would remain
a bypass and can persist a destination that workers contact later during sends or reply polling.
Fix: Apply the same complete destination and credential validation to the proposed combined mailbox
configuration before persisting any update. Reject partial changes that cannot be validated safely.
```

### Correctness and reliability

```text
[IMPACT: High] Updating smtp_port silently writes an unmapped Python attribute and is not persisted
File: backend/app/models/mailbox.py:53-64; backend/app/schemas/mailbox.py:64-74;
      backend/app/services/mailbox_service.py:264-285
Description: The ORM column is named `port`, while the update schema and allowlist use `smtp_port`.
The generic `setattr(mailbox, "smtp_port", value)` succeeds as a normal transient Python attribute,
so the endpoint can return success even though SQLAlchemy never updates the database column. After
refresh/reload, the old SMTP port remains.
Fix: Use an explicit field map (`smtp_port -> port`) instead of generic setattr, add `ge=1, le=65535`
to both update ports, and add a persistence test that reloads the row in a new session.
```

```text
[IMPACT: Medium] Gmail sign-in lookup does not normalize the provider email before querying
File: backend/app/services/google_auth_service.py:101-123; normalization used elsewhere in
      backend/app/services/user_service.py:38,115
Description: Password registration stores lowercase email and normal email lookup lowercases input,
but the Google callback queries `User.email == email` using the provider's original casing. A casing
difference can miss the existing account and enter the new-user path, where normalization happens too
late and can end in a uniqueness error instead of login.
Fix: Normalize once (`email = email.strip().lower()`) immediately after validating the Google claim,
and enforce case-insensitive uniqueness at the database level (for example PostgreSQL `citext` or a
unique index on `lower(email)`) so every current and future write path shares the invariant.
```

```text
[IMPACT: Medium] Reply-fetch scheduler task is neither retained nor cancelled during application shutdown
File: backend/app/main.py:80-90,138-149; backend/app/core/scheduler.py:15-56
Description: Startup calls `asyncio.create_task(reply_fetcher_loop())` and discards the task handle.
Shutdown closes the checkpointer and Redis without first cancelling/awaiting the infinite scheduler.
This can race an in-progress fetch or its lock-release `redis.eval()` against Redis shutdown and makes
graceful worker draining unreliable.
Fix: Store the task on `app.state`; during lifespan teardown cancel it, await it while handling
`CancelledError`, and only then close shared resources. Also renew the distributed lock while a cycle
runs: its fixed 600-second TTL can expire during a slow all-mailbox scan, allowing another worker to
start an overlapping cycle.
```

```text
[IMPACT: Medium] Monetary cost fields use binary Float instead of exact decimal storage
File: backend/app/models/ai_usage_event.py:49-51;
      backend/app/models/external_api_usage_event.py:44-46
Description: Per-unit prices and accumulated USD estimates are stored as SQL `Float`. Binary floating
point introduces rounding drift in sums and recomputation, which is undesirable for billing/cost
reporting and can make totals disagree across Python, PostgreSQL, and exported reports.
Fix: Store money/rates as `Numeric(precision, scale)` and use Python `Decimal` end to end. Keep token
and unit counts as integers. Add a migration that converts existing values with an explicit rounding
policy.
```

### Efficiency, validation, and maintainability

- **Repeated Gmail client/TLS setup is broader than the original note:** `google_mailbox_service.py`, `google_gmail_token_service.py`, `google_gmail_sender.py`, and `thread_reply_service.py` also create a fresh `httpx.AsyncClient` per operation. Use one lifespan-managed client per process with explicit per-operation timeouts and connection limits; do not share an `AsyncSession` when introducing concurrency.
- **Input-size limits are inconsistent beyond file uploads:** many write schemas accept unbounded strings even though their database columns are bounded (examples include campaign updates, email-template inputs, mailbox hosts/usernames/passwords, roles, domains, and lead fields). Add schema limits matching DB columns and business limits; cap large text/prompt/body fields separately. This prevents late database errors and reduces validation, logging, prompt, and memory abuse.
- **PII is logged more widely than necessary:** authentication, reply polling, unsubscribe, test-email, contact, and cancellation paths log full email addresses. Use structured logging with redacted or keyed identifiers, define retention/access rules, and ensure exception reporting scrubs message bodies, tokens, credentials, and recipient data.
- **The environment file is working-directory dependent:** `SettingsConfigDict(env_file=".env")` resolves relative to the process working directory. Starting tooling or tests from the repository root does not load `backend/.env`, producing configuration collection failures. Resolve the file relative to `config.py` (while preserving real environment-variable precedence) or make the required launch directory explicit in every entrypoint and CI job.
- **Pydantic v2 cleanup is pending:** tests emit deprecation warnings for class-based `Config` and `Field(example=...)`. Replace them with `ConfigDict(from_attributes=True)` and `json_schema_extra` before Pydantic v3 turns these warnings into migration work under pressure.

### Re-audit validation notes

- All project-owned Python files under `backend/app`, `backend/alembic`, `backend/scripts`, and `backend/tests` passed bytecode compilation before runtime execution was stopped.
- A test run from the repository root was unable to collect tests because the relative `.env` path did not load the 19 required settings; this directly supports the working-directory finding above. A second test run from `backend/` was stopped on request, so no test-pass claim is made.
- No dependency CVE scan, live database query plan, load test, or penetration test was completed. Those remain necessary before treating this document as production certification.

### Primary guidance used for this re-audit

- OWASP API Security Top 10 (2023): object/function authorization, unrestricted resource consumption, SSRF, security misconfiguration, and unsafe consumption of APIs.
- SQLAlchemy 2.0 documentation: one `AsyncSession` per concurrent task; avoid implicit async relationship I/O; use eager-loading/query profiling where repeated SQL is observed.
- FastAPI security and deployment guidance: validate untrusted inputs at the boundary and manage application-scoped resources through lifespan.
- Celery task guidance: tasks must tolerate redelivery; use idempotency, bounded retries/backoff, and explicit lifecycle handling around long-running work.

---

## 7. Database normalization group

This section consolidates the normalization work identified during the backend review. The current database is not fundamentally unnormalized and does **not** need a wholesale redesign. The goal is to remove competing sources of truth, enforce identity/state invariants in PostgreSQL, and split models only when fields have genuinely different lifecycles, access rules, or loading patterns.

The current model registry contains approximately **36 exported SQLAlchemy ORM classes across 33 model files** (excluding `models/__init__.py`). The numbers differ because some files define more than one mapped class. `UserProfile` described below is a **proposed new model**; it is not currently a separate exported ORM model. Introducing it would increase the approximate ORM-class total to 37.

### Normalization priority summary

| Priority | Models/area | Classification | Recommended change |
|---|---|---|---|
| Highest | `EmailActivity`, `EmailThread`, `EmailMessage` | Required structural normalization | Establish one canonical message and event model |
| High | `User`, `Mailbox`, `Waitlist`, lead email fields | Required invariant normalization | Enforce normalized, case-insensitive email identity |
| Medium-High | `UserCreditPool`, `CreditTransaction` | Required constraints/ledger strengthening | Constrain finite values and add idempotent source references |
| Medium | `User` + proposed `UserProfile` | Recommended vertical split | Separate account/security data from optional profile data |
| Medium | `Mailbox` | Conditional structural split | Separate SMTP, IMAP, and OAuth credentials as providers grow |
| Medium | `Company` | Conditional structural split | Separate targeting profiles if multiple/versioned profiles are needed |
| Conditional | `Campaign.tags` | Conditional many-to-many normalization | Create `Tag` and `CampaignTag` only if tags are queried independently |
| Low/Conditional | `AiUsageEvent`, `ExternalApiUsageEvent` | Shared-contract improvement | Standardize common fields; do not merge automatically |
| Cross-cutting | Money and finite-state fields | Data-type/constraint correction | Use `Numeric`/`Decimal`, enums, or DB `CHECK` constraints |

### 7.1 Email messages, threads, activities, and events — highest priority

**Affected existing models:**

- `EmailThread`
- `EmailMessage`
- `EmailActivity`

**Current problem:** Reply and message truth is duplicated across `EmailActivity` and `EmailMessage`. Both can contain overlapping message IDs, sender/recipient data, bodies, reply flags, reply text, and timestamps. Different ingestion/sending paths can update one representation without updating the other, producing inconsistent Inbox, analytics, and campaign state.

**Recommended normalized structure:**

```text
EmailThread
  └── EmailMessage
        └── EmailEvent
```

**Recommended responsibilities:**

`EmailThread`

- Conversation container.
- Owns the user/campaign relationship and thread-level timestamps.
- May keep derived counters such as unread count only if updates are atomic and repairable.

`EmailMessage`

- Canonical record for every inbound and outbound message.
- Stores direction, sender, recipient, subject/body, provider message ID, threading headers, lead, campaign, mailbox, and sent/received time.
- Provides the only writable source of message/reply content.

`EmailEvent` (new or evolved from `EmailActivity`)

- Stores append-oriented events such as queued, sent, delivered, opened, clicked, bounced, complained, failed, and provider acceptance.
- References a canonical `email_message_id`.
- Stores provider event ID, event timestamp, metadata, and deduplication key.

**Rules:**

- Derive `has_replied`, latest reply, and reply count from inbound `EmailMessage` rows.
- Do not independently store mutable reply text in both activity and message tables.
- If summary columns are retained for fast reads, treat them as derived cache fields with one atomic updater and a repair/reconciliation job.
- Add unique provider/message constraints that match actual provider semantics and permit known null/legacy cases.
- Migrate in stages: introduce canonical references, backfill, dual-read for verification, switch writes, then remove obsolete duplicate fields.

### 7.2 `User` and proposed `UserProfile` — recommended

There is currently a `User` model, but no separate exported `UserProfile` model. The existing `User` record combines frequently loaded authentication/account data with optional presentation/profile data.

**Keep in `User`:**

- `id`
- normalized `email`
- `username`
- `hashed_password`
- `role_id`
- `is_active`
- `is_superuser`
- `email_verified`
- plan, billing interval, and subscription/account status fields
- email-sending preference
- account creation/update timestamps
- first/last-login timestamps

**Move to proposed `UserProfile`:**

- `full_name`
- `department`
- `location`
- `website`
- `bio`
- `profile_image`
- profile creation/update timestamps

**Proposed relationship:**

```text
User 1 ─── 0..1 UserProfile
```

**Required database rules:**

```text
UserProfile.user_id UNIQUE NOT NULL
UserProfile.user_id FOREIGN KEY -> users.id ON DELETE CASCADE
```

**Why this is useful here:**

- Authentication and authorization frequently load `User`; they should not need large optional fields such as profile-image data and biography.
- Profile mutation receives a smaller, safer write boundary and cannot accidentally alter plan, role, login, or authentication fields.
- Admin account lists can load account summaries without profile payloads.
- Profile access, validation, and audit rules can evolve independently.

**Existing `Company` separation:** `business_email` and `achievements` are not `User` columns and must not be included in a `UserProfile` migration. They already belong to the `Company` model. `User` also already has a one-to-one relationship with `Company` (`uselist=False`). That relationship provides an existing separation for business identity, onboarding, and targeting data, but `Company` should not automatically be renamed or reused as a personal `UserProfile`: the six actual profile fields above describe the application user's personal profile and have a different domain meaning from company/business data.

**When not to split:** If profile data remains small, is required by nearly every authenticated request, and profile images are stored outside the database, the extra one-to-one join may provide limited benefit. Measure common query shapes before migrating.

### 7.3 Case-insensitive email identity — high priority

Application services lowercase some email addresses, but identity correctness should not depend on every current and future code path remembering to normalize them.

**Affected models/fields:**

- `User.email`
- `Mailbox.email`
- `Waitlist.email`
- `Lead.email`
- `LeadLogLead.email`
- `Company.business_email` where treated as an identity

**Recommended database enforcement:**

- Use PostgreSQL `citext`, or
- create unique functional indexes on `lower(email)`.

**Recommended uniqueness scopes:**

```text
User:       UNIQUE lower(email)
Mailbox:    UNIQUE lower(email)
Waitlist:   UNIQUE lower(email)
Lead:       UNIQUE (user_id, lower(email)) where email is not null, if product rules forbid duplicates per user
LeadLogLead: preserve snapshot/search-result rules; do not make globally unique
```

**Important:** Lead email must not be globally unique because different users can legitimately discover or save the same business. If leads without email are deduplicated, use a documented business identity such as `overture_id`, not nullable text-field guesses.

### 7.4 Mailbox identity and provider credentials — conditional normalization

The current `Mailbox` model combines mailbox ownership/limits with SMTP, IMAP, and Google OAuth provider details.

**Possible future structure:**

```text
Mailbox
├── MailboxSmtpCredential
├── MailboxImapCredential
└── MailboxOAuthCredential
```

`Mailbox` should contain:

- mailbox identity and normalized email
- owner and mailbox type
- provider type
- active state
- daily limit and counters
- selection/rotation timestamps

Provider credential tables should contain only provider-specific encrypted secrets and configuration.

**Adopt this split when:**

- Microsoft, Yahoo, or other OAuth providers are added;
- one mailbox can support multiple connection methods;
- provider credentials require different rotation, audit, or access policies;
- the current nullable provider-column matrix becomes difficult to validate.

**Do first:** Fix SSRF protection, encrypt Gmail access tokens, validate mailbox updates, correct `smtp_port` persistence, and establish key rotation. Splitting insecure credential rows into multiple tables does not itself make them secure.

### 7.5 Company identity and targeting profiles — conditional normalization

The current `Company` model appears to combine company/profile information with onboarding answers and lead-targeting preferences.

**Potential structure:**

```text
Company
├── CompanyAddress          (only if multiple/structured addresses are required)
└── TargetingProfile        (when multiple or versioned targeting strategies are required)
```

Keep stable company identity/profile data in `Company`. Move target industry, target business type, target location, lead-volume expectations, and similar prospecting preferences into `TargetingProfile` only when:

- one user/company can have multiple target markets;
- campaigns need different targeting profiles;
- targeting preferences require history/versioning;
- targeting profiles are reused across searches/campaigns.

Do not create separate one-row tables merely to reduce column count. If there will always be one company and one target profile edited together, the current wide record may be simpler and sufficiently normalized.

### 7.6 Campaign tags — conditional normalization

If `Campaign.tags` contains delimited or serialized text and tags are searched, filtered, counted, reused, or renamed independently, introduce:

```text
Tag
- id
- normalized_name
- display_name

CampaignTag
- campaign_id
- tag_id
```

Recommended constraints:

```text
UNIQUE Tag.normalized_name
UNIQUE (CampaignTag.campaign_id, CampaignTag.tag_id)
```

If tags are only informal display text and are never addressed independently, retain the current text field. Normalizing decorative strings would add joins without product value.

### 7.7 Credits, transactions, billing references, and idempotency — medium-high priority

`UserCreditPool` and `CreditTransaction` are already correctly separated conceptually. The remaining work is stronger ledger structure and constrained values.

**Recommended `CreditTransaction` additions:**

- `idempotency_key`
- `source_type` (Stripe invoice, checkout session, subscription grant, lead action, campaign action, admin adjustment, refund)
- `source_id`
- `balance_type` (`subscription` or `topup`)
- optional actor/admin identifier
- structured metadata only where justified

**Recommended database rules:**

- Unique idempotency/source constraints for grants that must occur once.
- `CHECK` or enum constraint for `pool`.
- `CHECK` or enum constraint for `balance_type`.
- Constrained action/source categories rather than arbitrary spellings.
- Non-negative stored pool balances unless negative balances are an explicit product rule.
- Composite index aligned with history reads: `(user_id, created_at)`.

This is particularly important because Stripe webhooks and Celery tasks may be delivered more than once.

### 7.8 AI and external API usage models — standardize, do not automatically merge

**Affected models:**

- `AiUsageEvent`
- `ExternalApiUsageEvent`
- `GeminiPurchase`
- `GeminiApiStatusEvent`

AI and general external API usage share concepts such as user, provider, feature, status, latency, request ID, cost, and creation time. That does not automatically justify one large polymorphic table.

Recommended approach:

- Define one shared application-level usage contract and naming convention.
- Keep AI-specific token/rate fields in `AiUsageEvent`.
- Keep non-AI unit/API fields in `ExternalApiUsageEvent`.
- Add a common request/correlation ID when calls need cross-table tracing.
- Apply consistent retention, aggregation, and indexing policies.
- Introduce a parent `UsageRequest` table only if a real workflow requires one lifecycle spanning both detail types.

Avoid a generic entity-attribute-value usage table; it weakens constraints and makes analytics harder.

### 7.9 Exact money and rate storage — required data-type correction

Usage rate and estimated-cost fields currently use binary floating-point columns in places. Financial and cost-reporting values should use fixed-precision database types and Python `Decimal`.

Recommended shape:

```text
unit_cost_usd       Numeric(18, 10)
estimated_cost_usd  Numeric(18, 8)
```

Choose precision/scale from actual provider pricing requirements. Keep tokens, requests, leads, and other countable units as integers. Migrate existing values using an explicit rounding policy and test that recomputed totals match stored aggregates.

### 7.10 Finite state values — constraints rather than unnecessary tables

Several models use free-text values for finite business states, including examples such as:

- credit pool/action/source
- lead-log status
- enrichment status
- usage status
- billing interval
- subscription state
- provider and feature categories

Use one of:

- PostgreSQL enum when the set is stable and changes are controlled;
- `CHECK` constraint when values are stable but easier migrations are preferred;
- reference table when administrators or product configuration must add/change values dynamically.

Do not create separate lookup tables for every two- or three-value static flag. The goal is enforced validity, not the maximum possible number of joins.

### 7.11 Lead/catalog/campaign lifecycle — intentionally separate, do not collapse

The following models contain related business information but represent different ownership and historical boundaries:

```text
OverturePlace
    ↓ search-result snapshot
LeadLogLead
    ↓ user promotion/save
Lead
    ↓ campaign membership/context snapshot
CampaignLead
    ↓ campaign-specific generated content
CampaignLeadEmail
```

These models should generally remain separate:

- `OverturePlace` is shared catalog data.
- `LeadLogLead` records what a particular search returned at that time.
- `Lead` is user-owned reusable library data.
- `CampaignLead` is campaign membership plus campaign-time context.
- `CampaignLeadEmail` is campaign-specific generated/reviewed copy.

This is intentional snapshotting, not automatically harmful duplication.

Required documentation/invariants:

- Identify which copied fields are immutable historical snapshots.
- Identify which fields continue to read from the current `Lead` or catalog record.
- Preserve `overture_id` as the stable link for Overture-sourced businesses.
- Define the winning source when catalog, saved lead, and campaign snapshot differ.
- Keep duplicate filtering, quotas, promotion, and exhaustion deterministic and database-driven.
- Do not globally deduplicate businesses across different users' private lead libraries.

### 7.12 Models already reasonably normalized

These areas are structurally appropriate and mainly need service-logic or constraint fixes rather than table splitting:

- `Role`, `Permission`, `UserPermissionOverride`
- `Campaign`, `CampaignCategory`, `CampaignGoal`
- `OvertureCategory`, `OvertureCategoryAlias`
- `UserCreditPool`, `CreditTransaction` as separate balance and ledger concepts
- `EmailThread`, `EmailMessage` as separate conversation and message concepts (while activity/event overlap still needs correction)
- `ProcessedWebhookEvent` as a dedicated webhook deduplication record
- `SubscriptionInitialCreditGrant` as a dedicated once-only grant record

The permission bug documented elsewhere is caused by enforcement logic ignoring `is_enabled=False`, not by an incorrectly normalized permission schema.

### 7.13 Safe implementation order

1. Document current data ownership and invariants before moving columns.
2. Normalize email identity and add case-insensitive uniqueness safely after detecting existing collisions.
3. Introduce canonical `EmailMessage`/`EmailEvent` relationships and backfill them without immediately deleting old fields.
4. Switch all writers to the canonical message/event path and run reconciliation comparisons.
5. Add credit source/idempotency fields and constraints before changing webhook/task behavior.
6. Replace Float money fields with Numeric/Decimal using an explicit migration rounding policy.
7. Introduce `UserProfile` and backfill optional profile fields; update authentication queries to avoid unnecessary joins.
8. Split mailbox credentials only after security fixes and when provider growth justifies the migration.
9. Normalize Company targeting profiles and campaign tags only when confirmed product/query requirements justify them.
10. Remove obsolete duplicate columns only after production observation proves the new read/write path is complete.

### 7.14 Validation required for normalization migrations

- Inventory nulls, duplicates, case-colliding emails, invalid state strings, and orphaned foreign keys before adding constraints.
- Rehearse every migration against a production-shaped database snapshot, not only an empty database.
- Use staged nullable columns, backfills, validation queries, and later `SET NOT NULL` rather than unsafe one-step changes on populated tables.
- Add reconciliation queries for old versus new message/reply truth during the transition.
- Validate index changes with `EXPLAIN (ANALYZE, BUFFERS)` on realistic volumes.
- Add rollback/forward-fix plans for long-running data migrations.
- Add regression tests for case-insensitive identities, credit idempotency, canonical email events, profile creation/deletion, and snapshot lifecycle rules.
- Do not assign a post-normalization quality rating until migration and runtime validation complete successfully.

### Normalization conclusion

The database is approximately **7/10 for normalization today**. The highest-value structural correction is the email thread/message/activity model. Case-insensitive identity and ledger/state constraints are equally important integrity improvements. `UserProfile` is a useful recommended split, especially if profile images or profile content are large, but it is less urgent than eliminating competing message truth and enforcing identity/credit invariants.

After the required changes and successful migration validation, the schema would reasonably reach approximately **8.5–9/10**. Further splitting beyond the conditional cases above would likely create unnecessary joins and operational complexity rather than meaningful normalization.
