import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import { Loader2, Pencil, RefreshCw, Search, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import {
  apiService,
  type SystemDomainResponse,
  type SystemMailboxResponse,
} from '@/shared/services/api';
import { useAuth } from '@/shared/contexts/AuthContext';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { AdminFilterDropdown } from './AdminFilterDropdown';
import './AdminMailboxesPage.css';

type SectionKey = 'mailboxes' | 'domains' | 'add-mailbox' | 'add-domain';

const EMPTY_MAILBOX_FORM = {
  domain_id: '',
  email: '',
  smtp_host: '',
  smtp_user: '',
  smtp_password: '',
  smtp_port: '465',
  receive_email: '',
  receive_username: '',
  receive_password: '',
  imap_host: '',
  imap_port: '993',
  daily_limit: '2',
  sameAsSmtp: true,
  provider: 'ANY_PROVIDER',
  can_receive: true,
  is_active: true,
};

const PROVIDER_OPTIONS = [
  { value: 'ANY_PROVIDER', label: 'Any provider (IMAP/SMTP)' },
  { value: 'GOOGLE', label: 'Google' },
];

function formatDate(value?: string | null) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString();
}

export function AdminMailboxesPage() {
  const { user: authUser } = useAuth();
  const isAdmin =
    !!authUser &&
    (authUser.is_admin || authUser.is_superuser || authUser.role === 'admin');

  const [section, setSection] = useState<SectionKey>('mailboxes');
  const [domains, setDomains] = useState<SystemDomainResponse[]>([]);
  const [mailboxes, setMailboxes] = useState<SystemMailboxResponse[]>([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [editingMailboxId, setEditingMailboxId] = useState<string | null>(null);
  const [editingDomainId, setEditingDomainId] = useState<string | null>(null);

  const [domainName, setDomainName] = useState('');
  const [domainDailyLimit, setDomainDailyLimit] = useState('100');
  const [domainActive, setDomainActive] = useState(true);
  const [mailboxForm, setMailboxForm] = useState(EMPTY_MAILBOX_FORM);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [d, m] = await Promise.all([
        apiService.getSystemDomains(),
        apiService.getSystemMailboxes(),
      ]);
      if (d.error) {
        setError(d.error);
        setDomains([]);
      } else {
        setDomains(d.data || []);
      }
      if (m.error) {
        setError((prev) => prev || m.error);
        setMailboxes([]);
      } else {
        setMailboxes(m.data || []);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load system mailboxes');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isAdmin) void load();
  }, [isAdmin, load]);

  const domainById = useMemo(() => {
    const map = new Map<string, SystemDomainResponse>();
    for (const d of domains) map.set(d.id, d);
    return map;
  }, [domains]);

  const filteredMailboxes = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return mailboxes;
    return mailboxes.filter((mb) => {
      const name = domainById.get(mb.domain_id)?.domain_name || '';
      return (
        mb.email?.toLowerCase().includes(q) ||
        mb.smtp_host?.toLowerCase().includes(q) ||
        mb.imap_host?.toLowerCase().includes(q) ||
        name.toLowerCase().includes(q)
      );
    });
  }, [mailboxes, query, domainById]);

  const filteredDomains = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return domains;
    return domains.filter((d) => d.domain_name?.toLowerCase().includes(q));
  }, [domains, query]);

  const domainOptions = useMemo(
    () =>
      domains.map((d) => ({
        value: d.id,
        label: d.domain_name,
        secondary: `limit ${d.daily_limit}/day`,
      })),
    [domains],
  );

  const resetMailboxForm = () => {
    setMailboxForm(EMPTY_MAILBOX_FORM);
    setEditingMailboxId(null);
  };

  const resetDomainForm = () => {
    setDomainName('');
    setDomainDailyLimit('100');
    setDomainActive(true);
    setEditingDomainId(null);
  };

  const goToSection = (key: SectionKey) => {
    setSection(key);
    setError(null);
    if (key === 'add-mailbox' && !editingMailboxId) resetMailboxForm();
    if (key === 'add-domain' && !editingDomainId) resetDomainForm();
    if (key === 'mailboxes') resetMailboxForm();
    if (key === 'domains') resetDomainForm();
  };

  const updateMailboxField = <K extends keyof typeof EMPTY_MAILBOX_FORM>(
    key: K,
    value: (typeof EMPTY_MAILBOX_FORM)[K],
  ) => {
    setMailboxForm((prev) => {
      const next = { ...prev, [key]: value };
      if (key === 'sameAsSmtp' && value === true) {
        next.receive_email = prev.email;
        next.receive_username = prev.smtp_user || prev.email;
        next.receive_password = prev.smtp_password;
      }
      if (prev.sameAsSmtp) {
        if (key === 'email') {
          next.receive_email = String(value);
          if (!prev.smtp_user) next.smtp_user = String(value);
          if (!prev.receive_username) next.receive_username = String(value);
        }
        if (key === 'smtp_user') next.receive_username = String(value);
        if (key === 'smtp_password') next.receive_password = String(value);
      }
      return next;
    });
  };

  const startEditMailbox = (mb: SystemMailboxResponse) => {
    const sameAsSmtp =
      !mb.receive_email ||
      (mb.receive_email === mb.email &&
        (!mb.receive_username || mb.receive_username === mb.smtp_user));
    setMailboxForm({
      domain_id: mb.domain_id,
      email: mb.email || '',
      smtp_host: mb.smtp_host || '',
      smtp_user: mb.smtp_user || '',
      smtp_password: '',
      smtp_port: String(mb.port ?? 465),
      receive_email: mb.receive_email || mb.email || '',
      receive_username: mb.receive_username || mb.smtp_user || '',
      receive_password: '',
      imap_host: mb.imap_host || '',
      imap_port: String(mb.imap_port ?? 993),
      daily_limit: String(mb.daily_limit ?? 2),
      sameAsSmtp,
      provider: mb.provider === 'GOOGLE' ? 'GOOGLE' : 'ANY_PROVIDER',
      can_receive: mb.can_receive !== false,
      is_active: mb.is_active !== false,
    });
    setEditingMailboxId(mb.id);
    setSection('add-mailbox');
    setError(null);
  };

  const startEditDomain = (d: SystemDomainResponse) => {
    setDomainName(d.domain_name || '');
    setDomainDailyLimit(String(d.daily_limit ?? 100));
    setDomainActive(d.is_active !== false);
    setEditingDomainId(d.id);
    setSection('add-domain');
    setError(null);
  };

  const handleSaveDomain = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const name = domainName.trim().toLowerCase();
    const daily_limit = Number.parseInt(domainDailyLimit, 10);
    if (!name) {
      setError('Domain name is required.');
      return;
    }
    if (!Number.isFinite(daily_limit) || daily_limit <= 0) {
      setError('Domain daily limit must be a positive number.');
      return;
    }
    setSubmitting(true);
    try {
      if (editingDomainId) {
        const res = await apiService.updateSystemDomain(editingDomainId, {
          name,
          daily_limit,
          is_active: domainActive,
        });
        if (res.error) {
          setError(res.error);
          toast.error(res.error);
          return;
        }
        toast.success(`Domain ${name} updated`);
      } else {
        const res = await apiService.createSystemDomain({ name, daily_limit });
        if (res.error) {
          setError(res.error);
          toast.error(res.error);
          return;
        }
        toast.success(`Domain ${name} created`);
      }
      resetDomainForm();
      await load();
      setSection('domains');
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to save domain';
      setError(msg);
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const handleSaveMailbox = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);

    const smtp_port = Number.parseInt(mailboxForm.smtp_port, 10);
    const imap_port = Number.parseInt(mailboxForm.imap_port, 10);
    const daily_limit = Number.parseInt(mailboxForm.daily_limit, 10);
    const isEdit = !!editingMailboxId;

    const receive_email = mailboxForm.sameAsSmtp
      ? mailboxForm.email.trim()
      : mailboxForm.receive_email.trim();
    const receive_username = mailboxForm.sameAsSmtp
      ? mailboxForm.smtp_user.trim() || mailboxForm.email.trim()
      : mailboxForm.receive_username.trim();
    const receive_password = mailboxForm.sameAsSmtp
      ? mailboxForm.smtp_password
      : mailboxForm.receive_password;

    if (!mailboxForm.domain_id) {
      setError('Select a domain first.');
      return;
    }
    if (!mailboxForm.email.trim()) {
      setError('Email is required.');
      return;
    }
    if (
      !mailboxForm.smtp_host.trim() ||
      !mailboxForm.smtp_user.trim() ||
      !mailboxForm.imap_host.trim() ||
      !receive_email ||
      !receive_username
    ) {
      setError('Fill in SMTP and IMAP credentials.');
      return;
    }
    if (!isEdit && (!mailboxForm.smtp_password || !receive_password)) {
      setError('SMTP and receive passwords are required for new mailboxes.');
      return;
    }
    if (!mailboxForm.sameAsSmtp && !isEdit && !receive_password) {
      setError('Receive password is required.');
      return;
    }
    if (!Number.isFinite(smtp_port) || !Number.isFinite(imap_port)) {
      setError('Ports must be numbers.');
      return;
    }
    if (!Number.isFinite(daily_limit) || daily_limit <= 0) {
      setError('Mailbox daily limit must be a positive number.');
      return;
    }

    setSubmitting(true);
    try {
      if (isEdit && editingMailboxId) {
        const payload: Parameters<typeof apiService.updateSystemMailbox>[1] = {
          domain_id: mailboxForm.domain_id,
          email: mailboxForm.email.trim(),
          smtp_host: mailboxForm.smtp_host.trim(),
          smtp_user: mailboxForm.smtp_user.trim(),
          smtp_port,
          receive_email,
          receive_username,
          imap_host: mailboxForm.imap_host.trim(),
          imap_port,
          daily_limit,
          is_active: mailboxForm.is_active,
          can_receive: mailboxForm.can_receive,
          provider: mailboxForm.provider,
        };
        if (mailboxForm.smtp_password) payload.smtp_password = mailboxForm.smtp_password;
        if (receive_password) payload.receive_password = receive_password;

        const res = await apiService.updateSystemMailbox(editingMailboxId, payload);
        if (res.error) {
          setError(res.error);
          toast.error(res.error);
          return;
        }
        toast.success(`Mailbox ${mailboxForm.email.trim()} updated`);
      } else {
        const res = await apiService.createSystemMailbox({
          domain_id: mailboxForm.domain_id,
          email: mailboxForm.email.trim(),
          smtp_host: mailboxForm.smtp_host.trim(),
          smtp_user: mailboxForm.smtp_user.trim(),
          smtp_password: mailboxForm.smtp_password,
          smtp_port,
          receive_email,
          receive_username,
          receive_password: receive_password || mailboxForm.smtp_password,
          imap_host: mailboxForm.imap_host.trim(),
          imap_port,
          daily_limit,
          provider: mailboxForm.provider,
          can_receive: mailboxForm.can_receive,
          is_active: mailboxForm.is_active,
        });
        if (res.error) {
          setError(res.error);
          toast.error(res.error);
          return;
        }
        toast.success(`Mailbox ${mailboxForm.email.trim()} created`);
      }
      resetMailboxForm();
      await load();
      setSection('mailboxes');
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to save mailbox';
      setError(msg);
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeleteMailbox = async (mb: SystemMailboxResponse) => {
    if (!window.confirm(`Delete system mailbox ${mb.email}? This cannot be undone.`)) return;
    setDeletingId(mb.id);
    setError(null);
    try {
      const res = await apiService.deleteSystemMailbox(mb.id);
      if (res.error) {
        setError(res.error);
        toast.error(res.error);
        return;
      }
      toast.success(`Deleted ${mb.email}`);
      if (editingMailboxId === mb.id) resetMailboxForm();
      await load();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to delete mailbox';
      setError(msg);
      toast.error(msg);
    } finally {
      setDeletingId(null);
    }
  };

  const handleDeleteDomain = async (d: SystemDomainResponse) => {
    const linked = mailboxes.filter((m) => m.domain_id === d.id).length;
    const warning =
      linked > 0
        ? `Delete domain ${d.domain_name}? This also deletes ${linked} linked mailbox${linked === 1 ? '' : 'es'}.`
        : `Delete domain ${d.domain_name}? This cannot be undone.`;
    if (!window.confirm(warning)) return;
    setDeletingId(d.id);
    setError(null);
    try {
      const res = await apiService.deleteSystemDomain(d.id);
      if (res.error) {
        setError(res.error);
        toast.error(res.error);
        return;
      }
      toast.success(`Deleted ${d.domain_name}`);
      if (editingDomainId === d.id) resetDomainForm();
      await load();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to delete domain';
      setError(msg);
      toast.error(msg);
    } finally {
      setDeletingId(null);
    }
  };

  if (!isAdmin) {
    return (
      <div className="admin-mailboxes">
        <p className="admin-mailboxes__subtitle">
          Admin credentials are required to manage system mailboxes.
        </p>
      </div>
    );
  }

  const mailboxTabLabel = editingMailboxId ? 'Edit mailbox' : 'Add mailbox';
  const domainTabLabel = editingDomainId ? 'Edit domain' : 'Add domain';

  return (
    <div className="admin-mailboxes">
      <div className="admin-mailboxes__intro">
        <p className="admin-mailboxes__subtitle">
          Create, edit, and remove platform sending domains and system mailboxes without server
          access. Mailbox daily limits must fit within the domain limit.
        </p>
      </div>

      <div className="admin-mailboxes__filter-bar">
        <div className="admin-mailboxes__tabs" role="tablist" aria-label="Mailbox sections">
          {(
            [
              ['mailboxes', 'Mailboxes'],
              ['domains', 'Domains'],
              ['add-mailbox', mailboxTabLabel],
              ['add-domain', domainTabLabel],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={section === key}
              className={`admin-mailboxes__tab${section === key ? ' admin-mailboxes__tab--active' : ''}`}
              onClick={() => goToSection(key)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="admin-mailboxes__filter-spacer" aria-hidden />
        {(section === 'mailboxes' || section === 'domains') && (
          <div className="admin-mailboxes__search">
            <Search className="admin-mailboxes__search-icon" size={14} strokeWidth={2} aria-hidden />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={section === 'domains' ? 'Search domains…' : 'Search mailboxes…'}
              className="admin-mailboxes__search-input focus-visible:ring-0 focus-visible:ring-transparent focus-visible:border-none focus-visible:ring-offset-0"
            />
          </div>
        )}
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="admin-mailboxes__refresh"
          onClick={() => void load()}
          disabled={loading}
        >
          {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          Refresh
        </Button>
      </div>

      {error && (
        <div className="admin-mailboxes__banner admin-mailboxes__banner--error" role="alert">
          {error}
        </div>
      )}

      {section === 'mailboxes' && (
        <section className="admin-mailboxes__panel">
          <div className="admin-mailboxes__panel-head">
            <h3 className="admin-mailboxes__panel-title">System mailboxes</h3>
            <span className="admin-mailboxes__count">{filteredMailboxes.length} accounts</span>
          </div>
          <div className="admin-mailboxes__table-wrap">
            <table className="admin-mailboxes__table">
              <thead>
                <tr>
                  <th>Email</th>
                  <th>Domain</th>
                  <th>SMTP</th>
                  <th>IMAP</th>
                  <th>Limit</th>
                  <th>Sent today</th>
                  <th>Status</th>
                  <th>Last used</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={9} className="admin-mailboxes__muted">
                      Loading…
                    </td>
                  </tr>
                ) : filteredMailboxes.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="admin-mailboxes__muted">
                      No system mailboxes yet. Use Add mailbox after creating a domain.
                    </td>
                  </tr>
                ) : (
                  filteredMailboxes.map((mb) => (
                    <tr key={mb.id}>
                      <td>
                        <div className="admin-mailboxes__user-primary">{mb.email}</div>
                      </td>
                      <td>{domainById.get(mb.domain_id)?.domain_name || mb.domain_id}</td>
                      <td className="admin-mailboxes__mono">
                        {mb.smtp_host}:{mb.port}
                      </td>
                      <td className="admin-mailboxes__mono">
                        {mb.imap_host}:{mb.imap_port}
                      </td>
                      <td>{mb.daily_limit}</td>
                      <td>{mb.sent_today}</td>
                      <td>
                        <span
                          className={`admin-mailboxes__badge${mb.is_active ? '' : ' admin-mailboxes__badge--inactive'}`}
                        >
                          {mb.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td className="admin-mailboxes__muted">{formatDate(mb.last_used)}</td>
                      <td>
                        <div className="admin-mailboxes__actions">
                          <button
                            type="button"
                            className="admin-mailboxes__icon-btn"
                            title="Edit mailbox"
                            aria-label={`Edit ${mb.email}`}
                            onClick={() => startEditMailbox(mb)}
                          >
                            <Pencil size={14} />
                          </button>
                          <button
                            type="button"
                            className="admin-mailboxes__icon-btn admin-mailboxes__icon-btn--danger"
                            title="Delete mailbox"
                            aria-label={`Delete ${mb.email}`}
                            disabled={deletingId === mb.id}
                            onClick={() => void handleDeleteMailbox(mb)}
                          >
                            {deletingId === mb.id ? (
                              <Loader2 size={14} className="animate-spin" />
                            ) : (
                              <Trash2 size={14} />
                            )}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {section === 'domains' && (
        <section className="admin-mailboxes__panel">
          <div className="admin-mailboxes__panel-head">
            <h3 className="admin-mailboxes__panel-title">Sending domains</h3>
            <span className="admin-mailboxes__count">{filteredDomains.length} domains</span>
          </div>
          <div className="admin-mailboxes__table-wrap">
            <table className="admin-mailboxes__table">
              <thead>
                <tr>
                  <th>Domain</th>
                  <th>Daily limit</th>
                  <th>Sent today</th>
                  <th>Status</th>
                  <th>Last used</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={6} className="admin-mailboxes__muted">
                      Loading…
                    </td>
                  </tr>
                ) : filteredDomains.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="admin-mailboxes__muted">
                      No domains yet. Use Add domain to create one.
                    </td>
                  </tr>
                ) : (
                  filteredDomains.map((d) => (
                    <tr key={d.id}>
                      <td>
                        <div className="admin-mailboxes__user-primary">{d.domain_name}</div>
                      </td>
                      <td>{d.daily_limit}</td>
                      <td>{d.sent_today}</td>
                      <td>
                        <span
                          className={`admin-mailboxes__badge${d.is_active ? '' : ' admin-mailboxes__badge--inactive'}`}
                        >
                          {d.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td className="admin-mailboxes__muted">{formatDate(d.last_used)}</td>
                      <td>
                        <div className="admin-mailboxes__actions">
                          <button
                            type="button"
                            className="admin-mailboxes__icon-btn"
                            title="Edit domain"
                            aria-label={`Edit ${d.domain_name}`}
                            onClick={() => startEditDomain(d)}
                          >
                            <Pencil size={14} />
                          </button>
                          <button
                            type="button"
                            className="admin-mailboxes__icon-btn admin-mailboxes__icon-btn--danger"
                            title="Delete domain"
                            aria-label={`Delete ${d.domain_name}`}
                            disabled={deletingId === d.id}
                            onClick={() => void handleDeleteDomain(d)}
                          >
                            {deletingId === d.id ? (
                              <Loader2 size={14} className="animate-spin" />
                            ) : (
                              <Trash2 size={14} />
                            )}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {section === 'add-domain' && (
        <section className="admin-mailboxes__panel admin-mailboxes__panel--form">
          <h3 className="admin-mailboxes__panel-title">
            {editingDomainId ? 'Edit domain' : 'Add domain'}
          </h3>
          <form className="admin-mailboxes__form" onSubmit={(e) => void handleSaveDomain(e)}>
            <div className="admin-mailboxes__field">
              <label htmlFor="admin-mb-domain-name">Domain name</label>
              <Input
                id="admin-mb-domain-name"
                value={domainName}
                onChange={(e) => setDomainName(e.target.value)}
                placeholder="mail.example.com"
                className="admin-mailboxes__input focus-visible:ring-0 focus-visible:ring-transparent focus-visible:border-none focus-visible:ring-offset-0"
                required
              />
            </div>
            <div className="admin-mailboxes__field">
              <label htmlFor="admin-mb-domain-limit">Daily send limit</label>
              <Input
                id="admin-mb-domain-limit"
                type="number"
                min={1}
                value={domainDailyLimit}
                onChange={(e) => setDomainDailyLimit(e.target.value)}
                className="admin-mailboxes__input focus-visible:ring-0 focus-visible:ring-transparent focus-visible:border-none focus-visible:ring-offset-0"
                required
              />
            </div>
            {editingDomainId ? (
              <label className="admin-mailboxes__check">
                <input
                  type="checkbox"
                  checked={domainActive}
                  onChange={(e) => setDomainActive(e.target.checked)}
                />
                Domain is active
              </label>
            ) : null}
            <div className="admin-mailboxes__form-actions">
              {editingDomainId ? (
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    resetDomainForm();
                    setSection('domains');
                  }}
                  disabled={submitting}
                >
                  Cancel
                </Button>
              ) : null}
              <Button type="submit" className="admin-mailboxes__submit" disabled={submitting}>
                {submitting ? <Loader2 size={14} className="animate-spin" /> : null}
                {editingDomainId ? 'Save domain' : 'Create domain'}
              </Button>
            </div>
          </form>
        </section>
      )}

      {section === 'add-mailbox' && (
        <section className="admin-mailboxes__panel admin-mailboxes__panel--form admin-mailboxes__panel--wide">
          <h3 className="admin-mailboxes__panel-title">
            {editingMailboxId ? 'Edit system mailbox' : 'Add system mailbox'}
          </h3>
          {domains.length === 0 ? (
            <p className="admin-mailboxes__muted">
              Create a domain first, then come back to add a mailbox.
            </p>
          ) : (
            <form className="admin-mailboxes__form" onSubmit={(e) => void handleSaveMailbox(e)}>
              <div className="admin-mailboxes__field">
                <label>Domain</label>
                <AdminFilterDropdown
                  options={domainOptions}
                  value={mailboxForm.domain_id}
                  onChange={(value) => updateMailboxField('domain_id', value)}
                  placeholder="Select domain…"
                  emptyLabel="Select domain…"
                  hideEmptyOption
                  hideFilterIcon
                  wide
                />
              </div>

              <div className="admin-mailboxes__field">
                <label>Provider</label>
                <AdminFilterDropdown
                  options={PROVIDER_OPTIONS}
                  value={mailboxForm.provider}
                  onChange={(value) => updateMailboxField('provider', value)}
                  placeholder="Select provider…"
                  emptyLabel="Select provider…"
                  hideEmptyOption
                  hideFilterIcon
                  wide
                />
              </div>

              <div className="admin-mailboxes__grid">
                <div className="admin-mailboxes__field">
                  <label htmlFor="admin-mb-email">Email</label>
                  <Input
                    id="admin-mb-email"
                    type="email"
                    value={mailboxForm.email}
                    onChange={(e) => updateMailboxField('email', e.target.value)}
                    placeholder="outreach@mail.example.com"
                    className="admin-mailboxes__input focus-visible:ring-0 focus-visible:ring-transparent focus-visible:border-none focus-visible:ring-offset-0"
                    required
                  />
                </div>
                <div className="admin-mailboxes__field">
                  <label htmlFor="admin-mb-daily-limit">Daily limit</label>
                  <Input
                    id="admin-mb-daily-limit"
                    type="number"
                    min={1}
                    value={mailboxForm.daily_limit}
                    onChange={(e) => updateMailboxField('daily_limit', e.target.value)}
                    className="admin-mailboxes__input focus-visible:ring-0 focus-visible:ring-transparent focus-visible:border-none focus-visible:ring-offset-0"
                    required
                  />
                </div>
              </div>

              <div className="admin-mailboxes__checks">
                <label className="admin-mailboxes__check">
                  <input
                    type="checkbox"
                    checked={mailboxForm.is_active}
                    onChange={(e) => updateMailboxField('is_active', e.target.checked)}
                  />
                  Mailbox is active
                </label>
                <label className="admin-mailboxes__check">
                  <input
                    type="checkbox"
                    checked={mailboxForm.can_receive}
                    onChange={(e) => updateMailboxField('can_receive', e.target.checked)}
                  />
                  Can receive (IMAP inbox)
                </label>
              </div>

              <h4 className="admin-mailboxes__section-label">SMTP (send)</h4>
              <div className="admin-mailboxes__grid">
                <div className="admin-mailboxes__field">
                  <label htmlFor="admin-mb-smtp-host">Host</label>
                  <Input
                    id="admin-mb-smtp-host"
                    value={mailboxForm.smtp_host}
                    onChange={(e) => updateMailboxField('smtp_host', e.target.value)}
                    placeholder="smtp.example.com"
                    className="admin-mailboxes__input focus-visible:ring-0 focus-visible:ring-transparent focus-visible:border-none focus-visible:ring-offset-0"
                    required
                  />
                </div>
                <div className="admin-mailboxes__field">
                  <label htmlFor="admin-mb-smtp-port">Port</label>
                  <Input
                    id="admin-mb-smtp-port"
                    type="number"
                    value={mailboxForm.smtp_port}
                    onChange={(e) => updateMailboxField('smtp_port', e.target.value)}
                    className="admin-mailboxes__input focus-visible:ring-0 focus-visible:ring-transparent focus-visible:border-none focus-visible:ring-offset-0"
                    required
                  />
                </div>
                <div className="admin-mailboxes__field">
                  <label htmlFor="admin-mb-smtp-user">Username</label>
                  <Input
                    id="admin-mb-smtp-user"
                    value={mailboxForm.smtp_user}
                    onChange={(e) => updateMailboxField('smtp_user', e.target.value)}
                    className="admin-mailboxes__input focus-visible:ring-0 focus-visible:ring-transparent focus-visible:border-none focus-visible:ring-offset-0"
                    required
                  />
                </div>
                <div className="admin-mailboxes__field">
                  <label htmlFor="admin-mb-smtp-pass">
                    Password{editingMailboxId ? ' (leave blank to keep)' : ''}
                  </label>
                  <Input
                    id="admin-mb-smtp-pass"
                    type="password"
                    autoComplete="new-password"
                    value={mailboxForm.smtp_password}
                    onChange={(e) => updateMailboxField('smtp_password', e.target.value)}
                    className="admin-mailboxes__input focus-visible:ring-0 focus-visible:ring-transparent focus-visible:border-none focus-visible:ring-offset-0"
                    required={!editingMailboxId}
                    placeholder={editingMailboxId ? '••••••••' : undefined}
                  />
                </div>
              </div>

              <h4 className="admin-mailboxes__section-label">IMAP (receive)</h4>
              <label className="admin-mailboxes__check">
                <input
                  type="checkbox"
                  checked={mailboxForm.sameAsSmtp}
                  onChange={(e) => updateMailboxField('sameAsSmtp', e.target.checked)}
                />
                Use same credentials as SMTP for receive
              </label>
              <div className="admin-mailboxes__grid">
                <div className="admin-mailboxes__field">
                  <label htmlFor="admin-mb-imap-host">IMAP host</label>
                  <Input
                    id="admin-mb-imap-host"
                    value={mailboxForm.imap_host}
                    onChange={(e) => updateMailboxField('imap_host', e.target.value)}
                    placeholder="imap.example.com"
                    className="admin-mailboxes__input focus-visible:ring-0 focus-visible:ring-transparent focus-visible:border-none focus-visible:ring-offset-0"
                    required
                  />
                </div>
                <div className="admin-mailboxes__field">
                  <label htmlFor="admin-mb-imap-port">IMAP port</label>
                  <Input
                    id="admin-mb-imap-port"
                    type="number"
                    value={mailboxForm.imap_port}
                    onChange={(e) => updateMailboxField('imap_port', e.target.value)}
                    className="admin-mailboxes__input focus-visible:ring-0 focus-visible:ring-transparent focus-visible:border-none focus-visible:ring-offset-0"
                    required
                  />
                </div>
                {!mailboxForm.sameAsSmtp && (
                  <>
                    <div className="admin-mailboxes__field">
                      <label htmlFor="admin-mb-recv-email">Receive email</label>
                      <Input
                        id="admin-mb-recv-email"
                        type="email"
                        value={mailboxForm.receive_email}
                        onChange={(e) => updateMailboxField('receive_email', e.target.value)}
                        className="admin-mailboxes__input focus-visible:ring-0 focus-visible:ring-transparent focus-visible:border-none focus-visible:ring-offset-0"
                        required
                      />
                    </div>
                    <div className="admin-mailboxes__field">
                      <label htmlFor="admin-mb-recv-user">Receive username</label>
                      <Input
                        id="admin-mb-recv-user"
                        value={mailboxForm.receive_username}
                        onChange={(e) => updateMailboxField('receive_username', e.target.value)}
                        className="admin-mailboxes__input focus-visible:ring-0 focus-visible:ring-transparent focus-visible:border-none focus-visible:ring-offset-0"
                        required
                      />
                    </div>
                    <div className="admin-mailboxes__field">
                      <label htmlFor="admin-mb-recv-pass">
                        Receive password{editingMailboxId ? ' (leave blank to keep)' : ''}
                      </label>
                      <Input
                        id="admin-mb-recv-pass"
                        type="password"
                        autoComplete="new-password"
                        value={mailboxForm.receive_password}
                        onChange={(e) => updateMailboxField('receive_password', e.target.value)}
                        className="admin-mailboxes__input focus-visible:ring-0 focus-visible:ring-transparent focus-visible:border-none focus-visible:ring-offset-0"
                        required={!editingMailboxId}
                        placeholder={editingMailboxId ? '••••••••' : undefined}
                      />
                    </div>
                  </>
                )}
              </div>

              <div className="admin-mailboxes__form-actions">
                {editingMailboxId ? (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => {
                      resetMailboxForm();
                      setSection('mailboxes');
                    }}
                    disabled={submitting}
                  >
                    Cancel
                  </Button>
                ) : null}
                <Button type="submit" className="admin-mailboxes__submit" disabled={submitting}>
                  {submitting ? <Loader2 size={14} className="animate-spin" /> : null}
                  {editingMailboxId ? 'Save mailbox' : 'Create mailbox'}
                </Button>
              </div>
            </form>
          )}
        </section>
      )}
    </div>
  );
}
