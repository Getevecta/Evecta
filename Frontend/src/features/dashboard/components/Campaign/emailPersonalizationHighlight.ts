/**
 * Personalization variable highlighting — shared by CampaignEmailScreen (step 3)
 * and preview surfaces (step 5, modals) so {{ business_name }} etc. use the same colors.
 */

export const personalizationVariables = [
  { name: '{{ business_name }}', color: '#D97706' },
  { name: '{{ industry }}', color: '#3B82F6' },
  { name: '{{ address }}', color: '#059669' },
] as const;

/** Map common spellings to canonical `{{ name }}` form (same as step 3). */
export function normalizeVariables(content: string): string {
  if (!content) return content;

  const variableMap: Record<string, string> = {
    '{{businessname}}': '{{ business_name }}',
    '{{business name}}': '{{ business_name }}',
    '{{business_name}}': '{{ business_name }}',
    '{{ business_name }}': '{{ business_name }}',
    '{{ business name }}': '{{ business_name }}',
    '{{ businessname }}': '{{ business_name }}',
    '{{company_name}}': '{{ business_name }}',
    '{{companyname}}': '{{ business_name }}',
    '{{company name}}': '{{ business_name }}',
    '{{ company_name }}': '{{ business_name }}',
    '{{ companyname }}': '{{ business_name }}',
    '{{ company name }}': '{{ business_name }}',
    '{{CompanyName}}': '{{ business_name }}',
    '{{Company_Name}}': '{{ business_name }}',
    '{{Company Name}}': '{{ business_name }}',
    '{{ CompanyName }}': '{{ business_name }}',
    '{{ Company_Name }}': '{{ business_name }}',
    '{{ Company Name }}': '{{ business_name }}',
    '{{BusinessName}}': '{{ business_name }}',
    '{{Business_Name}}': '{{ business_name }}',
    '{{Business Name}}': '{{ business_name }}',
    '{{ BusinessName }}': '{{ business_name }}',
    '{{ Business_Name }}': '{{ business_name }}',
    '{{ Business Name }}': '{{ business_name }}',
    '{{Industry}}': '{{ industry }}',
    '{{INDUSTRY}}': '{{ industry }}',
    '{{industry}}': '{{ industry }}',
    '{{ Industry }}': '{{ industry }}',
    '{{ INDUSTRY }}': '{{ industry }}',
    '{{industry }}': '{{ industry }}',
    '{{ industry}}': '{{ industry }}',
    '{{Address}}': '{{ address }}',
    '{{ Address }}': '{{ address }}',
    '{{location}}': '{{ address }}',
    '{{ location }}': '{{ address }}',
    '{{Location}}': '{{ address }}',
    '{{ Location }}': '{{ address }}',
    '{{LOCATION}}': '{{ address }}',
    '{{ LOCATION }}': '{{ address }}',
    '{{location }}': '{{ address }}',
    '{{ location}}': '{{ address }}',
    '{{address}}': '{{ address }}',
    '{{ address }}': '{{ address }}',
  };

  let normalized = content;
  Object.keys(variableMap).forEach((variation) => {
    const regex = new RegExp(variation.replace(/[{}]/g, '\\$&'), 'gi');
    normalized = normalized.replace(regex, variableMap[variation]);
  });

  return normalized;
}

function escapeHtml(str: string): string {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

export function htmlToPlainTextWithBreaks(html: string): string {
  if (!html) return '';
  const withNewlines = html
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/div>\s*/gi, '\n')
    .replace(/<div[^>]*>/gi, '')
    .replace(/<\/p>\s*/gi, '\n')
    .replace(/<p[^>]*>/gi, '')
    .replace(/<\/li>\s*/gi, '\n')
    .replace(/<li[^>]*>/gi, '• ');
  const div = document.createElement('div');
  div.innerHTML = withNewlines;
  return div.textContent || div.innerText || '';
}

/** Plain text → HTML paragraphs for persisting edited lead email bodies. */
export function plainTextToHtmlParagraphs(text: string): string {
  if (!text) return '';
  return text
    .split(/\n+/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => `<p>${escapeHtml(line)}</p>`)
    .join('\n');
}

