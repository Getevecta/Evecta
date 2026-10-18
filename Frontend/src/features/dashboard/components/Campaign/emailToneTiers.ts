/** Helpers for backend-driven email tone tiers (see GET /personalization/capabilities). */

export interface ToneCardOption {
  id: string;
  label: string;
  description: string;
}

export interface ToneTierGroup {
  tierPlan: string;
  tierLabel: string;
  minPlan: string;
  minPlanRank: number;
  unlocked: boolean;
  badge: string;
  tones: ToneCardOption[];
}

export function mapApiToneTiers(
  tiers: Array<{
    tier_plan: string;
    tier_label: string;
    min_plan: string;
    min_plan_rank: number;
    unlocked: boolean;
    badge: string;
    tones: ToneCardOption[];
  }> | undefined,
): ToneTierGroup[] {
  if (!tiers?.length) return [];
  return tiers.map((tier) => ({
    tierPlan: tier.tier_plan,
    tierLabel: tier.tier_label,
    minPlan: tier.min_plan,
    minPlanRank: tier.min_plan_rank,
    unlocked: tier.unlocked,
    badge: tier.badge,
    tones: tier.tones,
  }));
}

export function isToneUnlocked(tier: ToneTierGroup): boolean {
  return tier.unlocked;
}

/** When the same backend tone id appears in multiple tiers (e.g. partnership-focused). */
export function isToneCardSelected(
  toneId: string,
  tierPlan: string,
  selectedToneId: string,
  selectedTierPlan?: string,
): boolean {
  if (selectedToneId !== toneId) return false;

  // Same tone id can appear in multiple tiers (e.g. Consultative vs Strategic).
  if (toneId === 'partnership-focused') {
    if (!selectedTierPlan) return false;
    return tierPlan === selectedTierPlan;
  }

  return true;
}

/** Which tier card should show as selected for a stored tone id (e.g. after draft load). */
export function defaultTierPlanForTone(
  toneId: string,
  userPlan: string,
  tiers: ToneTierGroup[],
): string | undefined {
  if (toneId === 'partnership-focused') {
    const plan = userPlan.trim().toLowerCase();
    if (plan === 'scale' && tiers.some((t) => t.tierPlan === 'scale' && t.unlocked)) {
      return 'scale';
    }
    if (tiers.some((t) => t.tierPlan === 'growth' && t.unlocked)) {
      return 'growth';
    }
  }
  return findTierForTone(tiers, toneId)?.tierPlan;
}

export function findTierForTone(
  tiers: ToneTierGroup[],
  toneId: string,
): ToneTierGroup | undefined {
  return tiers.find((tier) => tier.tones.some((tone) => tone.id === toneId));
}

export function firstUnlockedToneId(tiers: ToneTierGroup[]): string | undefined {
  for (const tier of tiers) {
    if (!tier.unlocked) continue;
    const first = tier.tones[0];
    if (first) return first.id;
  }
  return undefined;
}
