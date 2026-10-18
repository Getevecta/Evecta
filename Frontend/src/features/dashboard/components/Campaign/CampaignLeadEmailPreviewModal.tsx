import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ChevronLeft, ChevronRight, Mail, Pencil, RefreshCw, X } from 'lucide-react';
import {
  apiService,
  CampaignLeadEmailRow,
  CampaignLeadResponse,
  SpamCheckResponse,
} from '../../../../shared/services/api';
import {
  countEmailWords,
  countFilledLeadVariables,
  formatLeadEmailPreviewBodyHtml,
  formatLeadEmailPreviewSubjectHtml,
  htmlToPlainTextWithBreaks,
  LeadPlaceholderData,
  plainTextToHtmlParagraphs,
} from './emailPersonalizationHighlight';
import { toast } from 'sonner';
import './CampaignLeadEmailPreviewModal.css';

/** Must match backend OUTREACH_READY_MIN_SCORE in compliance_gate.py */
const OUTREACH_READY_MIN_INBOX_SAFETY = 58;
const HIGH_RISK_MAX_INBOX_SAFETY = 40;

interface CampaignLeadEmailPreviewModalProps {
  campaignId: string;
  toneLabel: string;
  rows: CampaignLeadEmailRow[];
  initialRowId: string;
  campaignLeads?: CampaignLeadResponse[];
  onClose: () => void;
  onEmailsChange?: () => void;
  /** Step 5 — view only, no edit / approve / spam test */
  readOnly?: boolean;
  /** USER-mode From address */
  senderEmail?: string | null;
}

function rowLeadData(
  row: CampaignLeadEmailRow,
  campaignLeads: CampaignLeadResponse[],
): LeadPlaceholderData {
  const matched = campaignLeads.find(
    (lead) =>
      (row.campaign_lead_id && lead.id === row.campaign_lead_id) ||
      (row.lead_id && lead.lead_id === row.lead_id),
  );
  return {
    business_name: row.business_name,
    email: row.email,
    address: row.location,
    industry: matched?.lead?.industry ?? null,
    website: matched?.lead?.website ?? null,
    contact_number: matched?.lead?.contact_number ?? null,
  };
}

function recipientLabel(row: CampaignLeadEmailRow): string {
  return row.business_name?.trim() || 'Recipient';
}

function stripHtmlForCheck(html: string): string {
  const tmp = document.createElement('div');
  tmp.innerHTML = html;
  return tmp.textContent || tmp.innerText || '';
}

