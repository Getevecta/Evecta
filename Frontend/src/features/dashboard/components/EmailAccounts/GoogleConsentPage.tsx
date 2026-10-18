import React, { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { X } from 'lucide-react';
import { apiService } from '../../../../shared/services/api';
import { toast } from 'sonner';
import './GoogleConsentPage.css';

interface GoogleConsentPageProps {
  campaignId?: string;
  redirectTo?: string;
  asModal?: boolean;
  onClose?: () => void;
}

export function GoogleConsentPage({ campaignId, redirectTo, asModal, onClose }: GoogleConsentPageProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const [isConnecting, setIsConnecting] = useState(false);

  // Get campaign ID and redirect info from location state or props
  const finalCampaignId = campaignId || location.state?.campaignId;
  const finalRedirectTo = redirectTo || location.state?.redirectTo;

  const handleContinue = async () => {
    try {
      setIsConnecting(true);
      
      // Store flags based on where we came from
      if (finalCampaignId) {
        // Coming from campaign step 4
        sessionStorage.setItem(`campaignEmailAccountChoice_${finalCampaignId}`, 'existing');
        sessionStorage.setItem(`campaignEmailAccountStep_${finalCampaignId}`, finalCampaignId);
        sessionStorage.setItem('editCampaignId', finalCampaignId);
        sessionStorage.setItem('openExistingEmailsTab', 'true');
        sessionStorage.setItem('cameFromCampaign', 'true');
      } else {
        // Coming from email accounts page
        sessionStorage.setItem('openExistingEmailsTab', 'true');
      }

      // Get Google OAuth URL
      const response = finalCampaignId 
        ? await apiService.connectGoogleMailbox(finalCampaignId)
        : await apiService.connectGoogleMailbox();
      
      if (response.data?.auth_url) {
        // Redirect to Google OAuth
        window.location.href = response.data.auth_url;
      } else {
        toast.error('Failed to get Google authentication URL');
        setIsConnecting(false);
      }
    } catch (error: any) {
      console.error('Error connecting Google mailbox:', error);
      toast.error(error?.message || 'Failed to connect Google account. Please try again.');
      setIsConnecting(false);
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
    <div className="google-consent-card consent-form-card">
        {/* Header: Logo + Close */}
        <div className="consent-form-header">
          <div className="google-logo-container">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
              <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
              <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
              <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
            </svg>
          </div>
          <button type="button" className="consent-form-close" onClick={handleBack} aria-label="Close">
            <X size={24} color="#333" />
          </button>
        </div>

        {/* Main Title */}
        <h1 className="google-consent-title">
          Sign in with Google
        </h1>

        {/* Subtitle */}
        <p className="google-consent-subtitle">
          Allow evecta to access your gmail
        </p>

        {/* How it works section */}
        <div className="google-consent-section how-it-works-box">
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
        <div className="google-consent-section">
          <h3 className="consent-section-title consent-access-heading">What we&apos;ll access:</h3>
          <div className="consent-permissions-list">
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
                <h4 className="consent-permission-title">Read email activity</h4>
                <p className="consent-permission-description">Track opens, clicks, and replies for campaign analytics</p>
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
                <h4 className="consent-permission-title">Access your profile and contacts</h4>
                <p className="consent-permission-description">Your name, email address, profile picture, and email contacts will be accessed to set up your account</p>
              </div>
            </div>
          </div>
        </div>

        {/* Continue Button */}
        <div className="google-consent-button-wrap">
          <button 
            className="google-consent-continue-button"
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
    <div className="google-consent-container">
      {content}
    </div>
  );
}

