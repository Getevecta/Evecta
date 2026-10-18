import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Settings, ChevronRight, X, Eye, EyeOff, AlertCircle, Check, Plus, Calendar, ArrowLeft, Users, Send, BarChart3, Slack } from 'lucide-react';
import { apiService, MailboxCreateRequest } from '../../../../shared/services/api';
import { toast } from 'sonner';
import '../EmailAccounts/EmailAccounts.css';
import '../EmailAccounts/IMAPConsentPage.css';
import './SelectEmailAccount.css';

interface SelectEmailAccountProps {
  campaignId: string;
  onBack: () => void;
  onNext: () => void;
  onEmailAccountSelected?: (accountType: 'system' | 'existing', detailedType?: 'system' | 'gmail' | 'imap') => void;
  selectedAccountType?: 'system' | 'gmail' | 'imap' | null;
}

export function SelectEmailAccount({ campaignId, onBack, onNext, onEmailAccountSelected, selectedAccountType }: SelectEmailAccountProps) {
  console.log('[DEBUG] SelectEmailAccount render - selectedAccountType:', selectedAccountType);
  const [isConnecting, setIsConnecting] = useState(false);
  const [showLoading, setShowLoading] = useState(false);
  // Consent pages are DISABLED in Step 4 - always false
  // Never show consent pages in Step 4 - users go directly to OAuth/IMAP
  const [showGoogleConsent, setShowGoogleConsent] = useState(false);
  const [showImapConsent, setShowImapConsent] = useState(false);
  const [mailboxes, setMailboxes] = useState<any[]>([]);
  const [isLoadingMailboxes, setIsLoadingMailboxes] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  // IMAP form state
  const [showImapModal, setShowImapModal] = useState(false);
  const [imapHost, setImapHost] = useState('');
  const [imapPort, setImapPort] = useState('');
  const [imapUsername, setImapUsername] = useState('');
  const [imapPassword, setImapPassword] = useState('');
  const [smtpHost, setSmtpHost] = useState('');
  const [smtpPort, setSmtpPort] = useState('');
  const [smtpUsername, setSmtpUsername] = useState('');
  const [smtpPassword, setSmtpPassword] = useState('');
  const [showImapPassword, setShowImapPassword] = useState(false);
  const [showSmtpPassword, setShowSmtpPassword] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [messageType, setMessageType] = useState<'error' | 'success'>('error');
  const [showErrorModal, setShowErrorModal] = useState(false);
  const [showAddEmailAccountView, setShowAddEmailAccountView] = useState(false);
  // Restore tab and selection when returning from step 5 (parent passes selectedAccountType)
  const [selectedEmailMethod, setSelectedEmailMethod] = useState<'managed' | 'existing'>(() =>
    selectedAccountType === 'system' ? 'managed' : 'existing'
  );
  const [isMethodSelected, setIsMethodSelected] = useState(() => selectedAccountType != null);
  const [showConnectEmailLoader, setShowConnectEmailLoader] = useState(false);

  // Keep tab + “selected” UI in sync when parent restores choice (e.g. back from step 5)
  useEffect(() => {
    if (selectedAccountType === 'system') {
      setSelectedEmailMethod('managed');
      setIsMethodSelected(true);
    } else if (selectedAccountType === 'gmail' || selectedAccountType === 'imap') {
      setSelectedEmailMethod('existing');
      setIsMethodSelected(true);
    }
  }, [selectedAccountType]);

  // ---------------------------------------------------------------------------
  // Existing accounts detection (returning users)
  // ---------------------------------------------------------------------------
  useEffect(() => {
    // Fetch connected mailboxes so we can show the "returning user" view
    const fetchMailboxes = async () => {
      try {
        setIsLoadingMailboxes(true);
        const response = await apiService.getAllMailboxes();
        if (response.data && Array.isArray(response.data)) {
          setMailboxes(response.data);
        } else {
          setMailboxes([]);
        }
      } catch (error) {
        console.error('[DEBUG] SelectEmailAccount: Failed to fetch mailboxes:', error);
        setMailboxes([]);
      } finally {
        setIsLoadingMailboxes(false);
      }
    };

    fetchMailboxes();
  }, []);

  // Ensure consent pages are NEVER shown in Step 4 - always skip to OAuth/IMAP directly
  // Force consent states to always be false in Step 4
  useEffect(() => {
    // Always keep consent states false in Step 4
    if (showGoogleConsent) {
      console.log('[DEBUG] Consent page detected in Step 4 - preventing render and redirecting to OAuth');
      setShowGoogleConsent(false);
      // Redirect to OAuth immediately
      handleGoogleConnect();
    }
    if (showImapConsent) {
      console.log('[DEBUG] IMAP consent page detected in Step 4 - preventing render and showing IMAP form');
      setShowImapConsent(false);
      setShowImapModal(true);
    }
  }, [showGoogleConsent, showImapConsent]);

  const handleCloseImapModal = () => {
    setShowImapModal(false);
    setShowErrorModal(false);
    setErrorMessage('');
    setMessageType('error');
    // Reset form when closing
    setImapHost('');
    setImapPort('');
    setImapUsername('');
    setImapPassword('');
    setSmtpHost('');
    setSmtpPort('');
    setSmtpUsername('');
    setSmtpPassword('');
  };

  const validateImapForm = (): { isValid: boolean; error: string } => {
    // Check IMAP fields
    if (!imapHost || imapHost.trim() === '') {
      return { isValid: false, error: 'IMAP Host is required. Please enter a valid IMAP server address.' };
    }
    
    if (!imapPort || imapPort.trim() === '') {
      return { isValid: false, error: 'IMAP Port is required. Please enter a valid port number (e.g., 993).' };
    }
    
    const imapPortNum = parseInt(imapPort);
    if (isNaN(imapPortNum) || imapPortNum < 1 || imapPortNum > 65535) {
      return { isValid: false, error: 'IMAP Port must be a valid number between 1 and 65535.' };
    }
    
    if (!imapUsername || imapUsername.trim() === '') {
      return { isValid: false, error: 'IMAP Username is required. Usually this is your email address.' };
    }
    
    if (!imapPassword || imapPassword.trim() === '') {
      return { isValid: false, error: 'IMAP Password is required. Please enter your email password or app-specific password.' };
    }
    
    // Check SMTP fields
    if (!smtpHost || smtpHost.trim() === '') {
      return { isValid: false, error: 'SMTP Host is required. Please enter a valid SMTP server address.' };
    }
    
    if (!smtpPort || smtpPort.trim() === '') {
      return { isValid: false, error: 'SMTP Port is required. Please enter a valid port number (e.g., 587 or 465).' };
    }
    
    const smtpPortNum = parseInt(smtpPort);
    if (isNaN(smtpPortNum) || smtpPortNum < 1 || smtpPortNum > 65535) {
      return { isValid: false, error: 'SMTP Port must be a valid number between 1 and 65535.' };
    }
    
    if (!smtpUsername || smtpUsername.trim() === '') {
      return { isValid: false, error: 'SMTP Username is required. Usually this is your email address.' };
    }
    
    if (!smtpPassword || smtpPassword.trim() === '') {
      return { isValid: false, error: 'SMTP Password is required. Please enter your email password or app-specific password.' };
    }
    
    // Basic email validation for username fields
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (imapUsername.includes('@') && !emailRegex.test(imapUsername)) {
      return { isValid: false, error: 'IMAP Username appears to be an email address but is not in a valid format.' };
    }
    
    if (smtpUsername.includes('@') && !emailRegex.test(smtpUsername)) {
      return { isValid: false, error: 'SMTP Username appears to be an email address but is not in a valid format.' };
    }
    
    return { isValid: true, error: '' };
  };

  const handleConnectAccount = async () => {
    const validation = validateImapForm();
    
    if (!validation.isValid) {
      setErrorMessage(validation.error);
      setMessageType('error');
      setShowErrorModal(true);
      return;
    }
    
    try {
      setIsConnecting(true);
      // Determine email address - use username if it contains @, otherwise construct it
      let emailAddress = imapUsername;
      if (!imapUsername.includes('@')) {
        const domain = imapHost.replace(/^imap\./i, '').replace(/^mail\./i, '');
        emailAddress = `${imapUsername}@${domain}`;
      }

      // Construct SMTP host if not provided (try to derive from IMAP host)
      let smtpHostValue = smtpHost;
      if (!smtpHostValue) {
        smtpHostValue = imapHost.replace(/^imap\./i, 'smtp.').replace(/^mail\./i, 'smtp.');
      }

      const payload: MailboxCreateRequest = {
        email: emailAddress,
        username: smtpUsername.trim(),
        password: smtpPassword,
        smtp_host: smtpHostValue,
        smtp_port: smtpPort ? parseInt(smtpPort, 10) : undefined,
        receive_email: emailAddress,
        imap_username: imapUsername.trim(),
        imap_password: imapPassword,
        imap_host: imapHost,
        imap_port: imapPort ? parseInt(imapPort, 10) : undefined,
        provider: 'ANY_PROVIDER',
      };

      const response = await apiService.createMailbox(payload);
      
      if (response.data) {
        // Success
        toast.success('IMAP account connected successfully!');
        
        // Set email sending mode to USER for this specific campaign in the database
        if (campaignId) {
          await apiService.updateCampaign(campaignId, { email_sending_mode: 'USER' });
        }
        // Also set user preference for USER mode
        await apiService.updateEmailSendingMode('USER');

        if (onEmailAccountSelected) {
          onEmailAccountSelected('existing', 'imap');
        }
        sessionStorage.setItem(`campaignEmailAccountChoice_${campaignId}`, 'existing');
        sessionStorage.setItem(`campaignEmailType_${campaignId}`, 'imap');
        
        // No longer auto-nexting if we want the user to see the selection confirmed first
        // But for consistency with Gmail OAuth, we'll keep it for now.
        // Wait, the user specifically asked to show what's being used.
        handleCloseImapModal();
        // Proceed to step 5
        onNext();
      } else {
        // API returned an error
        const errorMsg = response.error || response.message || "We're Unable to Reach Your Inbox. Please review your email credentials and try connecting again.";
        setErrorMessage(errorMsg);
        setMessageType('error');
        setShowErrorModal(true);
      }
    } catch (error: any) {
      const errorMsg = error?.message || error?.error || "We're Unable to Reach Your Inbox. Please review your email credentials and try connecting again.";
      setErrorMessage(errorMsg);
      setMessageType('error');
      setShowErrorModal(true);
    } finally {
      setIsConnecting(false);
    }
  };

  const handleSystemEmail = async () => {
    if (isConnecting) return;
    setShowConnectEmailLoader(true);
    setIsConnecting(true);
    const minLoaderTime = 6000;
    const startTime = Date.now();
    try {
      if (campaignId) {
        await apiService.updateCampaign(campaignId, { email_sending_mode: 'SYSTEM' });
      }
      await apiService.updateEmailSendingMode('SYSTEM');
      const elapsed = Date.now() - startTime;
      const remaining = Math.max(0, minLoaderTime - elapsed);
      if (remaining > 0) {
        await new Promise((r) => setTimeout(r, remaining));
      }
      if (onEmailAccountSelected) {
        onEmailAccountSelected('system', 'system');
      }
      sessionStorage.setItem(`campaignEmailAccountChoice_${campaignId}`, 'managed');
      sessionStorage.setItem(`campaignEmailType_${campaignId}`, 'system');
      sessionStorage.setItem(`campaignEmailAccountStep_${campaignId}`, campaignId);
      setShowConnectEmailLoader(false);
      setIsConnecting(false);
      setIsMethodSelected(true);
      if (onNext) {
        onNext();
      }
    } catch (error: any) {
      console.error('Error connecting system email:', error);
      toast.error(error?.message || 'Failed to connect pre-warmed accounts. Please try again.');
      setShowConnectEmailLoader(false);
      setIsConnecting(false);
    }
  };

  const handleUseExistingEmailMethod = async () => {
    if (!mailboxes || mailboxes.length === 0) {
      // Safety guard – fall back to regular flow
      toast.error('No existing email accounts found. Please connect an email account first.');
      return;
    }

    try {
      setIsConnecting(true);

      // Set email sending mode to USER for this specific campaign in the database
      if (campaignId) {
        await apiService.updateCampaign(campaignId, { email_sending_mode: 'USER' });
      }
      // Also set user preference for USER mode
      await apiService.updateEmailSendingMode('USER');

      // Try to infer a detailed type from the first active mailbox
      const primaryMailbox = mailboxes.find((mb) => mb.is_active) || mailboxes[0];
      let detailedType: 'gmail' | 'imap' | 'system' | undefined;
      if (primaryMailbox?.provider === 'GOOGLE') {
        detailedType = 'gmail';
      } else if (primaryMailbox?.provider === 'ANY_PROVIDER') {
        detailedType = 'imap';
      }
      const resolvedType = detailedType === 'gmail' || detailedType === 'imap' ? detailedType : 'imap';

      if (onEmailAccountSelected) {
        onEmailAccountSelected('existing', resolvedType);
      }

      // Store flag to indicate user explicitly selected email account in Step 4
      sessionStorage.setItem(`campaignEmailAccountChoice_${campaignId}`, 'existing');
      sessionStorage.setItem(`campaignEmailType_${campaignId}`, resolvedType);
      sessionStorage.setItem(`campaignEmailAccountStep_${campaignId}`, campaignId);

      toast.success('Using your existing email accounts for this campaign');
      setIsConnecting(false);
      setIsMethodSelected(true);
      onNext();
    } catch (error: any) {
      console.error('[DEBUG] SelectEmailAccount: Failed to use existing email accounts:', error);
      toast.error(
        error?.message ||
          'Failed to apply existing email accounts. Please try again or connect a new account.',
      );
      setIsConnecting(false);
    }
  };

  const handleProceedToNext = () => {
    onNext(); // Move to step 5
  };

  const handleGoogleConnect = async () => {
    if (isConnecting) return;
    // Skip consent page in Step 4 (campaign creation flow) - go directly to OAuth
    // Ensure consent state is false
    setShowGoogleConsent(false);
    
    // Close the "Add Email Account" view if it's open
    if (showAddEmailAccountView) {
      setShowAddEmailAccountView(false);
    }
    
    console.log('[DEBUG] handleGoogleConnect: Skipping consent, going directly to OAuth');
    
    try {
      setIsConnecting(true);
      // Store flags and chosen type so when user comes back to step 4 we can restore selection
      sessionStorage.setItem(`campaignEmailAccountChoice_${campaignId}`, 'existing');
      sessionStorage.setItem(`campaignEmailType_${campaignId}`, 'gmail');
      sessionStorage.setItem('editCampaignId', campaignId);
      sessionStorage.setItem('openExistingEmailsTab', 'true');
      sessionStorage.setItem('cameFromCampaign', 'true');
      sessionStorage.setItem(`campaignEmailAccountStep_${campaignId}`, campaignId);
      
      // Notify parent immediately so selection shows when user returns from OAuth
      if (onEmailAccountSelected) {
        onEmailAccountSelected('existing', 'gmail');
      }
      
      // Get Google OAuth URL
      const response = await apiService.connectGoogleMailbox(campaignId);
      if (response.data?.auth_url) {
        // Redirect to Google OAuth immediately - no consent page
        console.log('[DEBUG] Redirecting to Google OAuth:', response.data.auth_url);
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

  const handleGoogleConsentContinue = async () => {
    try {
      setIsConnecting(true);
      // Store flags
      sessionStorage.setItem(`campaignEmailAccountChoice_${campaignId}`, 'existing');
      sessionStorage.setItem('editCampaignId', campaignId);
      sessionStorage.setItem('openExistingEmailsTab', 'true');
      sessionStorage.setItem('cameFromCampaign', 'true');
      sessionStorage.setItem(`campaignEmailAccountStep_${campaignId}`, campaignId);
      
      // Get Google OAuth URL
      const response = await apiService.connectGoogleMailbox(campaignId);
      if (response.data?.auth_url) {
        // Redirect to Google OAuth
        window.location.href = response.data.auth_url;
      } else {
        toast.error('Failed to get Google authentication URL');
        setIsConnecting(false);
        setShowGoogleConsent(false);
      }
    } catch (error: any) {
      console.error('Error connecting Google mailbox:', error);
      toast.error(error?.message || 'Failed to connect Google account. Please try again.');
      setIsConnecting(false);
      setShowGoogleConsent(false);
    }
  };

  const handleImapConnect = () => {
    // In Step 4 (campaign creation), skip consent and show IMAP form modal directly
    // Don't navigate to a new page - show the form inline
    setShowImapModal(true);
    // Close the "Add Email Account" view if it's open
    if (showAddEmailAccountView) {
      setShowAddEmailAccountView(false);
    }
  };

  const handleBackFromAddEmail = () => {
    setShowAddEmailAccountView(false);
  };

  const handleImapConsentContinue = () => {
    // After consent, show the IMAP form modal
    setShowImapConsent(false);
    setShowImapModal(true);
  };

  // Check if we should show IMAP form after returning from full-page consent
  useEffect(() => {
    const showImapForm = location.state?.showImapForm || sessionStorage.getItem('showImapForm') === 'true';
    if (showImapForm) {
      // Use setTimeout to ensure the component has fully rendered
      setTimeout(() => {
        setShowImapModal(true);
        // Clear the state to prevent reopening on re-render
        sessionStorage.removeItem('showImapForm');
        navigate(location.pathname, { replace: true, state: {} });
      }, 100);
    }
  }, [location.state, navigate, location.pathname]);

  // Inline Google consent component - DISABLED in Step 4 (campaign creation flow)
  // Consent page is NEVER shown in Step 4 - users go directly to OAuth
  // This condition is always false to prevent consent page from ever rendering
  if (false) { // NEVER render consent page in Step 4 - always skip to OAuth
    return (
      <div className="email-accounts-container">
        <div className="email-accounts-content google-consent-container">
          <div className="google-consent-card">
            {/* Google Logo */}
            <div className="google-consent-logo">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
                <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
                <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
                <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
              </svg>
            </div>

            {/* Main Title */}
            <h1 className="google-consent-title heading-xl">
              Sign in with Google
            </h1>

            {/* Subtitle */}
            <p className="google-consent-subtitle">
              Allow evecta to access your gmail
            </p>

            {/* How it works section */}
            <div className="google-consent-how-it-works">
              <div className="google-consent-how-it-works-header">
                <div className="google-consent-check-icon">
                  <svg width="16" height="16" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <circle cx="10" cy="10" r="9" stroke="#8B5CF6" strokeWidth="2" fill="none"/>
                    <path d="M6 10L9 13L14 7" stroke="#8B5CF6" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
                  </svg>
                </div>
                <h3 className="google-consent-how-it-works-title heading-m">
                  How it works:
                </h3>
              </div>
              <p className="google-consent-how-it-works-text">
                We'll configure a professional email address with optimized settings and 
                <br />
                warm it up automatically. This ensures your emails land in inboxes, not spam folders.
              </p>
            </div>

            {/* What we'll access section */}
            <div className="google-consent-access-section">
              <h3 className="google-consent-access-title heading-m">
                What we'll access:
              </h3>
              <div className="google-consent-access-grid">
                <div className="google-consent-access-item">
                  <div className="google-consent-access-item-icon">
                    <svg width="16" height="16" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <circle cx="10" cy="10" r="9" stroke="#8B5CF6" strokeWidth="2" fill="none"/>
                      <path d="M6 10L9 13L14 7" stroke="#8B5CF6" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
                    </svg>
                  </div>
                  <div className="google-consent-access-item-content">
                    <h4 className="google-consent-access-item-title heading-m">
                      Send emails on your behalf
                    </h4>
                    <p className="google-consent-access-item-text">
                      Send campaign emails and follow-ups from your Gmail account
                    </p>
                  </div>
                </div>
                <div className="google-consent-access-item">
                  <div className="google-consent-access-item-icon">
                    <svg width="16" height="16" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <circle cx="10" cy="10" r="9" stroke="#8B5CF6" strokeWidth="2" fill="none"/>
                      <path d="M6 10L9 13L14 7" stroke="#8B5CF6" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
                    </svg>
                  </div>
                  <div className="google-consent-access-item-content">
                    <h4 className="google-consent-access-item-title heading-m">
                      Read email activity
                    </h4>
                    <p className="google-consent-access-item-text">
                      Track opens, clicks, and replies for campaign analytics
                    </p>
                  </div>
                </div>
                <div className="google-consent-access-item">
                  <div className="google-consent-access-item-icon">
                    <svg width="16" height="16" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <circle cx="10" cy="10" r="9" stroke="#8B5CF6" strokeWidth="2" fill="none"/>
                      <path d="M6 10L9 13L14 7" stroke="#8B5CF6" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
                    </svg>
                  </div>
                  <div className="google-consent-access-item-content">
                    <h4 className="google-consent-access-item-title heading-m">
                      Access your profile and contacts
                    </h4>
                    <p className="google-consent-access-item-text">
                      Your name, email address, profile picture, and email contacts will be accessed to set up your account
                    </p>
                  </div>
                </div>
              </div>
            </div>

            {/* Continue Button */}
            <button 
              className="google-consent-button"
              onClick={handleGoogleConsentContinue}
              disabled={isConnecting}
            >
              {isConnecting ? 'Connecting...' : 'Continue'}
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Inline IMAP consent component - matches IMAPConsentPage design
  if (showImapConsent) {
    return (
      <div className="email-accounts-container">
        <div className="imap-consent-container">
          <div className="imap-consent-card consent-form-card">
            <div className="consent-form-header">
              <div className="imap-logo-container">
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path d="M12 2L2 7L12 12L22 7L12 2Z" stroke="#9164FF" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
                  <path d="M2 17L12 22L22 17" stroke="#9164FF" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
                  <path d="M2 12L12 17L22 12" stroke="#9164FF" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
                </svg>
              </div>
              <button type="button" className="consent-form-close" onClick={() => setShowImapConsent(false)} aria-label="Close">
                <X size={24} color="#333" />
              </button>
            </div>
            <h1 className="imap-consent-title">Connect with IMAP/SMTP</h1>
            <p className="imap-consent-subtitle">Configure your email to send and track campaign messages</p>
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
            <button className="imap-consent-continue-button" onClick={handleImapConsentContinue}>
              Continue
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Inline loading component
  if (showLoading) {
    return (
      <div className="email-accounts-container">
        <div className="email-accounts-content loading-container">
          <div className="loading-card" style={{ padding: '24px' }}>
            {/* Loading Spinner */}
            <div className="loading-spinner-container">
              {[...Array(12)].map((_, i) => (
                <div
                  key={i}
                  className="loading-spinner-dot"
                  data-index={i}
                />
              ))}
            </div>

            <h1 className="loading-title">Setting up your system account…</h1>

            <p className="loading-subtitle">
              Almost ready! We&apos;re handling the technical details for you.
            </p>

            <div className="loading-info-box">
              <div className="loading-info-icon">
                <svg width="16" height="16" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <circle cx="10" cy="10" r="9" stroke="#8B5CF6" strokeWidth="2" fill="none"/>
                  <path d="M6 10L9 13L14 7" stroke="#8B5CF6" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
                </svg>
              </div>
              <div className="loading-info-content">
                <h3 className="loading-info-title">How it works:</h3>
                <p className="loading-info-text">
                  We&apos;ll configure a professional email address with optimized settings and warm it up
                  automatically. This ensures your emails land in inboxes, not spam folders.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const hasExistingMailboxes = mailboxes.length > 0;

  // -------------------------------------------------------------------------
  // Add Email Account view (inline within step 4)
  // -------------------------------------------------------------------------
  if (showAddEmailAccountView && !showGoogleConsent && !showImapConsent && !showLoading && !isLoadingMailboxes) {
    return (
      <div className="select-email-existing-container">
        <div className="select-email-existing-card">
          <div className="select-email-existing-header-with-back">
            <button
              type="button"
              onClick={handleBackFromAddEmail}
              className="select-email-back-button-inline"
            >
              <ArrowLeft 
                size={16}
              />
            </button>
            <div className="select-email-existing-header-text">
              <h1 className="select-email-existing-main-title">Add Email Account</h1>
              <p className="select-email-existing-main-subtitle">
                Choose how you want to connect your email account
              </p>
            </div>
          </div>

          <div className="select-email-existing-accounts-section">
            <div className="email-account-card-header-wrapper email-account-card-header-wrapper-horizontal">
              <div className="email-account-card-icon existing-icon">
                <Settings size={16} />
              </div>
              <div className="email-account-card-header email-account-card-header-column">
                <h2 className="email-account-card-title email-accounts-card-title-conditional heading-l">
                  Connect Existing Accounts
                </h2>
                <p className="email-account-card-description email-accounts-card-description-conditional">
                  Integrate your own email accounts via Gmail or custom IMAP/SMTP settings
                </p>
              </div>
            </div>

            <div className="connection-options email-accounts-connection-options-conditional">
              <button 
                type="button"
                className="connection-option connection-option-secondary email-accounts-connection-option-conditional" 
                onClick={handleGoogleConnect}
                disabled={isConnecting}
              >
                <div className="connection-option-content">
                  <div className="connection-option-icon google-icon">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
                      <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
                      <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
                      <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
                    </svg>
                  </div>
                  <div className="connection-option-text connection-option-text-single-line">
                    <span className="connection-option-label">Let&apos;s Connect Your Email</span>
                  </div>
                </div>
                <ChevronRight className="connection-option-arrow" />
              </button>
              <button 
                type="button"
                className="connection-option connection-option-secondary email-accounts-connection-option-conditional" 
                onClick={handleImapConnect}
                disabled={isConnecting}
              >
                <div className="connection-option-content">
                  <div className="connection-option-icon connection-option-icon-imap">
                    <img src="/message.svg" alt="IMAP/SMTP" />
                  </div>
                  <div className="connection-option-text connection-option-text-single-line">
                    <span className="connection-option-label">Any Provider (IMAP/SMTP)</span>
                  </div>
                </div>
                <ChevronRight className="connection-option-arrow" />
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // -------------------------------------------------------------------------
  // Returning-user view:
  // If the workspace already has connected mailboxes, show a simplified
  // "Choose Email Sending Method" screen that highlights existing accounts.
  //
  // IMPORTANT: When IMAP modal is open (showImapModal === true), skip this
  // early return so the IMAP form modal can render instead.
  // -------------------------------------------------------------------------
  if (!showGoogleConsent && !showImapConsent && !showLoading && !isLoadingMailboxes && hasExistingMailboxes && !showImapModal) {
    return (
      <div className="select-email-existing-container">
        <div className="select-email-existing-card">
          <div className="select-email-existing-toggle-row">
            <button 
              type="button" 
              className={`select-email-existing-toggle ${selectedEmailMethod === 'managed' ? 'select-email-existing-toggle-active' : ''}`}
              onClick={() => setSelectedEmailMethod('managed')}
            >
              System Emails
            </button>
            <button
              type="button"
              className={`select-email-existing-toggle ${selectedEmailMethod === 'existing' ? 'select-email-existing-toggle-active' : ''}`}
              onClick={() => setSelectedEmailMethod('existing')}
            >
              Custom Emails
            </button>
          </div>

          {/* System Emails Content - Inside main card */}
          {selectedEmailMethod === 'managed' && (
            <div className="select-email-managed-pool-content">
              <div className="select-email-managed-pool-header">
                <h2 className="select-email-managed-pool-title heading-l">System Emails</h2>
              </div>
              <p className="select-email-managed-pool-subtitle">
                Use our pre-warmed, high-deliverability email infrastructure to send your campaigns instantly.
              </p>

              {/* Metrics Cards */}
              <div className="select-email-managed-pool-metrics">
                <div className="select-email-managed-pool-metric-card">
                  <div className="select-email-managed-pool-metric-header">
                    <div className="select-email-managed-pool-metric-icon">
                      <Send size={14} color="#8B5CF6" />
                    </div>
                    <span className="select-email-managed-pool-metric-label">Monthly Quota</span>
                  </div>
                  <span className="select-email-managed-pool-metric-value">30</span>
                </div>
                <div className="select-email-managed-pool-metric-card">
                  <div className="select-email-managed-pool-metric-header">
                    <div className="select-email-managed-pool-metric-icon">
                      <BarChart3 size={14} color="#8B5CF6" />
                    </div>
                    <span className="select-email-managed-pool-metric-label">Delivery Rate</span>
                  </div>
                  <span className="select-email-managed-pool-metric-value">98.7%</span>
                </div>
              </div>

              {/* Managed Pool Benefits - tick design like Key Improvements (step 3) */}
              <div className="select-email-managed-pool-benefits">
                <h3 className="select-email-managed-pool-benefits-title heading-m">Managed Pool Benefits</h3>
                <ul className="select-email-managed-pool-benefits-list">
                  <li className="select-email-managed-pool-benefits-item">
                    <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className="select-email-managed-pool-benefits-tick">
                      <rect x="2" y="2" width="16" height="16" rx="3" fill="none" stroke="currentColor" strokeWidth="1.5"/>
                      <path d="M5 10 L8 13 L15 6" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                    <span>Pre-warmed email accounts for maximum deliverability</span>
                  </li>
                  <li className="select-email-managed-pool-benefits-item">
                    <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className="select-email-managed-pool-benefits-tick">
                      <rect x="2" y="2" width="16" height="16" rx="3" fill="none" stroke="currentColor" strokeWidth="1.5"/>
                      <path d="M5 10 L8 13 L15 6" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                    <span>No setup required - start sending immediately</span>
                  </li>
                  <li className="select-email-managed-pool-benefits-item">
                    <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className="select-email-managed-pool-benefits-tick">
                      <rect x="2" y="2" width="16" height="16" rx="3" fill="none" stroke="currentColor" strokeWidth="1.5"/>
                      <path d="M5 10 L8 13 L15 6" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                    <span>Rotating IP addresses and domains for better reputation</span>
                  </li>
                  <li className="select-email-managed-pool-benefits-item">
                    <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className="select-email-managed-pool-benefits-tick">
                      <rect x="2" y="2" width="16" height="16" rx="3" fill="none" stroke="currentColor" strokeWidth="1.5"/>
                      <path d="M5 10 L8 13 L15 6" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                    <span>98% deliverability with professional monitoring</span>
                  </li>
                  <li className="select-email-managed-pool-benefits-item">
                    <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className="select-email-managed-pool-benefits-tick">
                      <rect x="2" y="2" width="16" height="16" rx="3" fill="none" stroke="currentColor" strokeWidth="1.5"/>
                      <path d="M5 10 L8 13 L15 6" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                    <span>No risk to your personal email reputation</span>
                  </li>
                </ul>
              </div>

              {/* Daily Email Limit */}
              <div className="select-email-managed-pool-daily-limit">
                <div className="select-email-managed-pool-daily-limit-content">
                  <span className="select-email-managed-pool-daily-limit-label">Daily email limit</span>
                  <span className="select-email-managed-pool-daily-limit-value">Gmail: 50 per day • IMAP/SMTP: 50 per day</span>
                </div>
              </div>

              {/* Campaign Duration */}
              <div className="select-email-managed-pool-duration">
                <div className="select-email-managed-pool-duration-content">
                  <span className="select-email-managed-pool-duration-text">
                    <strong>Campaign Duration:</strong> This campaign will take approximately <strong>3 days</strong> to complete.
                  </span>
                </div>
              </div>

              {/* Action Button - show "Selected" only when user chose System Emails */}
              <div className="select-email-managed-pool-actions">
                {selectedAccountType !== 'system' ? (
                  <button
                    type="button"
                    className="select-email-managed-pool-select-button select-email-primary-btn evecta-primary-btn"
                    disabled={isConnecting}
                    onClick={handleSystemEmail}
                  >
                    Select this method
                  </button>
                ) : (
                  <button
                    type="button"
                    className="select-email-managed-pool-select-button select-email-primary-btn evecta-primary-btn"
                    onClick={handleProceedToNext}
                  >
                    Selected
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Use Existing Email Section - Inside main card */}
          {selectedEmailMethod === 'existing' && (
            <>
          <div className="select-email-existing-accounts-section">
          <div className="select-email-existing-card-header">
            <div className="select-email-existing-card-header-left">
              <div className="select-email-existing-card-title-row">
                <h2 className="select-email-existing-card-title heading-l">Your Email Accounts</h2>
              </div>
              <p className="select-email-existing-card-subtitle">
                Choose from your connected email accounts to send this campaign
              </p>
            </div>
            <span className="select-email-existing-card-count">
              {mailboxes.length} connected {mailboxes.length === 1 ? 'account' : 'accounts'}
            </span>
          </div>

          <div className="select-email-existing-mailbox-list">
            {mailboxes.map((mailbox) => {
              return (
                <div key={mailbox.id} className="select-email-existing-mailbox-row">
                  <div className="select-email-existing-mailbox-main">
                    <div className="select-email-existing-mailbox-text">
                      <span className="select-email-existing-mailbox-email">{mailbox.email}</span>
                    </div>
                  </div>
                  <div className="select-email-existing-mailbox-status">
                    {mailbox.is_active ? (
                      <span className="select-email-existing-status-badge">Active</span>
                    ) : (
                      <span className="select-email-existing-status-badge inactive">Inactive</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          <button
            type="button"
            className="select-email-existing-connect-button"
            onClick={handleImapConnect}
          >
            Connect new email account
          </button>
          </div>

          <div className="select-email-existing-limit-card">
            <div className="select-email-existing-limit-content">
              <span className="select-email-existing-limit-label">Daily email limit</span>
              <span className="select-email-existing-limit-value">
                {(() => {
                  const fallback = 50;
                  const gmailLimit = mailboxes
                    .filter((mb) => mb.provider === 'GOOGLE')
                    .reduce((sum, mb) => sum + (typeof mb.daily_limit === 'number' ? mb.daily_limit : fallback), 0);
                  const smtpLimit = mailboxes
                    .filter((mb) => mb.provider !== 'GOOGLE')
                    .reduce((sum, mb) => sum + (typeof mb.daily_limit === 'number' ? mb.daily_limit : fallback), 0);
                  return `Gmail: ${gmailLimit || fallback} per day • IMAP/SMTP: ${smtpLimit || fallback} per day`;
                })()}
              </span>
            </div>
          </div>

          <div className="select-email-existing-duration-card">
            <div className="select-email-existing-duration-content">
              <span className="select-email-existing-duration-text">
                <strong>Campaign Duration:</strong> This campaign will take approximately{' '}
                <strong>
                  3 days
                </strong>{' '}
                to complete.
              </span>
            </div>
          </div>

          <div className="select-email-existing-actions">
            {(selectedAccountType !== 'gmail' && selectedAccountType !== 'imap') ? (
              <button
                type="button"
                className="select-email-existing-primary-svg select-email-primary-btn evecta-primary-btn"
                disabled={isConnecting}
                onClick={handleUseExistingEmailMethod}
              >
                Select this method
              </button>
            ) : (
              <button
                type="button"
                className="select-email-existing-primary-svg select-email-primary-btn evecta-primary-btn"
                onClick={handleProceedToNext}
              >
                Selected
              </button>
            )}
          </div>
            </>
          )}
        </div>
      </div>
    );
  }

  // -------------------------------------------------------------------------
  // First-time user view (no existing mailboxes yet)
  // -------------------------------------------------------------------------
  return (
    <div className="email-accounts-container">
      <div className="email-accounts-content select-email-content">
        <div className="email-accounts-title-container select-email-title-container">
          <h1 className="email-accounts-title select-email-title email-setup-option-page-title">Choose Your Email Setup Option</h1>
        </div>
        <div className="email-accounts-cards select-email-cards">
          {/* System Email Accounts Card - Same design as Email Accounts page */}
          <div className="email-account-card pre-warmed-card select-email-card">
            <span className="popular-badge">Popular</span>
            {selectedAccountType === 'system' && (
              <div className="currently-using-badge currently-using-badge-left">
                <div className="currently-using-badge-dot" />
                Currently Using
              </div>
            )}
            <div className="email-account-card-header select-email-card-header">
              <h2 className="email-account-card-title select-email-card-title heading-xl">System Email Accounts</h2>
            </div>
            <p className="email-account-card-description select-email-card-description">
              Get instant access to professionally warmed-up
              <br />
              email accounts ready for high deliverability
            </p>
            <ul className="email-account-features select-email-features">
              <li className="feature-item select-email-feature-item">
                <div className="feature-icon select-email-feature-icon">
                  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <rect x="2" y="2" width="16" height="16" rx="4" stroke="currentColor" strokeWidth="1.25"/>
                    <path d="M5 10l3 3 7-7" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </div>
                <div className="feature-text select-email-feature-text">
                  <span className="feature-title select-email-feature-title">Zero-Configuration Setup</span>
                  <span className="feature-subtitle select-email-feature-subtitle">Start sending emails immediately.</span>
                </div>
              </li>
              <li className="feature-item select-email-feature-item">
                <div className="feature-icon select-email-feature-icon">
                  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <rect x="2" y="2" width="16" height="16" rx="4" stroke="currentColor" strokeWidth="1.25"/>
                    <path d="M5 10l3 3 7-7" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </div>
                <div className="feature-text select-email-feature-text">
                  <span className="feature-title select-email-feature-title">100% Automated Management</span>
                  <span className="feature-subtitle select-email-feature-subtitle">Ensure 95%+ inbox placement.</span>
                </div>
              </li>
              <li className="feature-item select-email-feature-item">
                <div className="feature-icon select-email-feature-icon">
                  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <rect x="2" y="2" width="16" height="16" rx="4" stroke="currentColor" strokeWidth="1.25"/>
                    <path d="M5 10l3 3 7-7" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </div>
                <div className="feature-text select-email-feature-text">
                  <span className="feature-title select-email-feature-title">High-Volume Outreach</span>
                  <span className="feature-subtitle select-email-feature-subtitle">Maintain a strong sender reputation.</span>
                </div>
              </li>
              <li className="feature-item select-email-feature-item">
                <div className="feature-icon select-email-feature-icon">
                  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <rect x="2" y="2" width="16" height="16" rx="4" stroke="currentColor" strokeWidth="1.25"/>
                    <path d="M5 10l3 3 7-7" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </div>
                <div className="feature-text select-email-feature-text">
                  <span className="feature-title select-email-feature-title">Smart Tracking Dashboard</span>
                  <span className="feature-subtitle select-email-feature-subtitle">We handle all the technical details for you.</span>
                </div>
              </li>
            </ul>
            <button className="connect-button pre-warmed-button select-email-connect-button" onClick={handleSystemEmail} type="button">
              Connect Email (Early Access)
            </button>
          </div>

          {/* Connect Accounts Card - Same design as Email Accounts page */}
          <div className="email-account-card existing-card select-email-card">
            <div className="email-account-card-header-wrapper">
              <div className="email-account-card-header">
                <h2 className="email-account-card-title select-email-connect-accounts-title heading-xl">Connect Accounts</h2>
              </div>
            </div>
            <p className="email-account-card-description email-accounts-connect-card-blurb select-email-connect-accounts-description email-accounts-card-description-margin">
              Integrate your own email accounts via Gmail or custom IMAP/SMTP settings
            </p>
            <div className="email-accounts-feature-flex-container">
              <div className="feature-icon">
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <rect x="2" y="2" width="16" height="16" rx="4" stroke="currentColor" strokeWidth="1.25"/>
                  <path d="M5 10l3 3 7-7" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </div>
              <div className="email-accounts-feature-content">
                <h3 className="feature-title email-accounts-feature-title-conditional">Connect Your Own Email:</h3>
                <p className="feature-subtitle email-accounts-feature-subtitle-conditional">
                  Easily link your existing business or personal email (like Gmail or Outlook) using your account details.
                </p>
              </div>
            </div>
            <div className="connection-options select-email-connection-options">
              <button type="button" className="connection-option connection-option-secondary select-email-connection-option" onClick={handleGoogleConnect}>
                <div className="connection-option-content select-email-connection-option-content">
                  <div className="connection-option-icon google-icon select-email-connection-option-icon">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
                      <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
                      <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
                      <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
                    </svg>
                  </div>
                  <div className="connection-option-text select-email-connection-option-text">
                    <span className="connection-option-label">Google</span>
                    <span className="connection-option-sublabel">Gmail</span>
                  </div>
                </div>
                <ChevronRight className="connection-option-arrow select-email-connection-option-arrow" />
              </button>
              <button type="button" className="connection-option connection-option-secondary select-email-connection-option" onClick={handleImapConnect}>
                <div className="connection-option-content select-email-connection-option-content">
                  <div className="connection-option-icon connection-option-icon-imap select-email-connection-option-icon">
                    <img src="/message.svg" alt="IMAP/SMTP" />
                  </div>
                  <div className="connection-option-text select-email-connection-option-text">
                    <span className="connection-option-label">Any Provider</span>
                    <span className="connection-option-sublabel">IMAP/SMTP</span>
                  </div>
                </div>
                <ChevronRight className="connection-option-arrow select-email-connection-option-arrow" />
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Connect Email Loader Modal */}
      {showConnectEmailLoader && (
        <div className="connect-email-loader-overlay">
          <div className="connect-email-loader-modal" style={{ padding: '24px' }}>
            <div className="connect-email-loader-header">
              <div className="connect-email-loader-icon">
                <Slack size={48} color="#9164FF" strokeWidth={1.5} />
              </div>
              <button type="button" className="connect-email-loader-close" onClick={() => setShowConnectEmailLoader(false)} aria-label="Close">
                <X size={24} color="#333333" />
              </button>
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
      )}

      {/* IMAP Connection Modal */}
      {showImapModal && (
        <div className="imap-modal-overlay">
          <div className="imap-modal">
            {/* Header */}
            <div className="imap-modal-header">
              <div className="imap-modal-close-row">
                <button
                  onClick={handleCloseImapModal}
                  className="imap-modal-close-button"
                >
                  <X size={14} />
                </button>
              </div>
              <div className="imap-modal-header-content">
                <div className="imap-modal-header-left">
                  <div className="imap-modal-title-block">
                    <h2 className="imap-modal-title heading-l">
                      Connect IMAP
                    </h2>
                    <p className="imap-modal-subtitle">
                      Choose your connection method and configure your email account.
                    </p>
                  </div>
                </div>
              </div>
            </div>

            {/* Content */}
            <div className="imap-modal-content">
              {/* IMAP Settings */}
              <div className="imap-modal-section">
                <h3 className="imap-modal-section-title heading-m">
                  IMAP Settings (Incoming Mail)
                </h3>
                <div className="imap-modal-form-grid">
                  <div>
                    <label className="imap-modal-label">
                      IMAP Host
                    </label>
                    <input
                      type="text"
                      value={imapHost}
                      onChange={(e) => setImapHost(e.target.value)}
                      placeholder="imap.example.com"
                      className="imap-modal-input"
                    />
                  </div>
                  <div>
                    <label className="imap-modal-label">
                      Port
                    </label>
                    <input
                      type="text"
                      value={imapPort}
                      onChange={(e) => setImapPort(e.target.value)}
                      placeholder="993"
                      className="imap-modal-input"
                    />
                  </div>
                </div>
                <div className="imap-modal-form-grid">
                  <div>
                    <label className="imap-modal-label">
                      Username
                    </label>
                    <input
                      type="text"
                      value={imapUsername}
                      onChange={(e) => setImapUsername(e.target.value)}
                      placeholder="Usually your email address"
                      className="imap-modal-input"
                    />
                  </div>
                  <div>
                    <label className="imap-modal-label">
                      Password
                    </label>
                    <div className="imap-modal-password-container">
                      <input
                        type={showImapPassword ? 'text' : 'password'}
                        value={imapPassword}
                        onChange={(e) => setImapPassword(e.target.value)}
                        placeholder="••••••••"
                        className="imap-modal-password-input"
                      />
                      <button
                        type="button"
                        onClick={() => setShowImapPassword(!showImapPassword)}
                        className="imap-modal-password-toggle no-button-effects"
                        aria-label={showImapPassword ? 'Hide password' : 'Show password'}
                      >
                        {showImapPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              {/* SMTP Settings */}
              <div className="imap-modal-section">
                <h3 className="imap-modal-section-title heading-m">
                  SMTP Settings (Outgoing Mail)
                </h3>
                <div className="imap-modal-form-grid">
                  <div>
                    <label className="imap-modal-label">
                      SMTP Host
                    </label>
                    <input
                      type="text"
                      value={smtpHost}
                      onChange={(e) => setSmtpHost(e.target.value)}
                      placeholder="smtp.example.com"
                      className="imap-modal-input"
                    />
                  </div>
                  <div>
                    <label className="imap-modal-label">
                      Port
                    </label>
                    <input
                      type="text"
                      value={smtpPort}
                      onChange={(e) => setSmtpPort(e.target.value)}
                      placeholder="587"
                      className="imap-modal-input"
                    />
                  </div>
                </div>
                <div className="imap-modal-form-grid">
                  <div>
                    <label className="imap-modal-label">
                      Username
                    </label>
                    <input
                      type="text"
                      value={smtpUsername}
                      onChange={(e) => setSmtpUsername(e.target.value)}
                      placeholder="Usually your email address"
                      className="imap-modal-input"
                    />
                  </div>
                  <div>
                    <label className="imap-modal-label">
                      Password
                    </label>
                    <div className="imap-modal-password-container">
                      <input
                        type={showSmtpPassword ? 'text' : 'password'}
                        value={smtpPassword}
                        onChange={(e) => setSmtpPassword(e.target.value)}
                        placeholder="••••••••"
                        className="imap-modal-password-input"
                      />
                      <button
                        type="button"
                        onClick={() => setShowSmtpPassword(!showSmtpPassword)}
                        className="imap-modal-password-toggle no-button-effects"
                        aria-label={showSmtpPassword ? 'Hide password' : 'Show password'}
                      >
                        {showSmtpPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="imap-modal-actions">
                <button
                  type="button"
                  onClick={handleConnectAccount}
                  disabled={isConnecting}
                  className="imap-modal-connect-button create-campaign-style-button"
                >
                  Connect Account
                </button>
              </div>

              {/* Security Note */}
              <div className="imap-modal-security-note">
                <AlertCircle size={16} color="#6B7280" className="imap-modal-security-note-icon" />
                <div className="imap-modal-security-note-content">
                  <p className="imap-modal-security-note-title">
                    Security Note:
                  </p>
                  <p className="imap-modal-security-note-text">
                   Your credentials are securely encrypted. Use app-specific passwords when available.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Error Toast Notification */}
      {showErrorModal && (
        <div
          role="status"
          aria-live="assertive"
          className="error-modal"
        >
          <div className="error-modal-content">
            <div className="error-modal-text">
              <h3 className="error-modal-title heading-m">Almost there!</h3>
              <p className="error-modal-message">{errorMessage}</p>
            </div>
            <button onClick={() => setShowErrorModal(false)} className="error-modal-close">×</button>
            <div className="error-modal-indicator" />
          </div>
        </div>
      )}
    </div>
  );
}

