import { useState, useEffect, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import {
  apiService,
  CampaignLeadEmailRow,
  CampaignLeadResponse,
  CampaignResponse,
  PlanCapabilitiesResponse,
} from '../../../../shared/services/api';
import { CampaignEmailReview } from './CampaignEmailReview';
import './PreviewContentModal.css';
import {
  formatPersonalizedPreviewEmailHtml,
  LeadPlaceholderData,
} from './emailPersonalizationHighlight';

interface PreviewContentModalProps {
  campaignId: string;
  onClose: () => void;
}

interface PreviewLead extends LeadPlaceholderData {
  id: string;
}

function resolveToneLabel(toneId: string | undefined, capabilities: PlanCapabilitiesResponse | null): string {
  if (!toneId) return 'Professional';
  const tiers = capabilities?.tone_tiers ?? [];
  for (const tier of tiers) {
    const match = tier.tones.find((t) => t.id === toneId);
    if (match) return match.label;
  }
  const fromOptions = capabilities?.tone_options?.find((t) => t.id === toneId);
  if (fromOptions) return fromOptions.label;
  return toneId.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function mapCampaignLeadToPreviewLead(campaignLead: CampaignLeadResponse): PreviewLead | null {
  const leadInfo = campaignLead.lead;
  const id = leadInfo?.id || campaignLead.lead_id;
  if (!id) return null;

  return {
    id,
    business_name: leadInfo?.business_name,
    email: leadInfo?.email,
    address: leadInfo?.address,
    industry: leadInfo?.industry,
    website: leadInfo?.website,
    contact_number: leadInfo?.contact_number,
    first_name: null,
    last_name: null,
    job_title: null,
  };
}

function PreviewContentModalShell({
  onClose,
  wide,
  children,
}: {
  onClose: () => void;
  wide?: boolean;
  children: ReactNode;
}) {
  return createPortal(
    <div className="preview-content-modal-overlay" onClick={onClose}>
      <div
        className={`preview-content-modal${wide ? ' preview-content-modal--wide' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="preview-content-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="preview-content-modal-header">
          <h2 id="preview-content-modal-title" className="preview-content-modal-title">
            Preview Content
          </h2>
          <button
            type="button"
            className="preview-content-modal-close"
            onClick={onClose}
            aria-label="Close"
          >
            <X size={20} />
          </button>
        </div>
        <div className="preview-content-modal-body">{children}</div>
      </div>
    </div>,
    document.body,
  );
}

export function PreviewContentModal({ campaignId, onClose }: PreviewContentModalProps) {
  const [campaign, setCampaign] = useState<CampaignResponse | null>(null);
  const [leadEmails, setLeadEmails] = useState<CampaignLeadEmailRow[]>([]);
  const [campaignLeads, setCampaignLeads] = useState<CampaignLeadResponse[]>([]);
  const [legacyLeads, setLegacyLeads] = useState<PreviewLead[]>([]);
  const [toneLabel, setToneLabel] = useState('Professional');
  const [emailSubject, setEmailSubject] = useState('');
  const [emailContent, setEmailContent] = useState('');
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (!campaignId) return;

    const fetchData = async () => {
      setIsLoading(true);
      try {
        const [campaignResponse, leadsResponse, emailsResponse, capabilitiesResponse] =
          await Promise.all([
            apiService.getCampaignById(campaignId),
            apiService.getCampaignLeads(campaignId),
            apiService.getCampaignLeadEmails(campaignId),
            apiService.getPersonalizationCapabilities(),
          ]);

        if (campaignResponse.data) {
          setCampaign(campaignResponse.data);
          setEmailSubject(campaignResponse.data.email_subject || '');
          setEmailContent(campaignResponse.data.email_content || '');
          setToneLabel(
            resolveToneLabel(campaignResponse.data.tone, capabilitiesResponse.data ?? null),
          );
        }

        if (leadsResponse.data && Array.isArray(leadsResponse.data)) {
          setCampaignLeads(leadsResponse.data);
          const mapped = leadsResponse.data
            .map((cl) => mapCampaignLeadToPreviewLead(cl))
            .filter((lead): lead is PreviewLead => lead !== null);
          setLegacyLeads(mapped);
        }

        if (emailsResponse.data) {
          setLeadEmails(emailsResponse.data);
        }
      } catch (error) {
        console.error('Failed to load preview:', error);
      } finally {
        setIsLoading(false);
      }
    };

    fetchData();
  }, [campaignId]);

  const hasPerLeadEmails = leadEmails.some(
    (row) => row.generation_status === 'ready' && row.subject && row.body,
  );

  if (isLoading) {
    return (
      <PreviewContentModalShell onClose={onClose} wide={hasPerLeadEmails}>
        <div className="preview-loading">Loading...</div>
      </PreviewContentModalShell>
    );
  }

  if (!campaign) {
    return (
      <PreviewContentModalShell onClose={onClose}>
        <div className="preview-error">Campaign not found</div>
      </PreviewContentModalShell>
    );
  }

  if (hasPerLeadEmails) {
    return (
      <PreviewContentModalShell onClose={onClose} wide>
        <CampaignEmailReview
          campaignId={campaignId}
          emails={leadEmails}
          toneLabel={toneLabel}
          campaignLeads={campaignLeads}
          senderEmail={
            campaign.email_sending_mode === 'USER' ? campaign.sender_email || null : null
          }
          viewOnly
        />
      </PreviewContentModalShell>
    );
  }

  const previewLead = legacyLeads.length > 0 ? legacyLeads[0] : null;

  return (
    <PreviewContentModalShell onClose={onClose}>
      <div className="preview-content-modal-section">
        <div className="preview-content-modal-card">
          <h3 className="preview-content-modal-card-title">Email Preview</h3>
          <div className="preview-content-modal-email">
            {campaign.email_sending_mode === 'USER' && campaign.sender_email ? (
              <div className="preview-content-modal-email-row">
                <span className="preview-content-modal-label">From:</span>
                <span className="preview-content-modal-value">{campaign.sender_email}</span>
              </div>
            ) : null}
            <div className="preview-content-modal-email-row">
              <span className="preview-content-modal-label">Subject:</span>
              <span
                className="preview-content-modal-value"
                dangerouslySetInnerHTML={{
                  __html:
                    formatPersonalizedPreviewEmailHtml(emailSubject, previewLead, {
                      multiline: false,
                    }) || 'No subject',
                }}
              />
            </div>
            <div className="preview-content-modal-email-body">
              {emailContent ? (
                <div
                  className="preview-content-modal-email-body-text"
                  dangerouslySetInnerHTML={{
                    __html: formatPersonalizedPreviewEmailHtml(emailContent, previewLead),
                  }}
                />
              ) : (
                <div className="preview-content-modal-email-body-text">
                  <p>No email content available</p>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </PreviewContentModalShell>
  );
}
