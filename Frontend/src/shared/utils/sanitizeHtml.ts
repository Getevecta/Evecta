import DOMPurify from 'dompurify';

/**
 * Sanitize untrusted HTML (e.g. inbound email bodies) before dangerouslySetInnerHTML.
 * Strips scripts, event handlers, and dangerous URI schemes (javascript:, data:, etc.).
 */
const EMAIL_HTML_PURIFY: DOMPurify.Config = {
  USE_PROFILES: { html: true },
  FORBID_TAGS: [
    'script',
    'iframe',
    'object',
    'embed',
    'form',
    'base',
    'link',
    'meta',
    'svg',
    'math',
    'video',
    'audio',
    'source',
  ],
  ALLOW_DATA_ATTR: false,
  // Allow common email / web link schemes only — blocks javascript:, data:, vbscript:, etc.
  ALLOWED_URI_REGEXP:
    /^(?:(?:(?:f|ht)tps?|mailto|tel|cid):|[^a-z]|[a-z+.\-]+(?:[^a-z+.\-:]|$))/i,
};

export function sanitizeEmailHtml(dirty: string): string {
  if (!dirty) return '';
  return DOMPurify.sanitize(dirty, EMAIL_HTML_PURIFY);
}
