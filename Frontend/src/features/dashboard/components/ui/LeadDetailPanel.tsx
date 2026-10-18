import { X, Mail, FileText, ClipboardList, User, Phone } from 'lucide-react';
import { CheckCircle2 } from 'lucide-react';
import './LeadDetailPanel.css';

/**
 * Normalized lead data for the detail panel.
 * Supports leads from LeadDatabase, LeadLog, LeadGeneration, DetailCampaignScreen.
 */
export interface LeadDetailInput {
  id?: string;
  companyName?: string;
  business_name?: string;
  email?: string;
  contact_number?: string;
  phone?: string;
  location?: string;
  address?: string;
  tags?: string[];
  industry?: string;
  score?: number;
  lead_score?: number;
  outreach_status?: string;
  last_contacted?: string | null;
  campaign_status?: string;
}

function normalizeLead(raw: LeadDetailInput): {
  companyName: string;
  category: string;
  score: number;
  email: string;
  phone: string;
  industry: string;
  location: string;
  categoryValue: string;
  outreachStatus: string;
  lastContacted: string | null;
  campaignStatus?: string;
} {
  const companyName = raw.companyName ?? raw.business_name ?? 'N/A';
  const category = raw.tags?.[0] ?? raw.industry ?? 'No category';
  const score = raw.score ?? raw.lead_score ?? 0;
  const email = raw.email ?? 'N/A';
  const phoneRaw = raw.contact_number ?? raw.phone;
  const phone =
    phoneRaw !== undefined && phoneRaw !== null && String(phoneRaw).trim() !== ''
      ? String(phoneRaw).trim()
      : 'N/A';
  const industry = raw.tags?.[0] ?? raw.industry ?? 'N/A';
  const location = raw.location ?? raw.address ?? 'N/A';
  const s = score;
  const categoryValue = s >= 90 ? 'High Value' : s >= 70 ? 'Medium Value' : 'Low Value';
  const outreachStatus = raw.outreach_status ?? 'not_started';
  const lastContacted = raw.last_contacted ?? null;
  const campaignStatus = raw.campaign_status;

  return {
    companyName,
    category,
    score,
    email,
    phone,
    industry,
    location,
    categoryValue,
    outreachStatus,
    lastContacted,
    campaignStatus,
  };
}

const STATUS_CONFIG: Record<string, { bg: string; color: string; text: string; icon: typeof CheckCircle2 | null; borderColor?: string }> = {
  not_started: { bg: 'transparent', color: '#EF4444', text: 'Not Started', icon: null, borderColor: undefined },
  contacted: { bg: '#FEF3C7', color: '#92400E', text: 'Contacted', icon: null, borderColor: undefined },
  replied: { bg: '#10B981', color: 'white', text: 'Replied', icon: CheckCircle2, borderColor: undefined },
  no_response: { bg: '#FEE2E2', color: '#991B1B', text: 'No Response', icon: null, borderColor: undefined },
  ongoing: { bg: '#DBEAFE', color: '#1E40AF', text: 'Ongoing', icon: null, borderColor: undefined },
};

interface LeadDetailPanelProps {
  lead: LeadDetailInput;
  onClose: () => void;
}

