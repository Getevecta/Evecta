import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import { Loader2, RefreshCw, Search } from 'lucide-react';
import {
  apiService,
  type AdminTopupHistoryItem,
  type AdminUserBalanceResponse,
  type UserList,
} from '@/shared/services/api';
import { useAuth } from '@/shared/contexts/AuthContext';
import { CREDIT_POOL_ORDER, CREDIT_POOL_UI_LABELS } from '@/shared/billing/creditPools';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { AdminFilterDropdown } from './AdminFilterDropdown';
import './AdminCreditsPage.css';

type PoolAmounts = Record<(typeof CREDIT_POOL_ORDER)[number], string>;
type SectionKey = 'grant' | 'log';

const EMPTY_AMOUNTS: PoolAmounts = {
  lead: '',
  email_gen: '',
  outreach: '',
};

function parseAmount(raw: string): number {
  const n = Number.parseInt(raw.replace(/,/g, '').trim(), 10);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

export function AdminCreditsPage() {
  const { user: authUser } = useAuth();
  const [section, setSection] = useState<SectionKey>('grant');
  const [users, setUsers] = useState<UserList[]>([]);
  const [query, setQuery] = useState('');
  const [historyQuery, setHistoryQuery] = useState('');
  const [selectedUserId, setSelectedUserId] = useState<string>('');
  const [amounts, setAmounts] = useState<PoolAmounts>(EMPTY_AMOUNTS);
  const [reason, setReason] = useState('');
  const [balance, setBalance] = useState<AdminUserBalanceResponse | null>(null);
  const [history, setHistory] = useState<AdminTopupHistoryItem[]>([]);
  const [loadingUsers, setLoadingUsers] = useState(true);
  const [loadingBalance, setLoadingBalance] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const loadUsersAndHistory = useCallback(async () => {
    setLoadingUsers(true);
    setError(null);
    try {
      const [u, h] = await Promise.all([
        apiService.getAllUsers(),
        apiService.getAdminTopupHistory(50),
      ]);
      if (u.error) {
        setError(u.error);
        return;
      }
      setUsers(u.data || []);
      setHistory(h.data || []);
      if (h.error) {
        console.warn(h.error);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load users');
    } finally {
      setLoadingUsers(false);
    }
  }, []);

  useEffect(() => {
    void loadUsersAndHistory();
  }, [loadUsersAndHistory]);

  const filteredUsers = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return users;
    return users.filter(
      (u) =>
        u.email?.toLowerCase().includes(q) ||
        u.username?.toLowerCase().includes(q) ||
        u.full_name?.toLowerCase().includes(q),
    );
  }, [users, query]);

  const filteredHistory = useMemo(() => {
    const q = historyQuery.trim().toLowerCase();
    if (!q) return history;
    return history.filter(
      (row) =>
        (row.email || '').toLowerCase().includes(q) ||
        (row.username || '').toLowerCase().includes(q) ||
        (row.description || '').toLowerCase().includes(q) ||
        (row.pool || '').toLowerCase().includes(q),
    );
  }, [history, historyQuery]);

  const userOptions = useMemo(
    () =>
      filteredUsers.map((u) => ({
        value: u.id,
        label: u.email || u.id,
        secondary: u.username || u.full_name || undefined,
      })),
    [filteredUsers],
  );

  const selectedUser = useMemo(
    () => users.find((u) => u.id === selectedUserId) || null,
    [users, selectedUserId],
  );

  const loadBalance = useCallback(async (userId: string) => {
    if (!userId) {
      setBalance(null);
      return;
    }
    setLoadingBalance(true);
    try {
      const res = await apiService.getAdminUserCreditBalance(userId);
      if (res.error) {
        setError(res.error);
        setBalance(null);
        return;
      }
      setBalance(res.data || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load balance');
      setBalance(null);
    } finally {
      setLoadingBalance(false);
    }
  }, []);

  useEffect(() => {
    if (selectedUserId) void loadBalance(selectedUserId);
    else setBalance(null);
  }, [selectedUserId, loadBalance]);

  const selectMyself = () => {
    if (!authUser?.id) return;
    setSelectedUserId(authUser.id);
    setQuery(authUser.email || '');
    setSuccess(null);
    setError(null);
  };

  const totalToGrant =
    parseAmount(amounts.lead) + parseAmount(amounts.email_gen) + parseAmount(amounts.outreach);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSuccess(null);
    setError(null);
    if (!selectedUserId) {
      setError('Select a user first.');
      return;
    }
    if (totalToGrant <= 0) {
      setError('Enter at least one credit amount greater than 0.');
      return;
    }
    setSubmitting(true);
    try {
      const res = await apiService.adminTopupCredits({
        user_id: selectedUserId,
        lead: parseAmount(amounts.lead),
        email_gen: parseAmount(amounts.email_gen),
        outreach: parseAmount(amounts.outreach),
        reason: reason.trim() || undefined,
      });
      if (res.error) {
        setError(res.error);
        return;
      }
      const grantSummary = (res.data?.grants || [])
        .map(
          (g) =>
            `${g.amount.toLocaleString()} ${CREDIT_POOL_UI_LABELS[g.pool as keyof typeof CREDIT_POOL_UI_LABELS] || g.pool}`,
        )
        .join(', ');
      setSuccess(`Topped up ${selectedUser?.email || selectedUserId}: ${grantSummary}`);
      setAmounts(EMPTY_AMOUNTS);
      setReason('');
      await Promise.all([loadBalance(selectedUserId), loadUsersAndHistory()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Top-up failed');
    } finally {
      setSubmitting(false);
    }
  };

  const searchValue = section === 'grant' ? query : historyQuery;
  const setSearchValue = section === 'grant' ? setQuery : setHistoryQuery;

  return (
    <div className="admin-credits">
      <div className="admin-credits__intro">
        <p className="admin-credits__subtitle">
          Add top-up credits to any user without a card charge. Same top-up bucket as Stripe
          purchases, logged in credit_transactions. Admins only.
        </p>
      </div>

      <div className="admin-credits__filter-bar">
        <div className="admin-credits__tabs" role="tablist" aria-label="Credits sections">
          {(
            [
              ['grant', 'Grant top-up'],
              ['log', 'Top-up log'],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={section === key}
              className={`admin-credits__tab${section === key ? ' admin-credits__tab--active' : ''}`}
              onClick={() => setSection(key)}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="admin-credits__filter-spacer" aria-hidden />

        <div className="admin-credits__search">
          <Search className="admin-credits__search-icon" size={14} strokeWidth={2} aria-hidden />
          <Input
            type="search"
            placeholder={
              section === 'grant'
                ? 'Search users by email or username…'
                : 'Search top-up log…'
            }
            value={searchValue}
            onChange={(e) => setSearchValue(e.target.value)}
            disabled={section === 'grant' && loadingUsers}
            className="admin-credits__search-input focus-visible:ring-0 focus-visible:ring-transparent focus-visible:border-none focus-visible:ring-offset-0"
          />
        </div>

        {section === 'grant' && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="admin-credits__chip-btn"
            onClick={selectMyself}
            disabled={!authUser?.id}
          >
            Myself
          </Button>
        )}

        <Button
          type="button"
          variant="outline"
          size="sm"
          className="admin-credits__refresh"
          onClick={() => void loadUsersAndHistory()}
          disabled={loadingUsers}
        >
          <RefreshCw className={`h-3.5 w-3.5${loadingUsers ? ' animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {error && (
        <div className="admin-credits__banner admin-credits__banner--error" role="alert">
          {error}
        </div>
      )}
      {success && (
        <div className="admin-credits__banner admin-credits__banner--ok" role="status">
          {success}
        </div>
      )}

      {section === 'grant' && (
        <section className="admin-credits__panel admin-credits__panel--grant">
          <h3 className="admin-credits__panel-title">Grant top-up</h3>
          <form className="admin-credits__form" onSubmit={(e) => void handleSubmit(e)}>
            <div className="admin-credits__field">
              <label>User</label>
              <AdminFilterDropdown
                wide
                options={userOptions}
                value={selectedUserId}
                disabled={loadingUsers}
                placeholder="Select a user…"
                emptyLabel="Select a user…"
                onChange={(next) => {
                  setSelectedUserId(next);
                  setSuccess(null);
                  setError(null);
                }}
              />
              {query && filteredUsers.length === 0 && (
                <p className="admin-credits__muted">No users match your search.</p>
              )}
            </div>

            {selectedUserId && (
              <div className="admin-credits__balance">
                <div className="admin-credits__balance-title">
                  Current balance
                  {loadingBalance && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                </div>
                {balance ? (
                  <ul>
                    {CREDIT_POOL_ORDER.map((pool) => (
                      <li key={pool}>
                        <span>{CREDIT_POOL_UI_LABELS[pool]}</span>
                        <strong>
                          {(balance.balances[pool] ?? 0).toLocaleString()}
                          <span className="admin-credits__muted">
                            {' '}
                            (top-up {(balance.topup_balances[pool] ?? 0).toLocaleString()})
                          </span>
                        </strong>
                      </li>
                    ))}
                  </ul>
                ) : (
                  !loadingBalance && <p className="admin-credits__muted">No balance loaded.</p>
                )}
              </div>
            )}

            <div className="admin-credits__amounts">
              {CREDIT_POOL_ORDER.map((pool) => (
                <div className="admin-credits__field" key={pool}>
                  <label htmlFor={`admin-credits-${pool}`}>{CREDIT_POOL_UI_LABELS[pool]}</label>
                  <Input
                    id={`admin-credits-${pool}`}
                    type="number"
                    min={0}
                    max={500000}
                    step={1}
                    placeholder="0"
                    value={amounts[pool]}
                    onChange={(e) =>
                      setAmounts((prev) => ({ ...prev, [pool]: e.target.value }))
                    }
                    className="admin-credits__input focus-visible:ring-0 focus-visible:ring-transparent focus-visible:border-none focus-visible:ring-offset-0"
                  />
                </div>
              ))}
            </div>

            <div className="admin-credits__field">
              <label htmlFor="admin-credits-reason">Reason (optional)</label>
              <Input
                id="admin-credits-reason"
                type="text"
                maxLength={500}
                placeholder="e.g. Support compensation, internal testing"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                className="admin-credits__input focus-visible:ring-0 focus-visible:ring-transparent focus-visible:border-none focus-visible:ring-offset-0"
              />
            </div>

            <Button
              type="submit"
              className="admin-credits__submit"
              disabled={submitting || !selectedUserId || totalToGrant <= 0}
            >
              {submitting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Adding…
                </>
              ) : (
                `Add ${totalToGrant > 0 ? totalToGrant.toLocaleString() : ''} top-up credits`
              )}
            </Button>
          </form>
        </section>
      )}

      {section === 'log' && (
        <section className="admin-credits__panel">
          <div className="admin-credits__panel-head">
            <h3 className="admin-credits__panel-title">Admin top-up log</h3>
            <span className="admin-credits__count">{filteredHistory.length} records</span>
          </div>
          <div className="admin-credits__table-wrap">
            <table className="admin-credits__table">
              <thead>
                <tr>
                  <th>When</th>
                  <th>User</th>
                  <th>Pool</th>
                  <th>Amount</th>
                  <th>Description</th>
                </tr>
              </thead>
              <tbody>
                {filteredHistory.map((row) => (
                  <tr key={row.id}>
                    <td>{new Date(row.created_at).toLocaleString()}</td>
                    <td>
                      <div className="admin-credits__user-primary">
                        {row.email || row.user_id}
                      </div>
                      {row.username && (
                        <div className="admin-credits__muted">{row.username}</div>
                      )}
                    </td>
                    <td>
                      {CREDIT_POOL_UI_LABELS[row.pool as keyof typeof CREDIT_POOL_UI_LABELS] ||
                        row.pool}
                    </td>
                    <td>+{row.amount.toLocaleString()}</td>
                    <td className="admin-credits__desc">{row.description || '—'}</td>
                  </tr>
                ))}
                {filteredHistory.length === 0 && (
                  <tr>
                    <td colSpan={5}>
                      {historyQuery
                        ? 'No top-ups match your search.'
                        : 'No admin top-ups yet.'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
