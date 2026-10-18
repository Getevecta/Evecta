import { useState, useEffect, useCallback } from 'react';
import {
  Search,
  ArrowLeft,
  RefreshCw,
  Send,
  Loader2,
  Calendar,
  Users,
  Reply,
  Forward,
  Eye,
} from 'lucide-react';
import { Input } from '../ui/input';
import { Button } from '../ui/button';
import { Textarea } from '../ui/textarea';
import { DashboardPagination } from '../ui/DashboardPagination';
import { useAuth } from '../../../../shared/contexts/AuthContext';
import {
  apiService,
  type InboxThreadListItem,
  type InboxThreadDetail,
  type InboxLeadConversationSummary,
  type InboxThreadMessage,
} from '../../../../shared/services/api';
import { toast } from 'sonner';
import { EmptyState } from '../ui/EmptyState';
import { PreviewContentModal } from '../Campaign/PreviewContentModal';
import { sanitizeEmailHtml } from '../../../../shared/utils/sanitizeHtml';
import './Inbox.css';

interface InboxProps {
  onToggleSidebar?: () => void;
  /** Total unread inbound replies across all threads — drives sidebar badge */
  onUnreadCountChange?: (count: number) => void;
}

type InboxView = 'threads' | 'thread-detail' | 'conversation';

const formatTimeAgo = (dateString: string | undefined | null): string => {
  if (!dateString) return '';
  const date = new Date(dateString);
  const now = new Date();
  const diffInSeconds = Math.floor((now.getTime() - date.getTime()) / 1000);
  if (diffInSeconds < 60) return 'Just now';
  if (diffInSeconds < 3600) return `${Math.floor(diffInSeconds / 60)}m ago`;
  if (diffInSeconds < 86400) return `${Math.floor(diffInSeconds / 3600)}h ago`;
  if (diffInSeconds < 604800) return `${Math.floor(diffInSeconds / 86400)}d ago`;
  if (diffInSeconds < 2592000) return `${Math.floor(diffInSeconds / 604800)}w ago`;
  return `${Math.floor(diffInSeconds / 2592000)}mo ago`;
};

const formatTimestamp = (dateString: string | undefined | null): string => {
  if (!dateString) return '';
  const date = new Date(dateString);
  const months = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
  ];
  const month = months[date.getMonth()];
  const day = date.getDate();
  const hours = date.getHours();
  const minutes = date.getMinutes();
  const ampm = hours >= 12 ? 'PM' : 'AM';
  const displayHours = hours % 12 || 12;
  const displayMinutes = minutes.toString().padStart(2, '0');
  return `${month} ${day}, ${displayHours}:${displayMinutes} ${ampm}`;
};

/** Full date for thread cards: "Feb 18, 2026 at 12:50 PM" */
const formatSentOn = (dateString: string | undefined | null): string => {
  if (!dateString) return '—';
  const date = new Date(dateString);
  if (Number.isNaN(date.getTime())) return '—';
  const months = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
  ];
  const month = months[date.getMonth()];
  const day = date.getDate();
  const year = date.getFullYear();
  const hours = date.getHours();
  const minutes = date.getMinutes();
  const ampm = hours >= 12 ? 'PM' : 'AM';
  const displayHours = hours % 12 || 12;
  const displayMinutes = minutes.toString().padStart(2, '0');
  return `${month} ${day}, ${year} at ${displayHours}:${displayMinutes} ${ampm}`;
};

const formatDateLongUS = (iso: string | undefined | null): string => {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
};

const formatShortMonthDay = (iso: string | undefined | null): string => {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const months = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
  ];
  return `${months[d.getMonth()]} ${d.getDate()}`;
};

const getInitials = (name: string | undefined | null): string => {
  if (!name) return '??';
  const parts = name.trim().split(/\s+/);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }
  return name.substring(0, 2).toUpperCase();
};

const stripHtmlTags = (html: string | undefined | null): string => {
  if (!html) return '';
  return html.replace(/<[^>]+>/g, '');
};

/** Backend sends `outbound` | `inbound` (see MessageDirection). */
const isMessageOutbound = (direction: string | undefined | null): boolean =>
  String(direction ?? '').toLowerCase() === 'outbound';

