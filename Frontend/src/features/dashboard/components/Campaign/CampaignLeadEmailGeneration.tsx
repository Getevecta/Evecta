import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { RefreshCw, Search } from 'lucide-react';
import {
  apiService,
  CampaignEmailGenerationStatus,
  CampaignLeadResponse,
  CampaignLeadEmailRow,
  PlanCapabilitiesResponse,
} from '../../../../shared/services/api';
import { sortCampaignLeadsWithUserAddedFirst } from '../../../../shared/utils/leadSort';
import { DashboardPagination } from '../ui/DashboardPagination';
import { toast } from 'sonner';
import './CampaignLeadEmailGeneration.css';
import { CampaignLeadEmailPreviewModal } from './CampaignLeadEmailPreviewModal';

interface CampaignLeadEmailGenerationProps {
  campaignId: string;
  /** How the campaign draft was created — controls banner copy. */
  generationMode?: 'ai' | 'template' | 'manual';
  templateName?: string;
  toneLabel: string;
  planCapabilities: PlanCapabilitiesResponse | null;
  promptDescription?: string;
  /**
   * True while the parent is still writing/saving the campaign draft (AI drafting
   * takes ~15–20 s). Generation must not start before the draft is saved — the API
   * rejects it ("Campaign email draft is not ready") — so auto-start and auto-resume
   * wait; the parent starts generation itself once the draft is saved.
   */
  draftPending?: boolean;
  onGenerationStateChange?: (state: {
    isComplete: boolean;
    ready: number;
    total: number;
    allLeadEmailsSpamReady: boolean;
    partialGenerationAccepted: boolean;
    readyForOutreach: number;
  }) => void;
}

function displayScore(row: CampaignLeadEmailRow): number {
  if (row.lead_score != null && row.lead_score > 0) return row.lead_score;
  if (row.context_score === 'full') return 100;
  if (row.context_score === 'partial') return 70;
  return 30;
}

function isDraftReady(row: CampaignLeadEmailRow): boolean {
  return row.generation_status === 'ready' && !!row.subject?.trim() && !!row.body?.trim();
}

type RowEmailStatusKey =
  | 'ready'
  | 'generating'
  | 'queued'
  | 'failed'
  | 'spam-needed'
  | 'spam-failed';

function resolveRowEmailStatus(row: CampaignLeadEmailRow): {
  key: RowEmailStatusKey;
  label: string;
  progressPct: number;
} {
  if (row.generation_status === 'failed') {
    return { key: 'failed', label: 'Failed', progressPct: 100 };
  }
  if (row.generation_status === 'generating') {
    return { key: 'generating', label: 'Generating', progressPct: 50 };
  }
  if (row.generation_status === 'pending' || !isDraftReady(row)) {
    return { key: 'queued', label: 'Queued', progressPct: 8 };
  }
  if (row.compliance_status === 'passed') {
    return { key: 'ready', label: 'Ready', progressPct: 100 };
  }
  if (row.compliance_status === 'failed') {
    return { key: 'spam-failed', label: 'Spam failed', progressPct: 85 };
  }
  return { key: 'spam-needed', label: 'Spam check needed', progressPct: 72 };
}

function rowStatusProgressPct(
  row: CampaignLeadEmailRow,
  overallGenerationPct: number,
): number {
  if (row.generation_status === 'generating') {
    return Math.max(overallGenerationPct, 15);
  }
  if (row.generation_status === 'pending' || !isDraftReady(row)) {
    return Math.max(overallGenerationPct, 6);
  }
  return resolveRowEmailStatus(row).progressPct;
}

function renderLeadAction(
  row: CampaignLeadEmailRow,
  onPreview: () => void,
): ReactNode {
  const status = row.generation_status;
  if (status === 'generating') {
    return <span className="cle-gen-drafting">Drafting</span>;
  }
  if (status === 'pending') {
    return <span className="cle-gen-dash">—</span>;
  }
  if (status === 'ready' && row.subject && row.body) {
    return (
      <button type="button" className="cle-gen-preview-link" onClick={onPreview}>
        Preview
      </button>
    );
  }
  return <span className="cle-gen-dash">—</span>;
}

