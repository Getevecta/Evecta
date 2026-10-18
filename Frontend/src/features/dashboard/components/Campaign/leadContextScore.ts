/** Mirrors backend personalization_service.score_lead_context */

export type LeadContextScore = 'full' | 'partial' | 'none';

export interface LeadContextInput {
  services?: string | null;
  website_summary?: string | null;
  business_description?: string | null;
}

function nonEmpty(value: string | null | undefined): boolean {
  return Boolean(value && String(value).trim());
}

export function scoreLeadContext(lead: LeadContextInput): LeadContextScore {
  const present = [
    lead.website_summary,
    lead.business_description,
    lead.services,
  ].filter(nonEmpty).length;

  if (present >= 3) return 'full';
  if (present >= 1) return 'partial';
  return 'none';
}

export const CONTEXT_SCORE_LABELS: Record<LeadContextScore, string> = {
  full: 'Rich context',
  partial: 'Partial context',
  none: 'Thin context',
};

export const CONTEXT_SCORE_HINTS: Record<LeadContextScore, string> = {
  full: 'All enrichment fields available — deepest personalization when your plan allows.',
  partial: 'Some website context found — standard personalization depth.',
  none: 'No scraped context — email will use basic mail-merge and sender profile.',
};
