import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  apiService,
  CampaignEmailReviewSummary,
  CampaignLeadEmailRow,
  CampaignLeadResponse,
} from '../../../../shared/services/api';
import { CampaignLeadEmailPreviewModal } from './CampaignLeadEmailPreviewModal';
import './CampaignEmailReview.css';

interface CampaignEmailReviewProps {
  campaignId: string;
  emails: CampaignLeadEmailRow[];
  toneLabel: string;
  campaignLeads?: CampaignLeadResponse[];
  onEmailsChange?: (emails: CampaignLeadEmailRow[]) => void;
  onReviewSummaryChange?: (summary: CampaignEmailReviewSummary | null) => void;
  /** Ongoing / sent campaigns — view emails only, no selection or review actions */
  viewOnly?: boolean;
  /** USER-mode From address — shown in footer when present */
  senderEmail?: string | null;
}

type ReviewStatusKey = 'approved' | 'review' | 'editing' | 'rejected' | 'failed';

export function isApprovedLeadEmailRow(row: CampaignLeadEmailRow): boolean {
  if (row.generation_status === 'failed') return false;
  if (row.generation_status === 'generating' || row.generation_status === 'pending') return false;
  if (row.review_status === 'rejected') return false;
  if (row.generation_status !== 'ready') return false;
  if (row.compliance_status !== 'passed') return false;
  if (!row.subject?.trim() || !row.body?.trim()) return false;
  return true;
}

function reviewStatus(row: CampaignLeadEmailRow): { key: ReviewStatusKey; label: string } {
  if (row.review_status === 'approved') return { key: 'approved', label: 'Approved' };
  if (row.review_status === 'rejected') return { key: 'rejected', label: 'Rejected' };
  if (row.generation_status === 'failed') return { key: 'failed', label: 'Failed' };
  if (row.generation_status === 'generating' || row.generation_status === 'pending') {
    return { key: 'editing', label: 'Editing' };
  }
  // Outreach-ready from Step 3 (compliance passed) — show as approved, not review
  if (row.generation_status === 'ready' && row.compliance_status === 'passed') {
    return { key: 'approved', label: 'Approved' };
  }
  return { key: 'review', label: 'Review' };
}

function canOpenPreview(row: CampaignLeadEmailRow): boolean {
  return row.generation_status === 'ready' && !!row.subject && !!row.body;
}

export function CampaignEmailReview({
  campaignId,
  emails,
  toneLabel,
  campaignLeads = [],
  onEmailsChange,
  onReviewSummaryChange,
  viewOnly = false,
  senderEmail = null,
}: CampaignEmailReviewProps) {
  const [summary, setSummary] = useState<CampaignEmailReviewSummary | null>(null);
  const [previewRowId, setPreviewRowId] = useState<string | null>(null);

  const refreshSummary = useCallback(async () => {
    if (viewOnly) return;
    const res = await apiService.getCampaignEmailReviewSummary(campaignId);
    if (res.data) {
      setSummary(res.data);
      onReviewSummaryChange?.(res.data);
    }
  }, [campaignId, onReviewSummaryChange, viewOnly]);

  const refreshEmails = useCallback(async () => {
    const res = await apiService.getCampaignLeadEmails(campaignId);
    if (res.data) {
      onEmailsChange?.(res.data);
    }
  }, [campaignId, onEmailsChange]);

  useEffect(() => {
    if (viewOnly || !campaignId || emails.length === 0) return;
    refreshSummary();
  }, [campaignId, emails.length, refreshSummary, viewOnly]);

  const approvedEmails = useMemo(
    () => emails.filter(isApprovedLeadEmailRow),
    [emails],
  );

  const viewableEmails = useMemo(
    () =>
      [...emails]
        .filter(canOpenPreview)
        .sort((a, b) => (a.lead_index ?? 0) - (b.lead_index ?? 0)),
    [emails],
  );

  const listedEmails = viewOnly ? viewableEmails : approvedEmails;

  if (emails.length === 0) {
    return null;
  }

  if (listedEmails.length === 0) {
    return (
      <div className="campaign-email-review campaign-email-review--empty">
        <p>
          {viewOnly
            ? 'No email content available for this campaign yet.'
            : 'No approved emails yet. Go back to Step 3 to finish outreach-ready drafts.'}
        </p>
      </div>
    );
  }

  const total = listedEmails.length;

  return (
    <div className={`campaign-email-review${viewOnly ? ' campaign-email-review--view-only' : ''}`}>
      <div className="campaign-email-review-table-wrap">
        <div className="campaign-email-review-header" role="row">
          <span>Lead / Subject preview</span>
          <span>Tone</span>
          <span>Status</span>
          <span className="campaign-email-review-header-action" aria-hidden />
        </div>
        <div className="campaign-email-review-body" role="rowgroup">
          {listedEmails.map((row) => {
            const status = viewOnly
              ? { key: 'approved' as const, label: 'Sent' }
              : reviewStatus(row);
            const subjectPreview = row.subject
              ? `Subject: ${row.subject}`
              : status.key === 'editing'
                ? 'Draft in progress…'
                : 'No subject yet';
            return (
              <div key={row.id} className="campaign-email-review-row" role="row">
                <div className="campaign-email-review-td-lead">
                  <span className="campaign-email-review-company">
                    {row.business_name || row.email || 'Lead'}
                  </span>
                  <span className="campaign-email-review-subject">{subjectPreview}</span>
                </div>
                <div className="campaign-email-review-td-tone">
                  <span className="campaign-email-review-tone-pill">{toneLabel}</span>
                </div>
                <div className="campaign-email-review-td-status">
                  <span className={`campaign-email-review-status campaign-email-review-status--${status.key}`}>
                    <span className="campaign-email-review-status-dot" aria-hidden />
                    {status.label}
                  </span>
                </div>
                <div className="campaign-email-review-td-action">
                  {canOpenPreview(row) ? (
                    <button
                      type="button"
                      className="campaign-email-review-open"
                      onClick={(e) => {
                        e.stopPropagation();
                        setPreviewRowId(row.id);
                      }}
                    >
                      View
                    </button>
                  ) : (
                    <span className="campaign-email-review-open-disabled">—</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="campaign-email-review-table-footer">
        <span className="campaign-email-review-showing">
          {total} {total === 1 ? 'lead' : 'leads'}
          {senderEmail ? ` · From ${senderEmail}` : ''}
        </span>
      </div>

      {previewRowId && (
        <CampaignLeadEmailPreviewModal
          campaignId={campaignId}
          toneLabel={toneLabel}
          rows={listedEmails}
          initialRowId={previewRowId}
          campaignLeads={campaignLeads}
          senderEmail={senderEmail}
          readOnly
          onClose={() => setPreviewRowId(null)}
          onEmailsChange={
            viewOnly
              ? undefined
              : async () => {
                  await refreshEmails();
                  await refreshSummary();
                }
          }
        />
      )}
    </div>
  );
}
