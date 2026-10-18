import React, { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { X } from 'lucide-react';
import { apiService } from '../../../../shared/services/api';
import { toast } from 'sonner';
import './IMAPConsentPage.css';

interface IMAPConsentPageProps {
  campaignId?: string;
  redirectTo?: string;
  asModal?: boolean;
  onClose?: () => void;
}

export function IMAPConsentPage({ campaignId, redirectTo, asModal, onClose }: IMAPConsentPageProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const [isConnecting, setIsConnecting] = useState(false);

  // Only trust router `location.state.campaignId` when not in the Email Accounts modal — otherwise a stale
  // campaign id from a previous visit keeps us on the "campaign" branch (Connecting…) on the wrong page.
  const isEmailAccountsModalFlow =
    Boolean(asModal && redirectTo === '/dashboard/email-accounts');
  const finalCampaignId =
    campaignId ?? (isEmailAccountsModalFlow ? undefined : location.state?.campaignId);
  const finalRedirectTo = redirectTo || location.state?.redirectTo;

  const handleContinue = async () => {
    try {
      // Store flags based on where we came from
      if (finalCampaignId) {
        setIsConnecting(true);
        // Coming from campaign step 4
        sessionStorage.setItem(`campaignEmailAccountChoice_${finalCampaignId}`, 'existing');
        sessionStorage.setItem(`campaignEmailAccountStep_${finalCampaignId}`, finalCampaignId);
        sessionStorage.setItem('editCampaignId', finalCampaignId);
        sessionStorage.setItem('openExistingEmailsTab', 'true');
        sessionStorage.setItem('cameFromCampaign', 'true');
        // Navigate back to campaign step 4 with IMAP form flag
        sessionStorage.setItem('showImapForm', 'true');
        navigate('/dashboard/campaign-creation', { 
          replace: true,
          state: { showImapForm: true, campaignId: finalCampaignId }
        });
      } else {
        // Email accounts: dismiss consent first, then open IMAP credentials modal (no "Connecting…")
        onClose?.();
        sessionStorage.setItem('openExistingEmailsTab', 'true');
        sessionStorage.setItem('showImapForm', 'true');
        sessionStorage.setItem('showManagementView', 'true');
        navigate('/dashboard/email-accounts', { 
          replace: false,
          state: { showImapForm: true, showManagementView: true }
        });
        return;
      }
    } catch (error: any) {
      console.error('Error preparing IMAP connection:', error);
      toast.error(error?.message || 'Failed to prepare IMAP connection. Please try again.');
      setIsConnecting(false);
      // Clear flags on error
      sessionStorage.removeItem('showImapForm');
      sessionStorage.removeItem('showManagementView');
    }
  };

  const handleBack = () => {
    if (asModal && onClose) {
      onClose();
      return;
    }
    if (finalCampaignId) {
      // Go back to campaign step 4
      navigate('/dashboard/campaign-creation', { replace: true });
    } else {
      // Go back to email accounts page
      navigate('/dashboard/email-accounts', { replace: true });
    }
  };

  const content = (
    <div className="imap-consent-card consent-form-card">
        {/* Header: Logo + Close */}
        <div className="consent-form-header">
          <div className="imap-logo-container imap-header-message-icon">
            <svg width="32" height="32" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className="imap-header-icon" aria-hidden>
              <path d="M7.08317 15.8337H6.6665C3.33317 15.8337 1.6665 15.0003 1.6665 10.8337V6.66699C1.6665 3.33366 3.33317 1.66699 6.6665 1.66699H13.3332C16.6665 1.66699 18.3332 3.33366 18.3332 6.66699V10.8337C18.3332 14.167 16.6665 15.8337 13.3332 15.8337H12.9165C12.6582 15.8337 12.4082 15.9587 12.2498 16.167L10.9998 17.8337C10.4498 18.567 9.54984 18.567 8.99984 17.8337L7.74984 16.167C7.6165 15.9837 7.30817 15.8337 7.08317 15.8337Z" stroke="currentColor" strokeWidth="1.3" strokeMiterlimit="10" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M13.3305 9.16667H13.338" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M9.99607 9.16667H10.0036" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M6.66209 9.16667H6.66957" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </div>
          <button type="button" className="consent-form-close" onClick={handleBack} aria-label="Close">
            <X size={24} color="#333" />
          </button>
        </div>

        {/* Main Title */}
        <h1 className="imap-consent-title">
          Connect with IMAP/SMTP
        </h1>

        {/* Subtitle */}
        <p className="imap-consent-subtitle">
          Configure your email to send and track campaign messages
        </p>

        {/* How it works section */}
        <div className="imap-consent-section how-it-works-box">
          <div className="consent-section-header">
            <div className="consent-check-icon">
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                <rect x="2" y="2" width="16" height="16" rx="4" stroke="#A198CE" strokeWidth="1.25"/>
                <path d="M5 10l3 3 7-7" stroke="#A198CE" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </div>
            <h3 className="consent-section-title consent-how-heading">How it works:</h3>
          </div>
          <p className="consent-section-text">
            We&apos;ll configure a professional email address with optimized settings and warm it up
            automatically. This ensures your emails land in inboxes, not spam folders.
          </p>
        </div>

        {/* What we'll access section */}
        <div className="imap-consent-section">
          <h3 className="consent-section-title consent-access-heading">What we&apos;ll access:</h3>
          <div className="consent-permissions-list consent-permissions-vertical">
            <div className="consent-permission-item">
              <div className="consent-check-icon">
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <rect x="2" y="2" width="16" height="16" rx="4" stroke="#A198CE" strokeWidth="1.25"/>
                  <path d="M5 10l3 3 7-7" stroke="#A198CE" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </div>
              <div className="consent-permission-content">
                <h4 className="consent-permission-title">Send emails on your behalf</h4>
                <p className="consent-permission-description">
                  We&apos;ll configure a professional email address with optimized settings and warm it up
                  automatically. This ensures your emails land in inboxes, not spam folders.
                </p>
              </div>
            </div>
            <div className="consent-permission-item">
              <div className="consent-check-icon">
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <rect x="2" y="2" width="16" height="16" rx="4" stroke="#A198CE" strokeWidth="1.25"/>
                  <path d="M5 10l3 3 7-7" stroke="#A198CE" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </div>
              <div className="consent-permission-content">
                <h4 className="consent-permission-title">Track Replies</h4>
                <p className="consent-permission-description">Detect when a lead replies so we can stop automated follow-ups for that contact.</p>
              </div>
            </div>
            <div className="consent-permission-item">
              <div className="consent-check-icon">
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <rect x="2" y="2" width="16" height="16" rx="4" stroke="#A198CE" strokeWidth="1.25"/>
                  <path d="M5 10l3 3 7-7" stroke="#A198CE" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </div>
              <div className="consent-permission-content">
                <h4 className="consent-permission-title">Security</h4>
                <p className="consent-permission-description">Your credentials are encrypted and are only used to maintain the connection between your mailbox and our sender.</p>
              </div>
            </div>
          </div>
        </div>

        {/* Continue Button */}
        <div className="imap-consent-button-wrap">
          <button 
            className="imap-consent-continue-button"
            onClick={handleContinue}
            disabled={isConnecting}
          >
            {isConnecting ? 'Connecting...' : 'Continue'}
          </button>
        </div>
      </div>
  );

  if (asModal) {
    return (
      <div className="connect-email-loader-overlay consent-form-overlay">
        {content}
      </div>
    );
  }

  return (
    <div className="imap-consent-container">
      {content}
    </div>
  );
}

