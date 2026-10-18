import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Menu, Slack, X, Plus, ChevronDown } from 'lucide-react';
import { Sidebar, type DashboardWorkspaceMode } from './components/Sidebar/Sidebar';
import { LeadGeneration, LeadGenerationRef } from './components/LeadGeneration/LeadGeneration';
import { LeadDatabase, LeadDatabaseRef } from './components/LeadDatabase/LeadDatabase';
import { LeadLog } from './components/LeadLog/LeadLog';
import { Campaign } from './components/Campaign/Campaign';
import { CampaignDetail } from './components/Campaign/CampaignDetail';
import { CreateCampaign } from './components/Campaign/CreateCampaign';
import { PreviewCampaignDetail } from './components/Campaign/PreviewCampaignDetail';
import { UserProfile } from './components/UserProfile/UserProfile';
import { Template } from './components/template/Template';
import { Inbox } from './components/Inbox/Inbox';
import { EmailAccounts } from './components/EmailAccounts/EmailAccounts';
import { EmailAccountSetupLoading } from './components/EmailAccounts/EmailAccountSetupLoading';
import { GoogleConsentPage } from './components/EmailAccounts/GoogleConsentPage';
import { IMAPConsentPage } from './components/EmailAccounts/IMAPConsentPage';
import { ProfileSettings } from './components/ProfileSettings/ProfileSettings';
import { BillingPage } from './components/Billing/BillingPage';
import { UsagePage } from './components/Billing/UsagePage';
import { AiUsageAdminPage } from './components/Admin/AiUsageAdminPage';
import { AdminCreditsPage } from './components/Admin/AdminCreditsPage';
import { AdminUsersPage } from './components/Admin/AdminUsersPage';
import { AdminMailboxesPage } from './components/Admin/AdminMailboxesPage';
import { GeminiPurchasesAdminPage } from './components/Admin/GeminiPurchasesAdminPage';
import { SettingsSidebar } from './components/SettingsSidebar/SettingsSidebar';
import { ErrorBoundary } from '../../shared/components/ErrorBoundary/ErrorBoundary';
import { useAuth } from '../../shared/contexts/AuthContext';
import { useIsMobile } from './components/ui/use-mobile';
import { toast } from 'sonner';
import { apiService } from '../../shared/services/api';
import { DASHBOARD_FEATURES } from './dashboardFeatures';
import {
  clearCampaignLeadSelection,
  persistCampaignLeadSelection,
  readCampaignLeadSelection,
} from '../../shared/utils/campaignLeadSelection';
import './dashboard.css';

const WORKSPACE_STORAGE_KEY = 'evecta.dashboardWorkspace';
const ADMIN_WORKSPACE_VIEWS = new Set([
  'admin-ai-usage',
  'admin-credits',
  'admin-gemini-purchases',
  'admin-users',
  'admin-mailboxes',
]);

function readStoredWorkspaceMode(): DashboardWorkspaceMode {
  try {
    const raw = localStorage.getItem(WORKSPACE_STORAGE_KEY);
    if (raw === 'admin' || raw === 'user') return raw;
  } catch {
    /* ignore */
  }
  return 'admin';
}

function persistWorkspaceMode(mode: DashboardWorkspaceMode) {
  try {
    localStorage.setItem(WORKSPACE_STORAGE_KEY, mode);
  } catch {
    /* ignore */
  }
}

// Map URL paths to view names
const pathToViewMap: Record<string, 'generate' | 'leads' | 'lead-log' | 'campaigns' | 
  'campaign-creation' | 'outreach' | 'sequence-creation' | 
  'sequence-builder' | 'lead-outreach' | 
  'templates' | 'users' | 'admin' | 'settings' | 
  'campaign-detail' | 'campaign-preview' | 'profile' | 'inbox' | 'email-accounts' | 'email-account-setup-loading' |   'google-consent' | 'imap-consent' | 'settings-profile' | 'settings-billing' | 'settings-usage' | 'settings-lead-log' | 'admin-ai-usage' | 'admin-credits' | 'admin-gemini-purchases' | 'admin-users' | 'admin-mailboxes'> = {
  '/dashboard': 'generate',
  '/dashboard/generate': 'generate',
  '/dashboard/leads': 'leads',
  '/dashboard/lead-log': 'lead-log',
  '/dashboard/campaigns': 'campaigns',
  '/dashboard/campaign-creation': 'campaign-creation',
  '/dashboard/templates': 'templates',
  '/dashboard/inbox': 'inbox',
  '/dashboard/profile': 'profile',
  /** Legacy URL — redirects to Settings → Billing (pricing). */
  '/dashboard/billing': 'settings-billing',
  '/dashboard/settings': 'settings-profile',
  '/dashboard/settings/profile': 'settings-profile',
  '/dashboard/settings/billing': 'settings-billing',
  '/dashboard/settings/usage': 'settings-usage',
  '/dashboard/settings/search-history': 'settings-lead-log',
  '/dashboard/admin/ai-usage': 'admin-ai-usage',
  '/dashboard/admin/credits': 'admin-credits',
  '/dashboard/admin/gemini-purchases': 'admin-gemini-purchases',
  '/dashboard/admin/users': 'admin-users',
  '/dashboard/admin/mailboxes': 'admin-mailboxes',
  '/dashboard/email-accounts': 'email-accounts',
  '/dashboard/email-account-setup-loading': 'email-account-setup-loading',
  '/dashboard/google-consent': 'google-consent',
  '/dashboard/imap-consent': 'imap-consent',
};

// Map view names to URL paths
const viewToPathMap: Record<string, string> = {
  'generate': '/dashboard/generate',
  'leads': '/dashboard/leads',
  'lead-log': '/dashboard/lead-log',
  'campaigns': '/dashboard/campaigns',
  'campaign-creation': '/dashboard/campaign-creation',
  'templates': '/dashboard/templates',
  'inbox': '/dashboard/inbox',
  'profile': '/dashboard/profile',
  'email-accounts': '/dashboard/email-accounts',
  'email-account-setup-loading': '/dashboard/email-account-setup-loading',
  'google-consent': '/dashboard/google-consent',
  'imap-consent': '/dashboard/imap-consent',
  'settings-profile': '/dashboard/settings/profile',
  'settings-billing': '/dashboard/settings/billing',
  'settings-usage': '/dashboard/settings/usage',
  'settings-lead-log': '/dashboard/settings/search-history',
  'admin-ai-usage': '/dashboard/admin/ai-usage',
  'admin-credits': '/dashboard/admin/credits',
  'admin-gemini-purchases': '/dashboard/admin/gemini-purchases',
  'admin-users': '/dashboard/admin/users',
  'admin-mailboxes': '/dashboard/admin/mailboxes',
};

