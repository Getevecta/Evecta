import { useCallback, useEffect, useMemo, useState } from 'react';
import { Loader2, RefreshCw, Search } from 'lucide-react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  apiService,
  type AiUsageByDayItem,
  type AiUsageByFeatureItem,
  type AiUsageByModelItem,
  type AiUsageByMonthItem,
  type AiUsageByUserItem,
  type AiUsageByUserMonthItem,
  type AiUsageCreditsByUserItem,
  type AiUsageSummary,
  type ExternalApiUsageTrack,
} from '@/shared/services/api';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { AdminFilterDropdown } from './AdminFilterDropdown';
import './AiUsageAdminPage.css';

type RangeKey = 'month' | '7d' | '30d' | '90d' | 'all';
type SectionKey = 'overview' | 'users' | 'features' | 'credits';
type ProviderFilter = '' | 'gemini' | 'google_places' | 'hunter';

const PROVIDER_OPTIONS: { value: Exclude<ProviderFilter, ''>; label: string }[] = [
  { value: 'gemini', label: 'Gemini' },
  { value: 'google_places', label: 'Maps API' },
  { value: 'hunter', label: 'Hunter' },
];

const FEATURE_OPTIONS = [
  { value: '', label: 'All features' },
  { value: 'chat_understanding', label: 'AI Lead Gen · understanding' },
  { value: 'chat_response', label: 'AI Lead Gen · chat reply' },
  { value: 'nearby_city_suggestion', label: 'AI Lead Gen · city suggestion' },
  { value: 'campaign_email', label: 'Campaign email draft' },
  { value: 'spam_score', label: 'Spam check · score' },
  { value: 'spam_rewrite', label: 'Spam check · rewrite' },
  { value: 'lead_context', label: 'Lead enrichment context' },
  { value: 'category_resolution', label: 'Category resolution' },
  { value: 'company_profile', label: 'Company profile extract' },
] as const;

