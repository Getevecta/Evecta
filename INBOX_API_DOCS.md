# Inbox API Documentation

## Overview

The inbox system works like Gmail threads — one thread per campaign launch.

**3-Level Flow:**
```
Level 1: Inbox List        → list of campaigns (threads)
Level 2: Thread Detail     → list of leads who replied inside that campaign
Level 3: Lead Conversation → full back-and-forth messages with a specific lead
```

All endpoints require authentication via Bearer token.

---

## Base URL
```
/api/v1
```

## Authentication
```
Authorization: Bearer <jwt_token>
```

---

## Level 1 — Inbox Thread List

### `GET /inbox/threads`

Returns all campaign threads sorted by most recent activity.

**Query Params:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `page` | int | 1 | Page number |
| `per_page` | int | 20 | Items per page (max 100) |

**Response:** `200 OK`
```json
[
  {
    "id": "2b60f0ab-b9cd-444b-a31c-42e007cc94f3",
    "campaign_id": "e4f74150-1452-485f-906c-069d82a90fe9",
    "campaign_name": "Hotels Outreach",
    "subject": "Improving Efficiency for Sadhan.co",
    "last_message_at": "2026-03-03T13:10:59.474222Z",
    "total_recipients": 5,
    "replied_count": 2,
    "unread_reply_count": 1,
    "is_starred": false
  },
  {
    "id": "9a1c3f2b-...",
    "campaign_name": "School Outreach",
    "subject": "...",
    "last_message_at": "2026-03-02T10:00:00Z",
    "total_recipients": 3,
    "replied_count": 0,
    "unread_reply_count": 0,
    "is_starred": true
  }
]
```

**Field Guide:**
| Field | UI Usage |
|-------|----------|
| `campaign_name` | Thread title (e.g. "Hotels Outreach") |
| `total_recipients` | "Sent to X people" |
| `replied_count` | "X replied" badge |
| `unread_reply_count` | Unread badge count (bold thread if > 0) |
| `is_starred` | Star icon state |
| `last_message_at` | Timestamp shown in list |

**UI Notes:**
- Show thread as **bold/unread** if `unread_reply_count > 0`
- Show **no replies yet** state if `replied_count === 0` (thread still clickable)
- Sort is already by `last_message_at` desc (newest first)

---

## Level 2 — Thread Detail (Leads Who Replied)

### `GET /inbox/threads/{thread_id}`

Returns the campaign info + list of leads who have replied. Leads who never replied are NOT shown.

**Response:** `200 OK`
```json
{
  "id": "2b60f0ab-b9cd-444b-a31c-42e007cc94f3",
  "campaign_id": "e4f74150-1452-485f-906c-069d82a90fe9",
  "campaign_name": "Hotels Outreach",
  "subject": "Improving Efficiency for Sadhan.co",
  "total_recipients": 5,
  "unread_reply_count": 1,
  "is_starred": false,
  "replies": [
    {
      "lead_id": "8e74da45-8c12-408f-ae38-71fab9044cb4",
      "lead_email": "contact@hotel.com",
      "lead_name": "Grand Hotel",
      "lead_industry": "Hospitality",
      "lead_score": 85,
      "latest_reply": "Thanks for reaching out! I'm interested.",
      "replied_at": "2026-03-03T13:10:59Z",
      "is_read": false,
      "message_count": 3
    },
    {
      "lead_id": "32e544e9-...",
      "lead_email": "info@resort.com",
      "lead_name": "Mountain Resort",
      "lead_industry": "Tourism",
      "lead_score": 70,
      "latest_reply": "Sure, let's schedule a call.",
      "replied_at": "2026-03-02T09:00:00Z",
      "is_read": true,
      "message_count": 2
    }
  ]
}
```

**Field Guide:**
| Field | UI Usage |
|-------|----------|
| `replies` | List of leads who replied — each is a row in the thread |
| `latest_reply` | Message preview (snippet) |
| `is_read` | Bold row if `false` |
| `message_count` | "3 messages" label |
| `lead_score` | Score badge (0–100) |

**UI Notes:**
- If `replies` is empty → show "No replies yet" empty state
- Each reply row is clickable → navigates to Level 3 (lead conversation)
- Show lead name + email + industry + score in the row

---

## Level 3 — Lead Conversation (Full Messages)

### `GET /inbox/threads/{thread_id}/leads/{lead_id}`

Returns the full conversation with one specific lead (oldest → newest).
**Side effect:** automatically marks all unread messages from this lead as read, and recalculates `unread_reply_count` on the thread.