export default function Dashboard() {
  const { user: authUser, loading: authLoading, logout } = useAuth();
  const isMobile = useIsMobile();
  const location = useLocation();
  const navigate = useNavigate();
  
  // Check waitlist status on mount (only once, after auth is ready)
  useEffect(() => {
    // TEMPORARY: Check URL parameter to force waitlist page for testing
    const urlParams = new URLSearchParams(window.location.search);
    const forceWaitlist = urlParams.get('forceWaitlist') === 'true';
    
    if (forceWaitlist) {
      navigate('/waitlist', { replace: true });
      return;
    }
    
    // Don't check waitlist if auth is still loading or we don't have a user yet
    // This prevents the check from running before auth is ready
    if (authLoading || !authUser) {
      return;
    }
    
    let isMounted = true;
    let hasChecked = false;
    
    const checkWaitlistStatus = async () => {
      // Prevent multiple checks
      if (hasChecked) {
        return;
      }
      hasChecked = true;
      
      try {
        const response = await apiService.checkWaitlistStatus();
        // Only navigate if component is still mounted and user should be waitlisted
        if (isMounted && response.data && (response.data.is_on_waitlist || response.data.user_limit_reached)) {
          navigate('/waitlist', { replace: true });
        }
      } catch (error) {
        console.error('Error checking waitlist status:', error);
        // If error (including 401), allow access (fail open)
        // Don't let waitlist check failure block dashboard access
      }
    };
    
    // Small delay to ensure auth is fully settled
    const timeoutId = setTimeout(() => {
      checkWaitlistStatus();
    }, 100);
    
    return () => {
      isMounted = false;
      clearTimeout(timeoutId);
    };
  }, [authUser, authLoading, navigate]); // Run when authUser becomes available and loading is complete
  
  // Determine initial view from URL
  type ViewType = 'generate' | 'leads' | 'lead-log' | 'campaigns' | 
    'campaign-creation' | 'outreach' | 'sequence-creation' |
    'sequence-builder' | 'lead-outreach' | 
    'templates' | 'users' | 'admin' | 'settings' | 
    'campaign-detail' | 'campaign-preview' | 'profile' | 'inbox' | 'email-accounts' | 'email-account-setup-loading' | 'google-consent' | 'imap-consent' | 'settings-profile' | 'settings-billing' | 'settings-usage' | 'settings-lead-log' | 'admin-ai-usage' | 'admin-credits' | 'admin-gemini-purchases' | 'admin-users' | 'admin-mailboxes';
  
  // Extract campaign ID from URL path
  const extractCampaignId = (path: string): string | undefined => {
    const match = path.match(/\/campaigns\/([^\/]+)/);
    return match ? match[1] : undefined;
  };
  
  // Check if a path is a valid dashboard route
  const isValidDashboardRoute = (path: string): boolean => {
    // Check if it's a known path
    if (pathToViewMap[path]) {
      return true;
    }
    if (path === '/dashboard/settings/' || path.replace(/\/$/, '') === '/dashboard/settings') {
      return true;
    }
    
    // Check for /dashboard/campaigns/:id/edit
    if (path.match(/\/dashboard\/campaigns\/[^\/]+\/edit/)) {
      return true;
    }
    
    // Check if it's a campaign detail route (e.g., /dashboard/campaigns/:id)
    const campaignId = extractCampaignId(path);
    if (campaignId) {
      return true;
    }
    
    return false;
  };
  
  const getInitialView = (): ViewType => {
    const path = location.pathname;
    
    // Invalid routes are redirected to /404 in useEffect
    if (!isValidDashboardRoute(path)) {
      return 'generate'; // Placeholder - useEffect will redirect to full-page 404
    }
    
    // Handle /dashboard/campaigns/:id/edit (edit draft)
    if (path.match(/\/dashboard\/campaigns\/[^\/]+\/edit/)) {
      return 'campaign-creation';
    }
    
    // Handle campaign detail routes
    const campaignId = extractCampaignId(path);
    if (campaignId) {
      if (path.includes('/preview')) {
        return 'campaign-preview';
      }
      return 'campaign-detail';
    }
    
    // Map path to view
    const view = pathToViewMap[path];
    if (view) {
      return view;
    }
    return 'generate';
  };
  
  const [currentView, setCurrentView] = useState<ViewType>(getInitialView());
  
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [leadLogDetailView, setLeadLogDetailView] = useState(false);
  const [leadLogSearchQuery, setLeadLogSearchQuery] = useState('');
  const leadGenerationRef = useRef<LeadGenerationRef>(null);
  const leadDatabaseRef = useRef<LeadDatabaseRef>(null);
  const [pendingViewChange, setPendingViewChange] = useState<ViewType | null>(null);
  const [selectedCampaignId, setSelectedCampaignId] = useState<string | undefined>(extractCampaignId(location.pathname));
  // Store editCampaignId in state to persist across renders and trigger re-renders
  const [activeEditCampaignId, setActiveEditCampaignId] = useState<string | undefined>(undefined);
  // Store preselectedLeadIds in state to persist across renders and trigger re-renders
  const [activePreselectedLeadIds, setActivePreselectedLeadIds] = useState<string[] | undefined>(undefined);
  
  // Profile settings modal state
  const [showProfileSettings, setShowProfileSettings] = useState(false);
  const [isCheckingCompany, setIsCheckingCompany] = useState(true);
  
  // Sync view with URL on mount and when location changes
  useEffect(() => {
    const path = location.pathname;
    
    // Redirect /dashboard to /dashboard/generate
    if (path === '/dashboard') {
      navigate('/dashboard/generate', { replace: true });
      return;
    }

    // Legacy billing URL — only Plan & usage under Settings
    if (path.replace(/\/$/, '') === '/dashboard/billing') {
      navigate('/dashboard/settings/billing', { replace: true });
      return;
    }

    const settingsBare = path.replace(/\/$/, '') === '/dashboard/settings';
    if (settingsBare) {
      navigate('/dashboard/settings/profile', { replace: true });
      return;
    }

    if (
      path.replace(/\/$/, '') === '/dashboard/templates' &&
      !DASHBOARD_FEATURES.showEmailTemplatesSection
    ) {
      navigate('/dashboard/campaigns', { replace: true });
      return;
    }
    
    // Handle /dashboard/campaigns/:id/edit (edit draft campaign) - must check before general campaign routes
    const editMatch = path.match(/\/dashboard\/campaigns\/([^\/]+)\/edit/);
    if (editMatch) {
      const id = editMatch[1];
      setSelectedCampaignId(id);
      setActiveEditCampaignId(id);
      setCurrentView('campaign-creation');
      sessionStorage.setItem('editCampaignId', id);
      return;
    }
    
    // Handle campaign detail routes
    const campaignId = extractCampaignId(path);
    if (campaignId) {
      setSelectedCampaignId(campaignId);
      if (path.includes('/preview')) {
        setCurrentView('campaign-preview');
      } else {
        setCurrentView('campaign-detail');
      }
      return;
    }
    
    // Check if it's a valid route - redirect to full-page 404 for invalid paths
    if (!isValidDashboardRoute(path)) {
      navigate('/404', { replace: true });
      return;
    }
    
    // Map path to view
    const viewFromPath = pathToViewMap[path] || 'generate';
    setCurrentView(viewFromPath);
  }, [location.pathname, navigate]);

  // Don't reset chat on every navigate to /dashboard/generate - that would clear context when
  // user returns while processing or clicks "View" on the completed banner. Reset only happens
  // when user explicitly starts a new search (LeadGeneration.resetToInitial).

  // Set initial sidebar state based on screen size
  useEffect(() => {
    setSidebarOpen(!isMobile);
  }, [isMobile]);

  // Add data attribute to body when sidebar is open on mobile
  useEffect(() => {
    if (isMobile) {
      if (sidebarOpen) {
        document.body.setAttribute('data-sidebar-open', 'true');
      } else {
        document.body.removeAttribute('data-sidebar-open');
      }
    }
    return () => {
      document.body.removeAttribute('data-sidebar-open');
    };
  }, [isMobile, sidebarOpen]);

  /** Used for fixed UI (Lead Gen credits banner, chat bar) — must exist before `renderContent` references it */
  /** Expanded sidebar width — keep in sync with Sidebar.tsx / SettingsSidebar.css */
  const SIDEBAR_EXPANDED_WIDTH_PX = 280;
  const SETTINGS_SIDEBAR_WIDTH_PX = SIDEBAR_EXPANDED_WIDTH_PX;

  const isSettingsView =
    currentView === 'settings-profile' ||
    currentView === 'settings-billing' ||
    currentView === 'settings-usage' ||
    currentView === 'settings-lead-log';

  const sidebarWidth = useMemo(
    () =>
      isSettingsView
        ? isMobile
        ? 0
          : SETTINGS_SIDEBAR_WIDTH_PX
        : sidebarOpen
          ? sidebarCollapsed && !isMobile
            ? 64
            : !isMobile
              ? SIDEBAR_EXPANDED_WIDTH_PX
              : 0
          : 0,
    [sidebarOpen, sidebarCollapsed, isMobile, isSettingsView]
  );

  // Read editCampaignId and preselectedLeadIds from sessionStorage when navigating to campaign-creation
  useEffect(() => {
    if (currentView === 'campaign-creation') {
      // Check URL params first for campaign_id (from OAuth redirect)
      const urlParams = new URLSearchParams(location.search);
      const campaignIdFromURL = urlParams.get('campaign_id');
      const gmailConnected = urlParams.get('gmail_connected');
      const imapConnected = urlParams.get('imap_connected');
      const gmailError = urlParams.get('gmail_error');
      
      const hasOAuthCallback = gmailConnected === 'true' || imapConnected === 'true' || gmailError === 'true';
      
      // Priority: URL param > sessionStorage, but NEVER override an explicit
      // in-memory activeEditCampaignId that was just set via handleViewChange.
      const editCampaignIdFromStorage = sessionStorage.getItem('editCampaignId');
      const campaignIdFromStorageOrUrl = campaignIdFromURL || editCampaignIdFromStorage;
      const campaignIdToUse = activeEditCampaignId || campaignIdFromStorageOrUrl;
      
      // Read preselected lead IDs from sessionStorage FIRST (before clearing other storage)
      // Supports Lead Gen / Lead Log / Lead DB via shared helper keys
      // BUT: When EDITING a campaign (campaignIdToUse set), NEVER use sessionStorage - leads come from backend
      let hasPreselectedLeads = false;
      if (!activePreselectedLeadIds && !campaignIdToUse) {
        const parsedIds = readCampaignLeadSelection();
        if (parsedIds && parsedIds.length > 0) {
          console.log(`[DEBUG] Dashboard: Setting activePreselectedLeadIds from sessionStorage: ${parsedIds.length} leads`, parsedIds);
          setActivePreselectedLeadIds(parsedIds);
          hasPreselectedLeads = true;
        } else {
          console.log('[DEBUG] Dashboard: No preselected lead ids in sessionStorage');
          setActivePreselectedLeadIds(undefined);
        }
      } else {
        console.log(`[DEBUG] Dashboard: activePreselectedLeadIds already set (${activePreselectedLeadIds?.length ?? 0} leads), preserving it`);
        hasPreselectedLeads = !!(activePreselectedLeadIds && activePreselectedLeadIds.length > 0);
      }
      
      if (campaignIdToUse) {
        // Editing a campaign - load data from backend, never from sessionStorage
        if (activePreselectedLeadIds) {
          setActivePreselectedLeadIds(undefined);
        }
        // Only update state if it's not already set to this value
        if (activeEditCampaignId !== campaignIdToUse) {
          setActiveEditCampaignId(campaignIdToUse);
        }
      } else {
        setActiveEditCampaignId(undefined);
        // If no campaign ID and no OAuth callback, clear leftover sessionStorage
        // BUT: Don't clear lead selection if we just read it (hasPreselectedLeads)
        if (!hasOAuthCallback && !hasPreselectedLeads) {
          sessionStorage.removeItem('editCampaignId');
          sessionStorage.removeItem('campaignEmailAccountStep');
          sessionStorage.removeItem('campaignEmailAccountChoice');
          sessionStorage.removeItem('openExistingEmailsTab');
          sessionStorage.removeItem('cameFromCampaign');
          clearCampaignLeadSelection();
          sessionStorage.removeItem('showImapForm');
          sessionStorage.removeItem('emailSetupGoToStep5');
          sessionStorage.removeItem('emailSetupCampaignId');
          // Clear any campaign-specific sessionStorage keys
          Object.keys(sessionStorage).forEach(key => {
            if (key.startsWith('campaignEmailAccountStep_') || 
                key.startsWith('campaignEmailAccountChoice_') ||
                key.startsWith('spamCheckContentHash_') ||
                key.startsWith('spamCheckPassed_') ||
                key.startsWith('spamCheckScore_')) {
              sessionStorage.removeItem(key);
            }
          });
        }
      }
    } else {
      // Clear the state when leaving campaign-creation view
      setActiveEditCampaignId(undefined);
      // Only clear preselectedLeadIds if we're actually leaving (not just re-rendering)
      // This prevents clearing it prematurely
      if ((currentView as ViewType) !== 'campaign-creation') {
        setActivePreselectedLeadIds(undefined);
      }
    }
  }, [currentView, location.search]); // Add location.search to re-run on OAuth callbacks

  // Listen for logout events from other tabs
  useEffect(() => {
    const handleStorageChange = (e: StorageEvent) => {
      if (e.key === 'user_logged_out') {
        // User logged out in another tab, redirect to auth
        window.location.href = '/auth';
      }
    };

    const handleLogoutCheck = () => {
      const logoutTime = localStorage.getItem('user_logged_out');
      if (logoutTime) {
        // Check if logout happened recently (within last 5 seconds)
        const logoutTimestamp = parseInt(logoutTime, 10);
        const now = Date.now();
        if (now - logoutTimestamp < 5000) {
          window.location.href = '/auth';
        }
      }
    };

    // Listen for storage events (cross-tab communication)
    window.addEventListener('storage', handleStorageChange);
    
    // Check on mount and periodically
    handleLogoutCheck();
    const interval = setInterval(handleLogoutCheck, 1000);

    return () => {
      window.removeEventListener('storage', handleStorageChange);
      clearInterval(interval);
    };
  }, []);

  // Handle view change with unsaved leads check
  const handleViewChange = (newView: typeof currentView, bypassCheck: boolean = false, campaignId?: string) => {
    if (newView === 'templates' && !DASHBOARD_FEATURES.showEmailTemplatesSection) {
      navigate('/dashboard/campaigns', { replace: true });
      setCurrentView('campaigns');
      return;
    }

    // Handle campaign detail/preview views
    if (newView === 'campaign-detail' && campaignId) {
      setSelectedCampaignId(campaignId);
      navigate(`/dashboard/campaigns/${campaignId}`);
      setCurrentView('campaign-detail');
      return;
    }
    
    if (newView === 'campaign-preview' && campaignId) {
      setSelectedCampaignId(campaignId);
      navigate(`/dashboard/campaigns/${campaignId}/preview`);
      setCurrentView('campaign-preview');
      return;
    }

    // Ensure a truly fresh draft when starting a BRAND NEW campaign (no campaignId provided).
    // This prevents accidentally reusing an older draft campaign when coming from
    // AI Lead Gen, Lead Database, or Lead Log.
    if (newView === 'campaign-creation' && !campaignId) {
      setActiveEditCampaignId(undefined);
      sessionStorage.removeItem('editCampaignId');
    }

    if (newView === 'campaign-creation' && campaignId) {
      setActiveEditCampaignId(campaignId);
      sessionStorage.setItem('editCampaignId', campaignId);
      navigate(`/dashboard/campaigns/${campaignId}/edit`);
      setCurrentView('campaign-creation');
      return;
    }
    
    // If switching to generate view (AI Lead Gen)
    if (newView === 'generate') {
      // If a lead generation run is currently in progress and we're already on AI Lead Gen,
      // ignore repeated clicks so the user can't reset to a fresh page/start a new chat
      // until the current generation is finished.
      if (leadGenStatus.isGenerating && currentView === 'generate') {
        return;
      }

      const path = viewToPathMap[newView] || '/dashboard/generate';
      navigate(path);
      setCurrentView(newView);
      // Only reset when already on generate (user clicked "AI Lead Gen" again for new chat)
      if (currentView === 'generate' && leadGenerationRef.current) {
        leadGenerationRef.current.resetToInitial();
      }
      return;
    }

    // If bypassCheck is true, skip the unsaved leads check (used after saving)
    if (bypassCheck) {
      const path = viewToPathMap[newView] || '/dashboard';
      navigate(path);
      setCurrentView(newView);
      return;
    }

    // Allow navigation even when processing - background polling will continue
    // If currently on generate view, check for unsaved leads
    if (currentView === 'generate' && leadGenerationRef.current?.hasUnsavedLeads()) {
      // Store the pending navigation and show the save dialog
      setPendingViewChange(newView);
      leadGenerationRef.current.showSaveDialog();
    } else {
      // No unsaved leads or not on generate view, proceed with navigation
      const path = viewToPathMap[newView] || '/dashboard';
      navigate(path);
      setCurrentView(newView);
    }
  };

  /**
   * Single entry for Create Campaign from Lead Gen / Lead Database / Lead Log.
   * Always persists Lead Database UUIDs before navigating so Step 2 never opens empty.
   */
  const beginCreateCampaignWithLeads = (leadIds?: string[]) => {
    // Explicit lead selection = brand-new campaign. Never resume a leftover draft —
    // that jumps the wizard to Step 3+ and drops the Lead Database selection.
    sessionStorage.removeItem('resumeCampaignId');
    sessionStorage.removeItem('editCampaignId');
    setActiveEditCampaignId(undefined);

    sessionStorage.removeItem('campaignEmailAccountStep');
    sessionStorage.removeItem('campaignEmailAccountChoice');
    sessionStorage.removeItem('openExistingEmailsTab');
    sessionStorage.removeItem('cameFromCampaign');
    sessionStorage.removeItem('showImapForm');
    sessionStorage.removeItem('emailSetupGoToStep5');
    sessionStorage.removeItem('emailSetupCampaignId');
    Object.keys(sessionStorage).forEach((key) => {
      if (
        key.startsWith('campaignEmailAccountStep_') ||
        key.startsWith('campaignStep3Completed_') ||
        key.startsWith('spamCheckContentHash_') ||
        key.startsWith('spamCheckPassed_') ||
        key.startsWith('spamCheckScore_')
      ) {
        sessionStorage.removeItem(key);
      }
    });

    if (leadIds && leadIds.length > 0) {
      const uniqueIds = persistCampaignLeadSelection(leadIds);
      console.log(`[DEBUG] Dashboard: beginCreateCampaignWithLeads (${uniqueIds.length} leads)`);
      setActivePreselectedLeadIds(uniqueIds);
    } else {
      clearCampaignLeadSelection();
      setActivePreselectedLeadIds(undefined);
    }

    handleViewChange('campaign-creation', true);
  };
  
  // Get user info - extract first name only
  const getFirstName = (fullName: string | undefined): string => {
    if (!fullName) return 'User';
    return fullName.split(' ')[0] || fullName;
  };
  const currentUserName = getFirstName(authUser?.username);
  const currentUserEmail = authUser?.email || 'user@example.com';
  const currentUserRole: 'admin' | 'manager' | 'user' =
    authUser?.is_admin || authUser?.is_superuser || authUser?.role === 'admin'
      ? 'admin'
      : 'user';

  const [workspaceMode, setWorkspaceMode] = useState<DashboardWorkspaceMode>(() =>
    readStoredWorkspaceMode(),
  );

  useEffect(() => {
    if (currentUserRole !== 'admin') {
      setWorkspaceMode('user');
      return;
    }
    const next: DashboardWorkspaceMode = ADMIN_WORKSPACE_VIEWS.has(currentView)
      ? 'admin'
      : 'user';
    setWorkspaceMode(next);
    persistWorkspaceMode(next);
  }, [currentView, currentUserRole]);

  const handleSwitchWorkspace = (mode: DashboardWorkspaceMode) => {
    setWorkspaceMode(mode);
    persistWorkspaceMode(mode);
    if (mode === 'admin') {
      navigate('/dashboard/admin/ai-usage');
      setCurrentView('admin-ai-usage');
      return;
    }
    navigate('/dashboard/generate');
    setCurrentView('generate');
  };

  useEffect(() => {
    if (
      (currentView === 'admin-ai-usage' ||
        currentView === 'admin-credits' ||
        currentView === 'admin-gemini-purchases' ||
        currentView === 'admin-users' ||
        currentView === 'admin-mailboxes') &&
      currentUserRole !== 'admin'
    ) {
      navigate('/dashboard/generate', { replace: true });
      setCurrentView('generate');
    }
  }, [currentView, currentUserRole, navigate]);

  // State for sidebar counts
  const [leadCount, setLeadCount] = useState(0);
  const [campaignCount, setCampaignCount] = useState(0);
  const [inboxUnreadCount, setInboxUnreadCount] = useState(0);

  // Fetch lead count directly from API
  const fetchLeadCount = async () => {
    try {
      const response = await apiService.getLeads();
      if (response.data && Array.isArray(response.data)) {
        setLeadCount(response.data.length);
      }
    } catch (error) {
      console.error('Failed to fetch lead count:', error);
    }
  };

  // Fetch lead count on mount and periodically
  useEffect(() => {
    // Fetch immediately on mount
    fetchLeadCount();

    // Refresh lead count periodically to keep it up to date (every 3 seconds)
    const interval = setInterval(fetchLeadCount, 3000);

    return () => clearInterval(interval);
  }, []); // Run only on mount, not dependent on currentView

  // State for lead generation banner
  const [leadGenStatus, setLeadGenStatus] = useState<{
    isGenerating: boolean;
    isComplete: boolean;
    leadCount: number;
    logId: string | null;
  }>({
    isGenerating: false,
    isComplete: false,
    leadCount: 0,
    logId: null
  });
  
  // Track if user has dismissed the banner
  const [bannerDismissed, setBannerDismissed] = useState(false);
  // "Processing your leads" shows 5s after lead search actually starts (not on every chat message)
  const [showProcessingBanner, setShowProcessingBanner] = useState(false);
  const processingBannerTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const processingBannerDismissRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [profileHeaderDropdownOpen, setProfileHeaderDropdownOpen] = useState(false);
  const profileHeaderDropdownRef = useRef<HTMLDivElement>(null);

  // Close profile header dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (profileHeaderDropdownRef.current && !profileHeaderDropdownRef.current.contains(e.target as Node)) {
        setProfileHeaderDropdownOpen(false);
      }
    };
    if (profileHeaderDropdownOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [profileHeaderDropdownOpen]);

  // When user clicks "View" on completed banner, we pass this so LeadGeneration shows that log's results
  const [pendingViewResultsLogId, setPendingViewResultsLogId] = useState<string | null>(null);
  
  // Track when generation started to ensure minimum display duration
  const generationStartTimeRef = useRef<number | null>(null);
  // Mixkit "Software interface start" (sfx 2574) — https://mixkit.co/free-sound-effects/notification/
  const LEAD_GEN_SFX_URL = `${import.meta.env.BASE_URL}sounds/mixkit-software-interface-start.mp3`;
  const lastPlayedLeadReadyLogIdRef = useRef<string | null>(null);
  const prevShowProcessingBannerRef = useRef(false);

  const playLeadGenNotificationSound = () => {
    try {
      const audio = new Audio(LEAD_GEN_SFX_URL);
      audio.volume = 0.9;
      void audio.play().catch(() => undefined);
    } catch {
      // Sound must never block lead flow.
    }
  };

  // Debug: Log state changes
  useEffect(() => {
    console.log('[Banner] State changed:', {
      isGenerating: leadGenStatus.isGenerating,
      isComplete: leadGenStatus.isComplete,
      bannerDismissed,
      logId: leadGenStatus.logId,
      shouldShow: (leadGenStatus.isGenerating || leadGenStatus.isComplete) && !bannerDismissed
    });
  }, [leadGenStatus.isGenerating, leadGenStatus.isComplete, bannerDismissed, leadGenStatus.logId]);
  // Track if user navigated away from generate page while generation was in progress
  const [navigatedAwayDuringGeneration, setNavigatedAwayDuringGeneration] = useState(false);

  // Note: Banner now shows on all pages including generate page
  // No need to clear banner when navigating to generate page

  // Check for active polling on mount and periodically
  useEffect(() => {
    // Listen for a custom event that fires when sessionStorage is updated
    const handleLocalStorageUpdate = (event: CustomEvent) => {
      const { logId } = event.detail;
      if (logId) {
        console.log('[Banner] Detected logId update event:', logId);
        // Don't reset dismissed flag - respect user's choice
        setLeadGenStatus(prev => {
          if (prev.logId !== logId || !prev.isGenerating) {
            return {
              isGenerating: true,
              isComplete: false,
              leadCount: 0,
              logId: logId
            };
          }
          return prev;
        });
      }
    };
    
    window.addEventListener('leadGenLogIdSaved', handleLocalStorageUpdate as EventListener);
    
    const checkPollingStatus = () => {
      const isPolling = !!window.__leadGenPoller;
      const pollingLogId = window.__leadGenPollingLogId || null;
      
      // Also check sessionStorage for currentLogId to detect generation in progress
      let sessionStorageLogId = null;
      let hasLeads = false;
      try {
        const savedState = sessionStorage.getItem('leadGenerationChatState');
        if (savedState) {
          const parsed = JSON.parse(savedState);
          const storageBelongsToCurrentUser =
            !authUser?.id || !parsed.userId || parsed.userId === authUser.id;
          if (storageBelongsToCurrentUser) {
            sessionStorageLogId = parsed.currentLogId || null;
            
            // If we have leads, generation is complete
            if (parsed.currentLeads?.length > 0 && parsed.currentLogId && !parsed.discarded) {
              hasLeads = true;
              // Don't reset dismissed flag - respect user's choice
              setLeadGenStatus({
                isGenerating: false,
                isComplete: true,
                leadCount: parsed.currentLeads.length,
                logId: parsed.currentLogId
              });
              return;
            }
          }
        }
      } catch (e) {
        // Ignore parse errors
      }
      
      // Only show "Processing your leads" when polling is actually active (real lead generation in progress).
      // Do NOT set isGenerating from sessionStorage alone: stale currentLogId (e.g. from normal chat or
      // a previous run) would otherwise show the banner during normal chat.
      if (isPolling && pollingLogId) {
        // Still generating - ensure isGenerating is set to true
        // Don't reset dismissed flag - respect user's choice
        setLeadGenStatus(prev => {
          // Always update if logId is different or if not currently generating
          if (prev.logId !== pollingLogId || !prev.isGenerating) {
            console.log('[Banner] Setting isGenerating=true from polling detection:', pollingLogId);
            // Record start time if not already recorded
            if (!generationStartTimeRef.current) {
              generationStartTimeRef.current = Date.now();
            }
            return {
              isGenerating: true,
              isComplete: false,
              leadCount: 0,
              logId: pollingLogId
            };
          }
          return prev;
        });
      }
      // Note: We don't clear the status here - let it persist until leads are ready or user dismisses
    };

    // Check immediately on mount
    checkPollingStatus();
    // Then check every second
    const interval = setInterval(checkPollingStatus, 1000);
    
    return () => {
      clearInterval(interval);
      window.removeEventListener('leadGenLogIdSaved', handleLocalStorageUpdate as EventListener);
    };
  }, []); // Empty dependency array - check status continuously

  // Global listener for lead generation completion (works on any page)
  useEffect(() => {
    const clearProcessingBannerTimers = () => {
      setShowProcessingBanner(false);
      if (processingBannerTimeoutRef.current) {
        clearTimeout(processingBannerTimeoutRef.current);
        processingBannerTimeoutRef.current = null;
      }
      if (processingBannerDismissRef.current) {
        clearTimeout(processingBannerDismissRef.current);
        processingBannerDismissRef.current = null;
      }
    };

    const scheduleProcessingBanner = () => {
      setBannerDismissed(false);
      clearProcessingBannerTimers();
      processingBannerTimeoutRef.current = setTimeout(() => {
        setShowProcessingBanner(true);
        processingBannerTimeoutRef.current = null;
        if (processingBannerDismissRef.current) clearTimeout(processingBannerDismissRef.current);
        processingBannerDismissRef.current = setTimeout(() => {
          setShowProcessingBanner(false);
          processingBannerDismissRef.current = null;
        }, 10000);
      }, 5000);
    };

    const handleLeadGenReady = (event: CustomEvent) => {
      const { logId, leads } = event.detail;
      const leadCount = leads?.length || 0;
      
      console.log('[Banner] leadGenLeadsReady event received:', { logId, leadCount });
      
      if (leadCount > 0) {
        clearProcessingBannerTimers();
        // Reset dismissed flag when leads are ready so completed banner can show
        // (User may have dismissed processing banner, but completed should still show)
        setBannerDismissed(false);
        
        // Get current state to check if we're already generating
        setLeadGenStatus(prev => {
          // If not already generating, set it to generating first and schedule completion
          if (!prev.isGenerating || prev.logId !== logId) {
            console.log('[Banner] Leads ready early - setting isGenerating=true first, then will show completed after 2s');
            // Record start time if not already recorded
            if (!generationStartTimeRef.current) {
              generationStartTimeRef.current = Date.now();
            }
            
            // Schedule completion after minimum duration
            const minProcessingDuration = 2000;
            setTimeout(() => {
              setBannerDismissed(false); // Reset dismissed flag so completed banner can show
              setLeadGenStatus({
                isGenerating: false,
                isComplete: true,
                leadCount: leadCount,
                logId: logId
              });
            }, minProcessingDuration);
            
            // Return generating state immediately
            return {
              isGenerating: true,
              isComplete: false,
              leadCount: 0,
              logId: logId
            };
          }
          
          // Already generating, calculate remaining time
          const generationDuration = generationStartTimeRef.current 
            ? Date.now() - generationStartTimeRef.current 
            : 0;
          
          // Minimum display duration for processing banner: 2 seconds
          const minProcessingDuration = 2000;
          const remainingTime = Math.max(0, minProcessingDuration - generationDuration);
          
          if (remainingTime > 0) {
            console.log(`[Banner] Leads ready but showing processing banner for ${remainingTime}ms more`);
            // Schedule completion after remaining time
            setTimeout(() => {
              setBannerDismissed(false); // Reset dismissed flag so completed banner can show
              setLeadGenStatus({
                isGenerating: false,
                isComplete: true,
                leadCount: leadCount,
                logId: logId
              });
            }, remainingTime);
            // Keep current generating state
            return prev;
          } else {
            // Already shown for minimum duration, show completed immediately
            console.log('[Banner] Minimum duration met, showing completed banner');
            setBannerDismissed(false); // Reset dismissed flag so completed banner can show
            return {
              isGenerating: false,
              isComplete: true,
              leadCount: leadCount,
              logId: logId
            };
          }
        });
      }
    };

    const handleLeadGenStart = (event: CustomEvent) => {
      const { logId, isTemporary } = event.detail;
      console.log('[Banner] leadGenStarted event received:', { logId, isTemporary });
      
      if (!logId) {
        console.warn('[Banner] leadGenStarted event received without logId');
        return;
      }
      
      let shouldScheduleBanner = false;

      // Set state immediately - use functional update to ensure we get the latest state
      setLeadGenStatus(prev => {
        // Update if this is a new generation (different logId) or not currently generating
        // Also update if we're replacing a temporary ID with the real one
        const isNewGeneration = prev.logId !== logId || !prev.isGenerating;
        const isReplacingTemp = prev.logId?.startsWith('temp-') && !isTemporary;
        
        if (isNewGeneration || isReplacingTemp) {
          console.log('[Banner] Setting isGenerating=true from event handler:', logId, isTemporary ? '(temporary)' : '(real)');
          
          // Only reset dismissed flag for truly NEW generations (not just replacing temp ID)
          if (isNewGeneration && !isReplacingTemp) {
            setBannerDismissed(false);
            setNavigatedAwayDuringGeneration(false);
            shouldScheduleBanner = true;
          }
          
          // Record when generation started (only on first event, not on temporary ID updates)
          if (!generationStartTimeRef.current || isTemporary) {
            generationStartTimeRef.current = Date.now();
          }
          
          return {
            isGenerating: true,
            isComplete: false,
            leadCount: 0,
            logId: logId
          };
        }
        return prev;
      });

      if (shouldScheduleBanner) {
        scheduleProcessingBanner();
      }
    };

    const handleLeadGenCancelled = () => {
      clearProcessingBannerTimers();
      setLeadGenStatus(prev => {
        if (!prev.isGenerating) return prev;
        return {
          isGenerating: false,
          isComplete: false,
          leadCount: 0,
          logId: null
        };
      });
    };

    window.addEventListener('leadGenLeadsReady', handleLeadGenReady as EventListener);
    window.addEventListener('leadGenStarted', handleLeadGenStart as EventListener);
    window.addEventListener('leadGenCancelled', handleLeadGenCancelled);
    
    return () => {
      window.removeEventListener('leadGenLeadsReady', handleLeadGenReady as EventListener);
      window.removeEventListener('leadGenStarted', handleLeadGenStart as EventListener);
      window.removeEventListener('leadGenCancelled', handleLeadGenCancelled);
      if (processingBannerTimeoutRef.current) clearTimeout(processingBannerTimeoutRef.current);
      if (processingBannerDismissRef.current) clearTimeout(processingBannerDismissRef.current);
    };
  }, []); // Remove bannerDismissed dependency to keep listeners stable

  // Clear processing banner when leads are ready
  useEffect(() => {
    if (leadGenStatus.isComplete) {
      setShowProcessingBanner(false);
      if (processingBannerDismissRef.current) {
        clearTimeout(processingBannerDismissRef.current);
        processingBannerDismissRef.current = null;
      }
    }
  }, [leadGenStatus.isComplete]);

  // Mixkit "Software interface start" when "Processing your leads" banner appears.
  useEffect(() => {
    const justOpened = showProcessingBanner && !prevShowProcessingBannerRef.current;
    if (justOpened) {
      playLeadGenNotificationSound();
    }
    prevShowProcessingBannerRef.current = showProcessingBanner;
  }, [showProcessingBanner]);

  // Same cue once when AI leads become ready.
  useEffect(() => {
    if (!leadGenStatus.isComplete || !leadGenStatus.logId) return;
    if (lastPlayedLeadReadyLogIdRef.current === leadGenStatus.logId) return;
    lastPlayedLeadReadyLogIdRef.current = leadGenStatus.logId;
    playLeadGenNotificationSound();
  }, [leadGenStatus.isComplete, leadGenStatus.logId]);

  // Track navigation away from generate page during generation
  useEffect(() => {
    // If generation is in progress and user navigates away from generate page
    if (leadGenStatus.isGenerating && currentView !== 'generate') {
      setNavigatedAwayDuringGeneration(true);
    }
    // If user navigates back to generate page, reset the flag
    if (currentView === 'generate') {
      setNavigatedAwayDuringGeneration(false);
    }
  }, [currentView, leadGenStatus.isGenerating]);

  // When user is on AI lead gen page and completed banner is showing, auto-hide after 5 seconds
  useEffect(() => {
    if (currentView !== 'generate' || !leadGenStatus.isComplete || bannerDismissed) {
      return;
    }
    const timer = setTimeout(() => {
      setBannerDismissed(true);
      setLeadGenStatus(prev => ({
        ...prev,
        isComplete: false,
        leadCount: 0,
        logId: null
      }));
    }, 5000);
    return () => clearTimeout(timer);
  }, [currentView, leadGenStatus.isComplete, bannerDismissed]);

  // Also refresh lead count when view changes to ensure accuracy
  useEffect(() => {
    fetchLeadCount();
  }, [currentView]);

  // Fetch campaign count
  useEffect(() => {
    const fetchCampaignCount = async () => {
      try {
        const response = await apiService.getCampaigns({
          page: 1,
          per_page: 1
        });
        if (response.data && response.data.total_items !== undefined) {
          setCampaignCount(response.data.total_items);
        }
      } catch (error) {
        console.error('Failed to fetch campaign count:', error);
      }
    };

    fetchCampaignCount();
    
    // Refresh campaign count periodically and when view changes to campaigns
    const interval = setInterval(fetchCampaignCount, 5000);
    
    return () => clearInterval(interval);
  }, [currentView]);

  // First-time login: show Profile Settings when user has no company (new users and OAuth signups)
  useEffect(() => {
    const checkCompanyProfile = async () => {
      if (!authUser) {
        setIsCheckingCompany(false);
        return;
      }

      try {
        const response = await apiService.getMyCompany();
        
        // If company exists, user has completed setup — don't show profile settings
        if (response.data) {
          setShowProfileSettings(false);
        } else if (response.error) {
          const errorMessage = response.error.toLowerCase();
          if (errorMessage.includes('404') || 
              errorMessage.includes('not found') ||
              errorMessage.includes('does not exist')) {
            // No company — first-time login: show Profile Settings form
            setShowProfileSettings(true);
          } else {
            console.error('Error checking company profile:', response.error);
            setShowProfileSettings(false);
          }
        } else {
          // No data — first-time user: show Profile Settings
          setShowProfileSettings(true);
        }
      } catch (error: any) {
        console.error('Error checking company profile:', error);
        setShowProfileSettings(false);
      } finally {
        setIsCheckingCompany(false);
      }
    };

    checkCompanyProfile();
  }, [authUser]);

  const renderContent = () => {
    // Safety: if URL is edit path, always show campaign-creation (fixes blank page when clicking draft)
    const editPathMatch = location.pathname.match(/\/dashboard\/campaigns\/([^\/]+)\/edit/);
    if (editPathMatch) {
      const editIdFromPath = editPathMatch[1];
      return (
        <ErrorBoundary>
          <CreateCampaign
            onToggleSidebar={() => setSidebarCollapsed(!sidebarCollapsed)}
            onBack={() => handleViewChange('campaigns', true)}
            onNext={(campaignId) => setSelectedCampaignId(campaignId)}
            onNavigateToGenerate={() => handleViewChange('generate', true)}
            editCampaignId={activeEditCampaignId || editIdFromPath}
            preselectedLeadIds={activePreselectedLeadIds}
          />
        </ErrorBoundary>
      );
    }

    switch (currentView) {
      case 'generate':
        return <LeadGeneration 
          key={authUser?.id ?? 'no-user'}
          ref={leadGenerationRef}
          layoutSidebarWidthPx={sidebarWidth}
          generatingLogId={leadGenStatus.isGenerating ? leadGenStatus.logId : null}
          isLeadGenInProgress={leadGenStatus.isGenerating && !leadGenStatus.isComplete}
          openWithLogId={pendingViewResultsLogId || (leadGenStatus.isComplete && leadGenStatus.logId ? leadGenStatus.logId : null)}
          onOpenWithLogIdLoaded={() => setPendingViewResultsLogId(null)}
          onDiscardLeads={() => {
            setPendingViewResultsLogId(null);
            setLeadGenStatus({ isGenerating: false, isComplete: false, leadCount: 0, logId: null });
          }}
          onToggleSidebar={() => setSidebarCollapsed(!sidebarCollapsed)}
          onNavigationAttempt={(proceed) => {
            // This callback is called after save/discard
            if (pendingViewChange) {
              const path = viewToPathMap[pendingViewChange] || '/dashboard';
              navigate(path);
              setCurrentView(pendingViewChange);
              setPendingViewChange(null);
              proceed();
            }
          }}
          onNavigateToLeads={() => handleViewChange('leads', true)}
          onNavigateToCreateCampaign={(leadIds) => beginCreateCampaignWithLeads(leadIds)}
        />;
      case 'leads':
        return <LeadDatabase 
          ref={leadDatabaseRef}
          onToggleSidebar={() => setSidebarCollapsed(!sidebarCollapsed)}
          onNavigateToGenerate={() => handleViewChange('generate')}
          onNavigateToCreateCampaign={(leadIds) => beginCreateCampaignWithLeads(leadIds)}
        />;
      case 'lead-log':
        return <LeadLog 
          searchQuery={leadLogSearchQuery}
          onSearchQueryChange={setLeadLogSearchQuery}
          onToggleSidebar={() => setSidebarCollapsed(!sidebarCollapsed)}
          onViewModeChange={(isDetailView) => setLeadLogDetailView(isDetailView)}
          onLeadsSaved={async () => {
            // Refresh LeadDatabase when leads are saved
            if (leadDatabaseRef.current) {
              await leadDatabaseRef.current.refreshLeads();
              // Update lead count after refresh
              const count = leadDatabaseRef.current.getLeadCount();
              setLeadCount(count);
            }
            // Don't show toast here - it will be shown when navigating to campaigns
          }}
          onNavigateToLeads={() => handleViewChange('leads', true)}
          onNavigateToCampaigns={() => {
            handleViewChange('campaigns', true);
          }}
          onNavigateToCreateCampaign={(leadIds) => beginCreateCampaignWithLeads(leadIds)}
        />;
      case 'settings-lead-log':
        return (
          <LeadLog
            searchQuery={leadLogSearchQuery}
            onSearchQueryChange={setLeadLogSearchQuery}
            onToggleSidebar={() => setSidebarCollapsed(!sidebarCollapsed)}
            onViewModeChange={(isDetailView) => setLeadLogDetailView(isDetailView)}
            onLeadsSaved={async () => {
              if (leadDatabaseRef.current) {
                await leadDatabaseRef.current.refreshLeads();
                const count = leadDatabaseRef.current.getLeadCount();
                setLeadCount(count);
              }
            }}
            onNavigateToLeads={() => handleViewChange('leads', true)}
            onNavigateToCampaigns={() => {
              handleViewChange('campaigns', true);
            }}
            onNavigateToCreateCampaign={(leadIds) => beginCreateCampaignWithLeads(leadIds)}
          />
        );
      case 'campaigns':
        return <Campaign 
          onToggleSidebar={() => setSidebarCollapsed(!sidebarCollapsed)}
          onViewChange={(view, campaignId) => {
            if (view === 'campaign-detail' && campaignId) {
              handleViewChange('campaign-detail', true, campaignId);
            } else if (view === 'campaign-preview' && campaignId) {
              handleViewChange('campaign-preview', true, campaignId);
            } else if (view === 'campaign-creation' && campaignId) {
              handleViewChange('campaign-creation', true, campaignId);
            }
          }}
          onNavigateToCreateCampaign={(campaignId) => {
            // If campaignId is provided, it's a draft resume
            if (campaignId) {
              handleViewChange('campaign-creation', true, campaignId);
            } else {
              // Otherwise, it's a new campaign - clear all previous campaign state
              sessionStorage.removeItem('editCampaignId');
              sessionStorage.removeItem('campaignEmailAccountStep');
              sessionStorage.removeItem('campaignEmailAccountChoice');
              sessionStorage.removeItem('openExistingEmailsTab');
              sessionStorage.removeItem('cameFromCampaign');
              sessionStorage.removeItem('preselectedLeadIds');
              sessionStorage.removeItem('showImapForm');
              sessionStorage.removeItem('emailSetupGoToStep5');
              sessionStorage.removeItem('emailSetupCampaignId');
              // Clear any campaign-specific sessionStorage keys
              Object.keys(sessionStorage).forEach(key => {
                if (key.startsWith('campaignEmailAccountStep_') || 
                    key.startsWith('spamCheckContentHash_') ||
                    key.startsWith('spamCheckPassed_') ||
                    key.startsWith('spamCheckScore_')) {
                  sessionStorage.removeItem(key);
                }
              });
              handleViewChange('campaign-creation');
            }
          }}
        />;
      case 'campaign-creation':
        // Use editCampaignId and preselectedLeadIds from refs (set by useEffect when view changes to campaign-creation)
        // This ensures the values persist across renders and are only read once from sessionStorage
        console.log('[DEBUG] Dashboard: Rendering CreateCampaign with', {
          activePreselectedLeadIds,
          activePreselectedLeadIdsLength: activePreselectedLeadIds?.length || 0,
          activeEditCampaignId
        });
        return (
          <ErrorBoundary>
            <CreateCampaign 
              onToggleSidebar={() => setSidebarCollapsed(!sidebarCollapsed)}
              onBack={() => handleViewChange('campaigns', true)}
              onNext={(campaignId) => {
                setSelectedCampaignId(campaignId);
                // Stay on create campaign page for now, will navigate in step 2
              }}
              onNavigateToGenerate={() => handleViewChange('generate', true)}
              editCampaignId={activeEditCampaignId} // Pass campaignId as editCampaignId when editing draft
              preselectedLeadIds={activePreselectedLeadIds} // Pass lead IDs when navigating from Lead Generation
            />
          </ErrorBoundary>
        );
      case 'campaign-detail':
        return <CampaignDetail 
          campaignId={selectedCampaignId}
          onToggleSidebar={() => setSidebarCollapsed(!sidebarCollapsed)}
          onBack={() => handleViewChange('campaigns', true)}
        />;
      case 'campaign-preview':
        return <PreviewCampaignDetail 
          campaignId={selectedCampaignId || ''}
          onBack={() => handleViewChange('campaigns', true)}
        />;
      case 'templates':
        return <Template 
          onToggleSidebar={() => setSidebarCollapsed(!sidebarCollapsed)}
        />;
      case 'inbox':
        return <Inbox 
          onToggleSidebar={() => setSidebarCollapsed(!sidebarCollapsed)}
          onUnreadCountChange={setInboxUnreadCount}
        />;
      case 'email-accounts':
        return <EmailAccounts 
          onToggleSidebar={() => setSidebarCollapsed(!sidebarCollapsed)}
        />;
      case 'email-account-setup-loading':
        return <EmailAccountSetupLoading />;
      case 'google-consent':
        return <GoogleConsentPage />;
      case 'imap-consent':
        return <IMAPConsentPage />;
      case 'profile':
        return <UserProfile 
          onToggleSidebar={() => setSidebarCollapsed(!sidebarCollapsed)}
        />;
      case 'settings-profile':
        return <UserProfile 
          onToggleSidebar={() => setSidebarCollapsed(!sidebarCollapsed)}
        />;
      case 'settings-billing':
        return <BillingPage />;
      case 'settings-usage':
        return <UsagePage />;
      case 'admin-ai-usage':
        if (currentUserRole !== 'admin') {
          return (
            <div className="w-full h-full overflow-y-auto bg-white">
              <div className="max-w-3xl mx-auto px-6 py-8">
                <h1 className="text-2xl font-bold text-gray-900 mb-2">Access denied</h1>
                <p className="text-gray-600">Admin credentials are required to view AI usage.</p>
              </div>
            </div>
          );
        }
        return <AiUsageAdminPage />;
      case 'admin-credits':
        if (currentUserRole !== 'admin') {
          return (
            <div className="w-full h-full overflow-y-auto bg-white">
              <div className="max-w-3xl mx-auto px-6 py-8">
                <h1 className="text-2xl font-bold text-gray-900 mb-2">Access denied</h1>
                <p className="text-gray-600">Admin credentials are required to manage credits.</p>
              </div>
            </div>
          );
        }
        return <AdminCreditsPage />;
      case 'admin-gemini-purchases':
        if (currentUserRole !== 'admin') {
          return (
            <div className="w-full h-full overflow-y-auto bg-white">
              <div className="max-w-3xl mx-auto px-6 py-8">
                <h1 className="text-2xl font-bold text-gray-900 mb-2">Access denied</h1>
                <p className="text-gray-600">Admin credentials are required to view Gemini purchases.</p>
              </div>
            </div>
          );
        }
        return <GeminiPurchasesAdminPage />;
      case 'admin-users':
        if (currentUserRole !== 'admin') {
          return (
            <div className="w-full h-full overflow-y-auto bg-white">
              <div className="max-w-3xl mx-auto px-6 py-8">
                <h1 className="text-2xl font-bold text-gray-900 mb-2">Access denied</h1>
                <p className="text-gray-600">Admin credentials are required to manage users.</p>
              </div>
            </div>
          );
        }
        return <AdminUsersPage />;
      case 'admin-mailboxes':
        if (currentUserRole !== 'admin') {
          return (
            <div className="w-full h-full overflow-y-auto bg-white">
              <div className="max-w-3xl mx-auto px-6 py-8">
                <h1 className="text-2xl font-bold text-gray-900 mb-2">Access denied</h1>
                <p className="text-gray-600">Admin credentials are required to manage mailboxes.</p>
              </div>
            </div>
          );
        }
        return <AdminMailboxesPage />;
      default:
        return (
          <div className="w-full h-full overflow-y-auto bg-white">
            <div className="max-w-7xl mx-auto px-6 py-8">
              <h1 className="text-3xl font-bold text-gray-900 mb-6">
                {currentView.charAt(0).toUpperCase() + currentView.slice(1)}
              </h1>
              <div className="bg-white border border-gray-200 rounded-lg p-8">
                <p className="text-gray-700">This view will be implemented here.</p>
              </div>
            </div>
          </div>
        );
    }
  };

  // Views that use the profile-style layout (gap after header, 24px padding aligned with header)
  const profileStyleViews = ['generate', 'leads', 'lead-log', 'campaigns', 'campaign-detail', 'campaign-preview', 'campaign-creation', 'templates', 'inbox', 'email-accounts', 'profile', 'settings-profile', 'settings-billing', 'settings-usage', 'settings-lead-log', 'admin-ai-usage', 'admin-credits', 'admin-gemini-purchases', 'admin-users', 'admin-mailboxes'] as const;
  const useProfileStyleLayout = profileStyleViews.includes(currentView as typeof profileStyleViews[number]);

  // Handle profile settings completion
  const handleProfileSettingsComplete = () => {
    setShowProfileSettings(false);
    // Navigate to AI Lead Gen page
    navigate('/dashboard/generate');
    setCurrentView('generate');
  };

  const handleProfileSettingsSkip = () => {
    setShowProfileSettings(false);
    // Navigate to AI Lead Gen page when skip is clicked
    navigate('/dashboard/generate');
    setCurrentView('generate');
  };

  const handleProfileSettingsCancel = () => {
    // Allow user to cancel, but they'll see it again on next login
    setShowProfileSettings(false);
    // Navigate to AI Lead Gen page
    navigate('/dashboard/generate');
    setCurrentView('generate');
  };

  // Show loading state while checking company
  if (isCheckingCompany) {
    return (
      <div className="dashboard-loading-container">
        <div className="dashboard-loading-spinner" />
      </div>
    );
  }

  // Don't render dashboard for invalid paths - useEffect will redirect to full-page 404
  // Always allow edit path - prevents blank page when opening draft campaign
  const isEditPath = location.pathname.match(/\/dashboard\/campaigns\/[^\/]+\/edit/);
  if (!isEditPath && !isValidDashboardRoute(location.pathname)) {
    return null;
  }

  return (
    <div className="dashboard-main-container dashboard-page-background">
      {showProfileSettings && (
        <ProfileSettings
          onComplete={handleProfileSettingsComplete}
          onCancel={handleProfileSettingsCancel}
          onSkip={handleProfileSettingsSkip}
        />
      )}
      {isSettingsView && !isMobile && (
        <SettingsSidebar
          activeSection={
            currentView === 'settings-billing'
              ? 'billing'
              : currentView === 'settings-usage'
                ? 'usage'
                : currentView === 'settings-lead-log'
                  ? 'search-history'
                  : 'profile'
          }
        />
      )}
      {!isSettingsView && (
        <Sidebar 
          isOpen={sidebarOpen}
          collapsed={sidebarCollapsed}
          currentView={currentView === 'email-account-setup-loading' || currentView === 'google-consent' || currentView === 'imap-consent' ? 'generate' : currentView}
          onViewChange={handleViewChange}
          onClose={() => setSidebarOpen(false)}
          onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
          currentUserRole={currentUserRole}
          currentUserName={currentUserName}
          currentUserEmail={currentUserEmail}
          isLeadGenInProgress={leadGenStatus.isGenerating && !leadGenStatus.isComplete}
          workspaceMode={currentUserRole === 'admin' ? workspaceMode : 'user'}
          onSwitchWorkspace={
            currentUserRole === 'admin' ? handleSwitchWorkspace : undefined
          }
          onOpenBilling={() => {
            navigate(viewToPathMap['settings-usage']);
            setCurrentView('settings-usage');
          }}
        />
      )}
      
      <main 
        className={`dashboard-main-content dashboard-main-content-base${useProfileStyleLayout ? ' dashboard-main-profile-page' : ''}`}
        style={{ 
          '--sidebar-width': `${sidebarWidth}px`,
          '--main-content-width': `calc(100vw - ${sidebarWidth}px)`
        } as React.CSSProperties}
      >
        {/* Lead Generation Banner - "Processing" exactly 5s after prompt; "Your leads are ready" immediately */}
        {((showProcessingBanner && leadGenStatus.isGenerating) || leadGenStatus.isComplete) && !bannerDismissed && (
          <div className="lead-gen-side-banner" style={{
            background: 'linear-gradient(135deg, #D458FF 0%, #6B21A8 100%)',
            color: '#FFFFFF',
            padding: leadGenStatus.isComplete ? '16px 20px' : '12px 20px',
            display: 'flex',
            flexDirection: leadGenStatus.isComplete ? 'column' : 'row',
            alignItems: leadGenStatus.isComplete ? 'stretch' : 'center',
            gap: leadGenStatus.isComplete ? '12px' : '12px',
            fontSize: '14px',
            fontFamily: 'Urbanist, sans-serif',
            fontWeight: 500,
            position: 'fixed',
            top: '80px',
            right: 0,
            zIndex: 100001,
            boxShadow: '0 4px 20px rgba(107, 33, 168, 0.35)',
            borderRadius: '12px 0 0 12px',
            maxWidth: '380px',
            animation: 'lead-gen-banner-slide-in 0.3s ease-out'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <Slack size={18} style={{ flexShrink: 0 }} />
              <span style={{ flex: 1 }}>
                {leadGenStatus.isGenerating
                  ? 'Processing your leads. Feel free to explore other pages.'
                  : 'Your leads are ready to review!'}
              </span>
              <button
                onClick={() => {
                  if (leadGenStatus.isGenerating) {
                    setBannerDismissed(true);
                    setShowProcessingBanner(false);
                    if (processingBannerTimeoutRef.current) {
                      clearTimeout(processingBannerTimeoutRef.current);
                      processingBannerTimeoutRef.current = null;
                    }
                    if (processingBannerDismissRef.current) {
                      clearTimeout(processingBannerDismissRef.current);
                      processingBannerDismissRef.current = null;
                    }
                  } else if (leadGenStatus.isComplete) {
                    setBannerDismissed(true);
                    setLeadGenStatus({
                      isGenerating: false,
                      isComplete: false,
                      leadCount: 0,
                      logId: null
                    });
                  }
                }}
                style={{
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                  padding: '4px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: 'rgba(255,255,255,0.9)',
                  transition: 'opacity 0.2s',
                  flexShrink: 0
                }}
                onMouseEnter={(e) => { e.currentTarget.style.opacity = '0.7'; }}
                onMouseLeave={(e) => { e.currentTarget.style.opacity = '1'; }}
                title="Close"
              >
                <X size={18} />
              </button>
            </div>
            {leadGenStatus.isComplete && (
              <div style={{ display: 'flex', gap: '8px', marginTop: '4px', justifyContent: 'flex-end' }}>
                <button
                  onClick={() => {
                    setBannerDismissed(true);
                    setLeadGenStatus({
                      isGenerating: false,
                      isComplete: false,
                      leadCount: 0,
                      logId: null
                    });
                  }}
                  style={{
                    background: 'transparent',
                    color: '#FFFFFF',
                    border: '1px solid rgba(255,255,255,0.7)',
                    borderRadius: '6px',
                    padding: '4px 10px',
                    fontSize: '11px',
                    fontWeight: 600,
                    cursor: 'pointer',
                    fontFamily: 'Urbanist, sans-serif',
                    transition: 'background-color 0.2s, opacity 0.2s'
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.1)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = 'transparent';
                  }}
                >
                  View Later
                </button>
                <button
                  onClick={() => {
                    const logIdToShow = leadGenStatus.logId;
                    if (logIdToShow) setPendingViewResultsLogId(logIdToShow);
                    setBannerDismissed(true);
                    setLeadGenStatus(prev => ({ ...prev, isComplete: false }));
                    navigate('/dashboard/generate');
                    setCurrentView('generate');
                  }}
                  style={{
                    backgroundColor: '#FFFFFF',
                    color: '#1F2937',
                    border: 'none',
                    borderRadius: '6px',
                    padding: '4px 10px',
                    fontSize: '11px',
                    fontWeight: 600,
                    cursor: 'pointer',
                    fontFamily: 'Urbanist, sans-serif',
                    transition: 'opacity 0.2s'
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.opacity = '0.9';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.opacity = '1';
                  }}
                >
                  View Now
                </button>
              </div>
            )}
          </div>
        )}

        
        {/* Dashboard Header - Shows on all pages except consent pages and email-account-setup-loading */}
        {currentView !== 'google-consent' && currentView !== 'imap-consent' && currentView !== 'email-account-setup-loading' && (
        <>
        {isSettingsView && isMobile && (
          <SettingsSidebar
            variant="embedded"
            activeSection={
              currentView === 'settings-billing'
                ? 'billing'
                : currentView === 'settings-usage'
                  ? 'usage'
                  : currentView === 'settings-lead-log'
                    ? 'search-history'
                    : 'profile'
            }
          />
        )}
        <div className="dashboard-header">
          <div className="dashboard-header-left">
            <div className="dashboard-header-title">
              {currentView === 'settings-billing' ? (
                <>
                  <svg className="dashboard-header-icon dashboard-header-icon-gradient" width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="url(#dashboardHeaderIconGradientBilling)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                    <defs>
                      <linearGradient id="dashboardHeaderIconGradientBilling" x1="0%" y1="0%" x2="0%" y2="100%">
                        <stop offset="0%" stopColor="#D458FF" stopOpacity={0.7} />
                        <stop offset="100%" stopColor="#6B21A8" stopOpacity={1} />
                      </linearGradient>
                    </defs>
                    <rect x="2" y="5" width="20" height="14" rx="2" />
                    <path d="M2 10h20" />
                  </svg>
                  <h1 className="dashboard-header-text">Billing</h1>
                </>
              ) : currentView === 'settings-usage' ? (
                <>
                  <svg className="dashboard-header-icon dashboard-header-icon-gradient" width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="url(#dashboardHeaderIconGradientUsage)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                    <defs>
                      <linearGradient id="dashboardHeaderIconGradientUsage" x1="0%" y1="0%" x2="0%" y2="100%">
                        <stop offset="0%" stopColor="#D458FF" stopOpacity={0.7} />
                        <stop offset="100%" stopColor="#6B21A8" stopOpacity={1} />
                      </linearGradient>
                    </defs>
                    <path d="M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1" />
                    <path d="M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4" />
                  </svg>
                  <h1 className="dashboard-header-text">Usage</h1>
                </>
              ) : currentView === 'admin-ai-usage' ? (
                <>
                  <svg className="dashboard-header-icon dashboard-header-icon-gradient" width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="url(#dashboardHeaderIconGradientAiUsage)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                    <defs>
                      <linearGradient id="dashboardHeaderIconGradientAiUsage" x1="0%" y1="0%" x2="0%" y2="100%">
                        <stop offset="0%" stopColor="#D458FF" stopOpacity={0.7} />
                        <stop offset="100%" stopColor="#6B21A8" stopOpacity={1} />
                      </linearGradient>
                    </defs>
                    <path d="M3 3v18h18" />
                    <path d="M7 14l4-4 3 3 5-6" />
                  </svg>
                  <h1 className="dashboard-header-text">AI Usage</h1>
                </>
              ) : currentView === 'admin-credits' ? (
                <>
                  <svg className="dashboard-header-icon dashboard-header-icon-gradient" width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="url(#dashboardHeaderIconGradientAdminCredits)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                    <defs>
                      <linearGradient id="dashboardHeaderIconGradientAdminCredits" x1="0%" y1="0%" x2="0%" y2="100%">
                        <stop offset="0%" stopColor="#D458FF" stopOpacity={0.7} />
                        <stop offset="100%" stopColor="#6B21A8" stopOpacity={1} />
                      </linearGradient>
                    </defs>
                    <rect x="2" y="5" width="20" height="14" rx="2" />
                    <path d="M2 10h20" />
                  </svg>
                  <h1 className="dashboard-header-text">Credits</h1>
                </>
              ) : currentView === 'admin-gemini-purchases' ? (
                <>
                  <svg className="dashboard-header-icon dashboard-header-icon-gradient" width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="url(#dashboardHeaderIconGradientGeminiPurchases)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                    <defs>
                      <linearGradient id="dashboardHeaderIconGradientGeminiPurchases" x1="0%" y1="0%" x2="0%" y2="100%">
                        <stop offset="0%" stopColor="#D458FF" stopOpacity={0.7} />
                        <stop offset="100%" stopColor="#6B21A8" stopOpacity={1} />
                      </linearGradient>
                    </defs>
                    <circle cx="12" cy="12" r="10" />
                    <path d="M12 6v12" />
                    <path d="M8 10h8" />
                    <path d="M8 14h8" />
                  </svg>
                  <h1 className="dashboard-header-text">API Costs</h1>
                </>
              ) : currentView === 'admin-users' ? (
                <>
                  <svg className="dashboard-header-icon dashboard-header-icon-gradient" width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="url(#dashboardHeaderIconGradientAdminUsers)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                    <defs>
                      <linearGradient id="dashboardHeaderIconGradientAdminUsers" x1="0%" y1="0%" x2="0%" y2="100%">
                        <stop offset="0%" stopColor="#D458FF" stopOpacity={0.7} />
                        <stop offset="100%" stopColor="#6B21A8" stopOpacity={1} />
                      </linearGradient>
                    </defs>
                    <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
                    <circle cx="9" cy="7" r="4" />
                    <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
                    <path d="M16 3.13a4 4 0 0 1 0 7.75" />
                  </svg>
                  <h1 className="dashboard-header-text">Users</h1>
                </>
              ) : currentView === 'admin-mailboxes' ? (
                <>
                  <svg className="dashboard-header-icon dashboard-header-icon-gradient" width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="url(#dashboardHeaderIconGradientAdminMailboxes)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                    <defs>
                      <linearGradient id="dashboardHeaderIconGradientAdminMailboxes" x1="0%" y1="0%" x2="0%" y2="100%">
                        <stop offset="0%" stopColor="#D458FF" stopOpacity={0.7} />
                        <stop offset="100%" stopColor="#6B21A8" stopOpacity={1} />
                      </linearGradient>
                    </defs>
                    <rect x="2" y="4" width="20" height="16" rx="2" />
                    <path d="m22 7-10 7L2 7" />
                  </svg>
                  <h1 className="dashboard-header-text">Mailboxes</h1>
                </>
              ) : currentView === 'settings-profile' ? (
                <>
                  <svg className="dashboard-header-icon dashboard-header-icon-gradient" width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="url(#dashboardHeaderIconGradientSettingsProf)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                    <defs>
                      <linearGradient id="dashboardHeaderIconGradientSettingsProf" x1="0%" y1="0%" x2="0%" y2="100%">
                        <stop offset="0%" stopColor="#D458FF" stopOpacity={0.7} />
                        <stop offset="100%" stopColor="#6B21A8" stopOpacity={1} />
                      </linearGradient>
                    </defs>
                    <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
                    <circle cx="12" cy="7" r="4" />
                  </svg>
                  <h1 className="dashboard-header-text">User Profile</h1>
                </>
              ) : currentView === 'lead-log' || currentView === 'settings-lead-log' ? (
                <>
                  <svg className="dashboard-header-icon dashboard-header-icon-gradient" width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="url(#dashboardHeaderIconGradient)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                    <defs>
                      <linearGradient id="dashboardHeaderIconGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                        <stop offset="0%" stopColor="#D458FF" stopOpacity={0.7} />
                        <stop offset="100%" stopColor="#6B21A8" stopOpacity={1} />
                      </linearGradient>
                    </defs>
                    <circle cx="11" cy="11" r="8" />
                    <path d="m21 21-4.35-4.35" />
                  </svg>
                  <h1 className="dashboard-header-text">Search History</h1>
                </>
              ) : currentView === 'leads' ? (
                <>
                  <img src="/data-header.svg" alt="" className="dashboard-header-icon" width={20} height={20} aria-hidden />
                  <h1 className="dashboard-header-text">Lead Database</h1>
                </>
              ) : currentView === 'templates' ? (
                <>
                  <img src="/message-header.svg" alt="" className="dashboard-header-icon" width={20} height={20} aria-hidden />
                  <h1 className="dashboard-header-text">Email Templates</h1>
                </>
              ) : currentView === 'inbox' ? (
                <>
                  <img src="/direct-inbox-header.svg" alt="" className="dashboard-header-icon" width={20} height={20} aria-hidden />
                  <h1 className="dashboard-header-text">Inbox</h1>
                </>
              ) : currentView === 'email-accounts' ? (
                <>
                  <img src="/message-search-header.svg" alt="" className="dashboard-header-icon" width={20} height={20} aria-hidden />
                  <h1 className="dashboard-header-text">Email Accounts</h1>
                </>
              ) : currentView === 'profile' ? (
                <>
                  <svg className="dashboard-header-icon dashboard-header-icon-gradient" width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="url(#dashboardHeaderIconGradient)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                    <defs>
                      <linearGradient id="dashboardHeaderIconGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                        <stop offset="0%" stopColor="#D458FF" stopOpacity={0.7} />
                        <stop offset="100%" stopColor="#6B21A8" stopOpacity={1} />
                      </linearGradient>
                    </defs>
                    <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
                    <circle cx="12" cy="7" r="4" />
                  </svg>
                  <h1 className="dashboard-header-text">User Profile</h1>
                </>
              ) : currentView === 'generate' ? (
                <>
                  <img src="/slack-header.svg" alt="" className="dashboard-header-icon" width={20} height={20} aria-hidden />
                  <h1 className="dashboard-header-text dashboard-header-text--ai-lead-gen">AI Lead Gen</h1>
                </>
              ) : (currentView === 'campaigns' || currentView === 'campaign-detail' || currentView === 'campaign-preview' || currentView === 'campaign-creation') ? (
                <>
                  <img src="/finger-cricle-header.svg" alt="" className="dashboard-header-icon" width={20} height={20} aria-hidden />
                  <h1 className="dashboard-header-text">Campaign</h1>
                </>
              ) : (
                <>
                  <svg className="dashboard-header-icon dashboard-header-icon-gradient" width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="url(#dashboardHeaderIconGradient)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                    <defs>
                      <linearGradient id="dashboardHeaderIconGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                        <stop offset="0%" stopColor="#D458FF" stopOpacity={0.7} />
                        <stop offset="100%" stopColor="#6B21A8" stopOpacity={1} />
                      </linearGradient>
                    </defs>
                    <path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936a2 2 0 0 0 1.437-1.437l1.582-6.135a.5.5 0 0 1 .963 0l1.582 6.135a2 2 0 0 0 1.437 1.437l6.135 1.582a.5.5 0 0 1 0 .963L14.063 14.5a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0L9.937 15.5Z" />
                    <path d="M20.067 11.5a.502.502 0 0 0-.134-.364l-2.068-2.028a.5.5 0 0 1 .364-.864l2.716.224a.5.5 0 0 1 .364.364l.224 2.716a.5.5 0 0 1-.864.364l-2.028-2.068a.502.502 0 0 0-.364-.134Z" />
                    <path d="M4.067 20.5a.502.502 0 0 0-.134-.364L1.865 18.108a.5.5 0 0 1 .364-.864l2.716.224a.5.5 0 0 1 .364.364l.224 2.716a.5.5 0 0 1-.864.364l-2.028-2.068a.502.502 0 0 0-.364-.134Z" />
                  </svg>
                  <h1 className="dashboard-header-text">Campaign</h1>
                </>
              )}
            </div>
          </div>
          <div className="dashboard-profile-header-right">
            {currentView !== 'generate' && !isSettingsView && (
              <button
                type="button"
                className="dashboard-profile-generate-leads-btn"
                onClick={() => { navigate(viewToPathMap['generate']); setCurrentView('generate'); }}
              >
                <Plus className="dashboard-profile-generate-leads-icon" size={18} />
                Generate New Leads
              </button>
            )}
            <div className="dashboard-profile-user-dropdown" ref={profileHeaderDropdownRef}>
              <button
                type="button"
                className="dashboard-profile-user-trigger"
                onClick={() => setProfileHeaderDropdownOpen(!profileHeaderDropdownOpen)}
                aria-expanded={profileHeaderDropdownOpen}
                aria-haspopup="true"
              >
                <span
                  className="dashboard-profile-user-avatar dashboard-profile-user-avatar-gradient"
                >
                  {(authUser?.full_name || authUser?.username || 'U').charAt(0).toUpperCase()}
                </span>
                <span className="dashboard-profile-user-name">
                  {authUser?.full_name || authUser?.username || 'User'}
                </span>
                <ChevronDown className="dashboard-profile-user-chevron" size={18} />
              </button>
              {profileHeaderDropdownOpen && (
                <div className="dashboard-profile-user-menu">
                  <button
                    type="button"
                    className="dashboard-profile-user-menu-item"
                    onClick={() => {
                      setProfileHeaderDropdownOpen(false);
                      if (isSettingsView) {
                        navigate(viewToPathMap['generate']);
                        setCurrentView('generate');
                      } else {
                        navigate(viewToPathMap['settings-profile']);
                        setCurrentView('settings-profile');
                      }
                    }}
                  >
                    {isSettingsView ? 'Home' : 'Settings'}
                  </button>
                  <button
                    type="button"
                    className="dashboard-profile-user-menu-item"
                    onClick={async () => {
                      setProfileHeaderDropdownOpen(false);
                      try {
                        await logout();
                        window.location.href = '/auth';
                      } catch (e) {
                        window.location.href = '/auth';
                      }
                    }}
                  >
                    Logout
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
        </>
        )}

        {/* Hamburger Menu Button for Mobile - Only show on main/list pages, not detail pages */}
        {(() => {
          // Define detail views where hamburger menu should NOT appear
          const detailViews: ViewType[] = ['campaign-detail', 'campaign-preview', 'campaign-creation'];
          const isDetailView =
            detailViews.includes(currentView) ||
            ((currentView === 'lead-log' || currentView === 'settings-lead-log') && leadLogDetailView);
          
          return isMobile && !sidebarOpen && !isDetailView && !isSettingsView && (
            <button
              onClick={() => setSidebarOpen(true)}
              className="fixed top-3 left-3 z-50 p-2 rounded-md bg-white border border-gray-200 shadow-sm hover:bg-gray-50 transition-colors dashboard-hamburger-button"
              aria-label="Open menu"
            >
              <Menu className="h-5 w-5 text-gray-700" />
            </button>
          );
        })()}
        <div 
          className={`dashboard-content-wrapper dashboard-content-wrapper-base${useProfileStyleLayout ? ' dashboard-content-wrapper-profile-style' : ''}`}
          style={{ 
            '--content-padding-top': isMobile && !sidebarOpen ? '56px' : '0'
          } as React.CSSProperties}
        >
          {useProfileStyleLayout ? (
            <div 
              className="dashboard-page-content-area"
              style={{ 
                flex: 1,
                minHeight: 0,
                overflow: 'hidden',
                padding: '20px 24px 0 24px',
                display: 'flex',
                flexDirection: 'column'
              }}
            >
                <div 
                  className={`dashboard-page-content-card${currentView === 'generate' ? ' dashboard-page-content-card-lead-gen' : ''}`}
                  style={{
                    flex: 1,
                    minHeight: 0,
                    display: 'flex',
                    flexDirection: 'column',
                    overflowY: currentView === 'generate' ? 'hidden' : 'auto',
                    width: '100%',
                    backgroundColor: 'white',
                    borderRadius: '18px 18px 0 0',
                    padding: '24px',
                    border: '1px solid #E5E7EB',
                  boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.08), 0 2px 4px -2px rgba(0, 0, 0, 0.06)'
                }}
              >
                {renderContent()}
              </div>
            </div>
          ) : (
            renderContent()
          )}
        </div>
      </main>
    </div>
  );
}
