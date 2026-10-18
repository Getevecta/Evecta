---
title: Sending limits and campaign delivery pace
audience: customer
version: 1
last_reviewed: 2026-08-12
---

# Sending limits and campaign delivery pace

## What are the daily sending limit and send interval?

Each user can send up to 50 successful campaign emails per UTC day, and Evecta spaces sends by at least 60 seconds. Failed attempts do not count as successful sends.

## Why did some campaign emails move to the next day?

Emails are queued to protect sending health and enforce capacity. Once the user reaches 50 successful sends in the current UTC day, remaining queued emails wait for the next UTC day. The 60-second spacing also means a larger campaign is delivered gradually rather than all at once.

## Why is my campaign sending slowly?

Evecta intentionally spaces campaign sends by at least 60 seconds and caps each user at 50 successful campaign emails per UTC day. Provider restrictions, temporary failures, campaign queue processing, and mailbox availability can extend completion time further.

## Why does an Ongoing campaign take more than one day?

A campaign with more than 50 leads cannot finish in a single day. Evecta sends at least 60 seconds apart and caps each user at 50 successful campaign emails per UTC day, so remaining jobs stay queued for the next UTC day until the campaign completes.

## Why is a scheduled campaign delayed?

Possible causes: the daily sending cap was reached, mailbox limits, sending intervals, provider restrictions, campaign queue processing, or a disconnected mailbox.

## Why is my campaign not sending?

Check mailbox connection, campaign schedule, available Outreach credits, sending limits, campaign status, email draft status, Spam Check requirements, and provider restrictions.