**Response:** `200 OK`
```json
{
  "lead_id": "8e74da45-8c12-408f-ae38-71fab9044cb4",
  "lead_email": "contact@hotel.com",
  "lead_name": "Grand Hotel",
  "messages": [
    {
      "id": "uuid",
      "direction": "OUTBOUND",
      "sender_email": "hello@yourdomain.com",
      "recipient_email": "contact@hotel.com",
      "body": "Hello Grand Hotel, I've been following your impressive...",
      "message_id": "<EV-...@evecta>",
      "sent_at": "2026-02-27T07:41:25Z",
      "is_read": true
    },
    {
      "id": "uuid",
      "direction": "INBOUND",
      "sender_email": "contact@hotel.com",
      "recipient_email": "mail@yourdomain.com",
      "body": "Thanks for reaching out! I'm interested.",
      "message_id": "<gmail-message-id@mail.gmail.com>",
      "sent_at": "2026-03-03T13:00:00Z",
      "is_read": true
    },
    {
      "id": "uuid",
      "direction": "OUTBOUND",
      "sender_email": "hello@yourdomain.com",
      "recipient_email": "contact@hotel.com",
      "body": "Great to hear! Let's schedule a call.",
      "sent_at": "2026-03-03T13:05:00Z",
      "is_read": true
    }
  ]
}
```

**Field Guide:**
| Field | UI Usage |
|-------|----------|
| `direction: "OUTBOUND"` | Message sent by YOU (align right, your color) |
| `direction: "INBOUND"` | Message sent by LEAD (align left, lead color) |
| `body` | Message content |
| `sender_email` | Show in message header |
| `sent_at` | Timestamp on each message |

**UI Notes:**
- Render like a chat view: OUTBOUND on right, INBOUND on left
- Show a **Reply** text box at the bottom of this view
- Messages are already in chronological order (oldest first)

---

## Reply to a Lead

### `POST /inbox/threads/{thread_id}/leads/{lead_id}/reply`

Send a reply to a specific lead. The system automatically picks the correct outbound mailbox.

**Request Body:**
```json
{
  "message": "Great to hear! Let's schedule a call for next week."
}
```

**Response:** `200 OK`
```json
{
  "id": "uuid",
  "message_id": "<EV-reply-...@evecta>",
  "sent_at": "2026-03-03T13:10:00Z",
  "sender_email": "hello@yourdomain.com",
  "recipient_email": "contact@hotel.com"
}
```

**UI Notes:**
- After success, append the new message to the conversation view immediately (optimistic update)
- Show error toast on failure
- The reply box should clear after sending

---

## Mark Thread as Read

### `PATCH /inbox/threads/{thread_id}/read`

Marks ALL replies in a thread as read and resets unread count to 0.

**Response:** `200 OK`
```json
{
  "id": "2b60f0ab-...",
  "unread_reply_count": 0
}
```

---

## Star / Unstar Thread

### `PATCH /inbox/threads/{thread_id}/star`

Toggles the star on a thread. Call once to star, call again to unstar.

**Response:** `200 OK`
```json
{
  "id": "2b60f0ab-...",
  "is_starred": true
}
```

---

## Manually Fetch New Replies

### `POST /inbox/fetch-replies`

Triggers an immediate IMAP/Gmail check for new replies. Call this when user clicks a "Refresh" button.

**Response:** `200 OK`
```json
{
  "status": "success",
  "replies_found": 5,
  "items": [ ... ]
}
```

**UI Notes:**
- Call this when user opens the inbox or clicks refresh
- The scheduler also runs this automatically in the background every few minutes
- After calling this, refetch `GET /inbox/threads` to show updated counts

---

## Error Responses

| Status | Meaning |
|--------|---------|
| `401` | Not authenticated — redirect to login |
| `403` | Thread belongs to another user |
| `404` | Thread or lead not found |
| `400` | Lead has not replied yet (can't reply to them) |
| `502` | Email sending failed (SMTP/Gmail error) |
| `503` | No mailbox available to send from |

---

## Recommended UI Flow

```
1. User opens Inbox
   → GET /inbox/fetch-replies   (trigger sync)
   → GET /inbox/threads          (render list)

2. User clicks a campaign thread
   → GET /inbox/threads/{thread_id}   (show replied leads)

3. User clicks a lead
   → GET /inbox/threads/{thread_id}/leads/{lead_id}   (show full conversation)
   → unread count auto-decrements

4. User types and sends reply
   → POST /inbox/threads/{thread_id}/leads/{lead_id}/reply
   → append new message to UI

5. User stars a thread
   → PATCH /inbox/threads/{thread_id}/star

6. User marks all read
   → PATCH /inbox/threads/{thread_id}/read
```

---

## Data Relationships

```
Campaign (1) ──── (1) EmailThread
EmailThread (1) ── (many) EmailMessage
EmailMessage.direction = "OUTBOUND" | "INBOUND"
EmailMessage.lead_id   = which lead this message is with
```

One thread per campaign. Messages inside are per-lead conversations.
## -------------------------------------------
Don't start polling /leads/leadlogs/{id} until you have a real UUID from the API response.

The frontend should:

Send the chat message → wait for the POST /chat response which returns the real lead_log_id (UUID)
Only then start polling /leads/leadlogs/{lead_log_id}
So the fix is — don't poll with temp-{timestamp} IDs at all. The temp ID should only be used locally in the frontend UI state, never sent to the backend.