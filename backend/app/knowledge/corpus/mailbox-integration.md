---
title: Connecting your mailbox
audience: customer
version: 2
last_reviewed: 2026-08-12
---

# Connecting your mailbox

## Can I connect my own mailbox to Evecta?

Yes.

## Why should I connect my mailbox?

It lets the user send campaigns from their chosen email account, receive replies, view conversations, and respond from inside Evecta.

## How many mailboxes can I connect?

Unlimited, for now.

## How much can I send from a connected mailbox?

Sending is capped at 50 successful campaign emails per UTC day, with at least 60 seconds between sends. This cap applies to every plan and to both your own connected mailboxes and Evecta's warmed addresses. Your plan's Outreach credit allowance is a separate limit, and both apply.

## Which mailbox providers and connection types are supported?

Evecta supports a Google/Gmail connection flow and a separate manual connection for other providers using IMAP for incoming mail and SMTP for outgoing mail.

## How do I choose the mailbox used for a campaign?

During campaign creation or setup, select one of the available connected or warmed mailboxes.

## Can I send campaigns without connecting my own mailbox?

Yes — Evecta's built-in warmed email addresses are available on all packages and can be used instead. How much you can send through them is bounded by your package's Outreach credit allowance. The daily sending cap is the same either way: 50 successful campaign emails per UTC day, with at least 60 seconds between sends, whether you send from your own mailbox or a warmed one.

## What is the difference between IMAP and SMTP?

IMAP is used to read and synchronize incoming messages and replies. SMTP is used to send outgoing messages. A mailbox can therefore send successfully while reply synchronization fails, or synchronize incoming mail while outgoing sending fails, if only one side is configured correctly.

## Does connecting a mailbox guarantee delivery?

No. A valid connection enables sending and synchronization, but delivery still depends on address quality, sender and domain reputation, SPF/DKIM/DMARC configuration, message content, recipient filtering, bounce and complaint rates, provider policies, and sending behaviour.
