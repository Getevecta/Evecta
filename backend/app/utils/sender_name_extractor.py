"""
Extract sender name or company name from email body content.
Used for campaign email footers so "You are receiving this email from X" shows
the name/company the user wrote in their signature instead of a generic brand.
"""
import html as html_module
import re


def extract_company_name_from_content(email_content: str) -> str | None:
    """
    Extract company name from email content by looking for common company name patterns.
    Returns the company name if found, None otherwise.
    """
    if not email_content:
        return None

    plain_text = re.sub(r'<[^>]+>', '', email_content)
    plain_text = html_module.unescape(plain_text)
    plain_text = plain_text.replace('\r\n', '\n').replace('\r', '\n')

    same_line_patterns = [
        r'(?:Best\s+regards|Regards|Sincerely|Thanks|Thank\s+you|Warm\s+regards|Kind\s+regards|With\s+warm\s+regards|Best)[,\s]+\s*([A-Za-z][a-z]+(?:\s+[A-Za-z][a-z]+)?)\s+([A-Z][A-Za-z0-9\s&.,-]{1,50}(?:Inc|LLC|Ltd|Corp|Corporation|Company|Co|Group|Solutions|Technologies|Systems)?)\s*$',
        r'(?:Best\s+regards|Regards|Sincerely|Thanks|Thank\s+you|Warm\s+regards|Kind\s+regards|With\s+warm\s+regards|Best)[,\s]*\n\s*([A-Za-z][a-z]+(?:\s+[A-Za-z][a-z]+)?)\s+([A-Z][A-Za-z0-9\s&.,-]{1,50}(?:Inc|LLC|Ltd|Corp|Corporation|Company|Co|Group|Solutions|Technologies|Systems)?)\s*$',
        r'(?:Best\s+regards|Regards|Sincerely|Thanks|Thank\s+you|Warm\s+regards|Kind\s+regards|With\s+warm\s+regards|Best)[,\s]*\n\s*([A-Za-z][a-z]+(?:\s+[A-Za-z][a-z]+)?)\s*\n\s*([A-Z][A-Za-z0-9\s&.,-]{1,50}(?:Inc|LLC|Ltd|Corp|Corporation|Company|Co|Group|Solutions|Technologies|Systems)?)\s*$',
    ]

    for pattern in same_line_patterns:
        match = re.search(pattern, plain_text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
        if match:
            company_name = match.group(2).strip()
            if len(company_name) >= 2 and len(company_name) <= 60:
                excluded = ['Best regards', 'Thank you', 'Hello', 'Hi', 'Dear', 'Sincerely', 'Regards']
                if company_name not in excluded and not company_name.lower().startswith(('best', 'thank', 'hello', 'hi', 'dear')):
                    return company_name

    signature_company_pattern = r'(?:Best\s+regards|Regards|Sincerely|Thanks|Thank\s+you|Warm\s+regards|Kind\s+regards|With\s+warm\s+regards|Best)[,\s]*\n\s*([A-Za-z][a-z]+(?:\s+[A-Za-z][a-z]+)?)\s*\n\s*([A-Z][A-Za-z0-9\s&.,-]{1,50}(?:Inc|LLC|Ltd|Corp|Corporation|Company|Co|Group|Solutions|Technologies|Systems)?)\s*$'
    match = re.search(signature_company_pattern, plain_text, re.IGNORECASE | re.MULTILINE)
    if match:
        company_name = match.group(2).strip()
        if len(company_name) >= 2 and len(company_name) <= 60:
            excluded = ['Best regards', 'Thank you', 'Hello', 'Hi', 'Dear', 'Sincerely', 'Regards']
            if company_name not in excluded and not company_name.lower().startswith(('best', 'thank', 'hello', 'hi', 'dear')):
                return company_name

    company_patterns = [
        r'(?:from|at|with|by)\s+([A-Z][A-Za-z0-9\s&.,-]{2,40}(?:Inc|LLC|Ltd|Corp|Corporation|Company|Co|Group|Solutions|Technologies|Systems)?)\b',
        r'([A-Z][A-Za-z0-9\s&.,-]{2,40}(?:Inc|LLC|Ltd|Corp|Corporation|Company|Co|Group|Solutions|Technologies|Systems)?)\s+(?:team|company|organization)',
        r'(?:our|my|the)\s+([A-Z][A-Za-z0-9\s&.,-]{2,40}(?:Inc|LLC|Ltd|Corp|Corporation|Company|Co|Group|Solutions|Technologies|Systems)?)',
    ]

    for pattern in company_patterns:
        match = re.search(pattern, plain_text, re.IGNORECASE)
        if match:
            company_name = match.group(1).strip()
            if len(company_name) >= 2 and len(company_name) <= 60:
                excluded = ['Best regards', 'Thank you', 'Hello', 'Hi', 'Dear', 'Sincerely', 'Regards']
                if company_name not in excluded and not company_name.lower().startswith(('best', 'thank', 'hello', 'hi', 'dear')):
                    return company_name

    sender_name_match = re.search(r'(?:Best\s+regards|Regards|Sincerely|Thanks|Thank\s+you|Warm\s+regards|Kind\s+regards|With\s+warm\s+regards|Best)[,\s]+\s*([A-Za-z][a-z]+(?:\s+[A-Za-z][a-z]+)?)', plain_text, re.IGNORECASE | re.MULTILINE)
    if sender_name_match:
        sender_name = sender_name_match.group(1)
        try:
            after_sender_pattern = rf'{re.escape(sender_name)}\s+([A-Z][A-Za-z0-9\s&.,-]{{1,50}})\s*$'
            match = re.search(after_sender_pattern, plain_text, re.IGNORECASE | re.MULTILINE)
            if match:
                potential_company = match.group(1).strip()
                if len(potential_company) >= 2 and len(potential_company) <= 60:
                    excluded = ['Best regards', 'Thank you', 'Hello', 'Hi', 'Dear', 'Sincerely', 'Regards']
                    if potential_company not in excluded and not potential_company.lower().startswith(('best', 'thank', 'hello', 'hi', 'dear')):
                        return potential_company
        except re.error:
            pass

    # Last 3 lines: only return a short, name-like line (never a sentence like "schedule. Best regards, Rabin")
    lines = plain_text.split('\n')
    for line in reversed(lines[-3:]):
        line = line.strip()
        if not line or len(line) > 40:
            continue
        if 'best' in line.lower() or 'regards' in line.lower() or ('.' in line and 'Inc' not in line and 'Ltd' not in line):
            continue
        if re.match(r'^[A-Z][A-Za-z0-9\s&.,-]+$', line):
            excluded = ['Best regards', 'Thank you', 'Hello', 'Hi', 'Dear', 'Sincerely', 'Regards', 'Manual Lead']
            if line not in excluded and not line.lower().startswith(('best', 'thank', 'hello', 'hi', 'dear')):
                if (any(suffix in line for suffix in ['Inc', 'LLC', 'Ltd', 'Corp', 'Company', 'Co', 'Group', 'Solutions', 'Technologies', 'Systems'])
                        or ' ' in line
                        or (len(line) >= 3 and line[0].isupper() and line.isalpha())):
                    return line

    return None


def _normalize_plain_text(html_or_plain: str) -> str:
    """Strip HTML, unescape, normalize whitespace and BOM for reliable regex matching."""
    if not html_or_plain:
        return ""
    text = re.sub(r'<[^>]+>', '', html_or_plain)
    text = html_module.unescape(text)
    text = text.strip().lstrip('\ufeff')
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def extract_sender_name_from_content(email_content: str) -> str | None:
    """
    Extract only the sender's name (e.g. "Rabin") after a closing like "Best regards,".
    Returns a single name (1-2 words, letters only), never phrases like "schedule. Best regards, Rabin".
    """
    if not email_content:
        return None

    plain_text = re.sub(r'<[^>]+>', '', email_content)
    plain_text = html_module.unescape(plain_text)
    plain_text = plain_text.strip().lstrip('\ufeff')
    # Normalize line endings so regex $ and \\n match correctly (e.g. content from server with \\r\\n)
    plain_text = plain_text.replace('\r\n', '\n').replace('\r', '\n')

    excluded = {'best', 'thank', 'hello', 'hi', 'dear', 'sincerely', 'regards', 'manual', 'lead', 'you', 'schedule'}

    # 1) Prefer: closing on its own line, then name on next line only (e.g. "Best regards,\n\nRabin")
    #    This avoids capturing body text that appears before the closing.
    name_on_next_line = re.search(
        r'(?:Best\s+regards|Regards|Sincerely|Thanks|Thank\s+you|Warm\s+regards|Kind\s+regards|With\s+warm\s+regards|Best)[,\s]*\n\s*\n\s*([A-Za-z][a-z]+(?:\s+[A-Za-z][a-z]+)?)\s*$',
        plain_text,
        re.IGNORECASE | re.MULTILINE,
    )
    if name_on_next_line:
        name = name_on_next_line.group(1).strip()
        name = re.sub(r'[.,;:]+$', '', name).strip()
        if 2 <= len(name) <= 50 and re.match(r'^[A-Za-z\s]+$', name) and name.lower() not in excluded:
            return name

    # 2) Same line: "Best regards, Rabin" at end (optional trailing whitespace)
    same_line_end = re.search(
        r'(?:Best\s+regards|Regards|Sincerely|Thanks|Thank\s+you|Warm\s+regards|Kind\s+regards|With\s+warm\s+regards|Best)[,\s]+\s*([A-Za-z][a-z]+(?:\s+[A-Za-z][a-z]+)?)\s*$',
        plain_text,
        re.IGNORECASE | re.MULTILINE,
    )
    if same_line_end:
        name = same_line_end.group(1).strip()
        name = re.sub(r'[.,;:]+$', '', name).strip()
        if 2 <= len(name) <= 50 and re.match(r'^[A-Za-z\s]+$', name) and name.lower() not in excluded:
            return name

    # 3) Single newline: "Best regards,\nRabin" at end
    single_newline = re.search(
        r'(?:Best\s+regards|Regards|Sincerely|Warm\s+regards|Kind\s+regards|Best)[,\s]*\n\s*([A-Za-z][a-z]+(?:\s+[A-Za-z][a-z]+)?)\s*$',
        plain_text,
        re.IGNORECASE | re.MULTILINE,
    )
    if single_newline:
        name = single_newline.group(1).strip()
        name = re.sub(r'[.,;:]+$', '', name).strip()
        if 2 <= len(name) <= 50 and re.match(r'^[A-Za-z\s]+$', name) and name.lower() not in excluded:
            return name

    # 4) Last "Best regards, Name" in text (only accept if name is 1-2 words, letters only)
    closing_no_eol = r'(?:Best\s+regards|Regards|Sincerely|Thanks|Thank\s+you|Warm\s+regards|Kind\s+regards|With\s+warm\s+regards|Best)[,\s]+\s*([A-Za-z][a-z]+(?:\s+[A-Za-z][a-z]+)?)(?=\s*$)'
    matches = list(re.finditer(closing_no_eol, plain_text, re.IGNORECASE | re.MULTILINE))
    if matches:
        name = matches[-1].group(1).strip()
        name = re.sub(r'[.,;:]+$', '', name).strip()
        if 2 <= len(name) <= 50 and re.match(r'^[A-Za-z\s]+$', name):
            if name.lower() not in excluded and not any(w in excluded for w in name.lower().split()):
                return name

    # 5) Last "Best regards, Name" anywhere in text (server content may have trailing space/newline/invisible chars)
    closing_anywhere = r'(?:Best\s+regards|Regards|Sincerely|Thanks|Thank\s+you|Warm\s+regards|Kind\s+regards|With\s+warm\s+regards|Best)[,\s]+\s*([A-Za-z][a-z]+(?:\s+[A-Za-z][a-z]+)?)\s*'
    matches_any = list(re.finditer(closing_anywhere, plain_text, re.IGNORECASE))
    if matches_any:
        name = matches_any[-1].group(1).strip()
        name = re.sub(r'[.,;:]+$', '', name).strip()
        if 2 <= len(name) <= 50 and re.match(r'^[A-Za-z\s]+$', name):
            if name.lower() not in excluded and not any(w in excluded for w in name.lower().split()):
                return name

    return None


def _is_valid_display_sender(name: str) -> bool:
    """
    Return True only if the string is a plausible sender/company name for the footer.
    Reject phrases like "you. Best regards, Sadhan" or single words like "you".
    """
    if not name or len(name) > 60:
        return False
    # Must be 1–3 words, letters (and allowed company chars). No sentence-like content.
    if re.search(r'\b(you|best|regards|thank|sincerely|hello|dear|schedule)\b', name, re.IGNORECASE):
        return False
    if '.' in name or '  ' in name:
        return False
    words = name.split()
    if len(words) > 3:
        return False
    if not all(re.match(r'^[A-Za-z][A-Za-z0-9&.,\'-]*$', w) for w in words):
        return False
    return True


def get_display_sender_from_content(email_content: str) -> str:
    """
    Get the best display name for the email footer from content.
    Priority: valid sender name (after "Best regards,") -> valid company name.
    Returns "Evecta Outreach" if nothing valid is found.
    """
    # Prefer sender name first (the name after "Best regards,") so we get "Sadhan" not "you. Best regards, Sadhan"
    sender = extract_sender_name_from_content(email_content)
    if sender and _is_valid_display_sender(sender):
        return sender
    company = extract_company_name_from_content(email_content)
    if company and _is_valid_display_sender(company):
        return company
    return "Evecta Outreach"
