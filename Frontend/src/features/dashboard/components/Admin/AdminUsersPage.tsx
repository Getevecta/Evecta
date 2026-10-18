import { useCallback, useEffect, useMemo, useState } from 'react';
import { Check, Loader2, RefreshCw, Search, X } from 'lucide-react';
import { toast } from 'sonner';
import {
  apiService,
  type AdminPlanId,
  type UserList,
} from '@/shared/services/api';
import { useAuth } from '@/shared/contexts/AuthContext';
import { Button } from '../ui/button';
import { DashboardPagination } from '../ui/DashboardPagination';
import { AdminFilterDropdown } from './AdminFilterDropdown';
import './AdminUsersPage.css';

const PLAN_OPTIONS: AdminPlanId[] = ['free', 'starter', 'growth', 'scale'];

const PLAN_FILTER_OPTIONS = PLAN_OPTIONS.map((p) => ({
  value: p,
  label: p.charAt(0).toUpperCase() + p.slice(1),
}));

const PLAN_EDIT_OPTIONS = PLAN_FILTER_OPTIONS;

function formatDateTime(value?: string | null): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function normalizePlan(plan?: string | null): AdminPlanId {
  const p = (plan || 'free').trim().toLowerCase();
  return (PLAN_OPTIONS.includes(p as AdminPlanId) ? p : 'free') as AdminPlanId;
}

function planLabel(plan?: string | null): string {
  const p = normalizePlan(plan);
  return p.charAt(0).toUpperCase() + p.slice(1);
}

function roleName(user: UserList): string {
  return user.role_obj?.name || user.role?.name || '—';
}