export function LeadDetailPanel({ lead, onClose }: LeadDetailPanelProps) {
  const data = normalizeLead(lead);

  const displayStatus = data.campaignStatus === 'ongoing' ? 'ongoing' : data.outreachStatus;
  const config = STATUS_CONFIG[displayStatus] ?? STATUS_CONFIG.not_started;

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', { month: '2-digit', day: '2-digit', year: 'numeric' });
  };

  return (
    <div className="lead-detail-panel-wrapper">
      <div
        className="lead-detail-panel-backdrop"
        onClick={onClose}
        aria-hidden="true"
      />
      <div className="lead-detail-panel">
        <div className="lead-detail-panel-close-strip">
          <button
            onClick={onClose}
            className="lead-detail-panel-close-button"
            type="button"
            aria-label="Close"
          >
            <X className="lead-detail-panel-close-icon" aria-hidden />
          </button>
        </div>

        <div className="lead-detail-panel-body">
          <div className="lead-detail-panel-header">
            <div className="lead-detail-panel-title-row">
              <h2 className="lead-detail-panel-title">{data.companyName}</h2>
              <span className="lead-detail-panel-score-badge">{`${data.score}% Score`}</span>
            </div>
            <p className="lead-detail-panel-category">{data.category}</p>
          </div>

          <div className="lead-detail-panel-content">
          {/* Contact Information */}
          <div className="lead-detail-panel-section">
            <h3 className="lead-detail-panel-section-title">
              <User className="lead-detail-panel-section-icon" size={16} />
              Contact Information
            </h3>
            <div className="lead-detail-panel-contact-stack">
              <div className="lead-detail-panel-contact-row">
                <Mail className="lead-detail-panel-contact-icon" size={14} />
                <span className={data.email === 'N/A' ? 'lead-detail-panel-contact-text' : 'lead-detail-panel-contact-text lead-detail-panel-contact-value'}>{data.email}</span>
              </div>
              <div className="lead-detail-panel-contact-row">
                <Phone className="lead-detail-panel-contact-icon" size={14} />
                <span className={data.phone === 'N/A' ? 'lead-detail-panel-contact-text' : 'lead-detail-panel-contact-text lead-detail-panel-contact-value'}>{data.phone}</span>
              </div>
            </div>
          </div>

          {/* Company Details */}
          <div className="lead-detail-panel-section">
            <h3 className="lead-detail-panel-section-title">
              <FileText className="lead-detail-panel-section-icon" size={16} />
              Company Details
            </h3>
            <div className="lead-detail-panel-info-list">
              <div className="lead-detail-panel-info-row">
                <span className="lead-detail-panel-info-label">Industry:</span>
                <span className="lead-detail-panel-info-value">{data.industry}</span>
              </div>
              <div className="lead-detail-panel-info-row">
                <span className="lead-detail-panel-info-label">Location:</span>
                <span className="lead-detail-panel-info-value">{data.location}</span>
              </div>
              <div className="lead-detail-panel-info-row">
                <span className="lead-detail-panel-info-label">Category:</span>
                <span className="lead-detail-panel-info-value">{data.categoryValue}</span>
              </div>
            </div>
          </div>

          {/* Outreach Details */}
          <div className="lead-detail-panel-section">
            <h3 className="lead-detail-panel-section-title">
              <ClipboardList className="lead-detail-panel-section-icon" size={16} />
              Outreach Details
            </h3>
            <div className="lead-detail-panel-info-list">
              <div className="lead-detail-panel-info-row">
                <span className="lead-detail-panel-info-label">Status:</span>
                <span
                  className={displayStatus === 'not_started' ? 'lead-detail-panel-status-text' : 'lead-detail-panel-status-badge'}
                  style={{
                    backgroundColor: displayStatus === 'not_started' ? undefined : config.bg,
                    color: config.color,
                    border: config.borderColor ? `2px solid ${config.borderColor}` : 'none',
                  }}
                >
                  {config.icon && <config.icon size={12} style={{ color: config.color }} />}
                  {config.text}
                </span>
              </div>
              <div className="lead-detail-panel-info-row">
                <span className="lead-detail-panel-info-label">Last Contacted:</span>
                {!data.lastContacted || data.outreachStatus === 'not_started' ? (
                  <span className="lead-detail-panel-info-value lead-detail-panel-info-value-muted">
                    Not Contacted Yet
                  </span>
                ) : (
                  <span className="lead-detail-panel-info-value">
                    {formatDate(data.lastContacted)}
                  </span>
                )}
              </div>
            </div>
          </div>
          </div>
        </div>
      </div>
    </div>
  );
}