/**
 * Escape HTML, apply placeholder + variable spans (same colors/weights as step 3 contentEditable).
 */
export function highlightVariablesInText(text: string): string {
  if (!text) return '';

  let highlighted = escapeHtml(text);
  highlighted = highlighted.replace(/\n/g, '<br>');

  const placeholderColor = '#6B21A8';
  const placeholderRegex = /\[([^\]]+)\]/g;
  highlighted = highlighted.replace(
    placeholderRegex,
    `<span class="email-placeholder-token" style="color: ${placeholderColor}; font-weight: 600; background-color: #F3E8FF; padding: 2px 4px; border-radius: 3px;">[$1]</span>`
  );

  personalizationVariables.forEach((variable) => {
    const variableNameWithoutBraces = variable.name.replace(/[{}]/g, '').trim();
    const escapedVarName = variableNameWithoutBraces.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

    const singleBraceRegex = new RegExp(
      `\\{\\s*${escapedVarName}\\s*\\}(?!\\})`,
      'gi'
    );
    highlighted = highlighted.replace(
      singleBraceRegex,
      `{{ ${variableNameWithoutBraces} }}`
    );

    const doubleBraceRegex = new RegExp(
      `\\{\\{\\s*${escapedVarName}\\s*\\}\\}`,
      'gi'
    );

    highlighted = highlighted.replace(
      doubleBraceRegex,
      `<span class="email-personalization-variable" style="color: ${variable.color}; font-weight: 500;">${variable.name}</span>`
    );
  });

  return highlighted;
}

/**
 * Normalize + highlight for read-only preview (subject or body plain / HTML source).
 */
export function formatPreviewEmailHtml(raw: string): string {
  if (!raw?.trim()) return '';
  const normalized = normalizeVariables(raw);
  const plain =
    normalized.includes('<') && normalized.includes('>')
      ? htmlToPlainTextWithBreaks(normalized)
      : normalized;
  return highlightVariablesInText(plain);
}

export interface LeadPlaceholderData {
  business_name?: string | null;
  email?: string | null;
  address?: string | null;
  industry?: string | string[] | null;
  website?: string | null;
  contact_number?: string | null;
  first_name?: string | null;
  last_name?: string | null;
  job_title?: string | null;
}

function formatLeadFieldValue(value: unknown): string {
  if (value == null) return '';
  if (Array.isArray(value)) return value.filter(Boolean).join(', ');
  return String(value);
}

/** Replace `{{ business_name }}` etc. with a lead's values (matches backend send logic). */
export function replacePlaceholdersWithLead(
  template: string,
  lead: LeadPlaceholderData | null | undefined
): string {
  if (!template) return '';
  if (!lead) return template;

  let content = normalizeVariables(template);

  const fields: Record<string, string> = {
    business_name: formatLeadFieldValue(lead.business_name) || 'N/A',
    email: formatLeadFieldValue(lead.email) || 'N/A',
    address: formatLeadFieldValue(lead.address) || 'N/A',
    industry: formatLeadFieldValue(lead.industry) || 'N/A',
    website: formatLeadFieldValue(lead.website) || 'N/A',
    contact_number: formatLeadFieldValue(lead.contact_number) || 'N/A',
    first_name: formatLeadFieldValue(lead.first_name) || 'N/A',
    last_name: formatLeadFieldValue(lead.last_name) || 'N/A',
    job_title: formatLeadFieldValue(lead.job_title) || 'N/A',
  };

  for (const [attr, value] of Object.entries(fields)) {
    const regex = new RegExp(`\\{\\{\\s*${attr}\\s*\\}\\}`, 'gi');
    content = content.replace(regex, value);
  }

  return content;
}

/** Plain or HTML email source → preview HTML with paragraph spacing. */
function contentToPreviewParagraphsHtml(source: string): string {
  const plain =
    source.includes('<') && source.includes('>')
      ? htmlToPlainTextWithBreaks(source)
      : source;

  return plain
    .split(/\n+/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => `<p>${escapeHtml(line)}</p>`)
    .join('');
}

function contentToPreviewInlineHtml(source: string): string {
  const plain =
    source.includes('<') && source.includes('>')
      ? htmlToPlainTextWithBreaks(source)
      : source;
  return escapeHtml(plain.replace(/\s+/g, ' ').trim());
}

