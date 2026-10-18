# Inbox Threading System — Implementation Plan

## Overview

Gmail-like email threading for campaign emails. Each launched campaign creates one thread in the inbox. Inside the thread, only leads who replied are shown, each with a reply button for the user to respond back.

---

## Current Architecture (What Exists)

| Component | Current State |
|-----------|--------------|
| Email sending | AWS SES via SMTP, domain rotation, Celery queue |
| Gmail sending | Gmail API (`gmail.send` + `gmail.readonly` scopes) |
| Receive (system) | Hostinger/IMAP — separate from send domain, can differ per rotation |
| Receive (user Gmail) | Gmail API reply fetch — already implemented |
| Reply tracking | Tracking token `ev=campaign_id\|lead_id\|user_id` embedded in HTML body |
| Inbox | Flat list of `EmailActivity` rows, sorted by reply status |
| Reply storage | Single reply per `EmailActivity` row (latest overwrites previous) |

### Key Files

```
backend/app/
├── models/
│   ├── email_activity.py       # Tracks sent emails + reply fields
│   └── mailbox.py              # SMTP send + IMAP receive credentials
├── tasks/
│   └── mail_job.py             # Celery task: send email + log EmailActivity
├── services/
│   ├── reply_fetch_service.py       # IMAP reply fetcher (system mailboxes)
│   ├── gmail_reply_fetch_service.py # Gmail API reply fetcher (user mailboxes)
│   └── inbox_service.py             # Current flat inbox query
├── utils/
│   └── email_sender.py         # Core send — sets Message-ID header
└── api/v1/
    └── inbox.py                # Current inbox endpoint
```

---

## Target Inbox Structure

```
INBOX
├── Hotels Outreach     50 sent · 3 replied · 1 unread   (last activity: 2h ago)
└── School Outreach    100 sent · 0 replied               (last activity: 1d ago)

── Inside "Hotels Outreach" ─────────────────────────────────────────────────────

  [Bulk Send]  "Hi, we help hotels grow revenue through..."  sent to 50 leads · 2 days ago

  ↳ john@hilton.com     "This sounds interesting, tell me more"    Jan 15 · [Reply]
  ↳ sarah@marriott.com  "We'd love a demo, when are you free?"     Jan 15 · [Reply]  ← UNREAD
  ↳ mike@hyatt.com      "Not interested at the moment, thanks"     Jan 14 · [Reply]

── When user clicks Reply for john@hilton.com ───────────────────────────────────

  Full conversation:

  [YOU → John]  "Hi John, we help hotels..."       Jan 13  outreach@hotel1.com
  [John → YOU]  "This sounds interesting..."       Jan 15  john@hilton.com
  [YOU → John]  "Great! Happy to schedule a call"  Jan 15  (composing...)  [Send]
```

---

## The Threading Problem

### Mailbox Mismatch

```
Campaign send:   outreach@hotel1.com  (AWS SES — domain rotation)
Reply-To header: inbox@hostinger.com  (IMAP receive mailbox — different provider)

Different leads may get emails from different send domains:
  Lead 1 ← hotel1.com  (Reply-To: receive1@hostinger.com)
  Lead 2 ← hotel2.com  (Reply-To: receive2@hostinger.com)
  Lead 3 ← hotel3.com  (Reply-To: receive3@hostinger.com)

All replies land in different IMAP inboxes.
User Gmail accounts: send from Gmail, replies go back to Gmail (no separate receive).
```

### Why Current Tracking Token is Fragile

The current approach embeds `ev=campaign_id|lead_id|user_id` in the email HTML body. The reply fetcher looks for this token in the quoted body of replies.

**Fails when:** Lead writes a fresh reply on mobile without quoting the original — no token in the reply body, message is silently skipped.

### Solution: Message-ID Already Contains the IDs

In `email_sender.py:73`, the Message-ID is generated as:

```python
message_id = f"<EV-{uuid.uuid4()}-{campaign_id}-{lead_id}@evecta>"
```

The `campaign_id` and `lead_id` are **embedded in the Message-ID itself**.

When a lead replies, their email client automatically sets:
```
In-Reply-To: <EV-{uuid}-{campaign_id}-{lead_id}@evecta>
```

We parse this header → extract `campaign_id` + `lead_id` directly, **no DB lookup, no quoting required, works on all email clients and devices**.

For multi-turn replies (user replies back → lead replies again), the user's reply uses the same Message-ID format:
```python
message_id = f"<EV-reply-{uuid.uuid4()}-{campaign_id}-{lead_id}@evecta>"
```
Still parseable at every step in the chain.

