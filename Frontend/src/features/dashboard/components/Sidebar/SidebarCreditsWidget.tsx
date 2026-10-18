import { useCallback, useEffect, useState } from 'react';
import { apiService, type BillingCreditBalanceResponse } from '@/shared/services/api';
import { buildPoolBars, designPoolLabel } from '@/shared/billing/creditPools';
import './SidebarCreditsWidget.css';

type SidebarCreditsWidgetProps = {
  collapsed: boolean;
  onBuyMore: () => void;
};

/** `public/coin_img01 2.png` */
const CREDITS_COIN_SRC = `${import.meta.env.BASE_URL}coin_img01%202.png`;

export function SidebarCreditsWidget({
  collapsed,
  onBuyMore,
}: SidebarCreditsWidgetProps) {
  const [balanceData, setBalanceData] = useState<BillingCreditBalanceResponse | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const balRes = await apiService.getBillingCreditBalance();
      if (balRes.data) {
        setBalanceData(balRes.data);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const interval = setInterval(load, 30_000);
    const onVis = () => {
      if (document.visibilityState === 'visible') load();
    };
    const onCreditsUpdated = () => {
      load();
    };
    document.addEventListener('visibilitychange', onVis);
    window.addEventListener('evecta:credits-updated', onCreditsUpdated);
    return () => {
      clearInterval(interval);
      document.removeEventListener('visibilitychange', onVis);
      window.removeEventListener('evecta:credits-updated', onCreditsUpdated);
    };
  }, [load]);

  const bars = buildPoolBars(balanceData).map((b) => ({
    ...b,
    label: designPoolLabel(b.pool),
  }));
  const totalRemaining = bars.reduce((sum, b) => sum + b.remaining, 0);

  if (collapsed) {
    const collapsedTitle =
      loading || !balanceData
        ? 'Credits — Buy more'
        : `${totalRemaining.toLocaleString()} credits remaining — Buy more`;
    return (
      <div className="sidebar-credits sidebar-credits--collapsed">
        <button
          type="button"
          className="sidebar-credits-collapsed-btn"
          onClick={onBuyMore}
          title={collapsedTitle}
          aria-label={collapsedTitle}
        >
          <span className="sidebar-credits-icon-wrap" aria-hidden>
            <img src={CREDITS_COIN_SRC} alt="" className="sidebar-credits-coin" />
          </span>
        </button>
      </div>
    );
  }

  return (
    <div className={`sidebar-credits ${loading ? 'sidebar-credits-loading' : ''}`}>
      <div className="sidebar-credits-inner">
        <div className="sidebar-credits-header">
          <strong className="sidebar-credits-title">Credits Usage</strong>
        </div>

        <ul className="sidebar-credits-pools" aria-label="Credit balances by type">
          {bars.map((bar) => (
            <li key={bar.pool} className="sidebar-credits-pool">
              <div className="sidebar-credits-pool-row">
                <span className="sidebar-credits-pool-label">{bar.label}</span>
                <span className="sidebar-credits-meta">
                  <span className="sidebar-credits-icon-wrap" aria-hidden>
                    <img src={CREDITS_COIN_SRC} alt="" className="sidebar-credits-coin" />
                  </span>
                  <span className="sidebar-credits-count">
                    {loading
                      ? '…'
                      : `${bar.remaining.toLocaleString()}/${bar.denominator.toLocaleString()} credits`}
                  </span>
                </span>
              </div>
              <div
                className="sidebar-credits-track"
                role="progressbar"
                aria-valuenow={Math.round(bar.usedPct)}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label={`${bar.label} credits used`}
              >
                <div className="sidebar-credits-fill" style={{ width: `${bar.usedPct}%` }} />
              </div>
            </li>
          ))}
        </ul>

        <div className="sidebar-credits-actions">
          <button
            type="button"
            className="sidebar-credits-buy evecta-primary-btn"
            onClick={onBuyMore}
          >
            + Buy More Credits
          </button>
        </div>
      </div>
    </div>
  );
}