/**
 * Preview with first lead's data when available; otherwise highlight variables.
 */
export function formatPersonalizedPreviewEmailHtml(
  raw: string,
  lead?: LeadPlaceholderData | null,
  options?: { multiline?: boolean }
): string {
  if (!raw?.trim()) return '';

  const source = lead ? replacePlaceholdersWithLead(raw, lead) : normalizeVariables(raw);

  if (lead) {
    return options?.multiline === false
      ? contentToPreviewInlineHtml(source)
      : contentToPreviewParagraphsHtml(source);
  }

  const plain =
    source.includes('<') && source.includes('>')
      ? htmlToPlainTextWithBreaks(source)
      : source;
  return highlightVariablesInText(plain);
}

function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function plainFromEmailSource(raw: string): string {
  if (!raw) return '';
  return raw.includes('<') && raw.includes('>')
    ? htmlToPlainTextWithBreaks(raw)
    : raw;
}

/** Lead field values that may appear in a generated per-lead email. */
export function leadPersonalizationValues(lead: LeadPlaceholderData | null | undefined): string[] {
  if (!lead) return [];
  const values = [
    formatLeadFieldValue(lead.business_name),
    formatLeadFieldValue(lead.address),
    formatLeadFieldValue(lead.industry),
    formatLeadFieldValue(lead.email),
    formatLeadFieldValue(lead.website),
    formatLeadFieldValue(lead.contact_number),
    formatLeadFieldValue(lead.first_name),
    formatLeadFieldValue(lead.last_name),
    formatLeadFieldValue(lead.job_title),
  ];
  return [...new Set(values.map((v) => v.trim()).filter((v) => v.length >= 3))].sort(
    (a, b) => b.length - a.length,
  );
}

const PREVIEW_HIGHLIGHT_OPEN =
  '<span class="cle-preview-highlight" style="color:#6B21A8;font-weight:600;background-color:#F3E8FF;padding:1px 4px;border-radius:3px;">';
const PREVIEW_HIGHLIGHT_CLOSE = '</span>';

/** Highlight lead-specific values and any remaining placeholders in preview text. */
export function highlightLeadEmailPreviewLine(
  raw: string,
  lead: LeadPlaceholderData | null | undefined,
): string {
  const plain = plainFromEmailSource(raw).trim();
  if (!plain) return '';

  let html = escapeHtml(plain);

  for (const value of leadPersonalizationValues(lead)) {
    const regex = new RegExp(escapeRegex(value), 'gi');
    html = html.replace(regex, `${PREVIEW_HIGHLIGHT_OPEN}$&${PREVIEW_HIGHLIGHT_CLOSE}`);
  }

  const placeholderRegex = /\[([^\]]+)\]/g;
  html = html.replace(
    placeholderRegex,
    `${PREVIEW_HIGHLIGHT_OPEN}[$1]${PREVIEW_HIGHLIGHT_CLOSE}`,
  );

  return html;
}

export function formatLeadEmailPreviewSubjectHtml(
  raw: string,
  lead: LeadPlaceholderData | null | undefined,
): string {
  return highlightLeadEmailPreviewLine(raw, lead);
}

export function formatLeadEmailPreviewBodyHtml(
  raw: string,
  lead: LeadPlaceholderData | null | undefined,
): string {
  const plain = plainFromEmailSource(raw);
  return plain
    .split(/\n+/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => `<p>${highlightLeadEmailPreviewLine(line, lead)}</p>`)
    .join('');
}

export function countEmailWords(raw: string): number {
  const plain = plainFromEmailSource(raw);
  if (!plain.trim()) return 0;
  return plain.trim().split(/\s+/).filter(Boolean).length;
}

export function countFilledLeadVariables(
  subject: string,
  body: string,
  lead: LeadPlaceholderData | null | undefined,
): number {
  const combined = `${plainFromEmailSource(subject)} ${plainFromEmailSource(body)}`.toLowerCase();
  if (!combined.trim() || !lead) return 0;
  return leadPersonalizationValues(lead).filter((value) =>
    combined.includes(value.toLowerCase()),
  ).length;
}