---

## Data Model Changes

### New Model 1: `EmailThread`

One per campaign. Created when the first email in the campaign is sent.

```python
class EmailThread(Base):
    __tablename__ = "email_threads"

    id            = UUID  (primary key)
    campaign_id   = UUID  (FK → campaigns.id, UNIQUE — one thread per campaign)
    user_id       = UUID  (FK → users.id)
    subject       = String   # Campaign email subject
    last_message_at = DateTime  # Latest activity across all leads
    total_recipients = Integer  # How many leads were emailed (incremented on each send)
    unread_reply_count = Integer (default 0)
    is_starred    = Boolean (default False)
    created_at    = DateTime
```

### New Model 2: `EmailMessage`

Individual messages within a thread — one row per outbound send, one row per inbound reply.

```python
class EmailMessage(Base):
    __tablename__ = "email_messages"

    id              = UUID (primary key)
    thread_id       = UUID (FK → email_threads.id)
    lead_id         = UUID (FK → leads.id)
    campaign_id     = UUID (FK → campaigns.id)

    direction       = Enum(OUTBOUND, INBOUND)
    sender_email    = String  # Our mailbox (OUTBOUND) or lead email (INBOUND)
    recipient_email = String  # Lead email (OUTBOUND) or our receive mailbox (INBOUND)
    body            = Text    # HTML for OUTBOUND, plain text for INBOUND

    # RFC822 threading headers
    message_id      = String  # Our Message-ID (OUTBOUND) or lead's Message-ID (INBOUND)
    in_reply_to     = String  # Set when replying
    references      = String  # Full header chain (space-separated message IDs)

    sent_at         = DateTime
    is_read         = Boolean (default True for OUTBOUND, False for INBOUND)
    mailbox_id      = UUID (FK → mailboxes.id, nullable)

    # Backward compatibility
    email_activity_id = UUID (FK → email_activities.id, nullable)
```

### Indexes

```sql
CREATE INDEX idx_email_messages_thread_lead ON email_messages (thread_id, lead_id);
CREATE INDEX idx_email_messages_message_id  ON email_messages (message_id);
CREATE INDEX idx_email_messages_in_reply_to ON email_messages (in_reply_to);
CREATE INDEX idx_email_threads_campaign     ON email_threads  (campaign_id);
CREATE INDEX idx_email_threads_user         ON email_threads  (user_id, last_message_at DESC);
```

### No Breaking Changes

`EmailActivity` is **not modified**. All existing tracking, analytics, open/click/bounce events continue working unchanged.

---

## Implementation Phases

---

### Phase 1 — Models + Migration

**Files to create:**
- `backend/app/models/email_thread.py`
- `backend/app/models/email_message.py`
- `backend/alembic/versions/xxxx_add_email_threads.py`

**Migration steps:**
1. Create `email_threads` table
2. Create `email_messages` table
3. Backfill: for each unique `campaign_id` in `email_activities`, insert one `EmailThread`
4. Backfill: for each `EmailActivity` row, insert one `EmailMessage(direction=OUTBOUND)`
5. For each `EmailActivity` where `replied=True`, insert one `EmailMessage(direction=INBOUND)`

---

### Phase 2 — Thread Creation on Send

**File to update:** `backend/app/tasks/mail_job.py`

After `send_campaign_email()` returns success, before `_mark_sent()`:

```python
# 1. Upsert EmailThread for this campaign (INSERT ... ON CONFLICT DO UPDATE)
thread = await upsert_email_thread(
    db=db,
    campaign_id=campaign.id,
    user_id=job.user_id,
    subject=personalized_subject,
)

# 2. Create OUTBOUND EmailMessage
db.add(EmailMessage(
    thread_id=thread.id,
    lead_id=lead.id,
    campaign_id=campaign.id,
    direction=MessageDirection.OUTBOUND,
    sender_email=result["sent_from"],
    recipient_email=lead.email,
    body=personalized_content_with_footer,
    message_id=result["message_id"],   # <EV-uuid-campaign_id-lead_id@evecta>
    sent_at=result["sent_at"],
    is_read=True,
    mailbox_id=mailbox.id,
    email_activity_id=new_activity.id,
))

# 3. Increment thread.total_recipients
await db.execute(
    update(EmailThread)
    .where(EmailThread.id == thread.id)
    .values(total_recipients=EmailThread.total_recipients + 1, last_message_at=now)
)
```

---

### Phase 3 — Reply Fetch Creates EmailMessage

**Files to update:**
- `backend/app/services/reply_fetch_service.py`
- `backend/app/services/gmail_reply_fetch_service.py`

