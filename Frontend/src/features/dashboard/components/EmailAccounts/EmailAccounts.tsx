import React, { useState, useEffect, useRef } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Zap, Settings, Mail, ChevronRight, Plus, Eye, EyeOff, X, CheckCircle, AlertCircle, MoreVertical, TrendingUp, Activity, Check, Slack, ArrowLeft } from 'lucide-react';
import { toast } from 'sonner';
import { apiService } from '../../../../shared/services/api';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';
import { Tabs, TabsList, TabsTrigger } from '../ui/tabs';
import { GoogleConsentPage } from './GoogleConsentPage';
import { IMAPConsentPage } from './IMAPConsentPage';
import './EmailAccounts.css';
import '../Campaign/Campaign.css';

interface EmailAccountsProps {
  onToggleSidebar?: () => void;
}

export function EmailAccounts({ onToggleSidebar }: EmailAccountsProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const [showManagementView, setShowManagementView] = useState(false);
  const [activeTab, setActiveTab] = useState<'managed' | 'existing'>('managed');
  const [showImapModal, setShowImapModal] = useState(false);
  const [hasManagedPool, setHasManagedPool] = useState(false);
  const [connectionSource, setConnectionSource] = useState<'managed' | 'existing' | null>(null);
  // Track which tabs have been explicitly connected
  const [managedPoolConnected, setManagedPoolConnected] = useState(false);
  const [existingEmailsConnected, setExistingEmailsConnected] = useState(false);
  // Track if user clicked "Let's Connect Your Email" to show only existing accounts options
  const [showOnlyExistingAccounts, setShowOnlyExistingAccounts] = useState(false);
  /** True when "Let's Connect Your Email" was opened from the management dashboard — Back restores dashboard, not marketing cards */
  const [connectFlowFromDashboard, setConnectFlowFromDashboard] = useState(false);
  // Track if we should show "Add Email Account" title (from campaign)
  const [showAddEmailAccountTitle, setShowAddEmailAccountTitle] = useState(false);
  // Track active state for each tab
  const [isManagedActive, setIsManagedActive] = useState(true);
  const [isExistingActive, setIsExistingActive] = useState(true);
  
  // Ref to track processed connection events to prevent duplicate toasts
  const processedConnectionRef = useRef<string | null>(null);
  
  // IMAP form state
  const [emailProvider, setEmailProvider] = useState('');
  const [imapHost, setImapHost] = useState('');
  const [imapPort, setImapPort] = useState('');
  const [imapUsername, setImapUsername] = useState('');
  const [imapPassword, setImapPassword] = useState('');
  const [showImapPassword, setShowImapPassword] = useState(false);
  const [smtpHost, setSmtpHost] = useState('');
  const [smtpPort, setSmtpPort] = useState('');
  const [smtpUsername, setSmtpUsername] = useState('');
  const [smtpPassword, setSmtpPassword] = useState('');
  const [showSmtpPassword, setShowSmtpPassword] = useState(false);
  
  // Connect Email (Early Access) loader modal
  const [showConnectEmailLoader, setShowConnectEmailLoader] = useState(false);
  // Consent form modals (Gmail + IMAP) - show as overlay instead of full-page
  const [showGoogleConsentModal, setShowGoogleConsentModal] = useState(false);
  const [showImapConsentModal, setShowImapConsentModal] = useState(false);
  
  // Mailboxes state
  const [mailboxes, setMailboxes] = useState<any[]>([]);
  const [isLoadingMailboxes, setIsLoadingMailboxes] = useState(false);
  
  // Statistics state
  const [emailStats, setEmailStats] = useState({
    sentToday: 0,
    deliveryRate: 0,
    bounceRate: 0,
  });
  const [isLoadingStats, setIsLoadingStats] = useState(false);
  /** False until first bootstrap finishes — avoids flashing connect cards then swapping to dashboard */
  const [emailAccountsLayoutReady, setEmailAccountsLayoutReady] = useState(false);

  // Fetch mailboxes function (`silent` avoids full-tab "Loading email accounts..." — e.g. right after IMAP connect)
  const fetchMailboxes = async (options?: { silent?: boolean }) => {
    const silent = options?.silent ?? false;
    if (!silent) {
      setIsLoadingMailboxes(true);
    }
    try {
      const response = await apiService.getAllMailboxes();
      if (response.data) {
        setMailboxes(response.data);
      } else {
        setMailboxes([]);
      }
    } catch (error) {
      console.error('Error fetching mailboxes:', error);
      setMailboxes([]);
    } finally {
      if (!silent) {
        setIsLoadingMailboxes(false);
      }
    }
  };

  // Fetch email statistics function
  const fetchEmailStatistics = async () => {
    setIsLoadingStats(true);
    try {
      const response = await apiService.getEmailStatistics();
      if (response.data) {
        setEmailStats({
          sentToday: response.data.sent_today || 0,
          deliveryRate: response.data.delivery_rate || 0,
          bounceRate: response.data.bounce_rate || 0,
        });
      }
    } catch (error) {
      console.error('Error fetching email statistics:', error);
      // Keep default values on error
    } finally {
      setIsLoadingStats(false);
    }
  };

  // Initial load: if user already connected system email (SYSTEM) or custom mailboxes, show the
  // management dashboard — not the first-time connect cards (also applies on refresh).
  useEffect(() => {
    const skipBootstrapDashboard =
      sessionStorage.getItem('showOnlyExistingAccounts') === 'true' ||
      sessionStorage.getItem('showAddEmailAccountPage') === 'true';

    let cancelled = false;

    const bootstrap = async () => {
      try {
        if (skipBootstrapDashboard) {
          await fetchMailboxes();
          fetchEmailStatistics();
          return;
        }

        setIsLoadingMailboxes(true);
        try {
          const [mailboxRes, userRes] = await Promise.all([
            apiService.getAllMailboxes(),
            apiService.getCurrentUser().catch(() => ({ data: undefined })),
          ]);
          if (cancelled) return;

          const list = mailboxRes.data ?? [];
          setMailboxes(list);

          const mode = userRes.data?.email_sending_mode ?? undefined;
          const hasMailboxes = list.length > 0;
          const isSystemMode = mode === 'SYSTEM';

          if (hasMailboxes || isSystemMode) {
            setShowManagementView(true);
            if (isSystemMode) {
              setHasManagedPool(true);
              setManagedPoolConnected(true);
              setConnectionSource('managed');
              setActiveTab('managed');
            }
            if (hasMailboxes) {
              setExistingEmailsConnected(true);
              if (!isSystemMode) {
                setConnectionSource('existing');
                setActiveTab('existing');
              }
            }
          }
        } catch (e) {
          console.error('Failed to bootstrap email accounts page', e);
          setMailboxes([]);
        } finally {
          if (!cancelled) {
            setIsLoadingMailboxes(false);
          }
        }
        fetchEmailStatistics();
      } finally {
        if (!cancelled) {
          setEmailAccountsLayoutReady(true);
        }
      }
    };

    bootstrap();
    return () => {
      cancelled = true;
    };
  }, []);

  // Check if we should show IMAP form after returning from consent page
  // This needs to run FIRST, before other useEffects that might redirect
  useEffect(() => {
    // Check both location state and sessionStorage
    const showImapFormFromState = location.state?.showImapForm;
    const showImapFormFromStorage = sessionStorage.getItem('showImapForm') === 'true';
    const showManagementViewFromState = location.state?.showManagementView;
    const showManagementViewFromStorage = sessionStorage.getItem('showManagementView') === 'true';
    
    console.log('[DEBUG] IMAP form check', { 
      showImapFormFromState, 
      showImapFormFromStorage, 
      showManagementViewFromState,
      showManagementViewFromStorage,
      pathname: location.pathname,
      locationState: location.state,
      currentShowManagementView: showManagementView,
      currentShowImapModal: showImapModal
    });
    
    if (showImapFormFromState || showImapFormFromStorage) {
      console.log('[DEBUG] Opening IMAP modal from consent page');
      setShowImapConsentModal(false);
      
      // Set management view FIRST - this is critical to stay on email accounts page
      setShowManagementView(true);
      if (showManagementViewFromStorage) {
        sessionStorage.removeItem('showManagementView');
      }
      
      // Set active tab
      setActiveTab('existing');
      
      // Open modal immediately
      setShowImapModal(true);
      console.log('[DEBUG] Modal state set to true immediately');
      
      // Also set with delays as backup to ensure it opens
      const timer1 = setTimeout(() => {
        console.log('[DEBUG] Setting showManagementView and showImapModal (backup 1)');
        setShowManagementView(true);
        setActiveTab('existing');
        setShowImapModal(true);
      }, 50);
      
      const timer2 = setTimeout(() => {
        console.log('[DEBUG] Setting showImapModal to true (backup 2)');
        setShowImapModal(true);
        setShowManagementView(true);
      }, 150);
      
      // Clear the state to prevent reopening on re-render
      sessionStorage.removeItem('showImapForm');
      
      // Clear location state after a delay to ensure modal opens
      if (showImapFormFromState) {
        setTimeout(() => {
          navigate(location.pathname, { replace: true, state: {} });
        }, 500);
      }
      
      return () => {
        clearTimeout(timer1);
        clearTimeout(timer2);
      };
    } else if (showManagementViewFromState || showManagementViewFromStorage) {
      // Just set management view if flag is present
      setShowManagementView(true);
      sessionStorage.removeItem('showManagementView');
    }
  }, [location.state, location.pathname, navigate]);

  // Check if we should show the "Add Email Account" page (from campaign)
  useEffect(() => {
    const showOnlyExistingAccountsFlag = sessionStorage.getItem('showOnlyExistingAccounts') === 'true';
    const showAddEmailAccountPageFlag = sessionStorage.getItem('showAddEmailAccountPage') === 'true';
    
    if (showOnlyExistingAccountsFlag || showAddEmailAccountPageFlag) {
      setShowManagementView(false);
      setShowOnlyExistingAccounts(true);
      if (showAddEmailAccountPageFlag) {
        setShowAddEmailAccountTitle(true);
      }
      // Clear the flags after using them
      sessionStorage.removeItem('showOnlyExistingAccounts');
      sessionStorage.removeItem('showAddEmailAccountPage');
    }
  }, []);

  // Handle connection callbacks and set initial tab based on source
  useEffect(() => {
    const searchParams = new URLSearchParams(location.search);
    const gmailConnected = searchParams.get('gmail_connected');
    const gmailError = searchParams.get('gmail_error');
    const imapConnected = searchParams.get('imap_connected');
    const managedPoolConnected = searchParams.get('managed_pool_connected');
    const errorMessage = searchParams.get('message');
    const fromCampaign = searchParams.get('from_campaign');

    // Check if user has a stored choice from campaign flow (when visiting email accounts page later)
    // This takes priority if no specific URL params are provided
    // Prefer campaign-specific key when editCampaignId is set (avoids cross-campaign leakage)
    const editCampaignId = sessionStorage.getItem('editCampaignId');
    const emailAccountChoice = (editCampaignId && sessionStorage.getItem(`campaignEmailAccountChoice_${editCampaignId}`)) ||
                              sessionStorage.getItem('campaignEmailAccountChoice');
    
    // Check if we came from campaign flow and should open specific views
    if (fromCampaign === 'true') {
      // Always show the full management view when coming from campaign flow
      setShowManagementView(true);
      
      const openManaged = searchParams.get('open_managed');
      const openExisting = searchParams.get('open_existing');
      const openImap = searchParams.get('open_imap');
      
      // Set appropriate tab based on what was requested in URL params (takes priority)
      if (openManaged === 'true') {
        setActiveTab('managed');
        setHasManagedPool(true); // Mark managed pool as active
        setManagedPoolConnected(true); // Mark as connected to show stats cards
      } else if (openExisting === 'true' || openImap === 'true') {
        setActiveTab('existing');
        setExistingEmailsConnected(true); // Mark as connected to show stats cards
        fetchMailboxes(); // Fetch mailboxes to show connected accounts
        if (openImap === 'true' && !imapConnected && !gmailConnected && !gmailError && !showImapModal) {
          // Auto-open IMAP modal
          setShowImapModal(true);
        }
      } else if (emailAccountChoice) {
        // No specific URL params, but we have a stored choice - use it
        if (emailAccountChoice === 'managed') {
          setActiveTab('managed');
          setHasManagedPool(true);
          setManagedPoolConnected(true);
        } else if (emailAccountChoice === 'existing') {
          setActiveTab('existing');
          setExistingEmailsConnected(true);
          fetchMailboxes();
        }
        // Clear the flag after using it (one-time use)
        if (editCampaignId) sessionStorage.removeItem(`campaignEmailAccountChoice_${editCampaignId}`);
        sessionStorage.removeItem('campaignEmailAccountChoice');
      } else {
        // Default to existing tab when coming from campaign (for Gmail/IMAP options)
        setActiveTab('existing');
        setExistingEmailsConnected(true); // Mark as connected to show stats cards
        fetchMailboxes(); // Fetch mailboxes to show connected accounts
      }
    } else if (emailAccountChoice) {
      // Not from campaign URL params, but user has a stored choice from campaign flow
      setShowManagementView(true);
      
      if (emailAccountChoice === 'managed') {
        setActiveTab('managed');
        setHasManagedPool(true);
        setManagedPoolConnected(true);
      } else if (emailAccountChoice === 'existing') {
        setActiveTab('existing');
        setExistingEmailsConnected(true);
        fetchMailboxes(); // Fetch mailboxes to show connected accounts
      }
      
      // Clear the flag after using it (one-time use)
      if (editCampaignId) sessionStorage.removeItem(`campaignEmailAccountChoice_${editCampaignId}`);
      sessionStorage.removeItem('campaignEmailAccountChoice');
    }
    
    // Check if we should open existing emails tab (from Gmail OAuth flow or sessionStorage)
    const openExistingEmailsTab = sessionStorage.getItem('openExistingEmailsTab');
    if (openExistingEmailsTab === 'true') {
      setShowManagementView(true);
      setActiveTab('existing');
      setExistingEmailsConnected(true); // Mark as connected to show stats cards
      fetchMailboxes(); // Fetch mailboxes to show connected accounts
      // Clear the flag after using it
      sessionStorage.removeItem('openExistingEmailsTab');
    }

    // Reset ref if search params are cleared (allows processing new connection events)
    if (!location.search || location.search === '') {
      processedConnectionRef.current = null;
      // If we came from campaign, always show full management view with complete page design
      const fromCampaignInStorage = sessionStorage.getItem('cameFromCampaign');
      if (fromCampaignInStorage === 'true' && !showManagementView) {
        setShowManagementView(true);
        setActiveTab('existing');
        setExistingEmailsConnected(true); // Mark as connected to show stats cards
        sessionStorage.removeItem('cameFromCampaign');
      }
      return;
    }

    // Create a unique identifier for this connection event
    const connectionKey = location.search;
    
    // Skip if we've already processed this connection event
    if (processedConnectionRef.current === connectionKey) {
      return;
    }

    // Mark as processed immediately to prevent duplicate processing
    processedConnectionRef.current = connectionKey;

    // Handle managed pool connection (Early Access)
    if (managedPoolConnected === 'true') {
      toast.success('Managed email pool connected successfully!');
      setShowManagementView(true);
      setActiveTab('managed'); // Land on Managed Email Pool tab
      setHasManagedPool(true); // Mark that managed pool is active
      setConnectionSource('managed'); // Track that we came from managed pool
      setManagedPoolConnected(true); // Mark managed pool as connected
      // Don't clear existing emails data - preserve it for when user switches tabs
      // Clean up URL parameters
      navigate(location.pathname, { replace: true });
    }
    // Handle Gmail connection
    else if (gmailConnected === 'true') {
      toast.success('Gmail account connected successfully!');
      // Switch to existing emails tab to show the connected account
      setShowManagementView(true);
      setActiveTab('existing');
      setConnectionSource('existing'); // Track that we came from existing emails
      setExistingEmailsConnected(true); // Mark existing emails as connected
      // Don't clear managed pool data - preserve it for when user switches tabs
      // Fetch mailboxes to show the newly connected account
      fetchMailboxes();
      // Refresh statistics after connecting email
      fetchEmailStatistics();
      // Clean up URL parameters
      navigate(location.pathname, { replace: true });
      // Clear the flag if it exists
      sessionStorage.removeItem('openExistingEmailsTab');
    }
    // Handle IMAP connection
    else if (imapConnected === 'true') {
      toast.success('IMAP account connected successfully!');
      
      // Switch to existing emails tab to show the connected account
      setShowManagementView(true);
      setActiveTab('existing');
      setConnectionSource('existing'); // Track that we came from existing emails
      setExistingEmailsConnected(true); // Mark existing emails as connected
      // Don't clear managed pool data - preserve it for when user switches tabs
      // Fetch mailboxes to show the newly connected account
      fetchMailboxes();
      // Refresh statistics after connecting email
      fetchEmailStatistics();
      // Clean up URL parameters
      navigate(location.pathname, { replace: true });
    }
    // Handle errors
    else if (gmailError === 'true') {
      const displayMessage = errorMessage || 'Failed to connect Gmail account. Please try again.';
      toast.error(displayMessage);
      // Clean up URL parameters
      navigate(location.pathname, { replace: true });
    }
  }, [location.search, location.pathname, navigate]);

  const handleConnectEmailClick = async () => {
    setShowConnectEmailLoader(true);
    const minLoaderTime = 6000; // Show loader at least 6s so users can read the onboarding copy
    const startTime = Date.now();
    try {
      await apiService.setCampaignEmailSendingMode('SYSTEM');
      await apiService.updateEmailSendingMode('SYSTEM');
      const elapsed = Date.now() - startTime;
      const remaining = Math.max(0, minLoaderTime - elapsed);
      if (remaining > 0) {
        await new Promise((r) => setTimeout(r, remaining));
      }
    } catch (error) {
      console.error('Failed to set email sending mode:', error);
      setShowConnectEmailLoader(false);
      return;
    }
    setShowConnectEmailLoader(false);
    navigate('/dashboard/email-accounts?managed_pool_connected=true', { replace: true });
  };

  const handleCloseConnectEmailLoader = () => {
    setShowConnectEmailLoader(false);
  };

  // Handle tab switching - preserve data for both tabs
  const handleTabSwitch = (tab: 'managed' | 'existing') => {
    setActiveTab(tab);
    
    // If switching to existing emails tab and it's connected, fetch mailboxes if not already loaded
    if (tab === 'existing' && existingEmailsConnected && mailboxes.length === 0) {
      fetchMailboxes();
    }
    // Don't clear data when switching tabs - preserve what was previously loaded
  };

  // Handle "Let's Connect Your Email" button - show connection options
  const handleLetsConnectEmail = () => {
    setConnectFlowFromDashboard(true);
    setShowManagementView(false); // Full-page Gmail/IMAP options (same layout as first-time flow)
    setShowOnlyExistingAccounts(true); // Show only the "Connect Existing Accounts" section
  };

  const handleBackFromConnectExistingOnly = () => {
    setShowOnlyExistingAccounts(false);
    if (connectFlowFromDashboard) {
      setConnectFlowFromDashboard(false);
      setShowManagementView(true);
    }
  };

  // Handle "Configure Managed Pool" button - show managed pool data
  const handleConfigureManagedPool = () => {
    setHasManagedPool(true);
    setManagedPoolConnected(true);
    setConnectionSource('managed');
    // Don't clear existing emails data - preserve it for when user switches tabs
  };

  const handleGoogleConnect = async () => {
    setShowGoogleConsentModal(true);
  };

  const handleImapConnect = () => {
    setShowImapConsentModal(true);
  };

  const handleCloseImapModal = () => {
    setShowImapModal(false);
    // Reset form when closing
    setEmailProvider('');
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
      toast.error(validation.error);
      return;
    }
    
    // If validation passes, proceed with account creation
    try {
      // Determine email address - use username if it contains @, otherwise construct it
      let emailAddress = imapUsername;
      if (!imapUsername.includes('@')) {
        // Try to extract domain from IMAP host (e.g., imap.gmail.com -> gmail.com)
        const domain = imapHost.replace(/^imap\./i, '').replace(/^mail\./i, '');
        emailAddress = `${imapUsername}@${domain}`;
      }

      // Construct SMTP host if not provided (try to derive from IMAP host)
      let smtpHostValue = smtpHost;
      if (!smtpHostValue) {
        // Common patterns: imap.gmail.com -> smtp.gmail.com, mail.example.com -> smtp.example.com
        smtpHostValue = imapHost.replace(/^imap\./i, 'smtp.').replace(/^mail\./i, 'smtp.');
      }

      const payload = {
        email: emailAddress,
        username: smtpUsername,
        password: smtpPassword,
        smtp_host: smtpHostValue,
        smtp_port: smtpPort ? parseInt(smtpPort) : undefined,
        receive_email: emailAddress,
        imap_username: imapUsername,
        imap_password: imapPassword,
        imap_host: imapHost,
        imap_port: imapPort ? parseInt(imapPort) : undefined,
        provider: 'ANY_PROVIDER',
      };

      const response = await apiService.createMailbox(payload);
      
      if (response.data) {
        // Success
        toast.success('Account connected successfully!');
        setShowImapConsentModal(false);
        handleCloseImapModal();

        // Stay on email accounts with a clean URL — avoid `imap_connected` (prevents duplicate toast/effect + extra fetch)
        navigate({ pathname: location.pathname, search: '' }, { replace: true });
        setShowManagementView(true);
        setActiveTab('existing');
        setConnectionSource('existing');
        setExistingEmailsConnected(true);
        // Show the new row immediately, then sync from server without the loading placeholder
        const created = response.data;
        setMailboxes((prev) => {
          if (prev.some((m) => m.id === created.id)) {
            return prev.map((m) => (m.id === created.id ? created : m));
          }
          return [...prev, created];
        });
        fetchMailboxes({ silent: true });
        fetchEmailStatistics();
      } else {
        // API returned an error – make the message clearer than a raw "422" string
        const rawMessage =
          (response as any)?.error ||
          (response as any)?.message ||
          '';

        let userMessage = rawMessage;

        // If backend returned something like "Error 422: Unprocessable Entity",
        // replace it with a friendly explanation.
        if (!userMessage || /422/i.test(String(userMessage))) {
          userMessage =
            "We couldn’t validate these IMAP/SMTP details. The mail server rejected the connection, usually because the host, port, username, or password is incorrect or IMAP/SMTP isn’t enabled for this mailbox.";
        }

        toast.error(userMessage);
      }
    } catch (error: any) {
      // Network or validation errors - provide clearer, user-friendly messaging
      const status = error?.response?.status;
      const backendMessage =
        error?.response?.data?.message ||
        error?.response?.data?.detail ||
        error?.message ||
        error?.error;

      let userMessage = backendMessage;

      // Special handling for 422 validation errors so users understand what went wrong
      if (status === 422) {
        userMessage =
          backendMessage ||
          "We couldn't validate these IMAP/SMTP settings. Please double‑check the server addresses, ports, username, and password, then try again.";
      }

      if (!userMessage) {
        userMessage =
          "We're unable to reach your inbox right now. Please review your IMAP/SMTP settings and make sure IMAP/SMTP is enabled with your email provider.";
      }

      toast.error(userMessage);
    }
  };

  // After mailboxes are loaded, check if we came from campaign and should show management view
  useEffect(() => {
    // Check URL params first
    const searchParams = new URLSearchParams(location.search);
    const fromCampaignInURL = searchParams.get('from_campaign');
    
    // Also check sessionStorage
    const fromCampaignInStorage = sessionStorage.getItem('cameFromCampaign');
    
    // If we came from campaign (either via URL or storage), always show full management view
    if ((fromCampaignInURL === 'true' || fromCampaignInStorage === 'true') && !showManagementView) {
      setShowManagementView(true);
      setActiveTab('existing');
      setExistingEmailsConnected(true); // Mark as connected to show stats cards
      if (fromCampaignInStorage === 'true') {
        sessionStorage.removeItem('cameFromCampaign');
      }
    }
  }, [mailboxes, location.search, showManagementView]);

  // Fetch mailboxes when on Existing Emails tab if connected but not yet loaded
  useEffect(() => {
    if (showManagementView && activeTab === 'existing' && existingEmailsConnected && mailboxes.length === 0) {
      fetchMailboxes();
    }
    // Don't clear mailboxes when switching tabs - preserve data
  }, [showManagementView, activeTab, existingEmailsConnected]);

  // Handle provider selection to pre-fill settings
  useEffect(() => {
    if (emailProvider === 'gmail') {
      setImapHost('imap.gmail.com');
      setImapPort('993');
      setSmtpHost('smtp.gmail.com');
      setSmtpPort('587');
    } else if (emailProvider === 'outlook') {
      setImapHost('outlook.office365.com');
      setImapPort('993');
      setSmtpHost('smtp.office365.com');
      setSmtpPort('587');
    } else if (emailProvider === 'yahoo') {
      setImapHost('imap.mail.yahoo.com');
      setImapPort('993');
      setSmtpHost('smtp.mail.yahoo.com');
      setSmtpPort('587');
    } else if (emailProvider === 'custom' || emailProvider === '') {
      setImapHost('');
      setImapPort('');
      setSmtpHost('');
      setSmtpPort('');
    }
  }, [emailProvider]);

  // Show the management view with tabs
  return (
    <>
      {!emailAccountsLayoutReady ? (
        <div className="email-accounts-container">
          <div className="email-accounts-content email-accounts-content-management email-accounts-bootstrap-shell">
            <div className="email-accounts-loading-existing" aria-busy="true" aria-live="polite">
              <p className="email-accounts-loading-existing-text">Loading…</p>
            </div>
          </div>
        </div>
      ) : showManagementView ? (
        <div className="email-accounts-container">
        <div className="email-accounts-header email-accounts-header-management">
        
        </div>

        <div className="email-accounts-content email-accounts-content-management">
          {/* Tab Switch with Add Button */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <Tabs
              className="campaign-tabs-mobile"
              value={activeTab}
              onValueChange={(value) => handleTabSwitch(value as 'managed' | 'existing')}
            >
              <TabsList className="campaign-tabs-list-mobile">
                <TabsTrigger
                  value="managed"
                  className={`campaign-tab-trigger ${activeTab === 'managed' ? 'active' : 'inactive'}`}
                >
                  System Emails
                </TabsTrigger>
                <TabsTrigger
                  value="existing"
                  className={`campaign-tab-trigger ${activeTab === 'existing' ? 'active' : 'inactive'}`}
                >
                  Custom Emails
                </TabsTrigger>
              </TabsList>
            </Tabs>

            {/* Add More Email Account Button - Only show on Existing Emails tab when there are mailboxes */}
            {activeTab === 'existing' && mailboxes.length > 0 && (
              <button
                onClick={handleLetsConnectEmail}
                className="email-accounts-empty-existing-button create-campaign-style-button"
              >
                Let&apos;s Connect Your Email
              </button>
            )}
          </div>

          {/* Statistics Cards - Show for Existing Emails tab when there are mailboxes or existing emails are connected */}
          {activeTab === 'existing' && (existingEmailsConnected || mailboxes.length > 0) && (
          <div className="email-accounts-stats-grid">
            {/* Total Accounts Card */}
            <div className="email-accounts-stat-card">
              <div className="email-accounts-stat-card-icon-container purple">
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="url(#emailStatGradient)"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden
                >
                  <defs>
                    <linearGradient id="emailStatGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                      <stop offset="0%" stopColor="#D458FF" stopOpacity="0.7" />
                      <stop offset="100%" stopColor="#6B21A8" stopOpacity="1" />
                    </linearGradient>
                  </defs>
                  <rect x="4" y="6" width="16" height="12" rx="3" />
                  <path d="M4 8l8 5 8-5" />
                </svg>
              </div>
              <p className="email-accounts-stat-card-label">
                Total Accounts
              </p>
              <p className="email-accounts-stat-card-value">
                {mailboxes.length}
              </p>
              <p className="email-accounts-stat-card-description">
                active
              </p>
            </div>

            {/* Sent Today Card */}
            <div className="email-accounts-stat-card">
              <div className="email-accounts-stat-card-icon-container blue">
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="url(#emailStatGradient)"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden
                >
                  <defs>
                    <linearGradient id="emailStatGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                      <stop offset="0%" stopColor="#D458FF" stopOpacity="0.7" />
                      <stop offset="100%" stopColor="#6B21A8" stopOpacity="1" />
                    </linearGradient>
                  </defs>
                  <path d="M13 2L3 14l7-2 1 8 10-12-8 2 0-8z" />
                </svg>
              </div>
              <p className="email-accounts-stat-card-label">
                Sent Today
              </p>
              <p className="email-accounts-stat-card-value">
                {emailStats.sentToday}
              </p>
              <p className="email-accounts-stat-card-description">
                of {mailboxes.reduce((sum, mb) => sum + (mb.daily_limit || 10), 0)} daily limit
              </p>
            </div>

            {/* Delivery Rate Card */}
            <div className="email-accounts-stat-card">
              <div className="email-accounts-stat-card-icon-container green">
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="url(#emailStatGradient)"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden
                >
                  <defs>
                    <linearGradient id="emailStatGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                      <stop offset="0%" stopColor="#D458FF" stopOpacity="0.7" />
                      <stop offset="100%" stopColor="#6B21A8" stopOpacity="1" />
                    </linearGradient>
                  </defs>
                  <path d="M3 17l6-6 4 4 7-9" />
                  <path d="M14 6h6v6" />
                </svg>
              </div>
              <p className="email-accounts-stat-card-label">
                Delivery Rate
              </p>
              <p className="email-accounts-stat-card-value">
                {emailStats.deliveryRate.toFixed(1)}%
              </p>
              <p className="email-accounts-stat-card-description">
                Average across all accounts
              </p>
            </div>

            {/* Account Health Card */}
            <div className="email-accounts-stat-card">
              <div className="email-accounts-stat-card-icon-container secondary">
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="url(#emailStatGradient)"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden
                >
                  <defs>
                    <linearGradient id="emailStatGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                      <stop offset="0%" stopColor="#D458FF" stopOpacity="0.7" />
                      <stop offset="100%" stopColor="#6B21A8" stopOpacity="1" />
                    </linearGradient>
                  </defs>
                  <polyline points="3 12 7 12 10 4 14 20 17 12 21 12" />
                </svg>
              </div>
              <p className="email-accounts-stat-card-label">
                Account Health
              </p>
              <p className="email-accounts-stat-card-value">
                {mailboxes.filter(m => m.is_active).length}/{mailboxes.length}
              </p>
              <p className="email-accounts-stat-card-description">
                Healthy accounts
              </p>
            </div>
          </div>
          )}

          {/* Tab Content */}
          {activeTab === 'managed' && (
            <>
              {hasManagedPool && managedPoolConnected ? (
                <div className="email-accounts-managed-container">
                  {/* Managed Email Pool Statistics Cards */}
                  <div className="email-accounts-managed-stats-grid">
                    {/* Total Emails Sent Card */}
                    <div className="email-accounts-managed-stat-card">
                      <div className="email-accounts-managed-stat-card-icon-container blue">
                        <svg
                          width="16"
                          height="16"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="url(#emailStatGradient)"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          aria-hidden
                        >
                          <defs>
                            <linearGradient id="emailStatGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                              <stop offset="0%" stopColor="#D458FF" stopOpacity="0.7" />
                              <stop offset="100%" stopColor="#6B21A8" stopOpacity="1" />
                            </linearGradient>
                          </defs>
                          <path d="M13 2L3 14l7-2 1 8 10-12-8 2 0-8z" />
                        </svg>
                      </div>
                      <p className="email-accounts-managed-stat-card-label email-accounts-managed-total-emails-label">
                        Total Emails Sent
                      </p>
                      <p className="email-accounts-managed-stat-card-value email-accounts-managed-total-emails-value">
                        0
                      </p>
                      <p className="email-accounts-managed-stat-card-description email-accounts-managed-total-emails-meta">
                        of 15,000 total
                      </p>
                    </div>

                    {/* Remaining Emails Card */}
                    <div className="email-accounts-managed-stat-card full-padding">
                      <div className="email-accounts-managed-stat-card-icon-container green">
                        <svg
                          width="16"
                          height="16"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="url(#emailStatGradient)"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          aria-hidden
                        >
                          <defs>
                            <linearGradient id="emailStatGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                              <stop offset="0%" stopColor="#D458FF" stopOpacity="0.7" />
                              <stop offset="100%" stopColor="#6B21A8" stopOpacity="1" />
                            </linearGradient>
                          </defs>
                          <polyline points="3 12 7 12 10 4 14 20 17 12 21 12" />
                        </svg>
                      </div>
                      <p className="email-accounts-managed-stat-card-label small-margin">
                        Remaining Emails
                      </p>
                      <p className="email-accounts-managed-stat-card-value no-margin">
                        0
                      </p>
                    </div>

                    {/* Delivery Rate Card */}
                    <div className="email-accounts-managed-stat-card">
                      <div className="email-accounts-managed-stat-card-icon-container purple">
                        <svg
                          width="16"
                          height="16"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="url(#emailStatGradient)"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          aria-hidden
                        >
                          <defs>
                            <linearGradient id="emailStatGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                              <stop offset="0%" stopColor="#D458FF" stopOpacity="0.7" />
                              <stop offset="100%" stopColor="#6B21A8" stopOpacity="1" />
                            </linearGradient>
                          </defs>
                          <path d="M3 17l6-6 4 4 7-9" />
                          <path d="M14 6h6v6" />
                        </svg>
                      </div>
                      <p className="email-accounts-managed-stat-card-label small-margin">
                        Delivery Rate
                      </p>
                      <p className="email-accounts-managed-stat-card-value no-bottom-margin">
                        {emailStats.deliveryRate.toFixed(1)}%
                      </p>
                      <p className="email-accounts-managed-stat-card-description green">
                        Excellent delivery performance
                      </p>
                    </div>

                    {/* Bounce Rate Card */}
                    <div className="email-accounts-bounce-rate-card">
                      <div className="email-accounts-bounce-rate-icon-container">
                        <svg
                          width="16"
                          height="16"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="url(#emailStatGradient)"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          aria-hidden
                        >
                          <defs>
                            <linearGradient id="emailStatGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                              <stop offset="0%" stopColor="#D458FF" stopOpacity="0.7" />
                              <stop offset="100%" stopColor="#6B21A8" stopOpacity="1" />
                            </linearGradient>
                          </defs>
                          <circle cx="12" cy="12" r="9" />
                          <line x1="12" y1="8" x2="12" y2="13" />
                          <circle cx="12" cy="16" r="1" />
                        </svg>
                      </div>
                      <p className="email-accounts-bounce-rate-label">
                        Bounce Rate
                      </p>
                      <p className="email-accounts-bounce-rate-value">
                        {emailStats.bounceRate.toFixed(1)}%
                      </p>
                      <p className="email-accounts-bounce-rate-description">
                        Well below industry average
                      </p>
                    </div>
                  </div>

                  {/* Managed Email Pool Overview */}
                  <div className="email-accounts-managed-overview-card">
                    <div className="email-accounts-managed-overview-badge-container">
                      <span className="email-accounts-managed-overview-badge">
                        Active
                      </span>
                    </div>
                    <div className="email-accounts-managed-overview-header">
                      <div>
                        <h3 className="email-accounts-managed-overview-title">
                          Managed Email Pool Overview
                        </h3>
                        <p className="email-accounts-managed-overview-subtitle">
                          Pre-warmed email accounts managed by LeadGen Pro for optimal deliverability
                        </p>
                      </div>
                    </div>
                    <div className="email-accounts-managed-overview-quota-section">
                      <div className="email-accounts-managed-overview-stats-row">
                        <div className="email-accounts-managed-overview-stat-item">
                          <p className="email-accounts-managed-overview-quota-label">
                            Monthly Email Quota
                          </p>
                          <p className="email-accounts-managed-overview-quota-value">
                            0% Used
                          </p>
                          <p className="email-accounts-managed-overview-quota-text">
                            0 used of 15,000
                          </p>
                        </div>
                        <div className="email-accounts-managed-overview-stat-item">
                          <p className="email-accounts-managed-overview-stat-label">
                            Active Accounts
                          </p>
                          <p className="email-accounts-managed-overview-stat-value">
                            0
                          </p>
                        </div>
                        <div className="email-accounts-managed-overview-stat-item">
                          <p className="email-accounts-managed-overview-stat-label">
                            Average Daily Sending
                          </p>
                          <p className="email-accounts-managed-overview-stat-value">
                            0
                          </p>
                        </div>
                      </div>
                    </div>

                    {/* Performance Metrics */}
                    <div className="email-accounts-managed-overview-metrics">
                      <h3 className="email-accounts-managed-overview-metrics-title heading-m">
                        Performance Metrics
                      </h3>
                      <div className="email-accounts-managed-overview-metrics-grid">
                        {/* Delivery Rate Card */}
                        <div className="email-accounts-performance-metric-card-delivery">
                          <div className="email-accounts-performance-metric-main">
                            <p className="email-accounts-performance-metric-label">
                              Delivery Rate
                            </p>
                            <p className="email-accounts-performance-metric-value-delivery">
                              {emailStats.deliveryRate.toFixed(1)}%
                            </p>
                          </div>
                          <div className="email-accounts-performance-metric-icon-delivery">
                            <CheckCircle size={12} color="white" />
                          </div>
                        </div>
                        {/* Bounce Rate Card */}
                        <div className="email-accounts-performance-metric-card-bounce">
                          <div className="email-accounts-performance-metric-main">
                            <p className="email-accounts-performance-metric-label">
                              Bounce Rate
                            </p>
                            <p className="email-accounts-performance-metric-value-bounce">
                              {emailStats.bounceRate.toFixed(1)}%
                            </p>
                          </div>
                          <div className="email-accounts-performance-metric-icon-bounce">
                            <AlertCircle size={12} color="white" />
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="email-accounts-empty-managed-pool">
                  <div className="email-accounts-empty-managed-pool-icon">
                    <div className="email-accounts-empty-managed-pool-icon-inner">
                      <img src="/message-header.svg" alt="Managed pool icon" />
                    </div>
                  </div>
                  <h2 className="email-accounts-empty-managed-pool-title heading-l">
                    No managed email pool configured
                  </h2>
                  <p className="email-accounts-empty-managed-pool-description">
                    Configure a managed email pool to get pre-warmed accounts
                  </p>
                  <button
                    onClick={handleConfigureManagedPool}
                    className="email-accounts-empty-managed-pool-button create-campaign-style-button"
                  >
                    Configure Managed Pool
                  </button>
                </div>
              )}
            </>
          )}

          {activeTab === 'existing' && (
            <>
              {isLoadingMailboxes ? (
                <div className="email-accounts-loading-existing">
                  <p className="email-accounts-loading-existing-text">Loading email accounts...</p>
                </div>
              ) : mailboxes.length > 0 ? (
                <div className="email-accounts-table-container">
                  <div className="email-accounts-table-header-section">
                    <h3 className="email-accounts-table-header-title heading-m">
                      Connected Accounts
                    </h3>
                    <p
                      className="email-accounts-table-header-description"
                      style={{ color: '#A198CE' }}
                    >
                      Monitor and manage all your email accounts in one place
                    </p>
                  </div>
                  <table className="email-accounts-table-element">
                    <thead>
                      <tr className="email-accounts-table-header-row">
                        <th className="email-accounts-table-header-cell">Email Address</th>
                        <th className="email-accounts-table-header-cell">Provider</th>
                        <th className="email-accounts-table-header-cell">Health</th>
                        <th className="email-accounts-table-header-cell">Status</th>
                        <th className="email-accounts-table-header-cell">Delivery Rate</th>
                        <th className="email-accounts-table-header-cell">Total Sent</th>
                      </tr>
                    </thead>
                    <tbody>
                      {mailboxes.map((mailbox) => {
                        const isGmail = mailbox.provider === 'GOOGLE';
                        const isImap = mailbox.provider === 'ANY_PROVIDER';
                        const showProvider = isGmail || isImap;
                        
                        return (
                          <tr key={mailbox.id} className="email-accounts-table-header-row">
                            <td className="email-accounts-table-cell">{mailbox.email}</td>
                            <td className="email-accounts-table-cell">
                              {showProvider ? (
                                <span className={`email-accounts-provider-badge ${isGmail ? 'gmail' : 'imap'}`}>
                                  {isGmail ? 'Gmail' : 'IMAP/SMTP'}
                                </span>
                              ) : (
                                <span className="email-accounts-na-text">N/A</span>
                              )}
                            </td>
                            <td className="email-accounts-table-cell">
                              <span className="email-accounts-healthy-badge">
                                <CheckCircle size={8} color="#008236" className="email-accounts-healthy-badge-icon" />
                                Healthy
                              </span>
                            </td>
                            <td className="email-accounts-table-cell">
                              <span 
                                className={`email-accounts-status-badge ${mailbox.is_active ? 'active' : 'inactive'}`}
                              >
                                {mailbox.is_active ? 'Active' : 'InActive'}
                              </span>
                            </td>
                            <td className="email-accounts-table-cell">
                              {mailbox.delivery_rate !== null && mailbox.delivery_rate !== undefined ? (
                                <span className="email-accounts-delivery-rate">
                                  {mailbox.delivery_rate}%
                                  <TrendingUp size={12} color="#10B981" />
                                </span>
                              ) : (
                                <span className="email-accounts-delivery-rate-na">N/A</span>
                              )}
                            </td>
                            <td className="email-accounts-table-cell">N/A</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <>
                  <div className="email-accounts-empty-state">
                    <div className="email-accounts-empty-state-icon">
                      <div className="email-accounts-empty-state-icon-inner">
                        <img src="/message-header.svg" alt="Email icon" />
                      </div>
                    </div>
                    <h2 className="email-accounts-empty-state-title">
                      You haven&apos;t added any email
                      <br />
                      account yet.
                    </h2>
                    <p className="email-accounts-empty-state-description">
                      Please connect your email to begin sending campaigns and
                      <br />
                      viewing your inbox activity.
                    </p>
                    <button
                      onClick={handleLetsConnectEmail}
                      className="email-accounts-empty-existing-button create-campaign-style-button"
                    >
                      Let&apos;s Connect Your Email
                    </button>
                  </div>
                  {/* Instructions Box */}
                  <div className="email-accounts-instructions-box">
                    <h3 className="email-accounts-instructions-title">
                      How to Use Your Own Email Accounts for Outreach (SMTP/IMAP)
                    </h3>

                    <div className="email-accounts-imap-help-section">
                      {/* Checklist items with check icon */}
                      <div className="email-accounts-imap-help-item">
                        <div className="email-accounts-imap-help-icon purple">
                          <svg width="16" height="16" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden>
                            <rect x="2" y="2" width="16" height="16" rx="4" stroke="#A198CE" strokeWidth="1.25" />
                            <path d="M5 10l3 3 7-7" stroke="#A198CE" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                        </div>
                        <div className="email-accounts-imap-help-content">
                          <h4 className="email-accounts-imap-help-title">
                            Add Your Email
                          </h4>
                          <p className="email-accounts-imap-help-text">
                            You can add any email address you own or connect it using SMTP/IMAP by entering your provider&apos;s details.
                          </p>
                        </div>
                      </div>

                      <div className="email-accounts-imap-help-item">
                        <div className="email-accounts-imap-help-icon purple">
                          <svg width="16" height="16" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden>
                            <rect x="2" y="2" width="16" height="16" rx="4" stroke="#A198CE" strokeWidth="1.25" />
                            <path d="M5 10l3 3 7-7" stroke="#A198CE" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                        </div>
                        <div className="email-accounts-imap-help-content">
                          <h4 className="email-accounts-imap-help-title">
                            Configure Email Settings
                          </h4>
                          <p className="email-accounts-imap-help-text">
                            For SMTP/IMAP, enter the necessary settings like server, port, username, and password for seamless integration.
                          </p>
                        </div>
                      </div>

                      <div className="email-accounts-imap-help-item">
                        <div className="email-accounts-imap-help-icon purple">
                          <svg width="16" height="16" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden>
                            <rect x="2" y="2" width="16" height="16" rx="4" stroke="#A198CE" strokeWidth="1.25" />
                            <path d="M5 10l3 3 7-7" stroke="#A198CE" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                        </div>
                        <div className="email-accounts-imap-help-content">
                          <h4 className="email-accounts-imap-help-title">
                            Email Integration
                          </h4>
                          <p className="email-accounts-imap-help-text">
                            Once added or configured, your email will be linked and ready for sending emails to leads.
                          </p>
                        </div>
                      </div>

                      <div className="email-accounts-imap-help-item">
                        <div className="email-accounts-imap-help-icon purple">
                          <svg width="16" height="16" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden>
                            <rect x="2" y="2" width="16" height="16" rx="4" stroke="#A198CE" strokeWidth="1.25" />
                            <path d="M5 10l3 3 7-7" stroke="#A198CE" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                        </div>
                        <div className="email-accounts-imap-help-content">
                          <h4 className="email-accounts-imap-help-title">
                            Automatic Email Sending
                          </h4>
                          <p className="email-accounts-imap-help-text">
                            Emails will be sent automatically from the email address you&apos;ve added, using the system or SMTP/IMAP settings for smooth delivery.
                          </p>
                        </div>
                      </div>

                      <div className="email-accounts-imap-help-item">
                        <div className="email-accounts-imap-help-icon purple">
                          <svg width="16" height="16" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden>
                            <rect x="2" y="2" width="16" height="16" rx="4" stroke="#A198CE" strokeWidth="1.25" />
                            <path d="M5 10l3 3 7-7" stroke="#A198CE" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                        </div>
                        <div className="email-accounts-imap-help-content">
                          <h4 className="email-accounts-imap-help-title">
                            Personalized Communication
                          </h4>
                          <p className="email-accounts-imap-help-text">
                            Send emails using your personal or business email for a more professional and reliable outreach.
                          </p>
                        </div>
                      </div>
                    </div>
                  </div>
              </>
              )}
            </>
          )}
        </div>
      </div>
      ) : (
        <div className="email-accounts-container">
          <div className="email-accounts-content">
            <div className={`email-accounts-title-container ${showOnlyExistingAccounts && !showAddEmailAccountTitle ? 'email-accounts-title-container-with-back' : ''}`}>
              {showAddEmailAccountTitle ? (
                <div>
                  <h1 className="email-accounts-title email-accounts-title-conditional">Add Email Account</h1>
                  <p className="email-accounts-title-subtitle">
                    Choose how you want to connect your email account
                  </p>
                </div>
              ) : showOnlyExistingAccounts && !showAddEmailAccountTitle ? (
                <div className="email-accounts-setup-option-title-row">
                  <button
                    type="button"
                    className="email-accounts-setup-back-button"
                    onClick={handleBackFromConnectExistingOnly}
                    aria-label="Back to email accounts dashboard"
                  >
                    <ArrowLeft size={18} strokeWidth={2} aria-hidden />
                  </button>
                  <h1 className="email-accounts-title email-accounts-title-conditional email-setup-option-page-title">
                    Choose Your Email Setup Option
                  </h1>
                </div>
              ) : (
                <h1 className="email-accounts-title email-accounts-title-conditional email-setup-option-page-title">
                  Choose Your Email Setup Option
                </h1>
              )}
            </div>
            <div className={`email-accounts-cards ${showOnlyExistingAccounts ? 'email-accounts-cards-conditional' : ''}`}>
              {/* Pre-Warmed Accounts Card - Only show if not coming from "Let's Connect Your Email" */}
              {!showOnlyExistingAccounts && (
                <div className="email-account-card pre-warmed-card">
                  <span className="popular-badge">Popular</span>
                  <div className="email-account-card-header">
                    <h2 className="email-account-card-title heading-xl">System Email Accounts</h2>
                  </div>
                  <p className="email-account-card-description">
                    Get instant access to professionally warmed-up
                    <br />
                    email accounts ready for high deliverability
                  </p>
                  <ul className="email-account-features">
              <li className="feature-item">
                <div className="feature-icon">
                  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <rect x="2" y="2" width="16" height="16" rx="4" stroke="currentColor" strokeWidth="1.25"/>
                    <path d="M5 10l3 3 7-7" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </div>
                <div className="feature-text">
                  <span className="feature-title">Zero-Configuration Setup</span>
                  <span className="feature-subtitle">Start sending emails immediately.</span>
                </div>
              </li>
              <li className="feature-item">
                <div className="feature-icon">
                  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <rect x="2" y="2" width="16" height="16" rx="4" stroke="currentColor" strokeWidth="1.25"/>
                    <path d="M5 10l3 3 7-7" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </div>
                <div className="feature-text">
                  <span className="feature-title">100% Automated Management</span>
                  <span className="feature-subtitle">Ensure 95%+ inbox placement.</span>
                </div>
              </li>
              <li className="feature-item">
                <div className="feature-icon">
                  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <rect x="2" y="2" width="16" height="16" rx="4" stroke="currentColor" strokeWidth="1.25"/>
                    <path d="M5 10l3 3 7-7" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </div>
                <div className="feature-text">
                  <span className="feature-title">High-Volume Outreach</span>
                  <span className="feature-subtitle">Maintain a strong sender reputation.</span>
                </div>
              </li>
              <li className="feature-item">
                <div className="feature-icon">
                  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <rect x="2" y="2" width="16" height="16" rx="4" stroke="currentColor" strokeWidth="1.25"/>
                    <path d="M5 10l3 3 7-7" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </div>
                <div className="feature-text">
                  <span className="feature-title">Smart Tracking Dashboard</span>
                  <span className="feature-subtitle">We handle all the technical details for you.</span>
                </div>
              </li>
                  </ul>
                  <button className="connect-button pre-warmed-button" onClick={handleConnectEmailClick}>
                    Connect Email (Early Access)
                  </button>
                </div>
              )}

          {/* Connect Existing Accounts Card */}
          <div className={`email-account-card existing-card ${showOnlyExistingAccounts ? 'email-accounts-card-existing-conditional' : ''}`}>
            <div className={`email-account-card-header-wrapper ${showAddEmailAccountTitle ? 'email-account-card-header-wrapper-horizontal' : ''}`}>
              <div className={`email-account-card-header ${showAddEmailAccountTitle ? 'email-account-card-header-column' : ''}`}>
                {showAddEmailAccountTitle ? (
                  <h2 className={`email-account-card-title heading-xl ${showOnlyExistingAccounts ? 'email-accounts-card-title-conditional' : ''}`}>
                    Connect Existing Accounts
                  </h2>
                ) : !showOnlyExistingAccounts ? (
                  <h2 className="email-account-card-title heading-xl">Connect Accounts</h2>
                ) : (
                  <h2 className={`email-account-card-title heading-xl ${showOnlyExistingAccounts ? 'email-accounts-card-title-conditional' : ''}`}>
                    Connect Accounts
                  </h2>
                )}
              </div>
              {!showAddEmailAccountTitle && !showOnlyExistingAccounts && (
                <p className="email-account-card-description email-accounts-connect-card-blurb">
                  Integrate your own email accounts via Gmail or custom IMAP/SMTP settings
                </p>
              )}
            </div>
            {!showAddEmailAccountTitle && (
            <div className="email-accounts-feature-flex-container">
              <div className="feature-icon">
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <rect x="2" y="2" width="16" height="16" rx="4" stroke="currentColor" strokeWidth="1.25"/>
                  <path d="M5 10l3 3 7-7" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </div>
              <div className="email-accounts-feature-content">
                <h3 className="feature-title email-accounts-feature-title-conditional">
                  Connect Your Own Email:
                </h3>
                <p className="feature-subtitle email-accounts-feature-subtitle-conditional">
                  Easily link your existing business or personal email (like Gmail or Outlook) using your account details.
                </p>
              </div>
            </div>
            )}
            <div className={`connection-options ${showOnlyExistingAccounts ? 'email-accounts-connection-options-conditional' : ''}`}>
              <button
                type="button"
                className={`connection-option connection-option-secondary ${showOnlyExistingAccounts ? 'email-accounts-connection-option-conditional' : ''}`}
                onClick={handleGoogleConnect}
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
                className={`connection-option connection-option-secondary ${showOnlyExistingAccounts ? 'email-accounts-connection-option-conditional' : ''}`}
                onClick={handleImapConnect}
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
        </div>
      )}

      {/* Connect Email Loader Modal - Shows when user clicks Connect Email (Early Access) */}
      {showConnectEmailLoader && (
        <div className="connect-email-loader-overlay">
          <div className="connect-email-loader-modal" style={{ padding: '24px' }}>
            <div className="connect-email-loader-header" style={{ marginBottom: '8px' }}>
              <div className="connect-email-loader-icon">
                <Slack size={48} color="#9164FF" strokeWidth={1.5} />
              </div>
              <button type="button" className="connect-email-loader-close" onClick={handleCloseConnectEmailLoader} aria-label="Close">
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

      {/* Google Consent Modal - overlay instead of full-page */}
      {showGoogleConsentModal && (
        <GoogleConsentPage
          redirectTo="/dashboard/email-accounts"
          asModal
          onClose={() => setShowGoogleConsentModal(false)}
        />
      )}

      {/* IMAP Consent Modal - overlay instead of full-page */}
      {showImapConsentModal && (
        <IMAPConsentPage
          redirectTo="/dashboard/email-accounts"
          asModal
          onClose={() => setShowImapConsentModal(false)}
        />
      )}

      {/* IMAP Connection Modal - Render outside conditional so it shows regardless of view */}
      {showImapModal && (
        <div className="email-accounts-imap-modal-overlay">
          <div className="email-accounts-imap-modal-content">
            {/* Header */}
            <div className="email-accounts-imap-modal-header-container">
              <div className="email-accounts-imap-modal-close-row">
                <button
                  onClick={handleCloseImapModal}
                  className="email-accounts-imap-modal-close-button"
                >
                  <X size={14} />
                </button>
              </div>
              <div className="email-accounts-imap-modal-header">
                <div className="email-accounts-imap-modal-header-left">
                  <div className="email-accounts-imap-modal-title-block">
                    <h2 className="email-accounts-imap-modal-header-title">
                      Connect IMAP
                    </h2>
                    <p className="email-accounts-imap-modal-subtitle">
                      Choose your connection method and configure your email account.
                    </p>
                  </div>
                </div>
              </div>
            </div>

            {/* Content */}
            <div className="email-accounts-imap-modal-body">
              {/* IMAP Settings */}
              <div className="email-accounts-imap-modal-section">
                <h3 className="email-accounts-imap-modal-section-title">
                  IMAP Settings (Incoming Mail)
                </h3>
                <div className="email-accounts-imap-modal-form-grid">
                  <div>
                    <label className="email-accounts-imap-modal-label">
                      IMAP Host
                    </label>
                    <input
                      type="text"
                      value={imapHost}
                      onChange={(e) => setImapHost(e.target.value)}
                      placeholder="imap.example.com"
                      className="email-accounts-imap-modal-input"
                    />
                  </div>
                  <div>
                    <label className="email-accounts-imap-modal-label">
                      Port
                    </label>
                    <input
                      type="text"
                      value={imapPort}
                      onChange={(e) => setImapPort(e.target.value)}
                      placeholder="993"
                      className="email-accounts-imap-modal-input"
                    />
                  </div>
                </div>
                <div className="email-accounts-imap-modal-form-grid-full">
                  <div>
                    <label className="email-accounts-imap-modal-label">
                      Username
                    </label>
                    <input
                      type="text"
                      value={imapUsername}
                      onChange={(e) => setImapUsername(e.target.value)}
                      placeholder="Usually your email address"
                      className="email-accounts-imap-modal-input"
                    />
                  </div>
                  <div>
                    <label className="email-accounts-imap-modal-label">
                      Password
                    </label>
                    <div className="email-accounts-imap-modal-password-container">
                      <input
                        type={showImapPassword ? 'text' : 'password'}
                        value={imapPassword}
                        onChange={(e) => setImapPassword(e.target.value)}
                        placeholder="••••••••"
                        className="email-accounts-imap-modal-input-password"
                      />
                      <button
                        type="button"
                        className="password-toggle-button no-button-effects"
                        aria-label={showImapPassword ? 'Hide password' : 'Show password'}
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          setShowImapPassword(!showImapPassword);
                        }}
                        onMouseDown={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                        }}
                      >
                        {showImapPassword ? <EyeOff size={18} className="email-accounts-eye-icon" /> : <Eye size={18} className="email-accounts-eye-icon" />}
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              {/* SMTP Settings */}
              <div className="email-accounts-imap-modal-section">
                <h3 className="email-accounts-imap-modal-section-title">
                  SMTP Settings (Outgoing Mail)
                </h3>
                <div className="email-accounts-imap-modal-form-grid">
                  <div>
                    <label className="email-accounts-imap-modal-label">
                      SMTP Host
                    </label>
                    <input
                      type="text"
                      value={smtpHost}
                      onChange={(e) => setSmtpHost(e.target.value)}
                      placeholder="smtp.example.com"
                      className="email-accounts-imap-modal-input"
                    />
                  </div>
                  <div>
                    <label className="email-accounts-imap-modal-label">
                      Port
                    </label>
                    <input
                      type="text"
                      value={smtpPort}
                      onChange={(e) => setSmtpPort(e.target.value)}
                      placeholder="587"
                      className="email-accounts-imap-modal-input"
                    />
                  </div>
                </div>
                <div className="email-accounts-imap-modal-form-grid-full">
                  <div>
                    <label className="email-accounts-imap-modal-label">
                      Username
                    </label>
                    <input
                      type="text"
                      value={smtpUsername}
                      onChange={(e) => setSmtpUsername(e.target.value)}
                      placeholder="Usually your email address"
                      className="email-accounts-imap-modal-input"
                    />
                  </div>
                  <div>
                    <label className="email-accounts-imap-modal-label">
                      Password
                    </label>
                    <div className="email-accounts-imap-modal-password-container">
                      <input
                        type={showSmtpPassword ? 'text' : 'password'}
                        value={smtpPassword}
                        onChange={(e) => setSmtpPassword(e.target.value)}
                        placeholder="••••••••"
                        className="email-accounts-imap-modal-input-password"
                      />
                      <button
                        type="button"
                        className="password-toggle-button no-button-effects"
                        aria-label={showSmtpPassword ? 'Hide password' : 'Show password'}
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          setShowSmtpPassword(!showSmtpPassword);
                        }}
                        onMouseDown={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                        }}
                      >
                        {showSmtpPassword ? <EyeOff size={18} className="email-accounts-eye-icon" /> : <Eye size={18} className="email-accounts-eye-icon" />}
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="email-accounts-imap-modal-actions">
                <button
                  type="button"
                  onClick={handleConnectAccount}
                  className="email-accounts-imap-modal-button create-campaign-style-button"
                >
                  Connect Account
                </button>
              </div>

              {/* Security Note */}
              <div className="email-accounts-imap-modal-security-note">
                <AlertCircle size={16} color="#6B7280" className="email-accounts-imap-modal-security-note-icon" />
                <div className="email-accounts-imap-modal-security-note-content">
                  <p className="email-accounts-imap-modal-security-note-title">
                    Security Note:
                  </p>
                  <p className="email-accounts-imap-modal-security-note-text">
                    Your credentials are securely encrypted. Use app-specific passwords when available.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

    </>
  );
}

