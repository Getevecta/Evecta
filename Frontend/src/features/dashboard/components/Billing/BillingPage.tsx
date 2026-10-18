import React, { useState, useEffect, useCallback } from 'react';
import { Check, Loader2, X } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { apiService } from '@/shared/services/api';
import './BillingPage.css';

export type PlanId = 'free' | 'starter' | 'growth' | 'scale';

export interface Plan {
  id: PlanId;
  name: string;
  description: string;
  monthlyPrice: number;
  /** Price shown per month when user chooses annual billing */
  annualEffectiveMonthly: number;
  /** Total charged per year when paying annually */
  annualTotal: number;
  /** Savings vs 12 × monthly price */
  annualSavings: number;
  recommended?: boolean;
  headerVariant: 'neutral' | 'gradient';
  ctaVariant: 'outline' | 'solid';
  features: string[];
}

/** Plan card “What’s included” — full pricing content lives on cards only (no comparison table). */
export const PLANS: Plan[] = [
  {
    id: 'free',
    name: 'Free',
    description: 'Exploring Evecta',
    monthlyPrice: 0,
    annualEffectiveMonthly: 0,
    annualTotal: 0,
    annualSavings: 0,
    headerVariant: 'neutral',
    ctaVariant: 'outline',
    features: [
      'Lead Credits: 50',
      'Spam-Check Credits: 50',
      'Outreach Credits: 50',
      'Lead Search: Basic targeted search',
      'Verified Lead Data: Limited access',
      'AI-Assisted Drafts: Basic drafting access',
      'Campaign Usage: Test outreach campaigns',
      'Open & Reply Tracking: Track opens and replies',
      'Campaign Dashboard: Campaign performance dashboard',
      'Platform Access: Essential platform access',
    ],
  },
  {
    id: 'starter',
    name: 'Starter',
    description: 'Individuals and small teams',
    monthlyPrice: 29,
    annualEffectiveMonthly: 26,
    annualTotal: 312,
    annualSavings: 36,
    headerVariant: 'neutral',
    ctaVariant: 'outline',
    features: [
      'Lead Credits: 500/month',
      'Spam-Check Credits: 1,000 + 250 bonus credits',
      'Outreach Credits: 1,500 + 500 bonus credits',
      'Lead Search: Targeted lead search',
      'Verified Lead Data: Verified lead access',
      'AI-Assisted Drafts: Professional & Friendly',
      'Campaign Usage: Run regular campaigns',
      'Open & Reply Tracking: Track opens and replies',
      'Campaign Dashboard: Campaign performance dashboard',
      'Platform Access: Core platform access',
    ],
  },
  {
    id: 'growth',
    name: 'Growth',
    description: 'Growing businesses',
    monthlyPrice: 59,
    annualEffectiveMonthly: 53,
    annualTotal: 636,
    annualSavings: 72,
    recommended: true,
    headerVariant: 'gradient',
    ctaVariant: 'solid',
    features: [
      'Lead Credits: 1,150/month',
      'Spam-Check Credits: 2,300 + 500 bonus credits',
      'Outreach Credits: 3,500 + 1,000 bonus credits',
      'Lead Search: Expanded lead search',
      'Verified Lead Data: More verified lead access',
      'AI-Assisted Drafts: Everything in Starter + Concise, Persuasive & Consultative',
      'Campaign Usage: Manage growing campaigns',
      'Open & Reply Tracking: Track opens and replies',
      'Campaign Dashboard: Campaign performance dashboard',
      'Platform Access: Complete platform access',
    ],
  },
  {
    id: 'scale',
    name: 'Scale',
    description: 'Teams managing outreach at scale',
    monthlyPrice: 119,
    annualEffectiveMonthly: 107,
    annualTotal: 1284,
    annualSavings: 144,
    headerVariant: 'neutral',
    ctaVariant: 'outline',
    features: [
      'Lead Credits: 2,500/month',
      'Spam-Check Credits: 5,000 + 1,250 bonus credits',
      'Outreach Credits: 7,500 + 2,500 bonus credits',
      'Lead Search: High-volume lead search',
      'Verified Lead Data: Large-scale verified lead access',
      'AI-Assisted Drafts: Everything in Growth + Research-Based, Problem-Focused & Strategic',
      'Campaign Usage: Run high-volume campaigns',
      'Open & Reply Tracking: Track opens and replies',
      'Campaign Dashboard: Campaign performance dashboard',
      'Platform Access: Complete platform access',
    ],
  },
];

