---
title: Mailbox setup and connection troubleshooting
audience: customer
version: 1
last_reviewed: 2026-08-12
---

# Mailbox setup and connection troubleshooting

## Where do I add a new mailbox?

Open Email Accounts and choose Add Email Account. A mailbox can also be added or selected during the campaign mailbox-selection step. Choose Google/Gmail for the Google authorization flow, or Any Provider (IMAP/SMTP) for manual server configuration.

## How do I connect a Google or Gmail mailbox?

1. Select Google/Gmail and continue to Google.
2. Choose the intended Google account.
3. Review the requested access and grant the permissions Evecta needs.
4. After Google returns you to Evecta, confirm the mailbox appears in Email Accounts as connected.

Google authorization is used instead of entering the Google password into Evecta.

## Why did the Google or Gmail connection fail?

Confirm that the correct Google account was selected and that the authorization was not cancelled. Grant all permissions required for sending and mailbox synchronization. If the connection was previously working, the authorization may have expired or been revoked. Retry the Google connection; if it still fails, check whether the Google account or organization administrator blocks third-party access.

## How do I manually connect an SMTP provider or another mailbox provider?

Select Any Provider (IMAP/SMTP). Enter the incoming IMAP host, IMAP port, IMAP username, and IMAP password. Then enter the outgoing SMTP host, SMTP port, SMTP username, and SMTP password. Use the exact server, port, encryption, and authentication details supplied by the mailbox provider. Do not guess settings from another provider.

## Where can I find my IMAP and SMTP settings?

Check the official help or administrator documentation for the mailbox provider or hosting company. Obtain the IMAP and SMTP host names, ports, SSL/TLS requirements, username format, authentication requirements, and whether an app password is required. For a company-managed mailbox, ask the email administrator.

## Should I use my normal mailbox password or an app password?

Follow the provider's requirements. Accounts protected by two-factor authentication commonly require a provider-generated app password for manual IMAP/SMTP access. If the provider requires an app password, the normal login password will fail. Never paste either password into an Evecta support message.

## Why does Evecta say my IMAP or SMTP username or password is incorrect?

Re-enter the full mailbox address when the provider uses it as the username, verify there are no copied spaces, and confirm whether an app password is required. Also check that IMAP/SMTP access is enabled and that the provider has not blocked the sign-in as suspicious. Generate a new app password when an existing one was revoked or expired.

## Why can Evecta not reach the IMAP or SMTP server?

Check the host name, port, and required SSL/TLS configuration against the provider's current documentation. The service may also be temporarily unavailable, blocked by a provider policy, firewall, or organization administrator, or affected by a DNS or network timeout. Retry after confirming the official settings.

## What should I do if IMAP is disabled?

Enable IMAP access in the provider or administrator settings if the provider allows it. Some organizations disable IMAP or third-party mailbox access centrally; in that case, the organization administrator must permit it or provide another supported connection method.

## What should I do if SMTP authentication is disabled?

Enable authenticated SMTP if the provider and organization policy allow it, then verify the SMTP username, password or app password, port, and encryption method. If an administrator controls the mailbox, ask them whether authenticated SMTP is permitted.

## How do I confirm that a newly connected mailbox works?

Confirm that the mailbox is listed as connected, select it for a draft campaign, and send a personalized test email to your own address. Verify the sender, subject, content, links, and delivery. Then confirm that mailbox synchronization is active so campaign replies can appear in the Unified Inbox. A successful test email checks sending but does not by itself prove that incoming reply synchronization works.

## Why can I send email but not see replies in the Unified Inbox?

The SMTP or Google sending connection may be working while incoming synchronization is delayed or unavailable. Check the IMAP connection or Google authorization, confirm the reply was sent to the same connected address, and look for provider filtering. Reconnect the mailbox if authorization or credentials changed. Allow time for synchronization, then contact support if the reply still does not appear.

## Why can I see incoming mail but campaign emails will not send?

Incoming IMAP synchronization may be working while SMTP sending is failing. Verify SMTP host, port, encryption, authentication, password or app password, provider sending restrictions, campaign readiness, Outreach credits, daily capacity, and mailbox connection status.

## Why is my mailbox not connecting?

Possible causes: incorrect login details, incorrect SMTP/IMAP settings, missing permissions, two-factor authentication, app-password requirements, provider security restrictions, disabled third-party access, or expired authorization. Verify provider settings and reconnect.

## What should I do if a connected mailbox becomes disconnected?

Open Email Accounts and reconnect it using the same connection type. For Google/Gmail, repeat Google authorization and grant the required permissions. For manual IMAP/SMTP, verify current server settings and replace changed or expired credentials. Reconnection may be necessary after a password change, app-password revocation, security-policy change, or authorization expiry.

## Can I remove a mailbox and add it again?

Yes. Use the mailbox management controls in Email Accounts to remove or disconnect the mailbox, then add it again with the correct Google authorization or IMAP/SMTP settings. Before removing a mailbox, check whether it is selected by a draft or ongoing campaign so campaign sending or reply context is not disrupted.

## Why is a connected mailbox not available when I create a campaign?

Refresh the mailbox list and confirm that the account is connected and eligible for sending. Check whether campaign setup is using the intended sending mode and whether the connection finished successfully. Reconnect the mailbox if it is marked disconnected; contact support if it remains missing.

## What information should I send to support about a mailbox problem?

Email contact@evecta.io with the mailbox provider, connection type (Google or IMAP/SMTP), the exact non-secret error message, the affected Evecta screen or campaign, and the approximate failure time and time zone. A screenshot is useful if it contains no credentials or tokens. Never include passwords, app passwords, authorization codes, or recovery codes.