function toDateInput(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function rangeBounds(key: RangeKey): { from?: string; to?: string } {
  const to = new Date();
  if (key === 'all') return {};
  if (key === 'month') {
    const from = new Date(Date.UTC(to.getUTCFullYear(), to.getUTCMonth(), 1));
    return { from: toDateInput(from), to: toDateInput(to) };
  }
  const from = new Date();
  const days = key === '7d' ? 7 : key === '30d' ? 30 : 90;
  from.setUTCDate(from.getUTCDate() - (days - 1));
  return { from: toDateInput(from), to: toDateInput(to) };
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function formatUsd(n: number): string {
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
}

function formatMonthLabel(month: string): string {
  const [y, m] = month.split('-').map(Number);
  if (!y || !m) return month;
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleString(undefined, {
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  });
}

function rangeLabel(key: RangeKey): string {
  if (key === 'month') return 'This month';
  if (key === 'all') return 'All time';
  return key.toUpperCase();
}

function featureLabel(feature: string): string {
  const found = FEATURE_OPTIONS.find((o) => o.value === feature);
  return found?.label || feature.replace(/_/g, ' ');
}

function matchesUserQuery(
  query: string,
  email?: string | null,
  username?: string | null,
): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return (
    (email || '').toLowerCase().includes(q) ||
    (username || '').toLowerCase().includes(q) ||
    (!email && 'unassigned'.includes(q))
  );
}

function userDisplay(email?: string | null, username?: string | null): string {
  return email || 'Unassigned';
}

const PRICING_RECOMPUTE_KEY = 'ai-usage-costs-recomputed-v2026-08-gemini-live';

type GoogleMapsApiPrice = {
  api_name: string;
  label: string;
  endpoint?: string;
  unit_cost_usd: number;
  unit_label?: string;
  free_monthly?: number | null;
  notes?: string;
};

type PricingStatus = {
  source: string;
  source_url?: string | null;
  age_seconds?: number | null;
  model_count: number;
  error?: string | null;
  models: Record<string, Record<string, number>>;
  google_maps_apis?: GoogleMapsApiPrice[];
  google_maps_source?: string;
  google_maps_source_url?: string;
};

function pricingSourceLabel(source: string): string {
  if (source === 'google_pricing_page') return 'Google pricing page (live)';
  if (source === 'aipricing_guru') return 'Live feed (Google-sourced)';
  return 'Offline fallback rates';
}

function formatFlashRates(pricing: PricingStatus | null): string {
  const flash = pricing?.models?.['gemini-2.5-flash'];
  if (!flash) return 'Rates refresh from Google when you open this page or recalculate.';
  const input = flash.input_per_million;
  const output = flash.output_per_million;
  const cached = flash.cached_per_million;
  const parts = [
    input != null ? `input $${input}/1M` : null,
    output != null ? `output $${output}/1M` : null,
    cached != null ? `cache $${cached}/1M` : null,
  ].filter(Boolean);
  return parts.length ? `Current Gemini 2.5 Flash: ${parts.join(', ')}.` : '';
}

function formatUnitUsd(n: number): string {
  if (n >= 0.01) return `$${n.toFixed(3)}`;
  return `$${n.toFixed(4)}`;
}

export function AiUsageAdminPage() {
  const [section, setSection] = useState<SectionKey>('overview');
  const [range, setRange] = useState<RangeKey>('month');
  const [searchQuery, setSearchQuery] = useState('');
  const [featureFilter, setFeatureFilter] = useState('');
  const [providerFilter, setProviderFilter] = useState<ProviderFilter>('');
  const [loading, setLoading] = useState(true);
  const [recomputing, setRecomputing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recomputeNote, setRecomputeNote] = useState<string | null>(null);
  const [pricingStatus, setPricingStatus] = useState<PricingStatus | null>(null);
  const [placesTrack, setPlacesTrack] = useState<ExternalApiUsageTrack | null>(null);
  const [hunterTrack, setHunterTrack] = useState<ExternalApiUsageTrack | null>(null);
  const [summary, setSummary] = useState<AiUsageSummary | null>(null);
  const [byFeature, setByFeature] = useState<AiUsageByFeatureItem[]>([]);
  const [byModel, setByModel] = useState<AiUsageByModelItem[]>([]);
  const [byDay, setByDay] = useState<AiUsageByDayItem[]>([]);
  const [byMonth, setByMonth] = useState<AiUsageByMonthItem[]>([]);
  const [byUser, setByUser] = useState<AiUsageByUserItem[]>([]);
  const [byUserMonth, setByUserMonth] = useState<AiUsageByUserMonthItem[]>([]);
  const [creditsByUser, setCreditsByUser] = useState<AiUsageCreditsByUserItem[]>([]);

  const bounds = useMemo(() => rangeBounds(range), [range]);
  const isMapsProvider = providerFilter === 'google_places';
  const isHunterProvider = providerFilter === 'hunter';
  const isExternalProvider = isMapsProvider || isHunterProvider;

  const queryParams = useMemo(() => {
    const base: { from?: string; to?: string; provider?: string; feature?: string } = {
      ...bounds,
    };
    // Only Gemini AI usage accepts provider=gemini; Maps/Hunter use external-api-usage.
    if (providerFilter === 'gemini') base.provider = 'gemini';
    if (!isExternalProvider && featureFilter) base.feature = featureFilter;
    return base;
  }, [bounds, providerFilter, featureFilter, isExternalProvider]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const rangeParams = { from: bounds.from, to: bounds.to };
      const failures: string[] = [];

      if (isMapsProvider) {
        const [places, c] = await Promise.all([
          apiService.getExternalApiUsageTrack('google_places', rangeParams),
          apiService.getAiUsageCreditsByUser({ from: bounds.from, to: bounds.to }),
        ]);
        if (places.error) failures.push(places.error);
        if (c.error) failures.push(c.error);
        if (places.data) setPlacesTrack(places.data);
        if (c.data) setCreditsByUser(c.data);
        setHunterTrack(null);
      } else if (isHunterProvider) {
        const [hunter, c] = await Promise.all([
          apiService.getExternalApiUsageTrack('hunter', rangeParams),
          apiService.getAiUsageCreditsByUser({ from: bounds.from, to: bounds.to }),
        ]);
        if (hunter.error) failures.push(hunter.error);
        if (c.error) failures.push(c.error);
        if (hunter.data) setHunterTrack(hunter.data);
        if (c.data) setCreditsByUser(c.data);
        setPlacesTrack(null);
      } else {
        const geminiParams = {
          from: queryParams.from,
          to: queryParams.to,
          provider: queryParams.provider,
        };
        const dayParams = {
          ...geminiParams,
          feature: queryParams.feature,
        };
        const summaryParams = {
          ...geminiParams,
          feature: queryParams.feature,
        };

        const [s, f, m, d] = await Promise.all([
          apiService.getAiUsageSummary(summaryParams),
          apiService.getAiUsageByFeature(geminiParams),
          apiService.getAiUsageByModel(geminiParams),
          apiService.getAiUsageByDay(dayParams),
        ]);
        const [mo, u, um, c, places, hunter] = await Promise.all([
          apiService.getAiUsageByMonth(geminiParams),
          apiService.getAiUsageByUser(geminiParams),
          apiService.getAiUsageByUserMonth(geminiParams),
          apiService.getAiUsageCreditsByUser({ from: bounds.from, to: bounds.to }),
          apiService.getExternalApiUsageTrack('google_places', rangeParams),
          apiService.getExternalApiUsageTrack('hunter', rangeParams),
        ]);

        for (const r of [s, f, m, d, mo, u, um, c, places, hunter]) {
          if (r.error) failures.push(r.error);
        }

        if (s.data) setSummary(s.data);
        if (f.data) setByFeature(f.data);
        if (m.data) setByModel(m.data);
        if (d.data) setByDay(d.data);
        if (mo.data) setByMonth(mo.data);
        if (u.data) setByUser(u.data);
        if (um.data) setByUserMonth(um.data);
        if (c.data) setCreditsByUser(c.data);
        if (places.data) setPlacesTrack(places.data);
        if (hunter.data) setHunterTrack(hunter.data);

        if (!s.data && failures.length) {
          setError(failures[0] || 'Failed to load AI usage');
          return;
        }
      }

      if (failures.length) {
        setError(`Some sections failed to load. ${failures[0]}`);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load AI usage');
    } finally {
      setLoading(false);
    }
  }, [
    queryParams,
    bounds.from,
    bounds.to,
    isMapsProvider,
    isHunterProvider,
  ]);

  const recomputeCosts = useCallback(
    async (opts?: { silent?: boolean }) => {
      setRecomputing(true);
      if (!opts?.silent) setError(null);
      try {
        const res = await apiService.recomputeAiUsageCosts();
        if (res.error) {
          if (!opts?.silent) setError(res.error);
          return false;
        }
        if (res.data) {
          setRecomputeNote(res.data.message);
          try {
            sessionStorage.setItem(PRICING_RECOMPUTE_KEY, '1');
          } catch {
            /* ignore */
          }
        }
        const pricing = await apiService.getAiUsagePricing(false);
        if (pricing.data) setPricingStatus(pricing.data);
        await load();
        return true;
      } catch (e) {
        if (!opts?.silent) {
          setError(e instanceof Error ? e.message : 'Failed to recalculate costs');
        }
        return false;
      } finally {
        setRecomputing(false);
      }
    },
    [load],
  );

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      let already = false;
      try {
        already = sessionStorage.getItem(PRICING_RECOMPUTE_KEY) === '1';
      } catch {
        already = false;
      }
      if (!already) {
        setRecomputing(true);
        try {
          const res = await apiService.recomputeAiUsageCosts();
          if (!cancelled && res.data) {
            setRecomputeNote(res.data.message);
            try {
              sessionStorage.setItem(PRICING_RECOMPUTE_KEY, '1');
            } catch {
              /* ignore */
            }
          }
        } catch {
          /* still load usage even if recompute fails */
        } finally {
          if (!cancelled) setRecomputing(false);
        }
      } else {
        try {
          const pricing = await apiService.getAiUsagePricing(true);
          if (!cancelled && pricing.data) setPricingStatus(pricing.data);
        } catch {
          /* ignore */
        }
      }
      try {
        const pricing = await apiService.getAiUsagePricing(false);
        if (!cancelled && pricing.data) setPricingStatus(pricing.data);
      } catch {
        /* ignore */
      }
      if (!cancelled) await load();
    };
    void run();
    return () => {
      cancelled = true;
    };
    // Initial mount + whenever filters change via `load` identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- recompute only once per session; load handles filter refreshes
  }, [load]);

  const filteredByFeature = useMemo(() => {
    if (!featureFilter) return byFeature;
    return byFeature.filter((row) => row.feature === featureFilter);
  }, [byFeature, featureFilter]);

  const filteredByUser = useMemo(
    () => byUser.filter((row) => matchesUserQuery(searchQuery, row.email, row.username)),
    [byUser, searchQuery],
  );

  const filteredByUserMonth = useMemo(
    () => byUserMonth.filter((row) => matchesUserQuery(searchQuery, row.email, row.username)),
    [byUserMonth, searchQuery],
  );

  const filteredCredits = useMemo(
    () => creditsByUser.filter((row) => matchesUserQuery(searchQuery, row.email, row.username)),
    [creditsByUser, searchQuery],
  );

  const mapsCatalog = pricingStatus?.google_maps_apis || [];
  const placesSummary = placesTrack?.summary;
  const hunterSummary = hunterTrack?.summary;
  const externalSummary = isHunterProvider ? hunterSummary : placesSummary;
  const geocodeRate = mapsCatalog.find((a) => a.api_name === 'geocode');
  const hasDashboardData = Boolean(summary || placesTrack || hunterTrack);

  const mapsRows = useMemo(() => {
    const usageByApi = new Map(
      (placesTrack?.by_api || []).map((row) => [row.api_name, row]),
    );
    const catalog = mapsCatalog.length
      ? mapsCatalog
      : [
          { api_name: 'geocode', label: 'Geocoding', unit_cost_usd: 0.005 },
          { api_name: 'nearby_search', label: 'Nearby Search', unit_cost_usd: 0.032 },
          { api_name: 'place_details', label: 'Place Details', unit_cost_usd: 0.017 },
          { api_name: 'text_search', label: 'Text Search', unit_cost_usd: 0.032 },
        ];
    return catalog.map((api) => {
      const usage = usageByApi.get(api.api_name);
      return {
        ...api,
        request_count: usage?.request_count || 0,
        total_units: usage?.total_units || 0,
        estimated_cost_usd: usage?.estimated_cost_usd || 0,
        failed_count: usage?.failed_count || 0,
      };
    });
  }, [mapsCatalog, placesTrack]);

  const hunterRows = useMemo(
    () =>
      (hunterTrack?.by_api || []).map((row) => ({
        api_name: row.api_name,
        label: row.api_name.replace(/_/g, ' '),
        request_count: row.request_count,
        total_units: row.total_units,
        estimated_cost_usd: row.estimated_cost_usd,
        failed_count: row.failed_count,
      })),
    [hunterTrack],
  );

  const dayChartData = useMemo(() => {
    if (isMapsProvider) {
      return (placesTrack?.by_day || []).map((row) => ({
        day: String(row.day),
        tokens: row.total_units,
        units: row.total_units,
        cost: Number(row.estimated_cost_usd || 0),
      }));
    }
    if (isHunterProvider) {
      return (hunterTrack?.by_day || []).map((row) => ({
        day: String(row.day),
        tokens: row.total_units,
        units: row.total_units,
        cost: Number(row.estimated_cost_usd || 0),
      }));
    }
    return byDay.map((row) => ({
      day: row.day,
      tokens: row.total_tokens,
      units: row.total_tokens,
      cost: Number(row.estimated_cost_usd || 0),
    }));
  }, [isMapsProvider, isHunterProvider, placesTrack, hunterTrack, byDay]);

  const featureChartData = useMemo(() => {
    if (isMapsProvider) {
      return mapsRows
        .filter((row) => row.estimated_cost_usd > 0 || row.request_count > 0)
        .slice(0, 8)
        .map((row) => ({
          feature: row.label,
          cost: Number(row.estimated_cost_usd || 0),
          tokens: row.total_units,
        }));
    }
    if (isHunterProvider) {
      return hunterRows.slice(0, 8).map((row) => ({
        feature: row.label,
        cost: Number(row.estimated_cost_usd || 0),
        tokens: row.total_units,
      }));
    }
    return filteredByFeature.slice(0, 8).map((row) => ({
      feature: featureLabel(row.feature),
      cost: Number(row.estimated_cost_usd || 0),
      tokens: row.total_tokens,
    }));
  }, [isMapsProvider, isHunterProvider, mapsRows, hunterRows, filteredByFeature]);

  const monthChartData = useMemo(
    () =>
      [...byMonth]
        .reverse()
        .map((row) => ({
          month: formatMonthLabel(row.month),
          tokens: row.total_tokens,
          cost: Number(row.estimated_cost_usd || 0),
        })),
    [byMonth],
  );

  const totalCreditsSpent = useMemo(
    () => filteredCredits.reduce((sum, row) => sum + (row.credits_spent_total || 0), 0),
    [filteredCredits],
  );

  const currentMonthTotal = byMonth[0];
  const providerOptions = PROVIDER_OPTIONS;

  const featureOptions = useMemo(
    () =>
      FEATURE_OPTIONS.filter((o) => o.value).map((o) => ({
        value: o.value,
        label: o.label,
      })),
    [],
  );

  const showUserSearch = section === 'users' || section === 'credits';
  const showFeatureFilter = !isExternalProvider;

  const featureCostTotal = useMemo(
    () => filteredByFeature.reduce((sum, row) => sum + Number(row.estimated_cost_usd || 0), 0),
    [filteredByFeature],
  );

  const externalDayRows = isHunterProvider ? hunterTrack?.by_day || [] : placesTrack?.by_day || [];
  const externalRecent = isHunterProvider
    ? hunterTrack?.recent_events || []
    : placesTrack?.recent_events || [];
  const mapsApiCostTotal = useMemo(
    () => mapsRows.reduce((sum, row) => sum + Number(row.estimated_cost_usd || 0), 0),
    [mapsRows],
  );

  return (
    <div className="ai-usage-admin">
      <div className="ai-usage-admin__intro">
        <p className="ai-usage-admin__subtitle">
          Track Gemini token cost, Google Maps / Places API spend, and product credits. Gemini
          pricing is dynamic from Google&apos;s list prices. {formatFlashRates(pricingStatus)}{' '}
          {geocodeRate
            ? `Geocoding ${formatUnitUsd(geocodeRate.unit_cost_usd)}/request (first ${
                geocodeRate.free_monthly?.toLocaleString() || '10,000'
              }/mo free on Google).`
            : ''}{' '}
          No prompts are stored.
        </p>
        {pricingStatus && (
          <p className="ai-usage-admin__pricing-source">
            Gemini source: {pricingSourceLabel(pricingStatus.source)}
            {pricingStatus.model_count ? ` · ${pricingStatus.model_count} models` : ''}
            {pricingStatus.age_seconds != null
              ? ` · refreshed ${Math.max(0, Math.round(pricingStatus.age_seconds / 60))}m ago`
              : ''}
            {pricingStatus.error ? ` · fallback note: ${pricingStatus.error}` : ''}
            {pricingStatus.google_maps_source
              ? ` · Maps/Places: ${pricingStatus.google_maps_source}`
              : ''}
          </p>
        )}
        {recomputeNote && (
          <p className="ai-usage-admin__recompute-note" role="status">
            {recomputeNote}
          </p>
        )}
      </div>

      <div className="ai-usage-admin__filter-bar">
        <div className="ai-usage-admin__tabs" role="tablist" aria-label="AI usage sections">
          {(
            [
              ['overview', 'Overview'],
              ['users', 'Users'],
              ['features', 'Features'],
              ['credits', 'Credits'],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={section === key}
              className={`ai-usage-admin__tab${section === key ? ' ai-usage-admin__tab--active' : ''}`}
              onClick={() => setSection(key)}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="ai-usage-admin__filter-spacer" aria-hidden />

        {showUserSearch && (
          <div className="ai-usage-admin__search">
            <Search className="ai-usage-admin__search-icon" size={14} strokeWidth={2} aria-hidden />
            <Input
              type="search"
              placeholder="Search users by email or username…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="ai-usage-admin__search-input focus-visible:ring-0 focus-visible:ring-transparent focus-visible:border-none focus-visible:ring-offset-0"
            />
          </div>
        )}

        {showFeatureFilter && (
          <AdminFilterDropdown
            options={featureOptions}
            value={featureFilter}
            onChange={setFeatureFilter}
            placeholder="Feature"
            emptyLabel="All features"
          />
        )}

        <AdminFilterDropdown
          options={providerOptions}
          value={providerFilter}
          onChange={(value) => setProviderFilter((value || '') as ProviderFilter)}
          placeholder="Provider"
          emptyLabel="All providers"
        />

        <div className="ai-usage-admin__ranges" role="group" aria-label="Date range">
          {(['month', '7d', '30d', '90d', 'all'] as RangeKey[]).map((key) => (
            <button
              key={key}
              type="button"
              className={`ai-usage-admin__range-chip${range === key ? ' ai-usage-admin__range-chip--active' : ''}`}
              onClick={() => setRange(key)}
            >
              {rangeLabel(key)}
            </button>
          ))}
        </div>

        <Button
          type="button"
          variant="outline"
          size="sm"
          className="ai-usage-admin__refresh"
          onClick={() => void recomputeCosts()}
          disabled={loading || recomputing}
          title="Recalculate all stored event costs with latest Gemini list prices"
        >
          <RefreshCw className={`h-3.5 w-3.5${recomputing ? ' animate-spin' : ''}`} />
          Recalculate costs
        </Button>

        <Button
          type="button"
          variant="outline"
          size="sm"
          className="ai-usage-admin__refresh"
          onClick={() => void load()}
          disabled={loading || recomputing}
        >
          <RefreshCw className={`h-3.5 w-3.5${loading && !recomputing ? ' animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {(loading || recomputing) && (
        <div className="ai-usage-admin__loading">
          <Loader2 className="h-5 w-5 animate-spin" />
          {recomputing ? 'Recalculating Gemini costs…' : 'Loading usage…'}
        </div>
      )}

      {error && !loading && (
        <div className="ai-usage-admin__error" role="alert">
          {error}
        </div>
      )}

      {!loading && !recomputing && hasDashboardData && (
        <>
          {isExternalProvider ? (
            <div className="ai-usage-admin__stats">
              <div className="ai-usage-admin__stat-card">
                <div className="ai-usage-admin__stat-label">
                  {isMapsProvider ? 'Maps API' : 'Hunter'} cost ({rangeLabel(range)})
                </div>
                <div className="ai-usage-admin__stat-value">
                  {formatUsd(externalSummary?.estimated_cost_usd || 0)}
                </div>
              </div>
              <div className="ai-usage-admin__stat-card">
                <div className="ai-usage-admin__stat-label">
                  {isHunterProvider ? 'Credits used' : 'Billable units'}
                </div>
                <div className="ai-usage-admin__stat-value">
                  {(externalSummary?.total_units || 0).toLocaleString()}
                </div>
              </div>
              <div className="ai-usage-admin__stat-card">
                <div className="ai-usage-admin__stat-label">Requests</div>
                <div className="ai-usage-admin__stat-value">
                  {(externalSummary?.request_count || 0).toLocaleString()}
                  {(externalSummary?.failed_count || 0) > 0 && (
                    <span className="ai-usage-admin__failed">
                      {' '}
                      · {externalSummary?.failed_count} failed
                    </span>
                  )}
                </div>
              </div>
              {isMapsProvider && (
                <div className="ai-usage-admin__stat-card">
                  <div className="ai-usage-admin__stat-label">Geocoding unit price</div>
                  <div className="ai-usage-admin__stat-value ai-usage-admin__stat-value--sm">
                    {geocodeRate
                      ? `${formatUnitUsd(geocodeRate.unit_cost_usd)} · ${
                          geocodeRate.free_monthly?.toLocaleString() || '10,000'
                        } free/mo`
                      : '$0.005 · 10,000 free/mo'}
                  </div>
                </div>
              )}
            </div>
          ) : (
            summary && (
              <div className="ai-usage-admin__stats">
                <div className="ai-usage-admin__stat-card">
                  <div className="ai-usage-admin__stat-label">Range cost ({rangeLabel(range)})</div>
                  <div className="ai-usage-admin__stat-value">
                    {formatUsd(summary.estimated_cost_usd)}
                  </div>
                </div>
                <div className="ai-usage-admin__stat-card">
                  <div className="ai-usage-admin__stat-label">This calendar month</div>
                  <div className="ai-usage-admin__stat-value ai-usage-admin__stat-value--sm">
                    {currentMonthTotal
                      ? `${formatUsd(currentMonthTotal.estimated_cost_usd)} · ${formatTokens(currentMonthTotal.total_tokens)}`
                      : '$0.00 · 0'}
                  </div>
                </div>
                <div className="ai-usage-admin__stat-card">
                  <div className="ai-usage-admin__stat-label">Input / output</div>
                  <div className="ai-usage-admin__stat-value ai-usage-admin__stat-value--sm">
                    {formatTokens(summary.input_tokens)} / {formatTokens(summary.output_tokens)}
                  </div>
                </div>
                <div className="ai-usage-admin__stat-card">
                  <div className="ai-usage-admin__stat-label">Requests</div>
                  <div className="ai-usage-admin__stat-value">
                    {summary.request_count.toLocaleString()}
                    {summary.failed_count > 0 && (
                      <span className="ai-usage-admin__failed"> · {summary.failed_count} failed</span>
                    )}
                  </div>
                </div>
                <div className="ai-usage-admin__stat-card">
                  <div className="ai-usage-admin__stat-label">Credits spent</div>
                  <div className="ai-usage-admin__stat-value">
                    {totalCreditsSpent.toLocaleString()}
                  </div>
                </div>
              </div>
            )
          )}

          {section === 'overview' && isExternalProvider && (
            <>
              <div className="ai-usage-admin__grid">
                <section className="ai-usage-admin__panel">
                  <h3 className="ai-usage-admin__panel-title">
                    Cost by {isMapsProvider ? 'API' : 'Hunter API'}
                  </h3>
                  <div className="ai-usage-admin__chart-body">
                    {featureChartData.length === 0 ? (
                      <p className="ai-usage-admin__empty">No usage in this range yet.</p>
                    ) : (
                      <ResponsiveContainer width="100%" height={260}>
                        <BarChart data={featureChartData} layout="vertical" margin={{ left: 24 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                          <XAxis type="number" tick={{ fontSize: 11 }} />
                          <YAxis type="category" dataKey="feature" width={140} tick={{ fontSize: 11 }} />
                          <Tooltip />
                          <Bar dataKey="cost" name="Cost (USD)" fill="#0F766E" radius={[0, 4, 4, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    )}
                  </div>
                </section>

                <section className="ai-usage-admin__panel">
                  <h3 className="ai-usage-admin__panel-title">
                    Daily cost & units ({rangeLabel(range)})
                  </h3>
                  <div className="ai-usage-admin__chart-body">
                    {dayChartData.length === 0 ? (
                      <p className="ai-usage-admin__empty">No usage in this range yet.</p>
                    ) : (
                      <ResponsiveContainer width="100%" height={260}>
                        <LineChart data={dayChartData}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                          <XAxis dataKey="day" tick={{ fontSize: 11 }} />
                          <YAxis yAxisId="left" tick={{ fontSize: 11 }} />
                          <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} />
                          <Tooltip />
                          <Legend />
                          <Line
                            yAxisId="left"
                            type="monotone"
                            dataKey="cost"
                            name="Cost (USD)"
                            stroke="#0F766E"
                            strokeWidth={2}
                            dot={false}
                          />
                          <Line
                            yAxisId="right"
                            type="monotone"
                            dataKey="units"
                            name="Units"
                            stroke="#1D4ED8"
                            strokeWidth={2}
                            dot={false}
                          />
                        </LineChart>
                      </ResponsiveContainer>
                    )}
                  </div>
                </section>
              </div>

              <section className="ai-usage-admin__panel">
                <div className="ai-usage-admin__panel-head">
                  <h3 className="ai-usage-admin__panel-title">
                    {isMapsProvider
                      ? 'Google Maps / Places APIs used at Evecta'
                      : 'Hunter APIs used at Evecta'}
                  </h3>
                  <span className="ai-usage-admin__count">
                    {isMapsProvider ? mapsRows.length : hunterRows.length} APIs
                  </span>
                </div>
                {isMapsProvider && (
                  <p className="ai-usage-admin__panel-note">
                    Unit rates match Google Maps Platform list prices. Cache hits are not billed.
                    Geocoding first {geocodeRate?.free_monthly?.toLocaleString() || '10,000'}{' '}
                    requests/month are free on Google Essentials.
                  </p>
                )}
                <div className="ai-usage-admin__table-wrap">
                  <table className="ai-usage-admin__table">
                    <thead>
                      <tr>
                        <th>API</th>
                        {isMapsProvider && <th>Unit price</th>}
                        {isMapsProvider && <th>Free / month</th>}
                        <th>Requests</th>
                        <th>Units</th>
                        <th>Failed</th>
                        <th>Est. cost</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(isMapsProvider ? mapsRows : hunterRows).map((row) => (
                        <tr key={row.api_name}>
                          <td>
                            <div className="ai-usage-admin__user-primary">{row.label}</div>
                            {'notes' in row && row.notes ? (
                              <div className="ai-usage-admin__muted">{row.notes}</div>
                            ) : null}
                            {'endpoint' in row && row.endpoint ? (
                              <div className="ai-usage-admin__mono">{row.endpoint}</div>
                            ) : null}
                          </td>
                          {isMapsProvider && (
                            <td>
                              {'unit_cost_usd' in row && row.unit_cost_usd != null
                                ? formatUnitUsd(row.unit_cost_usd)
                                : '—'}
                            </td>
                          )}
                          {isMapsProvider && (
                            <td>
                              {'free_monthly' in row && row.free_monthly != null
                                ? row.free_monthly.toLocaleString()
                                : '—'}
                            </td>
                          )}
                          <td>{row.request_count.toLocaleString()}</td>
                          <td>{row.total_units.toLocaleString()}</td>
                          <td>{row.failed_count.toLocaleString()}</td>
                          <td>{formatUsd(row.estimated_cost_usd)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              <section className="ai-usage-admin__panel">
                <h3 className="ai-usage-admin__panel-title">
                  Daily records ({rangeLabel(range)})
                </h3>
                <div className="ai-usage-admin__table-wrap">
                  <table className="ai-usage-admin__table">
                    <thead>
                      <tr>
                        <th>Day</th>
                        <th>Requests</th>
                        <th>Units</th>
                        <th>Cost</th>
                      </tr>
                    </thead>
                    <tbody>
                      {externalDayRows.map((row) => (
                        <tr key={String(row.day)}>
                          <td>{String(row.day)}</td>
                          <td>{row.request_count.toLocaleString()}</td>
                          <td>{row.total_units.toLocaleString()}</td>
                          <td>{formatUsd(row.estimated_cost_usd)}</td>
                        </tr>
                      ))}
                      {externalDayRows.length === 0 && (
                        <tr>
                          <td colSpan={4}>No usage recorded in this range yet.</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )}

          {section === 'overview' && !isExternalProvider && (
            <>
              <div className="ai-usage-admin__grid">
                <section className="ai-usage-admin__panel">
                  <h3 className="ai-usage-admin__panel-title">Monthly cost & tokens</h3>
                  <div className="ai-usage-admin__chart-body">
                    {monthChartData.length === 0 ? (
                      <p className="ai-usage-admin__empty">No monthly usage yet.</p>
                    ) : (
                      <ResponsiveContainer width="100%" height={260}>
                        <BarChart data={monthChartData}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                          <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                          <YAxis yAxisId="left" tick={{ fontSize: 11 }} />
                          <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} />
                          <Tooltip />
                          <Legend />
                          <Bar yAxisId="left" dataKey="cost" name="Cost (USD)" fill="#0F766E" radius={[4, 4, 0, 0]} />
                          <Bar yAxisId="right" dataKey="tokens" name="Tokens" fill="#1D4ED8" radius={[4, 4, 0, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    )}
                  </div>
                </section>

                <section className="ai-usage-admin__panel">
                  <h3 className="ai-usage-admin__panel-title">Daily cost & tokens ({rangeLabel(range)})</h3>
                  <div className="ai-usage-admin__chart-body">
                    {dayChartData.length === 0 ? (
                      <p className="ai-usage-admin__empty">No usage in this range yet.</p>
                    ) : (
                      <ResponsiveContainer width="100%" height={260}>
                        <LineChart data={dayChartData}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                          <XAxis dataKey="day" tick={{ fontSize: 11 }} />
                          <YAxis yAxisId="left" tick={{ fontSize: 11 }} />
                          <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} />
                          <Tooltip />
                          <Legend />
                          <Line yAxisId="left" type="monotone" dataKey="cost" name="Cost (USD)" stroke="#0F766E" strokeWidth={2} dot={false} />
                          <Line yAxisId="right" type="monotone" dataKey="tokens" name="Tokens" stroke="#1D4ED8" strokeWidth={2} dot={false} />
                        </LineChart>
                      </ResponsiveContainer>
                    )}
                  </div>
                </section>
              </div>

              <section className="ai-usage-admin__panel">
                <div className="ai-usage-admin__panel-head">
                  <h3 className="ai-usage-admin__panel-title">Google Maps / Places rates (Evecta)</h3>
                  <span className="ai-usage-admin__count">
                    Est. spend ({rangeLabel(range)}):{' '}
                    {formatUsd(placesSummary?.estimated_cost_usd || 0)}
                  </span>
                </div>
                <div className="ai-usage-admin__table-wrap">
                  <table className="ai-usage-admin__table">
                    <thead>
                      <tr>
                        <th>API</th>
                        <th>Unit price</th>
                        <th>Free / month</th>
                        <th>Requests</th>
                        <th>Cost</th>
                      </tr>
                    </thead>
                    <tbody>
                      {mapsRows.map((row) => (
                        <tr key={row.api_name}>
                          <td>
                            <div className="ai-usage-admin__user-primary">{row.label}</div>
                            {row.endpoint && (
                              <div className="ai-usage-admin__muted">{row.endpoint}</div>
                            )}
                          </td>
                          <td>{formatUnitUsd(row.unit_cost_usd)}</td>
                          <td>
                            {row.free_monthly != null
                              ? row.free_monthly.toLocaleString()
                              : '—'}
                          </td>
                          <td>{row.request_count.toLocaleString()}</td>
                          <td>{formatUsd(row.estimated_cost_usd)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              <section className="ai-usage-admin__panel">
                <h3 className="ai-usage-admin__panel-title">Total per month (all users)</h3>
                <div className="ai-usage-admin__table-wrap">
                  <table className="ai-usage-admin__table">
                    <thead>
                      <tr>
                        <th>Month</th>
                        <th>Requests</th>
                        <th>Input</th>
                        <th>Output</th>
                        <th>Total tokens</th>
                        <th>Cost</th>
                      </tr>
                    </thead>
                    <tbody>
                      {byMonth.map((row) => (
                        <tr key={row.month}>
                          <td>{formatMonthLabel(row.month)}</td>
                          <td>{row.request_count.toLocaleString()}</td>
                          <td>{formatTokens(row.input_tokens)}</td>
                          <td>{formatTokens(row.output_tokens)}</td>
                          <td>{formatTokens(row.total_tokens)}</td>
                          <td>{formatUsd(row.estimated_cost_usd)}</td>
                        </tr>
                      ))}
                      {byMonth.length === 0 && (
                        <tr>
                          <td colSpan={6}>No monthly Gemini usage yet.</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )}

          {section === 'users' && isExternalProvider && (
            <section className="ai-usage-admin__panel">
              <div className="ai-usage-admin__panel-head">
                <h3 className="ai-usage-admin__panel-title">
                  Recent {isMapsProvider ? 'Maps API' : 'Hunter'} records
                </h3>
                <span className="ai-usage-admin__count">{externalRecent.length} events</span>
              </div>
              <div className="ai-usage-admin__table-wrap">
                <table className="ai-usage-admin__table">
                  <thead>
                    <tr>
                      <th>When</th>
                      <th>API</th>
                      <th>Feature</th>
                      <th>Status</th>
                      <th>Units</th>
                      <th>Cost</th>
                      <th>Meta</th>
                    </tr>
                  </thead>
                  <tbody>
                    {externalRecent.map((row) => (
                      <tr key={row.id}>
                        <td>{new Date(row.created_at).toLocaleString()}</td>
                        <td>{row.api_name}</td>
                        <td>{row.feature}</td>
                        <td>{row.status}</td>
                        <td>{row.units.toLocaleString()}</td>
                        <td>{formatUsd(row.estimated_cost_usd)}</td>
                        <td className="ai-usage-admin__muted">{row.meta || '—'}</td>
                      </tr>
                    ))}
                    {externalRecent.length === 0 && (
                      <tr>
                        <td colSpan={7}>No recorded events in this range yet.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {section === 'users' && !isExternalProvider && (
            <div className="ai-usage-admin__grid">
              <section className="ai-usage-admin__panel">
                <div className="ai-usage-admin__panel-head">
                  <h3 className="ai-usage-admin__panel-title">Users in selected range</h3>
                  <span className="ai-usage-admin__count">{filteredByUser.length} users</span>
                </div>
                <div className="ai-usage-admin__table-wrap">
                  <table className="ai-usage-admin__table">
                    <thead>
                      <tr>
                        <th>User</th>
                        <th>Requests</th>
                        <th>Input</th>
                        <th>Output</th>
                        <th>Total</th>
                        <th>Cost</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredByUser.map((row) => (
                        <tr key={row.user_id || row.email || 'unassigned'}>
                          <td>
                            <div className="ai-usage-admin__user-primary">
                              {userDisplay(row.email, row.username)}
                            </div>
                            {row.username && (
                              <div className="ai-usage-admin__muted">{row.username}</div>
                            )}
                          </td>
                          <td>{row.request_count.toLocaleString()}</td>
                          <td>{formatTokens(row.input_tokens)}</td>
                          <td>{formatTokens(row.output_tokens)}</td>
                          <td>{formatTokens(row.total_tokens)}</td>
                          <td>{formatUsd(row.estimated_cost_usd)}</td>
                        </tr>
                      ))}
                      {filteredByUser.length === 0 && (
                        <tr>
                          <td colSpan={6}>
                            {searchQuery
                              ? 'No users match your search.'
                              : 'No Gemini usage recorded in this range yet.'}
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </section>

              <section className="ai-usage-admin__panel">
                <div className="ai-usage-admin__panel-head">
                  <h3 className="ai-usage-admin__panel-title">Per user per month</h3>
                  <span className="ai-usage-admin__count">{filteredByUserMonth.length} rows</span>
                </div>
                <div className="ai-usage-admin__table-wrap">
                  <table className="ai-usage-admin__table">
                    <thead>
                      <tr>
                        <th>Month</th>
                        <th>User</th>
                        <th>Requests</th>
                        <th>Input</th>
                        <th>Output</th>
                        <th>Cost</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredByUserMonth.map((row) => (
                        <tr key={`${row.month}:${row.user_id || row.email || 'unassigned'}`}>
                          <td>{formatMonthLabel(row.month)}</td>
                          <td>
                            <div className="ai-usage-admin__user-primary">
                              {userDisplay(row.email, row.username)}
                            </div>
                            {row.username && (
                              <div className="ai-usage-admin__muted">{row.username}</div>
                            )}
                          </td>
                          <td>{row.request_count.toLocaleString()}</td>
                          <td>{formatTokens(row.input_tokens)}</td>
                          <td>{formatTokens(row.output_tokens)}</td>
                          <td>{formatUsd(row.estimated_cost_usd)}</td>
                        </tr>
                      ))}
                      {filteredByUserMonth.length === 0 && (
                        <tr>
                          <td colSpan={6}>
                            {searchQuery
                              ? 'No users match your search.'
                              : 'No per-user monthly usage yet.'}
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </section>
            </div>
          )}

          {section === 'features' && isExternalProvider && (
            <>
              <section className="ai-usage-admin__panel">
                <h3 className="ai-usage-admin__panel-title">
                  Cost by {isMapsProvider ? 'Maps API' : 'Hunter API'}
                </h3>
                <div className="ai-usage-admin__chart-body">
                  {featureChartData.length === 0 ? (
                    <p className="ai-usage-admin__empty">No API breakdown yet.</p>
                  ) : (
                    <ResponsiveContainer width="100%" height={280}>
                      <BarChart data={featureChartData} layout="vertical" margin={{ left: 24 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                        <XAxis type="number" tick={{ fontSize: 11 }} />
                        <YAxis type="category" dataKey="feature" width={140} tick={{ fontSize: 11 }} />
                        <Tooltip />
                        <Bar dataKey="cost" name="Cost (USD)" fill="#0F766E" radius={[0, 4, 4, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  )}
                </div>
              </section>

              <section className="ai-usage-admin__panel">
                <h3 className="ai-usage-admin__panel-title">API usage + pricing</h3>
                <div className="ai-usage-admin__table-wrap">
                  <table className="ai-usage-admin__table">
                    <thead>
                      <tr>
                        <th>API</th>
                        <th>Requests</th>
                        <th>Units</th>
                        <th>Cost</th>
                        <th>Share</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(isMapsProvider ? mapsRows : hunterRows).map((row) => {
                        const cost = Number(row.estimated_cost_usd || 0);
                        const total = isMapsProvider
                          ? mapsApiCostTotal
                          : hunterRows.reduce((s, r) => s + Number(r.estimated_cost_usd || 0), 0);
                        const share = total > 0 ? (cost / total) * 100 : 0;
                        return (
                          <tr key={row.api_name}>
                            <td>{row.label}</td>
                            <td>{row.request_count.toLocaleString()}</td>
                            <td>{row.total_units.toLocaleString()}</td>
                            <td>{formatUsd(cost)}</td>
                            <td>{share.toFixed(1)}%</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )}

          {section === 'features' && !isExternalProvider && (
            <>
              <section className="ai-usage-admin__panel">
                <h3 className="ai-usage-admin__panel-title">Cost by feature</h3>
                <div className="ai-usage-admin__chart-body">
                  {featureChartData.length === 0 ? (
                    <p className="ai-usage-admin__empty">No feature breakdown yet.</p>
                  ) : (
                    <ResponsiveContainer width="100%" height={280}>
                      <BarChart data={featureChartData} layout="vertical" margin={{ left: 24 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                        <XAxis type="number" tick={{ fontSize: 11 }} />
                        <YAxis type="category" dataKey="feature" width={140} tick={{ fontSize: 11 }} />
                        <Tooltip />
                        <Bar dataKey="cost" name="Cost (USD)" fill="#0F766E" radius={[0, 4, 4, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  )}
                </div>
              </section>

              <div className="ai-usage-admin__grid">
                <section className="ai-usage-admin__panel">
                  <h3 className="ai-usage-admin__panel-title">By feature (tokens + cost)</h3>
                  <div className="ai-usage-admin__table-wrap">
                    <table className="ai-usage-admin__table">
                      <thead>
                        <tr>
                          <th>Feature</th>
                          <th>Requests</th>
                          <th>Input</th>
                          <th>Output</th>
                          <th>Thinking</th>
                          <th>Cached</th>
                          <th>Cost</th>
                          <th>Share</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredByFeature.map((row) => {
                          const cost = Number(row.estimated_cost_usd || 0);
                          const share =
                            featureCostTotal > 0 ? (cost / featureCostTotal) * 100 : 0;
                          return (
                            <tr key={row.feature}>
                              <td>{featureLabel(row.feature)}</td>
                              <td>{row.request_count.toLocaleString()}</td>
                              <td>{formatTokens(row.input_tokens)}</td>
                              <td>{formatTokens(row.output_tokens)}</td>
                              <td>{formatTokens(row.reasoning_tokens || 0)}</td>
                              <td>{formatTokens(row.cached_tokens || 0)}</td>
                              <td>{formatUsd(cost)}</td>
                              <td>{share.toFixed(1)}%</td>
                            </tr>
                          );
                        })}
                        {filteredByFeature.length === 0 && (
                          <tr>
                            <td colSpan={8}>No Gemini usage for this filter yet.</td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </section>

                <section className="ai-usage-admin__panel">
                  <h3 className="ai-usage-admin__panel-title">By model</h3>
                  <div className="ai-usage-admin__table-wrap">
                    <table className="ai-usage-admin__table">
                      <thead>
                        <tr>
                          <th>Provider</th>
                          <th>Model</th>
                          <th>Requests</th>
                          <th>Input</th>
                          <th>Output</th>
                          <th>Cost</th>
                        </tr>
                      </thead>
                      <tbody>
                        {byModel.map((row) => (
                          <tr key={`${row.provider}:${row.model}`}>
                            <td>{row.provider}</td>
                            <td>{row.model}</td>
                            <td>{row.request_count.toLocaleString()}</td>
                            <td>{formatTokens(row.input_tokens)}</td>
                            <td>{formatTokens(row.output_tokens)}</td>
                            <td>{formatUsd(row.estimated_cost_usd)}</td>
                          </tr>
                        ))}
                        {byModel.length === 0 && (
                          <tr>
                            <td colSpan={6}>No model data yet.</td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </section>
              </div>
            </>
          )}

          {section === 'credits' && (
            <section className="ai-usage-admin__panel">
              <div className="ai-usage-admin__panel-head">
                <h3 className="ai-usage-admin__panel-title">
                  Product credits used ({rangeLabel(range)})
                </h3>
                <span className="ai-usage-admin__count">{filteredCredits.length} users</span>
              </div>
              <div className="ai-usage-admin__table-wrap">
                <table className="ai-usage-admin__table">
                  <thead>
                    <tr>
                      <th>User</th>
                      <th>Lead</th>
                      <th>Spam check</th>
                      <th>Email send</th>
                      <th>Total spent</th>
                      <th>Remaining</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredCredits.map((row) => (
                      <tr key={row.user_id}>
                        <td>
                          <div className="ai-usage-admin__user-primary">
                            {userDisplay(row.email, row.username)}
                          </div>
                          {row.username && (
                            <div className="ai-usage-admin__muted">{row.username}</div>
                          )}
                        </td>
                        <td>{row.credits_spent_lead.toLocaleString()}</td>
                        <td>{row.credits_spent_email_gen.toLocaleString()}</td>
                        <td>{row.credits_spent_outreach.toLocaleString()}</td>
                        <td>{row.credits_spent_total.toLocaleString()}</td>
                        <td>
                          {row.credits_remaining_lead}/{row.credits_remaining_email_gen}/
                          {row.credits_remaining_outreach}
                        </td>
                      </tr>
                    ))}
                    {filteredCredits.length === 0 && (
                      <tr>
                        <td colSpan={6}>
                          {searchQuery
                            ? 'No users match your search.'
                            : 'No credit spend in this range yet.'}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}
