import { useCallback, useEffect, useState } from 'react';
import { Loader2, RefreshCw } from 'lucide-react';
import {
  apiService,
  type ExternalApiProvider,
  type ExternalApiUsageTrack,
  type GeminiStatusTrack,
} from '@/shared/services/api';
import { Button } from '../ui/button';
import './GeminiPurchasesAdminPage.css';

type ProviderTab = 'gemini' | 'hunter' | 'places';

function formatWhen(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatUsd(n?: number | null): string {
  if (n == null || Number.isNaN(n)) return '$0.00';
  if (Math.abs(n) < 0.01 && n !== 0) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

function formatDay(day: string): string {
  const d = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return day;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function statusBadgeClass(status: string): string {
  if (status === 'credit_exhausted') return 'gemini-purchases__badge--danger';
  if (status === 'rate_limited' || status === 'unavailable') return 'gemini-purchases__badge--warn';
  return 'gemini-purchases__badge--completed';
}

function statusLabel(status: string): string {
  if (status === 'credit_exhausted') return 'Credit exhausted';
  if (status === 'rate_limited') return 'Rate limited';
  if (status === 'unavailable') return 'Unavailable';
  return 'OK';
}

function kindLabel(kind?: string | null): string {
  if (kind === 'quota_exhausted') return 'Quota / prepaid depleted';
  if (kind === 'billing') return 'Billing';
  if (kind === 'rate_limit') return 'Rate limit';
  if (kind === 'unavailable') return 'Unavailable';
  return kind || '—';
}

function apiNameLabel(apiName: string): string {
  const map: Record<string, string> = {
    domain_search: 'Domain search',
    company_find: 'Company find',
    geocode: 'Geocoding',
    nearby_search: 'Nearby search',
    place_details: 'Place details',
    text_search: 'Text search',
  };
  return map[apiName] || apiName;
}

function eventStatusLabel(status: string): string {
  if (status === 'zero_results') return 'Zero results';
  if (status === 'failed') return 'Failed';
  return 'Success';
}

function ProviderUsagePanel({
  title,
  unitLabel,
  track,
  loading,
  emptyHint,
}: {
  title: string;
  unitLabel: string;
  track: ExternalApiUsageTrack | null;
  loading: boolean;
  emptyHint: string;
}) {
  const summary = track?.summary;
  return (
    <>
      <div className="gemini-purchases__intro">
        <p className="gemini-purchases__subtitle">{title}</p>
      </div>

      <div className="gemini-purchases__stats">
        <div className="gemini-purchases__stat">
          <span className="gemini-purchases__stat-label">Est. cost (30d)</span>
          <span className="gemini-purchases__stat-value">
            {loading ? '…' : formatUsd(summary?.estimated_cost_usd)}
          </span>
        </div>
        <div className="gemini-purchases__stat">
          <span className="gemini-purchases__stat-label">{unitLabel}</span>
          <span className="gemini-purchases__stat-value">
            {loading ? '…' : (summary?.total_units ?? 0).toLocaleString()}
          </span>
        </div>
        <div className="gemini-purchases__stat">
          <span className="gemini-purchases__stat-label">Requests</span>
          <span className="gemini-purchases__stat-value">
            {loading ? '…' : (summary?.request_count ?? 0).toLocaleString()}
          </span>
        </div>
        <div className="gemini-purchases__stat">
          <span className="gemini-purchases__stat-label">Failed</span>
          <span className="gemini-purchases__stat-value">
            {loading ? '…' : (summary?.failed_count ?? 0).toLocaleString()}
          </span>
        </div>
      </div>

      <section className="gemini-purchases__panel">
        <div className="gemini-purchases__panel-head">
          <h3 className="gemini-purchases__panel-title">By API</h3>
          <span className="gemini-purchases__count">{track?.by_api?.length || 0}</span>
        </div>
        <div className="gemini-purchases__table-wrap">
          <table className="gemini-purchases__table">
            <thead>
              <tr>
                <th>API</th>
                <th>{unitLabel}</th>
                <th>Est. cost</th>
                <th>Requests</th>
                <th>Failed</th>
              </tr>
            </thead>
            <tbody>
              {loading && !(track?.by_api?.length) ? (
                <tr>
                  <td colSpan={5}>
                    <span className="gemini-purchases__muted inline-flex items-center gap-2">
                      <Loader2 size={14} className="animate-spin" /> Loading…
                    </span>
                  </td>
                </tr>
              ) : !(track?.by_api?.length) ? (
                <tr>
                  <td colSpan={5}>{emptyHint}</td>
                </tr>
              ) : (
                track!.by_api.map((row) => (
                  <tr key={row.api_name}>
                    <td>{apiNameLabel(row.api_name)}</td>
                    <td>{row.total_units.toLocaleString()}</td>
                    <td>{formatUsd(row.estimated_cost_usd)}</td>
                    <td>{row.request_count.toLocaleString()}</td>
                    <td>{row.failed_count.toLocaleString()}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="gemini-purchases__panel">
        <div className="gemini-purchases__panel-head">
          <h3 className="gemini-purchases__panel-title">Daily usage</h3>
          <span className="gemini-purchases__count">{track?.by_day?.length || 0} days</span>
        </div>
        <div className="gemini-purchases__table-wrap">
          <table className="gemini-purchases__table">
            <thead>
              <tr>
                <th>Day</th>
                <th>{unitLabel}</th>
                <th>Est. cost</th>
                <th>Requests</th>
              </tr>
            </thead>
            <tbody>
              {loading && !(track?.by_day?.length) ? (
                <tr>
                  <td colSpan={4}>
                    <span className="gemini-purchases__muted inline-flex items-center gap-2">
                      <Loader2 size={14} className="animate-spin" /> Loading…
                    </span>
                  </td>
                </tr>
              ) : !(track?.by_day?.length) ? (
                <tr>
                  <td colSpan={4}>No daily usage yet.</td>
                </tr>
              ) : (
                [...(track?.by_day || [])].reverse().map((row) => (
                  <tr key={row.day}>
                    <td>{formatDay(row.day)}</td>
                    <td>{row.total_units.toLocaleString()}</td>
                    <td>{formatUsd(row.estimated_cost_usd)}</td>
                    <td>{row.request_count.toLocaleString()}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="gemini-purchases__panel">
        <div className="gemini-purchases__panel-head">
          <h3 className="gemini-purchases__panel-title">Recent calls</h3>
          <span className="gemini-purchases__count">{track?.recent_events?.length || 0}</span>
        </div>
        <div className="gemini-purchases__table-wrap">
          <table className="gemini-purchases__table">
            <thead>
              <tr>
                <th>When</th>
                <th>API</th>
                <th>Status</th>
                <th>Units</th>
                <th>Cost</th>
                <th>Meta</th>
              </tr>
            </thead>
            <tbody>
              {loading && !(track?.recent_events?.length) ? (
                <tr>
                  <td colSpan={6}>
                    <span className="gemini-purchases__muted inline-flex items-center gap-2">
                      <Loader2 size={14} className="animate-spin" /> Loading…
                    </span>
                  </td>
                </tr>
              ) : !(track?.recent_events?.length) ? (
                <tr>
                  <td colSpan={6}>{emptyHint}</td>
                </tr>
              ) : (
                track!.recent_events.map((row) => (
                  <tr key={row.id}>
                    <td>{formatWhen(row.created_at)}</td>
                    <td>{apiNameLabel(row.api_name)}</td>
                    <td>{eventStatusLabel(row.status)}</td>
                    <td>{row.units}</td>
                    <td>{formatUsd(row.estimated_cost_usd)}</td>
                    <td className="gemini-purchases__desc">{row.meta || '—'}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

export function GeminiPurchasesAdminPage() {
  const [tab, setTab] = useState<ProviderTab>('gemini');
  const [geminiTrack, setGeminiTrack] = useState<GeminiStatusTrack | null>(null);
  const [hunterTrack, setHunterTrack] = useState<ExternalApiUsageTrack | null>(null);
  const [placesTrack, setPlacesTrack] = useState<ExternalApiUsageTrack | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadGemini = useCallback(async () => {
    const res = await apiService.getGeminiCreditTrack();
    if (res.error) throw new Error(res.error);
    setGeminiTrack(res.data || null);
  }, []);

  const loadProvider = useCallback(async (provider: ExternalApiProvider) => {
    const res = await apiService.getExternalApiUsageTrack(provider);
    if (res.error) throw new Error(res.error);
    if (provider === 'hunter') setHunterTrack(res.data || null);
    else setPlacesTrack(res.data || null);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (tab === 'gemini') {
        await loadGemini();
      } else if (tab === 'hunter') {
        await loadProvider('hunter');
      } else {
        await loadProvider('google_places');
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load usage');
    } finally {
      setLoading(false);
    }
  }, [tab, loadGemini, loadProvider]);

  useEffect(() => {
    void load();
  }, [load]);

  const bannerTone =
    geminiTrack?.status === 'ok'
      ? 'ok'
      : geminiTrack?.status === 'rate_limited'
        ? 'warn'
        : geminiTrack?.status
          ? 'error'
          : 'ok';

  return (
    <div className="gemini-purchases">
      <div className="gemini-purchases__filter-bar">
        <div className="gemini-purchases__tabs" role="tablist" aria-label="Provider usage">
          {(
            [
              ['gemini', 'Gemini'],
              ['hunter', 'Hunter'],
              ['places', 'Places API'],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              className={`gemini-purchases__tab${tab === key ? ' gemini-purchases__tab--active' : ''}`}
              onClick={() => setTab(key)}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="gemini-purchases__filter-spacer" aria-hidden />
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="gemini-purchases__refresh"
          onClick={() => void load()}
          disabled={loading}
        >
          {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          Refresh
        </Button>
      </div>

      {error && (
        <div className="gemini-purchases__banner gemini-purchases__banner--error" role="alert">
          {error}
        </div>
      )}

      {tab === 'gemini' && (
        <>
          <div className="gemini-purchases__intro">
            <p className="gemini-purchases__subtitle">
              When chat fails because Gemini prepaid credit is finished, Gemini returns an error status
              (often HTTP 429 / RESOURCE_EXHAUSTED). That status is recorded here so you can see it on
              the admin dashboard without opening the Gemini console.
            </p>
          </div>

          {geminiTrack && (
            <div
              className={`gemini-purchases__banner gemini-purchases__banner--${bannerTone}`}
              role={geminiTrack.status === 'ok' ? 'status' : 'alert'}
            >
              <div className="gemini-purchases__status-row">
                <span className={`gemini-purchases__badge ${statusBadgeClass(geminiTrack.status)}`}>
                  {statusLabel(geminiTrack.status)}
                </span>
                {geminiTrack.http_status != null && (
                  <span className="gemini-purchases__http">HTTP {geminiTrack.http_status}</span>
                )}
                {geminiTrack.error_kind && (
                  <span className="gemini-purchases__muted">{kindLabel(geminiTrack.error_kind)}</span>
                )}
              </div>
              <strong>{geminiTrack.title}</strong>
              <div>{geminiTrack.message}</div>
            </div>
          )}

          <div className="gemini-purchases__stats">
            <div className="gemini-purchases__stat">
              <span className="gemini-purchases__stat-label">Current status</span>
              <span className="gemini-purchases__stat-value">
                {loading ? '…' : statusLabel(geminiTrack?.status || 'ok')}
              </span>
            </div>
            <div className="gemini-purchases__stat">
              <span className="gemini-purchases__stat-label">Last HTTP status</span>
              <span className="gemini-purchases__stat-value">
                {loading ? '…' : geminiTrack?.http_status != null ? String(geminiTrack.http_status) : '—'}
              </span>
            </div>
            <div className="gemini-purchases__stat">
              <span className="gemini-purchases__stat-label">Last error</span>
              <span className="gemini-purchases__stat-value gemini-purchases__stat-value--sm">
                {loading ? '…' : formatWhen(geminiTrack?.last_error_at)}
              </span>
            </div>
            <div className="gemini-purchases__stat">
              <span className="gemini-purchases__stat-label">Last success</span>
              <span className="gemini-purchases__stat-value gemini-purchases__stat-value--sm">
                {loading ? '…' : formatWhen(geminiTrack?.last_success_at)}
              </span>
            </div>
          </div>

          <section className="gemini-purchases__panel">
            <div className="gemini-purchases__panel-head">
              <h3 className="gemini-purchases__panel-title">Gemini API status track</h3>
              <span className="gemini-purchases__count">{geminiTrack?.events?.length || 0} events</span>
            </div>
            <div className="gemini-purchases__table-wrap">
              <table className="gemini-purchases__table">
                <thead>
                  <tr>
                    <th>When</th>
                    <th>HTTP</th>
                    <th>Kind</th>
                    <th>Feature</th>
                    <th>Message</th>
                  </tr>
                </thead>
                <tbody>
                  {loading && !(geminiTrack?.events?.length) ? (
                    <tr>
                      <td colSpan={5}>
                        <span className="gemini-purchases__muted inline-flex items-center gap-2">
                          <Loader2 size={14} className="animate-spin" /> Loading…
                        </span>
                      </td>
                    </tr>
                  ) : !(geminiTrack?.events?.length) ? (
                    <tr>
                      <td colSpan={5}>
                        No Gemini credit/quota errors recorded yet. When chat hits an exhausted Gemini
                        purchase, the status code will appear here.
                      </td>
                    </tr>
                  ) : (
                    geminiTrack!.events.map((row) => (
                      <tr key={row.id}>
                        <td>{formatWhen(row.created_at)}</td>
                        <td>{row.http_status != null ? row.http_status : '—'}</td>
                        <td>{kindLabel(row.error_kind)}</td>
                        <td>{row.feature || '—'}</td>
                        <td className="gemini-purchases__desc">{row.message || '—'}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}

      {tab === 'hunter' && (
        <ProviderUsagePanel
          title="Hunter.io credit usage from email enrichment (domain-search / companies/find). Each successful call burns 1 credit; estimated USD uses your configured credit rate."
          unitLabel="Credits"
          track={hunterTrack}
          loading={loading}
          emptyHint="No Hunter calls recorded yet. Usage appears after email enrichment hits Hunter.io."
        />
      )}

      {tab === 'places' && (
        <ProviderUsagePanel
          title="Google Places / Maps API cost from geocode, nearby search, place details, and text search. Cache hits are not billed. Estimated USD uses list prices from cost analysis."
          unitLabel="Billable calls"
          track={placesTrack}
          loading={loading}
          emptyHint="No Places API calls recorded yet. Usage appears after lead search or geocoding hits Google."
        />
      )}
    </div>
  );
}