export function AdminUsersPage() {
  const { user: authUser } = useAuth();
  const [users, setUsers] = useState<UserList[]>([]);
  const [query, setQuery] = useState('');
  const [planFilter, setPlanFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftPlan, setDraftPlan] = useState<AdminPlanId>('free');
  const [savingId, setSavingId] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(10);

  const loadUsers = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiService.getAllUsers();
      if (res.error) {
        toast.error(res.error);
        return;
      }
      setUsers(res.data || []);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to load users');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  const filteredUsers = useMemo(() => {
    const q = query.trim().toLowerCase();
    return users.filter((u) => {
      const plan = normalizePlan(u.plan);
      if (planFilter && plan !== planFilter) return false;
      if (!q) return true;
      return (
        u.email?.toLowerCase().includes(q) ||
        u.username?.toLowerCase().includes(q) ||
        u.full_name?.toLowerCase().includes(q) ||
        plan.includes(q) ||
        roleName(u).toLowerCase().includes(q)
      );
    });
  }, [users, query, planFilter]);

  useEffect(() => {
    setCurrentPage(1);
    setEditingId(null);
  }, [query, planFilter]);

  const totalPages = Math.ceil(filteredUsers.length / itemsPerPage) || 1;
  useEffect(() => {
    if (currentPage > totalPages) setCurrentPage(totalPages);
  }, [currentPage, totalPages]);

  const pagedUsers = useMemo(() => {
    const start = (currentPage - 1) * itemsPerPage;
    return filteredUsers.slice(start, start + itemsPerPage);
  }, [filteredUsers, currentPage, itemsPerPage]);

  const startEdit = (user: UserList) => {
    setEditingId(user.id);
    setDraftPlan(normalizePlan(user.plan));
  };

  const cancelEdit = () => {
    setEditingId(null);
    setDraftPlan('free');
  };

  const handleSavePlan = async (user: UserList) => {
    const nextPlan = draftPlan;
    const currentPlan = normalizePlan(user.plan);
    if (nextPlan === currentPlan) {
      toast.success(`Already on ${planLabel(nextPlan)}.`);
      cancelEdit();
      return;
    }
    if (
      !window.confirm(
        `Change ${user.email} from ${planLabel(currentPlan)} to ${planLabel(nextPlan)}?\n\n` +
          'This updates their app plan and subscription credit buckets.',
      )
    ) {
      return;
    }

    setSavingId(user.id);
    try {
      const res = await apiService.updateUserPlan(user.id, {
        plan: nextPlan,
        plan_billing_interval: 'month',
      });
      if (res.error) {
        toast.error(res.error);
        return;
      }
      toast.success(res.data?.message || `Updated ${user.email} to ${planLabel(nextPlan)}.`);
      setEditingId(null);
      await loadUsers();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to update plan');
    } finally {
      setSavingId(null);
    }
  };

  if (authUser && !(authUser.is_admin || authUser.is_superuser || authUser.role === 'admin')) {
    return (
      <div className="admin-users">
        <p className="admin-users__subtitle">Admin credentials are required to view users.</p>
      </div>
    );
  }

  return (
    <div className="admin-users">
      <div className="admin-users__intro">
        <p className="admin-users__subtitle">
          All registered accounts — email, signup time, last login, and package. Click Edit to
          change a user&apos;s plan.
        </p>
      </div>

      <div className="admin-users__filter-bar">
        <div className="admin-users__search">
          <Search className="admin-users__search-icon" size={14} strokeWidth={2} aria-hidden />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search email, username, plan…"
            className="admin-users__search-input"
            aria-label="Search users"
          />
        </div>

        <AdminFilterDropdown
          options={PLAN_FILTER_OPTIONS}
          value={planFilter}
          onChange={setPlanFilter}
          placeholder="All plans"
          emptyLabel="All plans"
        />

        <div className="admin-users__filter-spacer" aria-hidden />

        <Button
          type="button"
          variant="outline"
          size="sm"
          className="admin-users__refresh"
          onClick={() => void loadUsers()}
          disabled={loading}
        >
          {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          Refresh
        </Button>
      </div>

      <div className="admin-users__main dashboard-content-with-pagination">
        <div className="admin-users__table-wrap dashboard-pagination-scroll-area">
          <table className="admin-users__table">
            <thead>
              <tr>
                <th>User</th>
                <th>Email</th>
                <th>Verified</th>
                <th>Status</th>
                <th>Signed up</th>
                <th>Last login</th>
                <th>Role</th>
                <th>Package</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && users.length === 0 ? (
                <tr>
                  <td colSpan={9} className="admin-users__muted">
                    <Loader2 size={16} className="animate-spin inline-block mr-2" />
                    Loading users…
                  </td>
                </tr>
              ) : pagedUsers.length === 0 ? (
                <tr>
                  <td colSpan={9} className="admin-users__muted">
                    No users match your filters.
                  </td>
                </tr>
              ) : (
                pagedUsers.map((u) => {
                  const current = normalizePlan(u.plan);
                  const isEditing = editingId === u.id;
                  const saving = savingId === u.id;
                  const verified = !!u.email_verified;
                  return (
                    <tr key={u.id} className={isEditing ? 'admin-users__row--editing' : undefined}>
                      <td>
                        <div className="admin-users__user-primary">
                          {u.username || u.full_name || '—'}
                        </div>
                        {u.full_name && u.username && u.full_name !== u.username ? (
                          <div className="admin-users__muted">{u.full_name}</div>
                        ) : null}
                      </td>
                      <td>{u.email}</td>
                      <td>
                        <span
                          className={`admin-users__badge${
                            verified ? ' admin-users__badge--verified' : ' admin-users__badge--unverified'
                          }`}
                        >
                          {verified ? 'Verified' : 'Unverified'}
                        </span>
                      </td>
                      <td>
                        <span
                          className={`admin-users__badge${
                            u.is_active ? ' admin-users__badge--active' : ' admin-users__badge--inactive'
                          }`}
                        >
                          {u.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td>{formatDateTime(u.created_at)}</td>
                      <td>{formatDateTime(u.last_login_at)}</td>
                      <td>{roleName(u)}</td>
                      <td>
                        {isEditing ? (
                          <AdminFilterDropdown
                            className="admin-users__plan-dropdown"
                            options={PLAN_EDIT_OPTIONS}
                            value={draftPlan}
                            onChange={(v) => {
                              if (v) setDraftPlan(v as AdminPlanId);
                            }}
                            placeholder="Select plan"
                            hideEmptyOption
                            hideFilterIcon
                            portalMenu
                            disabled={saving}
                          />
                        ) : (
                          <span className={`admin-users__plan admin-users__plan--${current}`}>
                            {planLabel(current)}
                            {u.plan_billing_interval && current !== 'free'
                              ? ` / ${u.plan_billing_interval}`
                              : ''}
                          </span>
                        )}
                      </td>
                      <td>
                        {isEditing ? (
                          <div className="admin-users__plan-actions">
                            <button
                              type="button"
                              className="admin-users__icon-btn admin-users__icon-btn--save"
                              disabled={saving}
                              onClick={() => void handleSavePlan(u)}
                              aria-label="Save plan"
                              title="Save"
                            >
                              {saving ? (
                                <Loader2 size={14} className="animate-spin" />
                              ) : (
                                <Check size={14} strokeWidth={2.5} />
                              )}
                            </button>
                            <button
                              type="button"
                              className="admin-users__icon-btn admin-users__icon-btn--cancel"
                              disabled={saving}
                              onClick={cancelEdit}
                              aria-label="Cancel"
                              title="Cancel"
                            >
                              <X size={14} strokeWidth={2.5} />
                            </button>
                          </div>
                        ) : (
                          <button
                            type="button"
                            className="admin-users__link-btn"
                            onClick={() => startEdit(u)}
                          >
                            Edit
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        <div className="dashboard-pagination-fixed">
          <DashboardPagination
            totalItems={filteredUsers.length}
            currentPage={currentPage}
            itemsPerPage={itemsPerPage}
            onPageChange={setCurrentPage}
            onItemsPerPageChange={(v) => {
              setItemsPerPage(v);
              setCurrentPage(1);
              setEditingId(null);
            }}
            itemLabel="users"
          />
        </div>
      </div>
    </div>
  );
}