/** Mirror backend draft_quality_violations for instant UI feedback. */
function draftQualityIssues(subject: string, body: string): string[] {
  const text = `${subject} ${body}`;
  const issues: string[] = [];
  if (/\bIf[a-z]{3,}\b/.test(text)) {
    issues.push("Typo: merged word like 'Ifantastic' — use 'It's fantastic'.");
  }
  if (/\bif this like\b/i.test(text)) {
    issues.push("Grammar: 'If this like' — use e.g. 'If this sounds like'.");
  }
  if (/\bIf(?![\s,.:;'"])([a-z]{2,})/.test(text)) {
    issues.push("Typo: 'If' is merged into the next word.");
  }
  return [...new Set(issues)];
}

export function CampaignLeadEmailPreviewModal({
  campaignId,
  toneLabel,
  rows,
  initialRowId,
  campaignLeads = [],
  onClose,
  onEmailsChange,
  readOnly = false,
  senderEmail = null,
}: CampaignLeadEmailPreviewModalProps) {
  const [activeRowId, setActiveRowId] = useState(initialRowId);
  const [isApproving, setIsApproving] = useState(false);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [editSubject, setEditSubject] = useState('');
  const [editBody, setEditBody] = useState('');
  const [spamCheckResult, setSpamCheckResult] = useState<SpamCheckResponse | null>(null);
  const [isCheckingSpam, setIsCheckingSpam] = useState(false);
  const [lockedModalSize, setLockedModalSize] = useState<{ width: number; height: number } | null>(
    null,
  );
  const modalRef = useRef<HTMLDivElement>(null);
  const subjectEditableRef = useRef<HTMLDivElement>(null);
  const bodyEditableRef = useRef<HTMLDivElement>(null);

  const orderedRows = useMemo(
    () => [...rows].sort((a, b) => (a.lead_index ?? 0) - (b.lead_index ?? 0)),
    [rows],
  );

  const readyRows = useMemo(
    () =>
      rows.filter(
        (row) => row.generation_status === 'ready' && row.subject?.trim() && row.body?.trim(),
      ),
    [rows],
  );

  const activeRow = useMemo(() => {
    const fromAll = orderedRows.find((row) => row.id === activeRowId);
    if (fromAll) return fromAll;
    return readyRows[0] ?? orderedRows[0] ?? null;
  }, [orderedRows, activeRowId, readyRows]);

  const activeIndex = activeRow ? readyRows.findIndex((row) => row.id === activeRow.id) : -1;
  const activeIndexInAll = activeRow
    ? orderedRows.findIndex((row) => row.id === activeRow.id)
    : -1;

  const compliancePassed = activeRow?.compliance_status === 'passed';
  const needsSpamRetest = !!activeRow && !compliancePassed;

  useEffect(() => {
    if (!activeRow && readyRows.length > 0) {
      setActiveRowId(readyRows[0].id);
    }
  }, [activeRow, readyRows]);

  useEffect(() => {
    setIsEditing(false);
    setLockedModalSize(null);
    setSpamCheckResult(null);
    if (activeRow) {
      setEditSubject(stripHtmlForCheck(activeRow.subject || ''));
      setEditBody(htmlToPlainTextWithBreaks(activeRow.body || ''));
    }
  }, [activeRow?.id, activeRow?.subject, activeRow?.body, activeRow?.compliance_status]);

  const goPrev = useCallback(() => {
    if (activeIndex <= 0) return;
    setActiveRowId(readyRows[activeIndex - 1].id);
  }, [activeIndex, readyRows]);

  const goNext = useCallback(() => {
    if (activeIndex < 0 || activeIndex >= readyRows.length - 1) return;
    setActiveRowId(readyRows[activeIndex + 1].id);
  }, [activeIndex, readyRows]);

  const startEditing = () => {
    if (readOnly || !activeRow || !modalRef.current) return;
    const rect = modalRef.current.getBoundingClientRect();
    const subject = stripHtmlForCheck(activeRow.subject || '');
    const body = htmlToPlainTextWithBreaks(activeRow.body || '');
    setEditSubject(subject);
    setEditBody(body);
    setLockedModalSize({ width: rect.width, height: rect.height });
    setIsEditing(true);
    setSpamCheckResult(null);
    requestAnimationFrame(() => {
      if (subjectEditableRef.current) {
        subjectEditableRef.current.textContent = subject;
      }
      if (bodyEditableRef.current) {
        bodyEditableRef.current.innerText = body;
      }
    });
  };

  const cancelEditing = () => {
    if (!activeRow) return;
    const subject = stripHtmlForCheck(activeRow.subject || '');
    const body = htmlToPlainTextWithBreaks(activeRow.body || '');
    setEditSubject(subject);
    setEditBody(body);
    setIsEditing(false);
    setLockedModalSize(null);
  };

  const handleSaveEdit = async () => {
    if (!activeRow) return;
    const subject = (subjectEditableRef.current?.textContent || editSubject).trim();
    const bodyPlain = (bodyEditableRef.current?.innerText || editBody).trim();
    if (!subject || !bodyPlain) {
      toast.error('Please fill in both subject and body.');
      return;
    }

    setIsSaving(true);
    try {
      const res = await apiService.updateCampaignLeadEmail(campaignId, activeRow.id, {
        subject,
        body: plainTextToHtmlParagraphs(bodyPlain),
        mark_spam_passed: false,
      });
      if (res.error) {
        toast.error(res.error);
        return;
      }
      setEditSubject(subject);
      setEditBody(bodyPlain);
      setIsEditing(false);
      setLockedModalSize(null);
      setSpamCheckResult(null);
      await onEmailsChange?.();
      toast.success('Draft saved — run spam test before approving.');
    } finally {
      setIsSaving(false);
    }
  };

  const handleSpamCheck = async () => {
    if (!activeRow) return;
    if (isEditing) {
      toast.error('Save your changes before running the spam test.');
      return;
    }
    const subject = stripHtmlForCheck(activeRow.subject || '');
    const bodyPlain = htmlToPlainTextWithBreaks(activeRow.body || '');

    if (!subject || !bodyPlain) {
      toast.error('Please fill in both subject and body before checking spam.');
      return;
    }

    const qualityIssues = draftQualityIssues(subject, bodyPlain);
    if (qualityIssues.length > 0) {
      toast.error(`Please fix email quality issues before spam test: ${qualityIssues[0]}`);
      return;
    }

    setIsCheckingSpam(true);
    setSpamCheckResult(null);
    try {
      const response = await apiService.checkEmailSpam(campaignId, {
        subject,
        body: bodyPlain,
      });
      if (response.error) {
        toast.error(response.error || 'Failed to check spam. Please try again.');
        return;
      }
      if (!response.data) return;

      setSpamCheckResult(response.data);
      const inboxSafetyScore = 100 - response.data.spam_score;
      if (inboxSafetyScore <= HIGH_RISK_MAX_INBOX_SAFETY) {
        toast.error(
          `Spam check failed — high risk (inbox safety ${inboxSafetyScore}%). ` +
            'Please rewrite your email before approving.',
        );
        return;
      }
      if (inboxSafetyScore < OUTREACH_READY_MIN_INBOX_SAFETY) {
        toast.error(
          `Spam check failed — inbox safety ${inboxSafetyScore}% is below the ${OUTREACH_READY_MIN_INBOX_SAFETY}% minimum. ` +
            'Fix typos or improve wording, then test again.',
        );
        return;
      }

      const updateRes = await apiService.updateCampaignLeadEmail(campaignId, activeRow.id, {
        subject,
        body: activeRow.body || plainTextToHtmlParagraphs(bodyPlain),
        mark_spam_passed: true,
      });
      if (updateRes.error) {
        toast.error(updateRes.error);
        return;
      }

      await onEmailsChange?.();
      toast.success(`Spam check passed! Inbox safety score: ${inboxSafetyScore}%.`);
    } finally {
      setIsCheckingSpam(false);
    }
  };

  const handleRegenerate = async () => {
    if (!activeRow || isRegenerating || isEditing) return;

    setIsRegenerating(true);
    setIsEditing(false);
    setLockedModalSize(null);
    setSpamCheckResult(null);
    try {
      const res = await apiService.regenerateCampaignLeadEmail(campaignId, activeRow.id);
      if (res.error) {
        toast.error(res.error || 'Failed to regenerate email. Please try again.');
        return;
      }
      await onEmailsChange?.();
      toast.success('New draft generated — review and run spam test if needed.');
    } catch {
      toast.error('Failed to regenerate email. Please try again.');
    } finally {
      setIsRegenerating(false);
    }
  };

  const handleApprove = async () => {
    if (!activeRow || activeRow.review_status === 'approved') return;
    if (activeRow.compliance_status !== 'passed') {
      toast.error('Please pass the spam test before approving this email.');
      return;
    }
    setIsApproving(true);
    try {
      const res = await apiService.approveCampaignEmails(campaignId, { email_ids: [activeRow.id] });
      if (res.error) {
        toast.error(res.error);
        return;
      }
      await onEmailsChange?.();
      toast.success('Email approved and queued');
      if (activeIndex >= 0 && activeIndex < readyRows.length - 1) {
        setActiveRowId(readyRows[activeIndex + 1].id);
      } else {
        onClose();
      }
    } finally {
      setIsApproving(false);
    }
  };

  if (!activeRow) return null;

  const leadData = rowLeadData(activeRow, campaignLeads);
  const previewSubject = isEditing ? editSubject : activeRow.subject || '';
  const previewBody = isEditing ? editBody : activeRow.body || '';
  const subjectHtml = formatLeadEmailPreviewSubjectHtml(previewSubject, leadData);
  const bodyHtml = formatLeadEmailPreviewBodyHtml(previewBody, leadData);
  const wordCount = countEmailWords(isEditing ? editBody : activeRow.body || '');
  const variablesFilled = countFilledLeadVariables(
    previewSubject,
    isEditing ? editBody : activeRow.body || '',
    leadData,
  );
  const isApproved = activeRow.review_status === 'approved';
  const plainSubjectForQuality = stripHtmlForCheck(activeRow.subject || '');
  const plainBodyForQuality = htmlToPlainTextWithBreaks(activeRow.body || '');
  const qualityIssues = draftQualityIssues(plainSubjectForQuality, plainBodyForQuality);
  const hasQualityIssues = qualityIssues.length > 0;
  const canApprove =
    compliancePassed && !isApproved && !isEditing && !isRegenerating && !hasQualityIssues;
  const showEmailContent =
    !isRegenerating &&
    activeRow.generation_status === 'ready' &&
    !!activeRow.subject?.trim() &&
    !!activeRow.body?.trim();

  const inboxSafetyFromResult = spamCheckResult ? 100 - spamCheckResult.spam_score : null;
  const spamCheckFailed =
    inboxSafetyFromResult != null &&
    (inboxSafetyFromResult <= HIGH_RISK_MAX_INBOX_SAFETY ||
      inboxSafetyFromResult < OUTREACH_READY_MIN_INBOX_SAFETY);

  return createPortal(
    <div
      className="cle-preview-overlay"
      onClick={onClose}
    >
      <div
        ref={modalRef}
        className={`cle-preview-modal${isEditing ? ' cle-preview-modal--editing' : ''}${readOnly ? ' cle-preview-modal--readonly' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="cle-preview-title"
        style={
          lockedModalSize
            ? {
                width: lockedModalSize.width,
                minWidth: lockedModalSize.width,
                maxWidth: lockedModalSize.width,
                height: lockedModalSize.height,
                minHeight: lockedModalSize.height,
                maxHeight: lockedModalSize.height,
              }
            : undefined
        }
        onClick={(e) => e.stopPropagation()}
      >
        <header className="cle-preview-header">
          <div className="cle-preview-header-left">
            <div className="cle-preview-icon" aria-hidden>
              <Mail size={18} strokeWidth={2} />
            </div>
            <div className="cle-preview-header-text">
              <h2 id="cle-preview-title" className="cle-preview-title">
                Email preview — {activeRow.business_name || 'Lead'}
              </h2>
              <p className="cle-preview-to">
                To: {recipientLabel(activeRow)}
                {activeRow.email ? ` · ${activeRow.email}` : ''}
              </p>
            </div>
          </div>
          <div className="cle-preview-header-right">
            {activeIndex > 0 && (
              <button
                type="button"
                className="cle-preview-nav-btn"
                onClick={goPrev}
                disabled={!readOnly && (isEditing || isRegenerating)}
                aria-label="Previous lead"
              >
                <ChevronLeft size={16} aria-hidden />
                Prev
              </button>
            )}
            <span className="cle-preview-nav-status">
              {activeIndex + 1} of {readyRows.length}
            </span>
            <button
              type="button"
              className="cle-preview-nav-btn"
              onClick={goNext}
              disabled={
                readOnly
                  ? activeIndex < 0 || activeIndex >= readyRows.length - 1
                  : isEditing || isRegenerating || activeIndex < 0 || activeIndex >= readyRows.length - 1
              }
              aria-label="Next lead"
            >
              Next
              <ChevronRight size={16} aria-hidden />
            </button>
            <button
              type="button"
              className="cle-preview-close"
              onClick={onClose}
              aria-label="Close preview"
            >
              <X size={16} />
            </button>
          </div>
        </header>

        <div className="cle-preview-meta">
          <span className="cle-preview-pill">
            Tone: <strong>{toneLabel}</strong>
          </span>
          <span className="cle-preview-pill">
            Length: <strong>{wordCount} words</strong>
          </span>
          <span className="cle-preview-pill">
            {variablesFilled} variables filled
          </span>
        </div>

        <div className="cle-preview-divider" aria-hidden />

        <div className="cle-preview-email">
          {isRegenerating ? (
            <div className="cle-preview-regenerating" role="status" aria-live="polite">
              <RefreshCw size={28} className="cle-preview-regenerating-icon" aria-hidden />
              <p className="cle-preview-regenerating-title">Regenerating email…</p>
              <p className="cle-preview-regenerating-text">
                Creating a new draft for {activeRow.business_name || 'this lead'}. This may take a moment.
              </p>
            </div>
          ) : isEditing ? (
            <div className="cle-preview-edit-form">
              {senderEmail ? (
                <div className="cle-preview-field cle-preview-field--row">
                  <span className="cle-preview-field-label">From</span>
                  <span className="cle-preview-field-value">{senderEmail}</span>
                </div>
              ) : null}
              <div className="cle-preview-field cle-preview-field--row cle-preview-field--subject">
                <span className="cle-preview-field-label">Subject</span>
                <div
                  ref={subjectEditableRef}
                  className="cle-preview-field-value cle-preview-subject cle-preview-editable"
                  contentEditable
                  suppressContentEditableWarning
                  role="textbox"
                  aria-label="Email subject"
                  onInput={(e) => setEditSubject(e.currentTarget.textContent || '')}
                />
              </div>
              <div className="cle-preview-divider cle-preview-divider--inner" aria-hidden />
              <div
                ref={bodyEditableRef}
                className="cle-preview-body cle-preview-editable cle-preview-editable--body"
                contentEditable
                suppressContentEditableWarning
                role="textbox"
                aria-label="Email body"
                onInput={(e) => setEditBody(e.currentTarget.innerText || '')}
              />
            </div>
          ) : showEmailContent ? (
            <>
              {senderEmail ? (
                <div className="cle-preview-field cle-preview-field--row">
                  <span className="cle-preview-field-label">From</span>
                  <span className="cle-preview-field-value">{senderEmail}</span>
                </div>
              ) : null}
              <div className="cle-preview-field cle-preview-field--row cle-preview-field--subject">
                <span className="cle-preview-field-label">Subject</span>
                <span
                  className="cle-preview-field-value cle-preview-subject"
                  dangerouslySetInnerHTML={{ __html: subjectHtml || '—' }}
                />
              </div>
              <div className="cle-preview-divider cle-preview-divider--inner" aria-hidden />
              <div
                className="cle-preview-body"
                dangerouslySetInnerHTML={{ __html: bodyHtml || '<p>—</p>' }}
              />
            </>
          ) : (
            <div className="cle-preview-regenerating" role="status">
              <p className="cle-preview-regenerating-text">Email draft is not available yet.</p>
            </div>
          )}
        </div>

        {hasQualityIssues && !isEditing && !readOnly && !isRegenerating && (
          <div className="cle-preview-quality-section">
            <p className="cle-preview-quality-text">
              This draft has wording issues that must be fixed before approval:{' '}
              {qualityIssues.join(' ')}
            </p>
          </div>
        )}

        {needsSpamRetest && !isEditing && !readOnly && !isRegenerating && (
          <div className="cle-preview-spam-section">
            <div className="cle-preview-spam-banner">
              <span className="cle-preview-spam-text">
                Take a moment to preview your message and ensure your hard work makes the best
                possible impact.
                {inboxSafetyFromResult != null && (
                  <>
                    {' '}
                    Inbox safety: <strong>{inboxSafetyFromResult}%</strong>
                    {inboxSafetyFromResult < OUTREACH_READY_MIN_INBOX_SAFETY && (
                      <> (need {OUTREACH_READY_MIN_INBOX_SAFETY}%+ to approve)</>
                    )}
                  </>
                )}
              </span>
              <button
                type="button"
                onClick={handleSpamCheck}
                disabled={isCheckingSpam || compliancePassed || isSaving}
                className={`cle-preview-spam-btn ${
                  compliancePassed ? 'cle-preview-spam-btn--passed' : ''
                } ${spamCheckFailed ? 'cle-preview-spam-btn--failed' : ''}`}
              >
                {isCheckingSpam
                  ? 'Checking…'
                  : compliancePassed
                    ? 'Spam Check Passed'
                    : spamCheckFailed
                      ? 'Spam Check Failed'
                      : 'Spam Email Test'}
              </button>
            </div>
          </div>
        )}

        {readOnly && compliancePassed && !isEditing && (
          <div className="cle-preview-spam-section">
            <div className="cle-preview-spam-banner">
              <span className="cle-preview-spam-text">
                This email passed inbox safety checks and is ready for outreach.
              </span>
              <span
                className="cle-preview-spam-btn cle-preview-spam-btn--passed cle-preview-spam-btn--readonly"
                aria-label="Spam check passed"
              >
                Spam Check Passed
              </span>
            </div>
          </div>
        )}

        <div className="cle-preview-divider" aria-hidden />

        {readOnly ? (
          <footer className="cle-preview-footer cle-preview-footer--readonly">
            <button type="button" className="cle-preview-close-btn" onClick={onClose}>
              Close
            </button>
          </footer>
        ) : (
        <footer className="cle-preview-footer">
          {isEditing ? (
            <>
              <button
                type="button"
                className="cle-preview-edit-btn"
                onClick={cancelEditing}
                disabled={isSaving}
              >
                Cancel
              </button>
              <button
                type="button"
                className="cle-preview-approve-btn"
                onClick={handleSaveEdit}
                disabled={isSaving}
              >
                {isSaving ? 'Saving…' : 'Save changes'}
              </button>
            </>
          ) : (
            <>
              <div className="cle-preview-footer-actions">
                <button
                  type="button"
                  className="cle-preview-edit-btn"
                  onClick={startEditing}
                  disabled={isRegenerating || isApproving || !showEmailContent}
                >
                  <Pencil size={16} aria-hidden />
                  Edit draft
                </button>
                <button
                  type="button"
                  className="cle-preview-regenerate-btn"
                  onClick={handleRegenerate}
                  disabled={isRegenerating || isApproving || isSaving}
                >
                  <RefreshCw
                    size={16}
                    aria-hidden
                    className={isRegenerating ? 'cle-preview-regenerate-spin' : undefined}
                  />
                  {isRegenerating ? 'Regenerating…' : 'Regenerate email'}
                </button>
              </div>
              <button
                type="button"
                className="cle-preview-approve-btn"
                onClick={handleApprove}
                disabled={isApproving || isApproved || !canApprove || isRegenerating}
                title={
                  isRegenerating
                    ? 'Wait for regeneration to finish'
                    : hasQualityIssues
                    ? 'Fix typos in the email before approving'
                    : !compliancePassed
                      ? 'Pass spam test before approving'
                      : isApproved
                        ? 'Already approved'
                        : undefined
                }
              >
                {isApproved ? 'Approved' : isApproving ? 'Approving…' : 'Approve'}
              </button>
            </>
          )}
        </footer>
        )}
      </div>
    </div>,
    document.body,
  );
}