#### Matching Priority

```
Priority 1 (NEW):  Parse In-Reply-To header
  → regex: r"<EV-[^-]+-([a-f0-9-]+)-([a-f0-9-]+)@evecta>"
  → extract campaign_id, lead_id directly
  → works even when lead doesn't quote the original email

Priority 2 (EXISTING): Tracking token in body
  → r"ev=([\w-]+)\|([\w-]+)\|([\w-]+)"
  → fallback when In-Reply-To is missing or malformed
```

#### On Match (both IMAP and Gmail)

```python
# 1. Find the thread
thread = await db.scalar(
    select(EmailThread).where(EmailThread.campaign_id == campaign_uuid)
)

# 2. Store the lead's Message-ID (for when user replies back)
lead_message_id = msg.get("Message-ID", "").strip()

# 3. Create INBOUND EmailMessage
db.add(EmailMessage(
    thread_id=thread.id,
    lead_id=lead_uuid,
    campaign_id=campaign_uuid,
    direction=MessageDirection.INBOUND,
    sender_email=msg.get("From", ""),
    recipient_email=receive_mailbox_email,
    body=clean_reply,
    message_id=lead_message_id,           # Lead's Message-ID (needed for our next reply)
    in_reply_to=msg.get("In-Reply-To", ""),
    sent_at=datetime.now(timezone.utc),
    is_read=False,
    mailbox_id=receive_mailbox.id,
    email_activity_id=activity.id,
))

# 4. Update thread metadata
await db.execute(
    update(EmailThread)
    .where(EmailThread.id == thread.id)
    .values(
        last_message_at=datetime.now(timezone.utc),
        unread_reply_count=EmailThread.unread_reply_count + 1,
    )
)

# 5. Still update EmailActivity (backward compat — analytics unchanged)
activity.replied = True
activity.replied_at = datetime.now(timezone.utc)
activity.reply_text = clean_reply
activity.replied_from = receive_mailbox_email
```

---

### Phase 4 — Reply From Inbox

**New file:** `backend/app/services/thread_reply_service.py`

#### Which Mailbox to Reply From

| Scenario | Reply mailbox |
|----------|--------------|
| System mailbox (SMTP/SES) | Find `Mailbox` where `receive_email == activity.replied_from` → use its SMTP credentials |
| User Gmail | Find `Mailbox` where `provider == GOOGLE` and `user_id == user_id` → use Gmail API |

#### Reply Flow

```python
async def send_thread_reply(
    thread_id: UUID,
    lead_id: UUID,
    user_id: UUID,
    reply_body: str,
    db: AsyncSession,
):
    # 1. Get thread + latest INBOUND message from this lead
    latest_inbound = await db.scalar(
        select(EmailMessage)
        .where(
            EmailMessage.thread_id == thread_id,
            EmailMessage.lead_id == lead_id,
            EmailMessage.direction == MessageDirection.INBOUND,
        )
        .order_by(EmailMessage.sent_at.desc())
        .limit(1)
    )

    # 2. Build References chain
    all_messages = await get_all_message_ids(db, thread_id, lead_id)
    references_chain = " ".join(m.message_id for m in all_messages if m.message_id)

    # 3. Generate our reply Message-ID (same parseable format)
    new_message_id = f"<EV-reply-{uuid4()}-{campaign_id}-{lead_id}@evecta>"

    # 4. Find reply mailbox
    reply_mailbox = await get_reply_mailbox(db, latest_inbound, user_id)

    # 5. Send email with proper threading headers
    result = await send_campaign_email(
        to_email=latest_inbound.sender_email,   # Reply to the lead
        subject=f"Re: {thread.subject}",
        html_content=reply_body,
        campaign_id=str(campaign_id),
        lead_id=str(lead_id),
        user_id=str(user_id),
        mailbox=reply_mailbox,
        extra_headers={
            "In-Reply-To": latest_inbound.message_id,
            "References": references_chain,
        },
        db=db,
    )

    # 6. Create OUTBOUND EmailMessage
    db.add(EmailMessage(
        thread_id=thread_id,
        lead_id=lead_id,
        direction=MessageDirection.OUTBOUND,
        sender_email=reply_mailbox.email,
        recipient_email=latest_inbound.sender_email,
        body=reply_body,
        message_id=new_message_id,
        in_reply_to=latest_inbound.message_id,
        references=references_chain,
        sent_at=datetime.now(timezone.utc),
        is_read=True,
        mailbox_id=reply_mailbox.id,
    ))

    # 7. Update thread
    await db.execute(
        update(EmailThread)
        .where(EmailThread.id == thread_id)
        .values(last_message_at=datetime.now(timezone.utc))
    )
```