const PLAN_IDS: PlanId[] = ['free', 'starter', 'growth', 'scale'];

function normalizeUserPlan(raw: string | undefined): PlanId | null {
  if (!raw) return null;
  const p = raw.toLowerCase() as PlanId;
  return PLAN_IDS.includes(p) ? p : null;
}

type PaidPlanId = Exclude<PlanId, 'free'>;

const PLAN_RANK: Record<PlanId, number> = { free: 0, starter: 1, growth: 2, scale: 3 };

/** Monthly plan lead-credit allowance — keep in sync with backend plans.py PLANS[*]['credits']['lead']. */
const PLAN_MONTHLY_LEAD_CREDITS: Record<PaidPlanId, number> = {
  starter: 500,
  growth: 1150,
  scale: 2500,
};

export function BillingPage() {
  const location = useLocation();
  const navigate = useNavigate();
  /** Only the card that started checkout/subscription shows “Redirecting…”. */
  const [checkoutBusyCardId, setCheckoutBusyCardId] = useState<PlanId | null>(null);
  /** Downgrade target awaiting the credit-reset warning confirmation. */
  const [pendingDowngradePlan, setPendingDowngradePlan] = useState<PaidPlanId | null>(null);

  const [annualByPlan, setAnnualByPlan] = useState<Record<PlanId, boolean>>({
    free: false,
    starter: false,
    growth: false,
    scale: false,
  });
  const [activePlan, setActivePlan] = useState<PlanId | null>(null);
  const [creditBalance, setCreditBalance] = useState<number | null>(null);

  const readLeadBalance = (balRes: Awaited<ReturnType<typeof apiService.getBillingCreditBalance>>) => {
    const leadPool = balRes.data?.pools?.lead?.balance;
    if (typeof leadPool === 'number') return leadPool;
    return typeof balRes.data?.balance === 'number' ? balRes.data.balance : 0;
  };

  const refreshBillingSnapshot = useCallback(async () => {
    const [subRes, balRes] = await Promise.all([
      apiService.getBillingSubscription(),
      apiService.getBillingCreditBalance(),
    ]);
    const fromApi = normalizeUserPlan(subRes.data?.plan);
    setActivePlan(fromApi ?? 'free');
    setCreditBalance(readLeadBalance(balRes));
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [subRes, balRes] = await Promise.all([
        apiService.getBillingSubscription(),
        apiService.getBillingCreditBalance(),
      ]);
      if (cancelled) return;
      const fromApi = normalizeUserPlan(subRes.data?.plan);
      setActivePlan(fromApi ?? 'free');
      setCreditBalance(readLeadBalance(balRes));
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const st = location.state as {
      billingCheckout?: 'success' | 'cancel';
      stripeSessionId?: string;
    } | undefined;
    if (!st?.billingCheckout) return;

    let cancelled = false;
    (async () => {
      if (st.billingCheckout === 'success' && st.stripeSessionId) {
        const res = await apiService.confirmCheckoutSession(st.stripeSessionId);
        if (cancelled) return;
        if (res.error) {
          toast.error(res.error);
        } else {
          if (res.data?.credits_added) {
            const added = res.data.credits_added;
            const total =
              typeof added === 'number'
                ? added
                : Object.values(added).reduce((s, n) => s + (typeof n === 'number' ? n : 0), 0);
            toast.success(
              total > 0
                ? `Added ${total.toLocaleString()} credits to your balance.`
                : 'Your plan is now active.',
            );
          } else {
            toast.success(
              res.data?.already_active
                ? 'Your subscription is already active.'
                : 'Your plan is now active.',
            );
          }
          if (!cancelled) {
            await refreshBillingSnapshot();
            window.dispatchEvent(new CustomEvent('evecta:credits-updated'));
          }
        }
      } else if (st.billingCheckout === 'success') {
        toast.success(
          'Payment completed. If your plan still shows as Free, refresh after a minute (webhook sync).',
        );
      } else {
        toast.message('Checkout was canceled.');
      }
      navigate(location.pathname, { replace: true, state: {} });
    })();

    return () => {
      cancelled = true;
    };
  }, [location.pathname, location.state, navigate, refreshBillingSnapshot]);

  const startPaidCheckout = async (fromCardId: PlanId, targetPlanId: PaidPlanId) => {
    setCheckoutBusyCardId(fromCardId);
    try {
      const res = await apiService.createBillingCheckoutSession(targetPlanId);
      if (res.error) {
        toast.error(res.error);
        return;
      }
      const url = res.data?.checkout_url;
      if (!url) {
        toast.error('Could not start checkout. Please try again.');
        return;
      }
      window.location.assign(url);
    } catch {
      toast.error('Could not start checkout. Please try again.');
    } finally {
      setCheckoutBusyCardId(null);
    }
  };

  const toggleAnnual = (id: PlanId) => {
    setAnnualByPlan((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const displayPriceMain = (plan: Plan) => {
    if (plan.id === 'free') return '$0';
    const useAnnual = annualByPlan[plan.id];
    const n = useAnnual ? plan.annualEffectiveMonthly : plan.monthlyPrice;
    return `$${n}`;
  };

  const priceSubtitle = (plan: Plan): string | null => {
    if (plan.id === 'free') return 'Free for everyone';
    /* Annual on: show same simple suffix as monthly (no “$288 billed annually” or savings line) */
    return 'per month';
  };

  return (
    <div className="billing-page">
      <div className="billing-page-intro">
        <header className="billing-page-hero">
          <h1 className="billing-page-title">Pricing</h1>
          <p className="billing-page-subtitle">
            Our AI identifies your next best customer and automates the introduction, choose the plan that matches your ambition.
          </p>
        </header>
      </div>

      <div className="billing-page-grid">
        {PLANS.map((plan) => {
          const isCurrentPlanCard = activePlan !== null && activePlan === plan.id;
          return (
          <article
            key={plan.id}
            className={`billing-card billing-card--${plan.headerVariant}${isCurrentPlanCard ? ' billing-card--active' : ''}`}
          >
            {plan.recommended && (
              <div className="billing-card-badge">
                <span className="billing-card-badge-dot" aria-hidden />
                Popular
              </div>
            )}
            <div className={`billing-card-header ${plan.headerVariant === 'gradient' ? 'billing-card-header--gradient' : 'billing-card-header--neutral'}`}>
              <h2 className="billing-card-name">
                {plan.name}
                {plan.recommended ? <span className="billing-card-name-star" aria-hidden> ★</span> : null}
              </h2>
              <p className="billing-card-desc">{plan.description}</p>
            </div>
            <div className="billing-card-body">
              <div className="billing-card-price-row">
                <div className="billing-card-price-block">
                  <span className="billing-card-price">{displayPriceMain(plan)}</span>
                  {priceSubtitle(plan) && (
                    <span className="billing-card-price-suffix">{priceSubtitle(plan)}</span>
                  )}
                </div>
                {plan.id !== 'free' && (
                  <label className="billing-card-toggle">
                    <input
                      type="checkbox"
                      checked={annualByPlan[plan.id]}
                      onChange={() => toggleAnnual(plan.id)}
                    />
                    <span className="billing-card-toggle-label">Annually</span>
                    <span className="billing-card-toggle-ui" aria-hidden />
                  </label>
                )}
              </div>

              <div className="billing-card-features">
                <h3 className="billing-card-features-title">What&apos;s included</h3>
                <ul className="billing-card-features-list">
                  {plan.features.map((f) => (
                    <li key={f} className="billing-card-feature-item">
                      <Check className="billing-card-check" size={18} strokeWidth={2.5} aria-hidden />
                      <span className="billing-card-feature-text">{f}</span>
                    </li>
                  ))}
                </ul>
              </div>

              {(() => {
                const loading = activePlan === null || creditBalance === null;
                const creditsExhausted = !loading && creditBalance <= 0;
                const isCurrent = !loading && activePlan === plan.id;
                const anyCheckoutBusy = checkoutBusyCardId !== null;
                const thisCardBusy = checkoutBusyCardId === plan.id;

                if (plan.id === 'free') {
                  return <div className="billing-card-footer-slot" aria-hidden />;
                }

                if (loading) {
                  return <div className="billing-card-footer-slot" aria-hidden />;
                }
                if (isCurrent) {
                  return <p className="billing-card-current-plan">Current plan</p>;
                }
                const paidId = plan.id as PaidPlanId;
                const busy = thisCardBusy;
                const isDowngrade = activePlan !== null && PLAN_RANK[paidId] < PLAN_RANK[activePlan];
                return (
                  <button
                    type="button"
                    className={
                      plan.ctaVariant === 'solid'
                        ? 'billing-card-cta billing-card-cta--solid'
                        : 'billing-card-cta billing-card-cta--outline'
                    }
                    disabled={anyCheckoutBusy}
                    aria-busy={busy}
                    onClick={() =>
                      isDowngrade ? setPendingDowngradePlan(paidId) : startPaidCheckout(plan.id, paidId)
                    }
                  >
                    {busy ? (
                      <>
                        <Loader2 className="billing-card-cta-spinner" size={18} aria-hidden />
                        Redirecting…
                      </>
                    ) : isDowngrade ? (
                      'Switch plan'
                    ) : (
                      'Upgrade plan'
                    )}
                  </button>
                );
              })()}
            </div>
          </article>
          );
        })}
      </div>

      <p className="billing-page-credits-note">
        Credits are per pool: 1 lead credit per generated lead, 1 spam-check credit per spam
        check / AI draft, 1 outreach credit per email sent.
      </p>

      {(() => {
        const pendingPlan = pendingDowngradePlan
          ? PLANS.find((p) => p.id === pendingDowngradePlan) ?? null
          : null;
        if (!pendingPlan) return null;
        const newAllowance = PLAN_MONTHLY_LEAD_CREDITS[pendingPlan.id as PaidPlanId];
        return (
          <>
            <div className="evecta-dialog-overlay" onClick={() => setPendingDowngradePlan(null)} />
            <div
              className="evecta-dialog"
              role="dialog"
              aria-modal="true"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="evecta-dialog-header">
                <h2 className="evecta-dialog-title">Switch to {pendingPlan.name}?</h2>
                <button
                  type="button"
                  aria-label="Close"
                  onClick={() => setPendingDowngradePlan(null)}
                  className="evecta-dialog-close"
                >
                  <X className="evecta-dialog-close-x" aria-hidden strokeWidth={2} size={18} />
                </button>
              </div>
              <p className="evecta-dialog-description">
                Switching to {pendingPlan.name} resets your plan credits (all pools) — lead pool
                becomes {newAllowance.toLocaleString()}; you currently have{' '}
                {(creditBalance ?? 0).toLocaleString()} lead credits. Your card is charged $
                {pendingPlan.monthlyPrice} today and your billing cycle restarts. One-time top-up
                credits are not affected.
              </p>
              <div className="evecta-dialog-actions">
                <button
                  type="button"
                  onClick={() => setPendingDowngradePlan(null)}
                  className="evecta-dialog-btn evecta-dialog-btn--secondary"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => {
                    const target = pendingPlan.id as PaidPlanId;
                    setPendingDowngradePlan(null);
                    startPaidCheckout(target, target);
                  }}
                  className="evecta-dialog-btn evecta-dialog-btn--primary"
                >
                  Continue to checkout
                </button>
              </div>
            </div>
          </>
        );
      })()}
    </div>
  );
}
