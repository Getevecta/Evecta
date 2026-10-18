import { useCallback, useEffect, useMemo, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import {
  apiService,
  type BillingCreditBalanceResponse,
  type BillingTopupPoolOption,
  type CreditPoolId,
} from '@/shared/services/api';
import {
  CREDIT_POOL_ORDER,
  buildPoolBars,
  designPoolLabel,
} from '@/shared/billing/creditPools';
import { Button } from '../ui/button';
import { cn } from '../ui/utils';
import './SpendingSection.css';

const CREDITS_COIN_SRC = `${import.meta.env.BASE_URL}coin_img01%202.png`;

/** Slider section labels matching the Additional Credits design. */
const SLIDER_POOL_LABELS: Record<CreditPoolId, string> = {
  lead: 'Lead Search Credits',
  email_gen: 'Spam Check Credits',
  outreach: 'Email Outreach Credits',
};

const EMPTY_AMOUNTS: Record<CreditPoolId, number> = {
  lead: 0,
  email_gen: 0,
  outreach: 0,
};

function formatMoney(n: number): string {
  return n.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

function formatTickLabel(n: number): string {
  if (n >= 1_000_000) {
    const m = n / 1_000_000;
    return Number.isInteger(m) ? `${m}M` : `${parseFloat(m.toFixed(1))}M`;
  }
  return n.toLocaleString();
}

function allowancePossessive(interval: 'month' | 'year' | null | undefined): string {
  if (interval === 'year') return "year's";
  if (interval === 'month') return "month's";
  return "period's";
}

/** Normalize a raw range value: below plan min ⇒ 0 (nothing chosen). */
function normalizeSliderCredits(raw: number, min: number, max: number, step: number): number {
  if (!Number.isFinite(raw) || raw <= 0 || max < min || min <= 0) return 0;
  if (raw < min) return 0;
  const snapped = Math.round(raw / step) * step;
  return Math.min(max, Math.max(min, snapped));
}

/** Scale ticks from real plan range: 0 → max (linear, aligned to slider). */
function buildPoolSliderTicks(
  min: number,
  max: number,
  step: number,
): { value: number; label: string; pct: number }[] {
  if (max <= 0) {
    return [{ value: 0, label: '0', pct: 0 }];
  }

  const safeStep = Math.max(1, step);
  const candidates = [0, max / 3, (2 * max) / 3, max].map((raw, index) => {
    if (index === 0) return 0;
    if (index === 3) return max;
    let snapped = Math.round(raw / safeStep) * safeStep;
    if (snapped <= 0) snapped = Math.min(min, max);
    if (snapped >= max) snapped = Math.max(max - safeStep, min > 0 ? min : safeStep);
    return Math.min(max, Math.max(0, snapped));
  });

  const unique = [...new Set(candidates)].sort((a, b) => a - b);
  return unique.map((value) => ({
    value,
    label: formatTickLabel(value),
    pct: Math.min(100, Math.max(0, (value / max) * 100)),
  }));
}

export type SpendingSectionProps = {
  /** Renders Credit usage hero (Settings → Usage page). Uses subscription billing interval for copy. */
  includeUsageHero?: boolean;
};

export function SpendingSection({ includeUsageHero = false }: SpendingSectionProps) {
  const [loading, setLoading] = useState(true);
  const [balanceData, setBalanceData] = useState<BillingCreditBalanceResponse | null>(null);
  const [topupMin, setTopupMin] = useState(100);
  const [topupStep, setTopupStep] = useState(100);
  const [poolOptions, setPoolOptions] = useState<BillingTopupPoolOption[]>([]);
  const [topupAvailable, setTopupAvailable] = useState(true);
  const [topupUnavailableReason, setTopupUnavailableReason] = useState<string | null>(null);
  const [planBillingInterval, setPlanBillingInterval] = useState<'month' | 'year' | null>(null);

  const [amounts, setAmounts] = useState<Record<CreditPoolId, number>>(EMPTY_AMOUNTS);
  const [checkoutBusy, setCheckoutBusy] = useState(false);

  const refresh = useCallback(async () => {
    const [balRes, subRes, optRes] = await Promise.all([
      apiService.getBillingCreditBalance(),
      apiService.getBillingSubscription(),
      apiService.getBillingTopupOptions(),
    ]);

    if (balRes.data) setBalanceData(balRes.data);

    const sub = subRes.data;
    setPlanBillingInterval(sub?.plan_billing_interval ?? null);

    if (optRes.data) {
      setTopupMin(optRes.data.min || 100);
      setTopupStep(optRes.data.step || 100);
      setTopupAvailable(optRes.data.available !== false);
      setTopupUnavailableReason(optRes.data.reason ?? null);

      if (optRes.data.pools && optRes.data.pools.length > 0) {
        setPoolOptions(optRes.data.pools);
      } else {
        const max = optRes.data.max ?? 0;
        const rate = optRes.data.price_per_credit ?? 0;
        setPoolOptions(
          CREDIT_POOL_ORDER.map((pool) => ({
            pool,
            label: designPoolLabel(pool),
            price_per_credit: rate,
            max: pool === 'lead' ? max : 0,
          })),
        );
      }
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        await refresh();
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  const poolBars = useMemo(
    () =>
      buildPoolBars(balanceData).map((b) => ({
        ...b,
        label: designPoolLabel(b.pool),
      })),
    [balanceData],
  );

  /** Always all three pools in one summary card (matches design). */
  const lineItems = useMemo(() => {
    return CREDIT_POOL_ORDER.map((pool) => {
      const opt = poolOptions.find((p) => p.pool === pool);
      const credits = amounts[pool] ?? 0;
      const rate = opt?.price_per_credit ?? 0;
      return {
        pool,
        credits,
        price: credits > 0 ? credits * rate : 0,
        label: SLIDER_POOL_LABELS[pool],
      };
    });
  }, [amounts, poolOptions]);

  const totalUsd = useMemo(() => {
    const sum = lineItems.reduce((acc, row) => acc + row.price, 0);
    return sum;
  }, [lineItems]);

  const hasSelection = lineItems.some((row) => row.credits > 0);

  const setPoolCredits = (pool: CreditPoolId, credits: number) => {
    setAmounts((prev) => ({ ...prev, [pool]: credits }));
  };

  const startCheckout = async () => {
    if (!topupAvailable) {
      toast.error(topupUnavailableReason || 'Top-up is not available on your plan.');
      return;
    }
    if (!hasSelection) {
      toast.error('Adjust a slider to choose credits before checkout.');
      return;
    }
    setCheckoutBusy(true);
    try {
      const payload: Partial<Record<CreditPoolId, number>> = {
        lead: amounts.lead || 0,
        email_gen: amounts.email_gen || 0,
        outreach: amounts.outreach || 0,
      };
      const res = await apiService.createBillingTopupCheckoutSession(payload);
      if (res.error) {
        toast.error(res.error);
        return;
      }
      const raw = res.data?.checkout_url;
      const url = typeof raw === 'string' ? raw.trim() : '';
      if (!url || !/^https?:\/\//i.test(url)) {
        toast.error('Could not start checkout. Please try again.');
        return;
      }
      window.location.href = url;
    } catch {
      toast.error('Could not start checkout. Please try again.');
    } finally {
      setCheckoutBusy(false);
    }
  };

  const usageHeroSubtitle = useMemo(() => {
    const ph = allowancePossessive(planBillingInterval);
    return `Balances for lead search, spam checks, and email sends — and how much of this ${ph} allowance you've used.`;
  }, [planBillingInterval]);

  return (
    <>
      {includeUsageHero ? (
        <div className="billing-page-intro">
          <header className="billing-page-hero">
            <h3 className="billing-page-title">Credits Usage</h3>
            <p className="billing-page-subtitle">{usageHeroSubtitle}</p>
          </header>
        </div>
      ) : null}
      <section className="spending-section" aria-label="Credits and top-up">
        <div className="spending-region spending-region--usage">
          <div className="spending-usage-card spending-usage-card--pools">
            {loading ? (
              <p className="spending-loading">Loading credit balance…</p>
            ) : (
              <ul className="spending-pool-list" aria-label="Credit balances by type">
                {poolBars.map((bar) => (
                  <li key={bar.pool} className="spending-pool-item">
                    <div className="spending-pool-row">
                      <span className="spending-pool-label">{bar.label}</span>
                      <span className="spending-pool-meta">
                        <img src={CREDITS_COIN_SRC} alt="" className="spending-pool-coin" aria-hidden />
                        <span className="spending-pool-count">
                          {bar.remaining.toLocaleString()}/{bar.denominator.toLocaleString()} credits
                        </span>
                      </span>
                    </div>
                    <div
                      className="spending-usage-bar-track"
                      role="progressbar"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={Math.round(bar.usedPct)}
                      aria-label={`${bar.label} credits used`}
                    >
                      <div
                        className="spending-usage-bar-fill"
                        style={{ width: `${bar.usedPct}%` }}
                      />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        <div className="spending-purchase-row">
          <div className="spending-purchase-main">
            <div className="spending-region spending-region--additional">
              <h3 className="spending-additional-title">Additional Credits</h3>
              <p className="spending-additional-lead">
                Our AI identifies your next best customer and automates the introduction, choose the
                plan that matches your ambition.
              </p>

              {!topupAvailable ? (
                <p className="spending-topup-unavailable">
                  {topupUnavailableReason ||
                    'Top-up is not available on the free plan. Upgrade to a paid plan.'}
                </p>
              ) : null}

              <div className="spending-slider-list" role="group" aria-label="Credit amounts by type">
                {CREDIT_POOL_ORDER.map((pool) => {
                  const opt = poolOptions.find((p) => p.pool === pool);
                  const max = opt?.max ?? 0;
                  const disabled = !topupAvailable || !opt || max < topupMin;
                  const credits = amounts[pool] ?? 0;
                  const fillPct =
                    disabled || max <= 0 || credits <= 0
                      ? 0
                      : Math.min(100, (credits / max) * 100);
                  const ticks = disabled
                    ? [{ value: 0, label: '0', pct: 0 }]
                    : buildPoolSliderTicks(topupMin, max, topupStep);

                  return (
                    <div
                      key={pool}
                      className={cn('spending-slider-block', disabled && 'spending-slider-block--disabled')}
                    >
                      <label className="spending-slider-label" htmlFor={`spending-slider-${pool}`}>
                        {SLIDER_POOL_LABELS[pool]}
                      </label>
                      <div className="spending-slider-control">
                        <input
                          id={`spending-slider-${pool}`}
                          type="range"
                          className="spending-slider-input"
                          min={0}
                          max={Math.max(max, topupMin)}
                          step={topupStep}
                          value={credits}
                          disabled={disabled}
                          aria-valuemin={0}
                          aria-valuemax={max}
                          aria-valuenow={credits}
                          aria-valuetext={
                            credits > 0
                              ? `${credits.toLocaleString()} ${SLIDER_POOL_LABELS[pool].toLowerCase()}`
                              : 'None selected'
                          }
                          style={{
                            background: `linear-gradient(90deg, #7c3aed 0%, #d946ef ${fillPct}%, #e8e8ef ${fillPct}%, #e8e8ef 100%)`,
                          }}
                          onChange={(e) => {
                            setPoolCredits(
                              pool,
                              normalizeSliderCredits(
                                Number(e.target.value),
                                topupMin,
                                max,
                                topupStep,
                              ),
                            );
                          }}
                        />
                        <div className="spending-slider-scale" aria-hidden>
                          {ticks.map((tick, index) => (
                            <span
                              key={`${pool}-${tick.value}-${index}`}
                              className={cn(
                                'spending-slider-tick',
                                index === 0 && 'spending-slider-tick--start',
                                index === ticks.length - 1 && 'spending-slider-tick--end',
                              )}
                              style={{ left: `${tick.pct}%` }}
                            >
                              <span className="spending-slider-tick-mark" />
                              <span className="spending-slider-tick-label">{tick.label}</span>
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          <aside className="spending-order" aria-label="Order summary">
            <h4 className="spending-order-title">Order Summary</h4>
            <ul className="spending-order-items">
              {lineItems.map((item) => {
                const empty = item.credits <= 0;
                return (
                  <li
                    key={item.pool}
                    className={cn('spending-order-item', empty && 'spending-order-item--empty')}
                  >
                    <span className="spending-order-item-label">
                      <strong className="spending-order-item-count">
                        {empty ? '0' : item.credits.toLocaleString()}
                      </strong>
                      <span>{item.label}</span>
                    </span>
                    <span className="spending-order-item-price">
                      {empty ? '$0' : `$${formatMoney(item.price)}`}
                    </span>
                  </li>
                );
              })}
            </ul>
            <div className="spending-order-divider" />
            <div className="spending-order-total">
              <span className="spending-order-total-label">Total</span>
              <strong className="spending-order-total-amount">${formatMoney(totalUsd)}</strong>
            </div>
            <div className="spending-order-cta-wrap">
              <Button
                type="button"
                variant="default"
                className="spending-order-cta"
                disabled={checkoutBusy || !hasSelection || loading || !topupAvailable}
                onClick={startCheckout}
              >
                {checkoutBusy ? (
                  <>
                    <Loader2 className="spending-order-cta-spinner" size={18} aria-hidden />
                    Redirecting…
                  </>
                ) : (
                  'Checkout'
                )}
              </Button>
            </div>
          </aside>
        </div>
      </section>
    </>
  );
}