---

### Phase 5 — New Inbox API

**File to update:** `backend/app/api/v1/inbox.py`

#### Endpoints

```
GET  /inbox/threads
     → Paginated list of EmailThread (one per campaign)
     → Response: id, campaign_name, last_message_at, total_recipients,
                 unread_reply_count, is_starred, last_reply_preview

GET  /inbox/threads/{thread_id}
     → Thread detail: only leads who have INBOUND messages
     → Grouped by lead: latest reply text, timestamp, is_read
     → Response: thread info + list of lead conversations

GET  /inbox/threads/{thread_id}/leads/{lead_id}
     → Full conversation for one lead (all OUTBOUND + INBOUND messages)
     → Sorted by sent_at ASC (chronological)
     → Marks all INBOUND messages as is_read=True

POST /inbox/threads/{thread_id}/leads/{lead_id}/reply
     → Body: { "message": "..." }
     → Calls thread_reply_service.send_thread_reply()
     → Returns: new EmailMessage

PATCH /inbox/threads/{thread_id}/read
     → Sets all INBOUND EmailMessage.is_read=True for this thread
     → Resets EmailThread.unread_reply_count=0

PATCH /inbox/threads/{thread_id}/star
     → Toggles EmailThread.is_starred

POST /inbox/sync
     → Triggers fetch_replies_for_user_mailboxes() for current user
     → Returns: { "synced_mailboxes": N, "new_replies": M }
```

#### Legacy Endpoint

`GET /inbox` (old flat list) — kept working, points to existing `inbox_service.py`.

---

### Phase 6 — Real-time Sync

#### Option A: Polling (Works Now, No Setup Required)

- `POST /inbox/sync` endpoint triggers on-demand fetch
- Existing 5-minute background scheduler continues running
- Frontend can call `/inbox/sync` when user opens inbox tab

#### Option B: Gmail Push Notifications (Real-time for Gmail Mailboxes)

Register Gmail push via `users.watch()` API when a Gmail mailbox is added:

```python
POST https://gmail.googleapis.com/gmail/v1/users/me/watch
{
  "topicName": "projects/{project}/topics/gmail-replies",
  "labelIds": ["INBOX"]
}
```

Google POSTs a notification to your webhook when new mail arrives:

```
POST /webhooks/gmail
Body: { "message": { "data": "<base64 encoded>" }, "subscription": "..." }
```

Webhook handler:
1. Decode notification → extract mailbox email
2. Find `Mailbox` with that email
3. Call `fetch_gmail_replies(db, mailbox)` immediately
4. New `EmailMessage` created → frontend polls `/inbox/threads`

**New file:** `backend/app/api/v1/webhook_gmail.py`
(Same pattern as existing `webhook_brevo.py`, `webhook_ses.py`)

---

## Full Change Summary

### New Files

| File | Purpose |
|------|---------|
| `models/email_thread.py` | EmailThread model |
| `models/email_message.py` | EmailMessage model + MessageDirection enum |
| `services/thread_reply_service.py` | Reply-from-inbox logic |
| `api/v1/webhook_gmail.py` | Gmail push notification handler (Phase 6B) |
| `schemas/thread.py` | Pydantic schemas for thread/message responses |
| `alembic/versions/xxxx_add_inbox_threading.py` | Migration |

### Modified Files

| File | Change |
|------|--------|
| `tasks/mail_job.py` | Upsert EmailThread + create OUTBOUND EmailMessage after send |
| `services/reply_fetch_service.py` | Add In-Reply-To parsing + create INBOUND EmailMessage |
| `services/gmail_reply_fetch_service.py` | Same |
| `api/v1/inbox.py` | Add new thread endpoints alongside legacy `/inbox` |
| `models/__init__.py` | Register new models |

### Unchanged Files (Zero Breaking Changes)

| File | Why unchanged |
|------|--------------|
| `models/email_activity.py` | Kept as-is, all analytics/tracking work |
| `utils/email_sender.py` | Message-ID format already correct |
| `services/inbox_service.py` | Legacy inbox kept working |
| `tasks/email_dispatcher.py` | No changes needed |
| `services/mailbox_selector_service.py` | No changes needed |

---

## Edge Cases & Decisions

### 1. Send Domain ≠ Receive Domain

**Not a problem.** `fetch_replies_for_all_mailboxes()` already checks ALL system IMAP mailboxes. Regardless of which Hostinger inbox receives the reply, we parse the `In-Reply-To` header to identify the thread — the receive mailbox is irrelevant for matching.

