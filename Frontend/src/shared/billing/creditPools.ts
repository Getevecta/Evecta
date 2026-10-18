import type { BillingCreditBalanceResponse, CreditPoolId } from '@/shared/services/api';

/** Display order matching backend POOLS. */
export const CREDIT_POOL_ORDER: CreditPoolId[] = ['lead', 'email_gen', 'outreach'];

/** UI labels for the Credits Usage design (maps to backend pools). */
export const CREDIT_POOL_UI_LABELS: Record<CreditPoolId, string> = {
  lead: 'Lead Search',
  email_gen: 'Spam check',
  outreach: 'Email Send',
};

export type CreditPoolBar = {
  pool: CreditPoolId;
  label: string;
  remaining: number;
  denominator: number;
  /** Fill % for “used” portion of the bar (0–100). */
  usedPct: number;
};

export function poolLabel(
  pool: CreditPoolId,
  fromApi?: string | null,
): string {
  const api = (fromApi || '').trim();
  if (api) return api;
  return CREDIT_POOL_UI_LABELS[pool];
}

export function getPoolRemaining(
  data: BillingCreditBalanceResponse | null | undefined,
  pool: CreditPoolId,
): number {
  const row = data?.pools?.[pool];
  if (row && typeof row.balance === 'number') return Math.max(0, row.balance);
  // Legacy single-balance response
  if (pool === 'lead' && typeof data?.balance === 'number') {
    return Math.max(0, data.balance);
  }
  return 0;
}

export function getPoolDenominator(
  data: BillingCreditBalanceResponse | null | undefined,
  pool: CreditPoolId,
  fallback = 1,
): number {
  const row = data?.pools?.[pool];
  if (row && typeof row.display_denominator === 'number' && row.display_denominator > 0) {
    return row.display_denominator;
  }
  if (pool === 'lead' && typeof data?.display_denominator === 'number' && data.display_denominator > 0) {
    return data.display_denominator;
  }
  return Math.max(1, fallback);
}

export function buildPoolBars(
  data: BillingCreditBalanceResponse | null | undefined,
): CreditPoolBar[] {
  return CREDIT_POOL_ORDER.map((pool) => {
    const rem = getPoolRemaining(data, pool);
    const denom = Math.max(getPoolDenominator(data, pool), 1);
    const consumed = Math.min(denom, Math.max(0, denom - rem));
    let usedPct = denom > 0 ? Math.min(100, (consumed / denom) * 100) : 0;
    if (consumed > 0 && usedPct > 0 && usedPct < 1) usedPct = 1;
    return {
      pool,
      label: poolLabel(pool, data?.pools?.[pool]?.label) || CREDIT_POOL_UI_LABELS[pool],
      remaining: rem,
      denominator: denom,
      usedPct,
    };
  });
}

/** Prefer design labels over short backend names when rendering usage UI. */
export function designPoolLabel(pool: CreditPoolId): string {
  return CREDIT_POOL_UI_LABELS[pool];
}
