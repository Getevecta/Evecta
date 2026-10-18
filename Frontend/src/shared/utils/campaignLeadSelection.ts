/**
 * Shared Create Campaign lead preselection.
 * All entry points (AI Lead Gen, Lead Database, Lead Log) must use these helpers
 * so Step 2 always receives the same Lead Database UUIDs.
 */

export const PRESELECTED_LEAD_IDS_KEY = 'preselectedLeadIds';
export const CAMPAIGN_LEAD_IDS_KEY = 'campaignLeadIds';

function uniqueIds(leadIds: string[]): string[] {
  return Array.from(new Set(leadIds.map(String).filter(Boolean)));
}

/** Persist selected Lead Database UUIDs for the Create Campaign wizard. */
export function persistCampaignLeadSelection(leadIds: string[]): string[] {
  const ids = uniqueIds(leadIds);
  if (ids.length === 0) {
    clearCampaignLeadSelection();
    return [];
  }
  sessionStorage.setItem(PRESELECTED_LEAD_IDS_KEY, JSON.stringify(ids));
  sessionStorage.setItem(CAMPAIGN_LEAD_IDS_KEY, JSON.stringify(ids));
  return ids;
}

export function clearCampaignLeadSelection(): void {
  sessionStorage.removeItem(PRESELECTED_LEAD_IDS_KEY);
  sessionStorage.removeItem(CAMPAIGN_LEAD_IDS_KEY);
}

/**
 * Read preselected Lead Database UUIDs from either storage key.
 * Used by Dashboard + CreateCampaign so no entry point is missed.
 */
export function readCampaignLeadSelection(): string[] | undefined {
  for (const key of [PRESELECTED_LEAD_IDS_KEY, CAMPAIGN_LEAD_IDS_KEY]) {
    const raw = sessionStorage.getItem(key);
    if (!raw) continue;
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) {
        return uniqueIds(parsed);
      }
    } catch {
      // ignore invalid JSON and try the other key
    }
  }
  return undefined;
}

/** Resolve props first, then sessionStorage — never lose a selection mid-navigation. */
export function resolveCampaignLeadSelection(
  propIds?: string[] | null,
): string[] | undefined {
  if (Array.isArray(propIds) && propIds.length > 0) {
    return uniqueIds(propIds);
  }
  return readCampaignLeadSelection();
}