export function CampaignLeadEmailGeneration({
  campaignId,
  generationMode = 'ai',
  templateName,
  toneLabel,
  planCapabilities,
  promptDescription,
  draftPending = false,
  onGenerationStateChange,
}: CampaignLeadEmailGenerationProps) {
  const [selectedLeads, setSelectedLeads] = useState<CampaignLeadResponse[]>([]);
  const [emails, setEmails] = useState<CampaignLeadEmailRow[]>([]);
  const [status, setStatus] = useState<CampaignEmailGenerationStatus | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(10);
  const [previewRowId, setPreviewRowId] = useState<string | null>(null);
  const [isRegeneratingAll, setIsRegeneratingAll] = useState(false);
  const [isRegeneratingFailed, setIsRegeneratingFailed] = useState(false);
  const [isStartingGeneration, setIsStartingGeneration] = useState(false);
  const [pollingPaused, setPollingPaused] = useState(false);
  const [partialGenerationAccepted, setPartialGenerationAccepted] = useState(false);
  const [generationCancelled, setGenerationCancelled] = useState(false);
  const [promptText, setPromptText] = useState(promptDescription?.trim() ?? '');
  const stalledPollsRef = useRef(0);
  const resumeRequestedRef = useRef(false);
  const initialLoadErrorShownRef = useRef(false);

  const leadIdsKey = useMemo(
    () =>
      selectedLeads
        .map((lead) => lead.lead_id || lead.id)
        .sort()
        .join('|'),
    [selectedLeads],
  );

  const refresh = useCallback(async () => {
    const [statusRes, emailsRes, leadsRes] = await Promise.all([
      apiService.getCampaignLeadEmailsStatus(campaignId),
      apiService.getCampaignLeadEmails(campaignId),
      apiService.getCampaignLeads(campaignId),
    ]);
    if (statusRes.data) setStatus(statusRes.data);
    if (emailsRes.data) setEmails(emailsRes.data);
    if (leadsRes.data) {
      setSelectedLeads(sortCampaignLeadsWithUserAddedFirst(leadsRes.data));
    }
  }, [campaignId]);

  useEffect(() => {
    refresh().catch(() => {
      if (initialLoadErrorShownRef.current) return;
      initialLoadErrorShownRef.current = true;
      toast.error('Failed to load lead email generation status', {
        id: 'cle-gen-load-error',
      });
    });
  }, [refresh]);

  useEffect(() => {
    let cancelled = false;

    const resolvePrompt = async () => {
      const fromProp = promptDescription?.trim();
      if (fromProp) {
        if (!cancelled) setPromptText(fromProp);
        return;
      }

      try {
        const res = await apiService.getCampaignDraft(campaignId);
        if (cancelled) return;
        const fromApi = res.data?.ai_email_prompt?.trim() || '';
        if (fromApi) {
          setPromptText(fromApi);
          try {
            sessionStorage.setItem(`campaignAiPrompt_${campaignId}`, fromApi);
          } catch {
            /* sessionStorage unavailable */
          }
          return;
        }
      } catch {
        /* optional — prompt may be unavailable */
      }

      try {
        const fromSession =
          sessionStorage.getItem(`campaignAiPrompt_${campaignId}`)?.trim() ?? '';
        if (fromSession && !cancelled) {
          setPromptText(fromSession);
        }
      } catch {
        /* sessionStorage unavailable */
      }
    };

    void resolvePrompt();

    return () => {
      cancelled = true;
    };
  }, [campaignId, promptDescription]);

  const tableRows = useMemo(() => {
    const rows =
      selectedLeads.length === 0
        ? emails
        : selectedLeads.map((lead, idx) => {
            const matched = emails.find(
              (email) =>
                (email.lead_id && lead.lead_id && email.lead_id === lead.lead_id) ||
                (email.campaign_lead_id && email.campaign_lead_id === lead.id),
            );
            return (
              matched ?? {
                id: `lead-${lead.id}`,
                campaign_id: lead.campaign_id,
                campaign_lead_id: lead.id,
                lead_id: lead.lead_id ?? null,
                lead_index: idx,
                business_name: lead.lead?.business_name ?? null,
                email: lead.lead?.email ?? null,
                location: lead.lead?.address ?? null,
                lead_score: lead.lead?.lead_score ?? null,
                context_score: lead.context_score ?? null,
                subject: null,
                body: null,
                generation_status: 'pending',
                compliance_status: 'pending',
                review_status: 'pending',
                regeneration_count: 0,
                variant_metadata: null,
                last_error: null,
                created_at: lead.created_at,
                updated_at: lead.created_at,
              }
            );
          });

    if (selectedLeads.length === 0) return rows;

    const userAddedLeadIds = new Set(
      selectedLeads.filter((lead) => lead.is_user_added).map((lead) => lead.id),
    );
    const userAddedLeadKeys = new Set(
      selectedLeads
        .filter((lead) => lead.is_user_added && lead.lead_id)
        .map((lead) => lead.lead_id as string),
    );

    return [...rows].sort((a, b) => {
      const aUserAdded =
        (a.campaign_lead_id && userAddedLeadIds.has(a.campaign_lead_id)) ||
        (a.lead_id != null && userAddedLeadKeys.has(a.lead_id));
      const bUserAdded =
        (b.campaign_lead_id && userAddedLeadIds.has(b.campaign_lead_id)) ||
        (b.lead_id != null && userAddedLeadKeys.has(b.lead_id));
      if (aUserAdded !== bUserAdded) {
        return aUserAdded ? -1 : 1;
      }
      if (!a.created_at && !b.created_at) return 0;
      if (!a.created_at) return 1;
      if (!b.created_at) return -1;
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    });
  }, [emails, selectedLeads]);

  const readyRowCount = useMemo(
    () => tableRows.filter(isDraftReady).length,
    [tableRows],
  );

  const failedRowCount = useMemo(
    () => tableRows.filter((row) => row.generation_status === 'failed').length,
    [tableRows],
  );

  const spamReadyRowCount = useMemo(
    () =>
      tableRows.filter((row) => isDraftReady(row) && row.compliance_status === 'passed').length,
    [tableRows],
  );

  const spamPendingRowCount = useMemo(
    () =>
      tableRows.filter((row) => isDraftReady(row) && row.compliance_status === 'pending').length,
    [tableRows],
  );

  const totalRowCount = tableRows.length;

  const allGenerationComplete =
    totalRowCount > 0 &&
    readyRowCount >= totalRowCount &&
    !tableRows.some(
      (row) => row.generation_status === 'generating' || row.generation_status === 'pending',
    );

  const hasPendingGeneration = useMemo(
    () =>
      tableRows.some(
        (row) =>
          row.generation_status === 'pending' || row.generation_status === 'generating',
      ),
    [tableRows],
  );

  const autoStartKeyRef = useRef('');

  useEffect(() => {
    if (!campaignId || isRegeneratingAll || pollingPaused || partialGenerationAccepted || generationCancelled) return;
    if (leadIdsKey.length === 0) return;

    const startKey = `${campaignId}:${leadIdsKey}`;

    // The parent starts generation once its draft is saved; treat this lead set as
    // started so the draft finishing does not trigger a second POST /generate.
    if (draftPending) {
      autoStartKeyRef.current = startKey;
      return;
    }

    const needsGeneration =
      hasPendingGeneration &&
      readyRowCount < totalRowCount &&
      (status?.generating ?? 0) === 0;

    if (!needsGeneration) {
      autoStartKeyRef.current = startKey;
      return;
    }

    if (autoStartKeyRef.current === startKey || isStartingGeneration) return;
    autoStartKeyRef.current = startKey;

    void (async () => {
      setIsStartingGeneration(true);
      try {
        const res = await apiService.generateCampaignLeadEmails(campaignId, {
          regenerateAll: false,
        });
        // On failure keep autoStartKeyRef set: clearing it re-ran this effect on the
        // next render and retried in a tight loop, which spent the 10/hour limit on
        // POST /generate within seconds and hid the real error behind 429s. The
        // stalled-resume effect below and "Regenerate all" remain the ways to retry.
        if (res.error) {
          toast.error(res.error || 'Could not start email generation for new leads.', {
            id: 'cle-gen-auto-start-error',
          });
          return;
        }
        await refresh();
      } catch {
        toast.error('Could not start email generation for new leads.', {
          id: 'cle-gen-auto-start-error',
        });
      } finally {
        setIsStartingGeneration(false);
      }
    })();
  }, [
    campaignId,
    leadIdsKey,
    hasPendingGeneration,
    readyRowCount,
    totalRowCount,
    status?.generating,
    isRegeneratingAll,
    isStartingGeneration,
    pollingPaused,
    partialGenerationAccepted,
    generationCancelled,
    draftPending,
    refresh,
  ]);

  useEffect(() => {
    const readyRows = emails.filter(isDraftReady);
    const allLeadEmailsSpamReady =
      readyRows.length > 0 && readyRows.every((row) => row.compliance_status === 'passed');
    const readyForOutreach = allGenerationComplete ? spamReadyRowCount : readyRowCount;
    const isComplete =
      totalRowCount > 0 &&
      readyRowCount >= totalRowCount &&
      !tableRows.some((row) => row.generation_status === 'generating' || row.generation_status === 'pending');

    onGenerationStateChange?.({
      isComplete: isComplete || partialGenerationAccepted,
      ready: readyForOutreach,
      total: totalRowCount,
      allLeadEmailsSpamReady,
      partialGenerationAccepted,
      readyForOutreach,
    });
  }, [
    emails,
    tableRows,
    readyRowCount,
    spamReadyRowCount,
    allGenerationComplete,
    totalRowCount,
    partialGenerationAccepted,
    onGenerationStateChange,
  ]);

  useEffect(() => {
    if (pollingPaused || generationCancelled) return;
    if (!isRegeneratingAll && !hasPendingGeneration && readyRowCount >= totalRowCount && totalRowCount > 0) {
      return;
    }
    const id = window.setInterval(() => {
      refresh().catch(() => undefined);
    }, 1500);
    return () => window.clearInterval(id);
  }, [
    refresh,
    pollingPaused,
    generationCancelled,
    isRegeneratingAll,
    hasPendingGeneration,
    readyRowCount,
    totalRowCount,
  ]);

  // If leads stay queued with nothing generating, resume background batch (e.g. Celery task failed).
  useEffect(() => {
    if (pollingPaused || partialGenerationAccepted || generationCancelled || draftPending) {
      stalledPollsRef.current = 0;
      resumeRequestedRef.current = false;
      return;
    }
    if (!hasPendingGeneration || readyRowCount >= totalRowCount) {
      stalledPollsRef.current = 0;
      resumeRequestedRef.current = false;
      return;
    }
    const queued = status?.queued ?? 0;
    const generating = status?.generating ?? 0;
    if (queued > 0 && generating === 0) {
      stalledPollsRef.current += 1;
      if (stalledPollsRef.current >= 3 && !resumeRequestedRef.current) {
        resumeRequestedRef.current = true;
        apiService
          .resumeCampaignLeadEmailGeneration(campaignId)
          .then(() => refresh())
          .catch(() => {
            resumeRequestedRef.current = false;
          });
      }
    } else {
      stalledPollsRef.current = 0;
      if (generating > 0) {
        resumeRequestedRef.current = false;
      }
    }
  }, [
    status,
    campaignId,
    pollingPaused,
    partialGenerationAccepted,
    generationCancelled,
    draftPending,
    hasPendingGeneration,
    readyRowCount,
    totalRowCount,
    refresh,
  ]);

  const filteredEmails = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return tableRows;
    return tableRows.filter((row) => {
      const name = (row.business_name || '').toLowerCase();
      const loc = (row.location || '').toLowerCase();
      const score = String(displayScore(row));
      return name.includes(q) || loc.includes(q) || score.includes(q);
    });
  }, [tableRows, searchQuery]);

  const paginatedEmails = useMemo(() => {
    const start = (currentPage - 1) * itemsPerPage;
    return filteredEmails.slice(start, start + itemsPerPage);
  }, [filteredEmails, currentPage, itemsPerPage]);

  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, itemsPerPage]);

  const handleRegenerateAll = async () => {
    setIsRegeneratingAll(true);
    setIsRegeneratingFailed(false);
    setPollingPaused(false);
    setPartialGenerationAccepted(false);
    setGenerationCancelled(false);
    stalledPollsRef.current = 0;
    resumeRequestedRef.current = false;
    setStatus((prev) =>
      prev
        ? { ...prev, is_complete: false, queued: prev.total, ready: 0, failed: 0, generating: 0 }
        : prev,
    );
    setEmails((prev) =>
      prev.map((row) => ({
        ...row,
        subject: null,
        body: null,
        generation_status: 'pending',
        compliance_status: 'pending',
        review_status: 'pending',
        last_error: null,
      })),
    );
    try {
      const res = await apiService.generateCampaignLeadEmails(campaignId, { regenerateAll: true });
      if (res.error) throw new Error(res.error);
      await refresh();
      toast.success('Regenerating emails for all leads', { id: 'cle-gen-regenerate-all' });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to regenerate emails';
      toast.error(msg);
      setIsRegeneratingAll(false);
      await refresh();
    }
  };

  const handleRegenerateFailed = async () => {
    if (failedRowCount <= 0 || isRegeneratingAll || isRegeneratingFailed) return;
    setIsRegeneratingFailed(true);
    setPollingPaused(false);
    setPartialGenerationAccepted(false);
    setGenerationCancelled(false);
    stalledPollsRef.current = 0;
    resumeRequestedRef.current = false;
    setEmails((prev) =>
      prev.map((row) =>
        row.generation_status === 'failed'
          ? {
              ...row,
              subject: null,
              body: null,
              generation_status: 'pending',
              compliance_status: 'pending',
              review_status: 'pending',
              last_error: null,
            }
          : row,
      ),
    );
    try {
      const res = await apiService.generateCampaignLeadEmails(campaignId, {
        regenerateFailed: true,
      });
      if (res.error) throw new Error(res.error);
      await refresh();
      toast.success(
        failedRowCount === 1
          ? 'Regenerating 1 failed email'
          : `Regenerating ${failedRowCount} failed emails`,
        { id: 'cle-gen-regenerate-failed' },
      );
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to regenerate failed emails';
      toast.error(msg);
      setIsRegeneratingFailed(false);
      await refresh();
    }
  };

  useEffect(() => {
    if (!isRegeneratingAll) return;
    if (readyRowCount >= totalRowCount && totalRowCount > 0) {
      setIsRegeneratingAll(false);
    }
  }, [isRegeneratingAll, readyRowCount, totalRowCount]);

  useEffect(() => {
    if (!isRegeneratingFailed) return;
    if (!hasPendingGeneration && failedRowCount === 0) {
      setIsRegeneratingFailed(false);
    }
  }, [isRegeneratingFailed, hasPendingGeneration, failedRowCount]);

  const handleCancelGeneration = async () => {
    if (partialGenerationAccepted || generationCancelled) return;
    try {
      const res = await apiService.cancelCampaignLeadEmailGeneration(campaignId);
      if (res.error) {
        toast.error(res.error);
        return;
      }
      setGenerationCancelled(true);
      setPollingPaused(true);
      setPartialGenerationAccepted(true);
      stalledPollsRef.current = 0;
      resumeRequestedRef.current = false;
      autoStartKeyRef.current = `${campaignId}:${leadIdsKey}`;
      await refresh();
      const ready = res.data?.ready ?? res.data?.ready_for_outreach ?? 0;
      if (ready <= 0) {
        toast.info('Email generation stopped. No emails are ready yet.', {
          id: 'cle-gen-cancelled-empty',
        });
        return;
      }
      toast.success(`${ready} email(s) ready for outreach. Click Next to continue.`, {
        id: 'cle-gen-partial-ready',
      });
    } catch {
      toast.error('Could not stop generation. Please try again.');
    }
  };

  const progressPct =
    totalRowCount > 0
      ? allGenerationComplete
        ? Math.round((spamReadyRowCount / totalRowCount) * 100)
        : Math.round((readyRowCount / totalRowCount) * 100)
      : 0;

  const displayReadyCount = allGenerationComplete ? spamReadyRowCount : readyRowCount;
  const totalCount = totalRowCount;

  const generationInFlight =
    isStartingGeneration ||
    isRegeneratingAll ||
    (status?.generating ?? 0) > 0 ||
    (hasPendingGeneration && readyRowCount < totalRowCount && !partialGenerationAccepted && !generationCancelled);

  const planLabel = planCapabilities?.label || planCapabilities?.plan || 'your plan';

  const bannerMeta =
    generationMode === 'template'
      ? `${templateName ? `${templateName} template` : 'Template'} · merge tags filled per lead`
      : generationMode === 'manual'
        ? 'Manual draft · merge tags filled per lead'
        : `${toneLabel} tone · per-lead personalization on · ${planLabel} plan`;

  const bannerTitleInProgress =
    generationMode === 'ai'
      ? 'Generating personalized emails…'
      : 'Personalizing emails for each lead…';

  const bannerTitle = (() => {
    if (partialGenerationAccepted) {
      return `${displayReadyCount} email${displayReadyCount === 1 ? '' : 's'} ready for outreach`;
    }
    if (allGenerationComplete && spamPendingRowCount > 0) {
      return `${spamPendingRowCount} email${spamPendingRowCount === 1 ? '' : 's'} need${spamPendingRowCount === 1 ? 's' : ''} a spam check`;
    }
    if (!generationInFlight && displayReadyCount >= totalCount && totalCount > 0) {
      return 'Personalized emails ready';
    }
    return bannerTitleInProgress;
  })();

  return (
    <div className="campaign-lead-email-generation">
      <div className="cle-gen-banner">
        <span
          className="cle-gen-banner-icon"
          style={{ '--progress': `${progressPct}%` } as React.CSSProperties}
          aria-hidden
        />
        <div className="cle-gen-banner-main">
          <div className="cle-gen-banner-text">
            <p className="cle-gen-banner-title">
              {bannerTitle}
            </p>
            <p className="cle-gen-banner-meta">{bannerMeta}</p>
          </div>
          <div className="cle-gen-progress-row">
            <div className="cle-gen-progress-track" aria-hidden>
              <div
                className="cle-gen-progress-fill"
                style={{ width: `${progressPct}%` }}
              />
            </div>
            <span className="cle-gen-progress-count">
              {displayReadyCount} / {totalCount}
            </span>
          </div>
        </div>
        <div className="cle-gen-banner-actions">
          <button
            type="button"
            className="evecta-secondary-btn"
            onClick={handleCancelGeneration}
            disabled={partialGenerationAccepted || (!generationInFlight && displayReadyCount >= totalCount && totalCount > 0 && spamPendingRowCount === 0)}
            title={
              partialGenerationAccepted
                ? 'Generation stopped — continue with ready emails'
                : 'Stop remaining generation and continue with completed emails'
            }
          >
            Cancel
          </button>
        </div>
      </div>

      {generationMode === 'ai' && (
      <section className="cle-gen-prompt" aria-label="Your email prompt">
        <span className="cle-gen-prompt-label">Your email prompt</span>
        <div className="cle-gen-prompt-field" aria-readonly="true">
          <p
            className={
              promptText
                ? 'cle-gen-prompt-value'
                : 'cle-gen-prompt-value cle-gen-prompt-value--empty'
            }
          >
            {promptText ||
              'No prompt saved for this campaign. Go back to compose and enter your email context, then generate again.'}
          </p>
        </div>
      </section>
      )}

      {allGenerationComplete && spamPendingRowCount > 0 && (
        <p className="cle-gen-spam-hint" role="status">
          {spamPendingRowCount === 1
            ? '1 email was edited and still needs a spam check — look for the amber “Spam check needed” row below.'
            : `${spamPendingRowCount} emails were edited and still need spam checks — look for amber “Spam check needed” rows below.`}
        </p>
      )}

      <div className="cle-gen-toolbar">
        <div className="cle-gen-search-wrap">
          <Search size={16} className="cle-gen-search-icon" aria-hidden />
          <input
            type="search"
            className="cle-gen-search"
            placeholder="Search leads by name, score or location…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
        <div className="cle-gen-toolbar-actions">
          {failedRowCount > 0 && (
            <button
              type="button"
              className="cle-gen-regenerate-failed"
              onClick={handleRegenerateFailed}
              disabled={
                isRegeneratingFailed ||
                isRegeneratingAll ||
                isStartingGeneration ||
                (generationInFlight && !partialGenerationAccepted)
              }
            >
              <RefreshCw
                size={16}
                className={isRegeneratingFailed ? 'cle-gen-spin' : ''}
                aria-hidden
              />
              Regenerate failed{generationMode === 'ai' ? ' mail' : ''}
            </button>
          )}
          <button
            type="button"
            className="cle-gen-regenerate-all"
            onClick={handleRegenerateAll}
            disabled={
              isRegeneratingAll ||
              isRegeneratingFailed ||
              isStartingGeneration ||
              (generationInFlight && !partialGenerationAccepted)
            }
          >
            <RefreshCw size={16} className={isRegeneratingAll ? 'cle-gen-spin' : ''} aria-hidden />
            Regenerate all{generationMode === 'ai' ? ' Emails' : ''}
          </button>
        </div>
      </div>

      <div className="cle-gen-table-wrap">
        <table className="cle-gen-table">
          <colgroup>
            <col className="cle-gen-col-name" />
            <col className="cle-gen-col-location" />
            <col className="cle-gen-col-score" />
            <col className="cle-gen-col-status" />
            <col className="cle-gen-col-actions" />
          </colgroup>
          <thead>
            <tr>
              <th>Company name</th>
              <th>Location</th>
              <th>Score</th>
              <th>Email status</th>
              <th className="cle-gen-th-actions">Actions</th>
            </tr>
          </thead>
          <tbody>
            {paginatedEmails.map((row) => {
              const status = resolveRowEmailStatus(row);
              const needsAttention = status.key === 'spam-needed' || status.key === 'spam-failed';
              return (
                <tr
                  key={row.id}
                  className={needsAttention ? 'cle-gen-row-attention' : undefined}
                >
                  <td className="cle-gen-td-name">{row.business_name || '—'}</td>
                  <td className="cle-gen-td-location" title={row.location || undefined}>
                    {row.location || '—'}
                  </td>
                  <td className="cle-gen-td-score">
                    <span className="cle-gen-score-pill">{displayScore(row)}%</span>
                  </td>
                  <td className="cle-gen-td-status">
                    <div className={`cle-gen-status cle-gen-status--${status.key}`}>
                      <span className="cle-gen-status-dot" aria-hidden />
                      <span className="cle-gen-status-text">{status.label}</span>
                      <span className="cle-gen-status-progress" aria-hidden>
                        <span
                          className="cle-gen-status-progress-fill"
                          style={{ width: `${rowStatusProgressPct(row, progressPct)}%` }}
                        />
                      </span>
                    </div>
                  </td>
                  <td className="cle-gen-td-actions">
                    {renderLeadAction(row, () => setPreviewRowId(row.id))}
                  </td>
                </tr>
              );
            })}
            {paginatedEmails.length === 0 && (
              <tr>
                <td colSpan={5} className="cle-gen-empty">
                  {tableRows.length === 0 ? 'Waiting for lead emails…' : 'No leads match your search.'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="cle-gen-table-footer">
        <DashboardPagination
          totalItems={filteredEmails.length}
          currentPage={currentPage}
          itemsPerPage={itemsPerPage}
          onPageChange={setCurrentPage}
          onItemsPerPageChange={(v) => {
            if (!Number.isNaN(v) && v > 0) setItemsPerPage(v);
          }}
          itemLabel="leads"
        />
      </div>

      {previewRowId && (
        <CampaignLeadEmailPreviewModal
          campaignId={campaignId}
          toneLabel={toneLabel}
          rows={tableRows}
          initialRowId={previewRowId}
          campaignLeads={selectedLeads}
          onClose={() => setPreviewRowId(null)}
          onEmailsChange={refresh}
        />
      )}
    </div>
  );
}