### 2. Lead Replies Without Quoting (Fresh Reply)

**Solved by In-Reply-To parsing.** Email clients always set `In-Reply-To` automatically, even when the user writes a fresh reply. The tracking token fallback is no longer the primary method.

### 3. Reply Mailbox for Sending Back

| Case | Mailbox used for reply |
|------|----------------------|
| System (SMTP/SES) send | `Mailbox` where `receive_email = activity.replied_from` — has SMTP credentials |
| User Gmail send | User's Gmail mailbox — send via Gmail API |
| No receive mailbox found | Use any available mailbox in rotation (last resort) |

### 4. Multi-turn Conversation Threading

```
Round 1:
  Our send:    Message-ID: <EV-uuid1-campaign_id-lead_id@evecta>
  Lead reply:  In-Reply-To: <EV-uuid1-...>  →  parsed → correct thread

Round 2 (user replies from inbox):
  Our reply:   Message-ID: <EV-reply-uuid2-campaign_id-lead_id@evecta>
               In-Reply-To: <lead's-message-id>
  Lead reply:  In-Reply-To: <EV-reply-uuid2-campaign_id-lead_id@evecta>  →  parsed → correct thread
```

Every outbound message uses the same parseable Message-ID format — the chain always stays intact.

### 5. User Gmail: No Separate Receive Mailbox

User Gmail accounts send and receive through the same Gmail address. The `gmail_reply_fetch_service.py` already fetches unread Gmail messages. No IMAP needed. Reply is sent back via Gmail API using the same mailbox.

### 6. Thread Already Exists (Campaign Sends More Emails Later)

`upsert_email_thread()` uses `INSERT ... ON CONFLICT (campaign_id) DO UPDATE` — safe to call on every job. Each new send just increments `total_recipients` and updates `last_message_at`.

---

## API Response Shapes

### `GET /inbox/threads`

```json
[
  {
    "id": "uuid",
    "campaign_id": "uuid",
    "campaign_name": "Hotels Outreach",
    "subject": "Hi {{ business_name }}, we help hotels...",
    "last_message_at": "2025-01-15T14:30:00Z",
    "total_recipients": 50,
    "replied_count": 3,
    "unread_reply_count": 1,
    "is_starred": false
  }
]
```

### `GET /inbox/threads/{thread_id}`

```json
{
  "id": "uuid",
  "campaign_name": "Hotels Outreach",
  "total_recipients": 50,
  "unread_reply_count": 1,
  "replies": [
    {
      "lead_id": "uuid",
      "lead_email": "john@hilton.com",
      "lead_name": "Hilton Hotels",
      "latest_reply": "This sounds interesting, tell me more",
      "replied_at": "2025-01-15T10:00:00Z",
      "is_read": true,
      "message_count": 3
    },
    {
      "lead_id": "uuid",
      "lead_email": "sarah@marriott.com",
      "lead_name": "Marriott",
      "latest_reply": "We'd love a demo",
      "replied_at": "2025-01-15T14:30:00Z",
      "is_read": false,
      "message_count": 2
    }
  ]
}
```

### `GET /inbox/threads/{thread_id}/leads/{lead_id}`

```json
{
  "lead_email": "john@hilton.com",
  "messages": [
    {
      "id": "uuid",
      "direction": "OUTBOUND",
      "sender_email": "outreach@hotel1.com",
      "body": "<div>Hi John, we help hotels...</div>",
      "sent_at": "2025-01-13T09:00:00Z",
      "is_read": true
    },
    {
      "id": "uuid",
      "direction": "INBOUND",
      "sender_email": "john@hilton.com",
      "body": "This sounds interesting, tell me more",
      "sent_at": "2025-01-15T10:00:00Z",
      "is_read": true
    }
  ]
}
```

---

## Implementation Order

```
Phase 1  →  Models + Migration            (foundation, nothing else can start without this)
Phase 2  →  Thread creation on send       (depends on Phase 1)
Phase 3  →  Reply fetch → EmailMessage    (depends on Phase 1)
Phase 4  →  Reply from inbox service      (depends on Phase 1 + 3)
Phase 5  →  New API endpoints             (depends on Phase 1 + 2 + 3 + 4)
Phase 6A →  /inbox/sync endpoint          (depends on Phase 5, minimal effort)
Phase 6B →  Gmail push notifications      (optional, depends on Phase 5)
```

Phases 2 and 3 can be developed in parallel after Phase 1 is done.
