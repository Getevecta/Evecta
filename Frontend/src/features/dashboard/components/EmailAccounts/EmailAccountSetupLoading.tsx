import React, { useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Slack } from 'lucide-react';
import './EmailAccountSetupLoading.css';

interface EmailAccountSetupLoadingProps {
  redirectTo?: string;
  delay?: number; // Delay in milliseconds before redirecting
}

export function EmailAccountSetupLoading({ redirectTo, delay = 6000 }: EmailAccountSetupLoadingProps) {
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    let targetPath = redirectTo || location.state?.redirectTo || '/dashboard';
    if (targetPath === 'preview' || location.state?.redirectTo === 'preview') {
      const campaignId = location.state?.campaignId || sessionStorage.getItem('emailSetupCampaignId');
      if (campaignId) {
        sessionStorage.setItem('emailSetupGoToStep5', 'true');
        sessionStorage.setItem('editCampaignId', campaignId);
        targetPath = `/dashboard/campaign-creation`;
        sessionStorage.removeItem('emailSetupRedirectToPreview');
        sessionStorage.removeItem('emailSetupCampaignId');
      } else {
        targetPath = '/dashboard';
      }
    } else if (targetPath === '/dashboard/email-accounts') {
      targetPath = '/dashboard/email-accounts?managed_pool_connected=true';
    }
    const timer = setTimeout(() => {
      navigate(targetPath, { replace: true });
    }, delay);
    return () => clearTimeout(timer);
  }, [navigate, redirectTo, delay, location.state]);

  return (
    <div className="email-account-setup-loading-container">
      <div className="email-account-setup-loading-card connect-email-loader-card" style={{ padding: '24px' }}>
        <div className="connect-email-loader-header" style={{ marginBottom: '8px' }}>
          <div className="connect-email-loader-icon">
            <Slack size={48} color="#9164FF" strokeWidth={1.5} />
          </div>
        </div>
        <h2 className="connect-email-loader-title">Setting up your system account</h2>
        <p className="connect-email-loader-subtitle">
          Almost ready! We&apos;re handling the technical details for you.
        </p>
        <div className="connect-email-loader-how-it-works">
          <div className="connect-email-loader-check-icon">
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
              <rect x="2" y="2" width="16" height="16" rx="4" stroke="#A198CE" strokeWidth="1.25"/>
              <path d="M5 10l3 3 7-7" stroke="#A198CE" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </div>
          <div className="connect-email-loader-how-content">
            <h3 className="connect-email-loader-how-title">How it works:</h3>
            <p className="connect-email-loader-how-text">
              We&apos;ll configure a professional email address with optimized settings and warm it up
              automatically. This ensures your emails land in inboxes, not spam folders.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