/** Plain text preview for session rows — API HTML stripped to plain text. */
const normalizeSessionSnippet = (raw: string | undefined | null): string => {
  const plain = stripHtmlTags(raw ?? '').replace(/\s+/g, ' ').trim();
  return plain;
};

function messageBodyLooksHtml(body: string | undefined | null): boolean {
  if (!body) return false;
  return /<[a-z][\s\S]*>/i.test(body);
}

function MessageBody({ body, className }: { body: string; className?: string }) {
  const html = messageBodyLooksHtml(body);
  const rootClass = className ? `${className} ` : '';
  if (html) {
    return (
      <div
        className={`${rootClass}inbox-chat-bubble-body inbox-chat-bubble-body-html`}
        dangerouslySetInnerHTML={{ __html: sanitizeEmailHtml(body) }}
      />
    );
  }
  return (
    <div className={`${rootClass}inbox-chat-bubble-body inbox-chat-bubble-body-plain`}>{body}</div>
  );
}

export function Inbox({ onUnreadCountChange }: InboxProps) {
  const { user } = useAuth();
  const [view, setView] = useState<InboxView>('threads');
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [activeLeadId, setActiveLeadId] = useState<string | null>(null);

  const [threads, setThreads] = useState<InboxThreadListItem[]>([]);
  const [threadDetail, setThreadDetail] = useState<InboxThreadDetail | null>(null);
  const [messages, setMessages] = useState<InboxThreadMessage[]>([]);
  const [conversationLead, setConversationLead] = useState<{
    lead_id: string;
    lead_email?: string | null;
    lead_name?: string | null;
  } | null>(null);

  const [activeTab, setActiveTab] = useState<
    'all' | 'unread' | 'opened' | 'sent'
  >('all');
  const [searchQuery, setSearchQuery] = useState('');

  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [conversationLoading, setConversationLoading] = useState(false);
  const [replyText, setReplyText] = useState('');
  const [sendingReply, setSendingReply] = useState(false);
  const [sessionPage, setSessionPage] = useState(1);
  const [sessionPageSize, setSessionPageSize] = useState(10);
  const [showPreviewContentModal, setShowPreviewContentModal] = useState(false);

  useEffect(() => {
    setShowPreviewContentModal(false);
  }, [activeThreadId, view]);

  useEffect(() => {
    const n = threadDetail?.replies?.length ?? 0;
    if (n > 0) setShowPreviewContentModal(false);
  }, [threadDetail?.replies?.length, threadDetail?.id]);

  const recomputeUnreadTotal = useCallback(
    (list: InboxThreadListItem[]) => {
      const total = list.reduce((acc, t) => acc + (t.unread_reply_count || 0), 0);
      onUnreadCountChange?.(total);
    },
    [onUnreadCountChange]
  );

  const loadThreads = useCallback(async () => {
    if (!user?.id) return;
    const response = await apiService.listInboxThreads({ page: 1, perPage: 100 });
    if (response.error) {
      toast.error(`Failed to load inbox: ${response.error}`);
      setThreads([]);
      recomputeUnreadTotal([]);
      return;
    }
    const list = Array.isArray(response.data) ? response.data : [];
    setThreads(list);
    recomputeUnreadTotal(list);
  }, [user?.id, recomputeUnreadTotal]);

  const openThread = async (threadId: string) => {
    setActiveThreadId(threadId);
    setDetailLoading(true);
    setView('thread-detail');
    try {
      const res = await apiService.getInboxThread(threadId);
      if (res.error) {
        toast.error(res.error);
        setView('threads');
        setActiveThreadId(null);
        return;
      }
      if (res.data) {
        setThreadDetail(res.data);
        setThreads((prev) =>
          prev.map((t) =>
            t.id === threadId
              ? { ...t, unread_reply_count: res.data!.unread_reply_count, is_starred: res.data!.is_starred }
              : t
          )
        );
      }
    } finally {
      setDetailLoading(false);
    }
  };

  const openLeadConversation = async (threadId: string, leadId: string) => {
    setActiveThreadId(threadId);
    setActiveLeadId(leadId);
    setConversationLoading(true);
    setView('conversation');
    try {
      const res = await apiService.getInboxLeadConversation(threadId, leadId);
      if (res.error) {
        toast.error(res.error);
        setView('thread-detail');
        setActiveLeadId(null);
        return;
      }
      if (res.data) {
        setConversationLead({
          lead_id: res.data.lead_id,
          lead_email: res.data.lead_email,
          lead_name: res.data.lead_name,
        });
        setMessages(res.data.messages || []);
      }
      await loadThreads();
      if (threadDetail?.id === threadId) {
        const detailRes = await apiService.getInboxThread(threadId);
        if (detailRes.data) setThreadDetail(detailRes.data);
      }
    } finally {
      setConversationLoading(false);
    }
  };

  const goBack = async () => {
    if (view === 'conversation') {
      setView('thread-detail');
      setActiveLeadId(null);
      setMessages([]);
      setConversationLead(null);
      setReplyText('');
      if (activeThreadId) {
        const detailRes = await apiService.getInboxThread(activeThreadId);
        if (detailRes.data) setThreadDetail(detailRes.data);
        await loadThreads();
      }
      return;
    }
    if (view === 'thread-detail') {
      setView('threads');
      setActiveThreadId(null);
      setThreadDetail(null);
      await loadThreads();
    }
  };

  useEffect(() => {
    if (!user?.id) return;
    let cancelled = false;
    (async () => {
      setIsLoading(true);
      try {
        await apiService.fetchReplies().catch(() => {
          /* rate limit or network — still show threads */
        });
        if (!cancelled) await loadThreads();
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user?.id, loadThreads]);

  useEffect(() => {
    setSessionPage(1);
  }, [activeThreadId, activeTab]);

  useEffect(() => {
    if (!threadDetail?.replies) return;
    const tp = Math.max(1, Math.ceil(threadDetail.replies.length / sessionPageSize));
    setSessionPage((p) => Math.min(p, tp));
  }, [threadDetail?.id, threadDetail?.replies?.length, sessionPageSize]);

  const handleRefresh = async () => {
    if (!user?.id || isRefreshing) return;
    setIsRefreshing(true);
    try {
      toast.loading('Syncing mailboxes…', { id: 'refresh-inbox' });
      const syncRes = await apiService.fetchReplies();
      if (syncRes.error) {
        toast.error(syncRes.error, { id: 'refresh-inbox' });
      } else {
        const n = (syncRes.data as { replies_found?: number } | undefined)?.replies_found;
        toast.success(
          typeof n === 'number' ? `Sync complete (${n} activities).` : 'Sync complete.',
          { id: 'refresh-inbox' }
        );
      }
      await loadThreads();
      if (activeThreadId && view === 'thread-detail') {
        const d = await apiService.getInboxThread(activeThreadId);
        if (d.data) setThreadDetail(d.data);
      }
    } catch {
      toast.error('Refresh failed.', { id: 'refresh-inbox' });
    } finally {
      setIsRefreshing(false);
    }
  };

  const sendReply = async () => {
    const trimmed = replyText.trim();
    if (!activeThreadId || !activeLeadId || !trimmed || sendingReply) return;
    setSendingReply(true);
    try {
      const res = await apiService.replyToInboxThreadLead(activeThreadId, activeLeadId, trimmed);
      if (res.error) {
        const err = res.error.includes('searching the leads')
          ? 'Request timed out. Please try again.'
          : res.error;
        toast.error(err);
        return;
      }
      if (res.data) {
        const newMsg: InboxThreadMessage = {
          id: res.data.id,
          direction: 'outbound',
          sender_email: res.data.sender_email ?? null,
          recipient_email: res.data.recipient_email ?? null,
          body: trimmed,
          message_id: res.data.message_id ?? null,
          sent_at: res.data.sent_at,
          is_read: true,
        };
        setMessages((prev) => [...prev, newMsg]);
      }
      setReplyText('');
      toast.success('Reply sent');
      await loadThreads();
    } catch {
      toast.error('Failed to send reply');
    } finally {
      setSendingReply(false);
    }
  };

  /** Threads with at least one inbound lead reply (actual inbox mail) */
  const hasIncomingMail = (t: InboxThreadListItem) => (t.replied_count || 0) > 0;
  /**
   * Tab matching is per-lead, not exclusive per campaign:
   * - Unread: any lead reply still unopened
   * - Opened: any lead opened by user but not replied to
   * - Sent: any lead the user replied to
   * So one campaign can appear in multiple tabs when leads are in mixed states.
   */
  const isUnreadForUser = (t: InboxThreadListItem) => (t.unread_reply_count || 0) > 0;
  const isOpenedByUser = (t: InboxThreadListItem) => (t.opened_unreplied_count || 0) > 0;
  const isSentByUser = (t: InboxThreadListItem) => (t.user_reply_count || 0) > 0;

  const matchesInboxTab = (t: InboxThreadListItem) => {
    if (activeTab === 'all') return hasIncomingMail(t);
    if (activeTab === 'unread') return isUnreadForUser(t);
    if (activeTab === 'opened') return isOpenedByUser(t);
    if (activeTab === 'sent') return isSentByUser(t);
    return true;
  };

  const filteredThreads = threads
    .filter((t) => {
      const q = searchQuery.toLowerCase();
      const matchesSearch =
        !q ||
        t.campaign_name.toLowerCase().includes(q) ||
        (t.subject || '').toLowerCase().includes(q);
      return matchesSearch && matchesInboxTab(t);
    })
    .sort((a, b) => {
      const ta = a.last_message_at ? new Date(a.last_message_at).getTime() : 0;
      const tb = b.last_message_at ? new Date(b.last_message_at).getTime() : 0;
      return tb - ta;
    });

  const allCount = threads.filter(hasIncomingMail).length;
  const unreadCount = threads.filter(isUnreadForUser).length;
  const openedCount = threads.filter(isOpenedByUser).length;
  const sentCount = threads.filter(isSentByUser).length;

  const renderThreadList = () => (
    <>
        <div className="inbox-search-filters">
          <div className="inbox-tabs">
            <button
            type="button"
              className={`inbox-tab ${activeTab === 'all' ? 'active' : ''}`}
              onClick={() => setActiveTab('all')}
            >
            All ({allCount})
            </button>
            <button
            type="button"
              className={`inbox-tab ${activeTab === 'unread' ? 'active' : ''}`}
              onClick={() => setActiveTab('unread')}
            >
              Unread ({unreadCount})
            </button>
            <button
            type="button"
              className={`inbox-tab ${activeTab === 'opened' ? 'active' : ''}`}
              onClick={() => setActiveTab('opened')}
            >
              Opened ({openedCount})
            </button>
          <button
            type="button"
            className={`inbox-tab ${activeTab === 'sent' ? 'active' : ''}`}
            onClick={() => setActiveTab('sent')}
          >
            Sent ({sentCount})
          </button>
          </div>
          <div className="inbox-search-filter-container">
            <div className="inbox-search-refresh-wrapper">
              <div className="inbox-search-input-container">
                <Search className="inbox-search-icon" />
                <Input
                placeholder="Search here..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="inbox-search-input"
                />
              </div>
              <button
              type="button"
                onClick={handleRefresh}
                disabled={isRefreshing || isLoading}
                className="inbox-refresh-button"
              title="Fetch new replies and refresh"
              >
                <RefreshCw
                  className={`inbox-refresh-icon ${isRefreshing ? 'spinning' : ''}`}
                  size={20}
                />
              </button>
            </div>
          </div>
        </div>

        <div className="inbox-email-list">
          {isLoading ? (
          <div className="inbox-email-list-empty-state">Loading inbox…</div>
        ) : filteredThreads.length === 0 ? (
            <div className="inbox-email-list-empty-state inbox-email-list-empty-state-centered">
              <EmptyState
                iconPath="/direct-inbox-header.svg"
              title="No emails found."
                description="Replies from leads will appear here after they respond to your campaigns"
              descriptionClassName="inbox-empty-state-description"
              />
            </div>
          ) : (
            <div className="inbox-thread-grid">
          {filteredThreads.map((t) => {
            const unread = isUnreadForUser(t);
            const sentLabel = formatSentOn(t.sent_at || t.last_message_at);
            const n = t.total_recipients || 0;
            return (
              <div
                key={t.id}
              className={`inbox-campaign-card${unread ? ' inbox-campaign-card--unread' : ''}`}
                role="button"
                tabIndex={0}
                onClick={() => openThread(t.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    openThread(t.id);
                }
              }}
            >
              <div className="inbox-campaign-card-row">
              <div className="inbox-campaign-card-text">
                    <h3
                      className={`inbox-campaign-card-title ${unread ? 'inbox-text-unread' : ''}`}
                    >
                      {unread ? <span className="inbox-unread-dot" aria-hidden /> : null}
                      {t.campaign_name}
                    </h3>
                    <p className="inbox-campaign-card-meta">
                      <span className="inbox-campaign-card-sent-label">Sent on: </span>
                      <span className="inbox-campaign-card-sent-value">{sentLabel}</span>
                    </p>
              </div>
                  <span className="inbox-campaign-card-leads-badge" title="Leads selected for this campaign">
                    {n} Lead{n === 1 ? '' : 's'}
                  </span>
            </div>
            </div>
            );
          })}
            </div>
        )}
      </div>
    </>
  );

  const matchesLeadTab = (r: InboxLeadConversationSummary) => {
    const unread = !r.is_read;
    const sent = Boolean(r.has_user_replied);
    if (activeTab === 'all') return true;
    if (activeTab === 'unread') return unread;
    if (activeTab === 'opened') return !unread && !sent;
    if (activeTab === 'sent') return sent;
    return true;
  };

  const renderThreadDetail = () => {
    if (!threadDetail) return null;

    const replies = (threadDetail.replies ?? []).filter(matchesLeadTab);
    const totalSessions = replies.length;
    const totalPages = Math.max(1, Math.ceil(totalSessions / sessionPageSize) || 1);
    const safePage = Math.min(sessionPage, totalPages);
    const startIdx = (safePage - 1) * sessionPageSize;
    const pageRows = replies.slice(startIdx, startIdx + sessionPageSize);
    const emailSubject = stripHtmlTags(threadDetail.subject || '') || '—';

    return (
      <div className="inbox-nested-view inbox-thread-detail-shell">
        <header className="inbox-thread-detail-header">
          <div className="inbox-thread-detail-header-bar">
            <button
              type="button"
              className="inbox-thread-detail-back"
              onClick={goBack}
              aria-label="Back"
            >
              <ArrowLeft size={16} strokeWidth={2} aria-hidden />
            </button>

            <div className="inbox-thread-detail-main">
              <div className="inbox-thread-detail-title-row">
                <h1 className="inbox-thread-detail-title">{threadDetail.campaign_name}</h1>
              </div>

              {(threadDetail.campaign_description || '').trim() ? (
                <p className="inbox-thread-detail-desc">{threadDetail.campaign_description}</p>
              ) : null}

              <div
                className={`inbox-thread-detail-meta-row${
                  (threadDetail.campaign_description || '').trim() ? '' : ' inbox-thread-detail-meta-row--after-title'
                }`}
              >
                <span className="inbox-thread-detail-meta-item">
                  <Calendar size={16} strokeWidth={2} aria-hidden />
                  Created on {formatDateLongUS(threadDetail.campaign_created_at)}
                </span>
                <span className="inbox-thread-detail-meta-item">
                  <Send size={16} strokeWidth={2} aria-hidden />
                  Launched {formatDateLongUS(threadDetail.thread_started_at)}
                </span>
                <span className="inbox-thread-detail-meta-item">
                  <Users size={16} strokeWidth={2} aria-hidden />
                  {threadDetail.total_recipients} lead{threadDetail.total_recipients === 1 ? '' : 's'}
                  {threadDetail.email_sending_mode === 'USER' && threadDetail.sender_email
                    ? ` · ${threadDetail.sender_email}`
                    : ''}
                </span>
              </div>
            </div>

            <div className="inbox-thread-detail-header-actions">
              {!detailLoading && totalSessions === 0 && threadDetail.campaign_id ? (
                <button
                  type="button"
                  className="inbox-thread-detail-icon-btn"
                  onClick={() => setShowPreviewContentModal(true)}
                  title="Preview sent email"
                  aria-label="Preview sent email"
                >
                  <Eye size={20} strokeWidth={2} aria-hidden />
                </button>
              ) : null}
              <button
                type="button"
                className="inbox-thread-detail-icon-btn"
                onClick={handleRefresh}
                disabled={isRefreshing}
                title="Refresh"
              >
                <RefreshCw className={`inbox-refresh-icon ${isRefreshing ? 'spinning' : ''}`} size={20} />
              </button>
            </div>
          </div>
          <div className="inbox-thread-detail-divider" />
        </header>

        {detailLoading ? (
          <div className="inbox-email-list-empty-state">Loading…</div>
        ) : totalSessions === 0 ? (
          <div className="inbox-email-list-empty-state inbox-email-list-empty-state-centered">
            <EmptyState
              iconPath="/direct-inbox-header.svg"
              title="No replies yet."
              description="When leads reply to this campaign, they will appear here."
            />
          </div>
        ) : (
          <div className="dashboard-content-with-pagination inbox-thread-detail-paginated">
            <div className="dashboard-pagination-scroll-area">
              <div className="inbox-session-cards">
                {pageRows.map((r: InboxLeadConversationSummary) => {
                  const snippetFull = normalizeSessionSnippet(r.latest_reply);
                  const snippet =
                    snippetFull.length > 220 ? `${snippetFull.slice(0, 220)}…` : snippetFull;
                  const unread = !r.is_read;
                  return (
                    <div
                      key={r.lead_id}
                      className={`inbox-session-card ${unread ? 'inbox-session-card--unread' : ''}`}
                      role="button"
                      tabIndex={0}
                      onClick={() => openLeadConversation(threadDetail.id, r.lead_id)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          openLeadConversation(threadDetail.id, r.lead_id);
                        }
                      }}
                    >
                      <div className="inbox-avatar-circle inbox-session-avatar">
                        {getInitials(r.lead_name)}
                      </div>
                      <div className="inbox-session-card-body">
                        <div className="inbox-session-card-to">
                          To {r.lead_name || 'Lead'}
                        </div>
                        <div className="inbox-session-card-subject">{emailSubject}</div>
                        <div className="inbox-session-card-snippet">{snippet || '—'}</div>
                      </div>
                      <div className="inbox-session-card-right">
                        {unread ? <span className="inbox-unread-dot" aria-label="Unread" /> : null}
                        <span className="inbox-session-card-date">
                          {formatShortMonthDay(r.replied_at) || '—'}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
            <div className="dashboard-pagination-fixed">
              <DashboardPagination
                totalItems={totalSessions}
                currentPage={safePage}
                itemsPerPage={sessionPageSize}
                onPageChange={setSessionPage}
                onItemsPerPageChange={(v) => setSessionPageSize(v)}
                itemLabel="sessions"
              />
            </div>
          </div>
        )}
      </div>
    );
  };

  const renderConversation = () => {
    const leadName = conversationLead?.lead_name || 'Lead';
    const leadEmail = conversationLead?.lead_email || '';
    const subjectLine = stripHtmlTags(threadDetail?.subject || '') || 'No subject';
    const campaignLabel = threadDetail?.campaign_name?.trim() || 'Campaign';
    const lastTs =
      messages.length > 0 ? messages[messages.length - 1]?.sent_at : threadDetail?.thread_started_at;
    const youLabel = user?.full_name || user?.username || user?.email || 'You';
    const youInitials = getInitials(youLabel);

    const focusReplyComposer = () => {
      document.getElementById('inbox-reply-composer-input')?.focus();
    };

    return (
      <div className="inbox-nested-view inbox-conversation-layout inbox-conversation-email-shell">
        <div className="inbox-email-detail-title-row">
          <button
            type="button"
            className="inbox-email-detail-back"
            onClick={goBack}
            aria-label="Go back"
          >
            <ArrowLeft size={18} strokeWidth={2} aria-hidden />
          </button>
          <h1 className="inbox-email-detail-subject">{subjectLine}</h1>
        </div>
        <div className="inbox-email-detail-meta">
          <span className="inbox-email-detail-time-ago">{formatTimeAgo(lastTs) || '—'}</span>
          <span className="inbox-email-detail-campaign-pill">{campaignLabel}</span>
        </div>

        <div className="inbox-email-detail-scroll">
          {conversationLoading ? (
            <div className="inbox-email-list-empty-state">
              <Loader2 className="inbox-refresh-icon spinning" size={24} />
            </div>
          ) : (
            <div className="inbox-email-message-stack">
              {messages.map((m) => {
                const outbound = isMessageOutbound(m.direction);
                const fromName = outbound ? youLabel : leadName;
                const fromEmail = outbound ? user?.email || '' : m.sender_email || leadEmail;
                const toLine = outbound
                  ? leadEmail || leadName
                  : user?.email || 'me';
                const initials = outbound ? youInitials : getInitials(leadName);
                return (
                  <article key={m.id} className="inbox-email-message">
                    <div className="inbox-email-message-toolbar">
                      <div className="inbox-email-message-from-row">
                        <div className="inbox-avatar-circle inbox-email-message-avatar">{initials}</div>
                        <div className="inbox-email-message-from-text">
                          <div className="inbox-email-message-from-primary">
                            <span className="inbox-email-message-from-name">{fromName}</span>
                            <span className="inbox-email-message-to-me">
                              {outbound ? ` to ${leadName}` : ' to me'}
                            </span>
                          </div>
                          {fromEmail ? (
                            <div className="inbox-email-message-secondary-email">{fromEmail}</div>
                          ) : null}
                        </div>
                      </div>
                      <div className="inbox-email-message-toolbar-right">
                        <time className="inbox-email-message-sent-at" dateTime={m.sent_at}>
                          {formatSentOn(m.sent_at)}
                        </time>
                      </div>
                    </div>

                    <div className="inbox-email-message-card">
                      <div className="inbox-email-message-card-header">
                        <div className="inbox-email-rfc-lines">
                          <div className="inbox-email-rfc-line">
                            <span className="inbox-email-rfc-label">To:</span>{' '}
                            <span className="inbox-email-rfc-value">{toLine}</span>
                          </div>
                          <div className="inbox-email-rfc-line">
                            <span className="inbox-email-rfc-label">Subject:</span>{' '}
                            <span className="inbox-email-rfc-value">{subjectLine}</span>
                          </div>
                        </div>
                      </div>
                      <div className="inbox-email-message-body">
                        <MessageBody body={m.body || ''} />
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </div>

        <p className="inbox-email-reply-hint">Use the reply box below to respond to this thread.</p>

        <div className="inbox-email-footer-actions">
          <button type="button" className="inbox-email-footer-btn" onClick={focusReplyComposer}>
            <Reply size={18} strokeWidth={2} aria-hidden />
            Reply
          </button>
          <button
            type="button"
            className="inbox-email-footer-btn"
            onClick={() => toast.message('Forward is not available yet.')}
          >
            <Forward size={18} strokeWidth={2} aria-hidden />
            Forward
          </button>
        </div>

        <div className="inbox-reply-composer inbox-reply-composer-email">
          <Textarea
            id="inbox-reply-composer-input"
            placeholder="Write a reply…"
            value={replyText}
            onChange={(e) => setReplyText(e.target.value)}
            className="inbox-reply-textarea"
            rows={3}
            disabled={sendingReply}
          />
          <button
            type="button"
            className="inbox-send-reply-btn evecta-primary-btn"
            disabled={sendingReply || !replyText.trim()}
            onClick={sendReply}
          >
            {sendingReply ? (
              <Loader2 className="inbox-refresh-icon spinning" size={18} />
            ) : (
              <Send size={18} />
            )}
            Send
          </button>
        </div>
      </div>
    );
  };

  return (
    <div className="inbox-container">
      <div className="inbox-content">
        {view === 'threads' && renderThreadList()}
        {view === 'thread-detail' && renderThreadDetail()}
        {view === 'conversation' && renderConversation()}
      </div>
      {showPreviewContentModal && threadDetail?.campaign_id ? (
        <PreviewContentModal
          campaignId={threadDetail.campaign_id}
          onClose={() => setShowPreviewContentModal(false)}
        />
      ) : null}
    </div>
  );
}
