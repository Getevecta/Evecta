import { useState, useRef, useEffect, useImperativeHandle, forwardRef, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Send, Slack, Lightbulb, CheckCircle2, Loader2, Filter, Plus, Search, ChevronLeft, ChevronRight, ChevronDown, ChevronUp, X, SlidersHorizontal, TrendingUp, Check, MapPin, Building2, ShoppingCart, Info, Inbox } from 'lucide-react';
import { DashboardPagination } from '../ui/DashboardPagination';
import { Button } from '../ui/button';
import { Textarea } from '../ui/textarea';
import { CardDescription } from '../ui/card';
import { apiService, ChatResponse, LeadLogLeadResponse } from '../../../../shared/services/api';
import { useAuth } from '../../../../shared/contexts/AuthContext';
import { useMobileGap } from '../ui/use-mobile-gap';
import { startLeadGenPolling, stopLeadGenPolling } from '../../../../shared/leadGenPoller';
import { persistCampaignLeadSelection } from '../../../../shared/utils/campaignLeadSelection';
import './LeadGeneration.css';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../ui/table';
import { LeadDetailPanel } from '../ui/LeadDetailPanel';
import { Tabs, TabsList, TabsTrigger } from '../ui/tabs';
import { Input } from '../ui/input';
interface ChatMessage {
  type: 'user' | 'ai';
  content: string;
  timestamp: Date;
  data?: ChatResponse;
  showUpgradePrompt?: boolean;
}

interface LeadGenerationProps {
  /** Dashboard sidebar width (px) — sets CSS vars so fixed UI (e.g. bottom chat) stays in the main column */
  layoutSidebarWidthPx?: number;
  /** When user returns to this page while leads are still processing, show loader and poll this logId */
  generatingLogId?: string | null;
  /** When true, chat input is disabled (e.g. "Processing your leads" banner is showing) */
  isLeadGenInProgress?: boolean;
  /** When user clicked "View" on completed banner, open and show results for this logId */
  openWithLogId?: string | null;
  /** Called after we've loaded and displayed results for openWithLogId */
  onOpenWithLogIdLoaded?: () => void;
  /** Called when user discards leads – parent should clear completed banner so we don't re-show the table */
  onDiscardLeads?: () => void;
  onToggleSidebar?: () => void;
  onNavigationAttempt?: (proceed: () => void) => void; // Callback when navigation is attempted
  onNavigateToLeads?: () => void; // Callback to navigate to Lead Database
  onNavigateToCreateCampaign?: (leadIds?: string[]) => void; // Callback to navigate to Create Campaign with lead IDs
}

export interface LeadGenerationRef {
  hasUnsavedLeads: () => boolean;
  showSaveDialog: () => void;
  resetToInitial: () => void;
  isProcessing: () => boolean;
  showProcessingDialog: () => void;
}

function isCreditDepletionText(text: string): boolean {
  const c = text.trim().toLowerCase();
  if (!c) return false;
  return (
    c.includes("you're out of lead credits") ||
    c.includes("you've used all your lead credits") ||
    c.includes("you've reached your credit limit") ||
    c.includes('insufficient_credits') ||
    c.includes('insufficient credits') ||
    c.includes('add credits in billing') ||
    c.includes('add credits from billing') ||
    c.includes('payment required')
  );
}

function isCreditDepletionMessage(msg: ChatMessage): boolean {
  if (msg.type !== 'ai') return false;
  if (msg.data?.status === 'insufficient_credits') return true;
  const c = typeof msg.content === 'string' ? msg.content : '';
  return isCreditDepletionText(c);
}

function isChatErrorMessage(msg: ChatMessage): boolean {
  if (msg.type !== 'ai') return false;
  if (isCreditDepletionMessage(msg)) return true;
  const c = typeof msg.content === 'string' ? msg.content : '';
  return c.startsWith('Sorry, I encountered an error:');
}

function LeadCreditHint() {
  return (
    <div className="lead-generation-credit-hint">
      <span className="lead-generation-credit-hint-text">1 lead uses 1 credit</span>
      <span className="lead-generation-credit-hint-info" tabIndex={0} aria-label="Credit usage info">
        <Info size={14} strokeWidth={2} aria-hidden />
        <span className="lead-generation-credit-hint-tooltip" role="tooltip">
          Each generated lead uses 1 credit. Total credit usage depends on the number of leads
          generated.
        </span>
      </span>
    </div>
  );
}

function stripChatErrorPrefix(text: string): string {
  return text.replace(/^Sorry, I encountered an error:\s*/i, '').trim();
}

function sanitizeStoredMessages(messages: ChatMessage[]): ChatMessage[] {
  return messages.filter((msg) => !isChatErrorMessage(msg));
}

function messagesIndicateCreditDepleted(msgs: ChatMessage[]): boolean {
  return msgs.some(isCreditDepletionMessage);
}

type LeadGenBanner =
  | { kind: 'credit' }
  | { kind: 'error'; message: string };

const DEV_PREVIEW_USER_MESSAGE = 'Preview banner UI';
/** Shown while waiting for a normal conversational reply (greeting, Q&A, etc.). */
const CHAT_PROGRESS_REPLY = 'Thinking';
/** Shown only when a lead search / generation is actually running. */
const CHAT_PROGRESS_STAGES_SEARCH = [
  'Understanding your request',
  'Checking the location',
  'Resolving business categories',
  'Searching available leads',
  'Ranking the results',
] as const;
/** Pause after announcing the lead count so the user sees how many they'll get. */
const LEAD_COUNT_REVEAL_DELAY_MS = 2800;

function isBannerPreviewEnabled(): boolean {
  if (import.meta.env.DEV) return true;
  if (import.meta.env.VITE_ENABLE_BANNER_PREVIEW === 'true') return true;
  if (typeof window !== 'undefined' && window.location.hostname === 'staging.evecta.io') {
    return true;
  }
  return false;
}

/** `?previewBanner=error&previewMessage=Failed%20to%fetch` or `?previewBanner=credit` (dev + staging) */
function parseDevBannerPreview(search: string): LeadGenBanner | null {
  if (!isBannerPreviewEnabled()) return null;
  const params = new URLSearchParams(search);
  const kind = params.get('previewBanner')?.trim().toLowerCase();
  if (kind === 'credit') return { kind: 'credit' };
  if (kind === 'error') {
    const message =
      params.get('previewMessage')?.trim() ||
      'Failed to fetch';
    return { kind: 'error', message: stripChatErrorPrefix(message) };
  }
  return null;
}

function devPreviewMessages(existing: ChatMessage[]): ChatMessage[] {
  if (existing.length > 0) return existing;
  return [
    {
      type: 'user',
      content: DEV_PREVIEW_USER_MESSAGE,
      timestamp: new Date(),
    },
  ];
}

function initialLeadGenBanner(
  savedState: LeadGenLoadedState,
  devPreview: LeadGenBanner | null,
): LeadGenBanner | null {
  if (devPreview) return devPreview;
  if (savedState.creditDepletedAfterSend || messagesIndicateCreditDepleted(savedState.messages)) {
    return { kind: 'credit' };
  }
  return null;
}

const LEAD_GEN_STORAGE_KEY = 'leadGenerationChatState';

type LeadGenLoadedState = {
  messages: ChatMessage[];
  currentLeads: LeadLogLeadResponse[];
  currentLogId: string | null;
  /** Lead log chat_title (e.g. "Restaurants In Kathmandu") shown as the results header */
  resultsTitle: string | null;
  prompt: string;
  selectedLeads: string[];
  leadsSaved: boolean;
  leadGenTimedOut: boolean;
  creditDepletedAfterSend: boolean;
};

const emptyLeadGenLoadedState = (): LeadGenLoadedState => ({
  messages: [],
  currentLeads: [],
  currentLogId: null,
  resultsTitle: null,
  prompt: '',
  selectedLeads: [],
  leadsSaved: false,
  leadGenTimedOut: false,
  creditDepletedAfterSend: false,
});

/** Only restore sessionStorage when it was saved for this signed-in user (prevents cross-account leaks). */
function loadLeadGenStateFromStorage(userId: string | null): LeadGenLoadedState {
  if (!userId) {
    return emptyLeadGenLoadedState();
  }
  try {
    const saved = sessionStorage.getItem(LEAD_GEN_STORAGE_KEY);
    if (saved) {
      const parsed = JSON.parse(saved);
      if (parsed.userId !== userId) {
        try {
          sessionStorage.removeItem(LEAD_GEN_STORAGE_KEY);
        } catch {
          /* ignore */
        }
        return emptyLeadGenLoadedState();
      }
      if (parsed.leadsSaved === true && (parsed.currentLeads?.length > 0 || parsed.currentLogId)) {
        sessionStorage.removeItem(LEAD_GEN_STORAGE_KEY);
        return emptyLeadGenLoadedState();
      }
      const mapped = (parsed.messages || []).map((msg: any) => ({
        ...msg,
        timestamp: new Date(msg.timestamp),
        data: msg.data || undefined,
      })) as ChatMessage[];
      const messages = sanitizeStoredMessages(mapped);
      const creditDepletedAfterSend =
        parsed.creditDepletedAfterSend === true || messagesIndicateCreditDepleted(messages);
      return {
        messages,
        currentLeads: parsed.currentLeads || [],
        currentLogId: parsed.currentLogId || null,
        resultsTitle: parsed.resultsTitle || null,
        prompt: parsed.prompt || '',
        selectedLeads: parsed.selectedLeads || [],
        leadsSaved: parsed.leadsSaved || false,
        leadGenTimedOut: parsed.leadGenTimedOut || false,
        creditDepletedAfterSend,
      };
    }
  } catch (e) {
    console.error('Failed to load chat state from storage:', e);
  }
  return emptyLeadGenLoadedState();
}

const LeadGenerationComponent = forwardRef<LeadGenerationRef, LeadGenerationProps>(
  ({ layoutSidebarWidthPx = 0, generatingLogId, isLeadGenInProgress = false, openWithLogId, onOpenWithLogIdLoaded, onDiscardLeads, onToggleSidebar, onNavigationAttempt, onNavigateToLeads, onNavigateToCreateCampaign }, ref) => {
    const { user: authUser } = useAuth();
    const authUserId = authUser?.id ?? null;
    const authUserIdRef = useRef<string | null>(authUserId);
    const navigate = useNavigate();
    const location = useLocation();

    useEffect(() => {
      authUserIdRef.current = authUserId;
    }, [authUserId]);

    useEffect(() => {
      if (!isBannerPreviewEnabled()) return;
      const preview = parseDevBannerPreview(location.search);
      if (!preview) return;
      setLeadGenBanner(preview);
      setLeadGenBannerDismissed(false);
      setCreditDepletedAfterSend(preview.kind === 'credit');
      setMessages((prev) => devPreviewMessages(prev));
      setCurrentLeads([]);
      setCurrentLogId(null);
      setIsLoading(false);
      setIsLoadingLeads(false);
      setShowFullPageLoader(false);
    }, [location.search]);

    const devBannerPreview = isBannerPreviewEnabled()
      ? parseDevBannerPreview(location.search)
      : null;
    // Mobile gap helpers
    const gap1 = useMobileGap(1);
    const gap4 = useMobileGap(4);
    const gap6 = useMobileGap(6);
    const gap8 = useMobileGap(8);
    const gap12 = useMobileGap(12);
    const gap16 = useMobileGap(16);

    const savedState = loadLeadGenStateFromStorage(authUserId);
    // Prefer parent's generatingLogId when returning while processing (so we show loader even if sessionStorage was stale)
    const effectiveInitialLogId = savedState.currentLogId || generatingLogId || null;
    // If we have a logId but no leads and not timed out, we're still waiting - show loader
    const isWaitingForLeads = effectiveInitialLogId && savedState.currentLeads.length === 0 && !savedState.leadsSaved && !savedState.leadGenTimedOut;
    
    const [prompt, setPrompt] = useState(savedState.prompt);
  const [messages, setMessages] = useState<ChatMessage[]>(() =>
    devBannerPreview ? devPreviewMessages(savedState.messages) : savedState.messages,
  );
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingLeads, setIsLoadingLeads] = useState(isWaitingForLeads);
  const [showFullPageLoader, setShowFullPageLoader] = useState(isWaitingForLeads);
  const [progressStageIndex, setProgressStageIndex] = useState(0);
  const [currentLeads, setCurrentLeads] = useState<LeadLogLeadResponse[]>(savedState.currentLeads);
  const [currentLogId, setCurrentLogId] = useState<string | null>(effectiveInitialLogId);
  /** chat_title of the current lead log — shown as the results header instead of the raw last message */
  const [resultsTitle, setResultsTitle] = useState<string | null>(savedState.resultsTitle);
  const [selectedLeads, setSelectedLeads] = useState<Set<string>>(new Set(savedState.selectedLeads));
  const [activeTab, setActiveTab] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(10);
  const [leadsSaved, setLeadsSaved] = useState(savedState.leadsSaved);
  const [leadGenTimedOut, setLeadGenTimedOut] = useState(savedState.leadGenTimedOut ?? false);
  /** `null` until first balance fetch */
  const [creditBalance, setCreditBalance] = useState<number | null>(null);
  /** After user sends a message and API reports no credits — show buy-credits banner and block further sends */
  const [creditDepletedAfterSend, setCreditDepletedAfterSend] = useState(
    () =>
      devBannerPreview?.kind === 'credit' ||
      savedState.creditDepletedAfterSend ||
      messagesIndicateCreditDepleted(savedState.messages),
  );
  const [leadGenBanner, setLeadGenBanner] = useState<LeadGenBanner | null>(() =>
    initialLeadGenBanner(savedState, devBannerPreview),
  );
  const [leadGenBannerDismissed, setLeadGenBannerDismissed] = useState(false);
  const showLeadGenBanner = leadGenBanner !== null && !leadGenBannerDismissed;
  const [savedLeadIds, setSavedLeadIds] = useState<Set<string>>(new Set());
  const [showOnlySaved, setShowOnlySaved] = useState(false);
  const [showFilters, setShowFilters] = useState(false);
  const [selectedIndustries, setSelectedIndustries] = useState<Set<string>>(new Set());
  const [selectedLocations, setSelectedLocations] = useState<Set<string>>(new Set());
  const [scoreRange, setScoreRange] = useState<[number, number]>([0, 100]);
  const [locationInput, setLocationInput] = useState('');
  const [industryInput, setIndustryInput] = useState('');
  const [showLocationSuggestions, setShowLocationSuggestions] = useState(false);
  const [showIndustrySuggestions, setShowIndustrySuggestions] = useState(false);
  const [showSaveAllDialog, setShowSaveAllDialog] = useState(false);
  const [showProcessingDialog, setShowProcessingDialog] = useState(false);
  const [showDiscardConfirmDialog, setShowDiscardConfirmDialog] = useState(false);
  const [lastVisibleLeadIndex, setLastVisibleLeadIndex] = useState<number>(5); // Default to 5 for small screens
  const [pendingClickAction, setPendingClickAction] = useState<(() => void) | null>(null);
  const [dialogContext, setDialogContext] = useState<'navigation'>('navigation');
  const [isTextareaFocused, setIsTextareaFocused] = useState(false);
  const [selectedSuggestionTag, setSelectedSuggestionTag] = useState<number | null>(null);
  const [emailFilter, setEmailFilter] = useState<'all' | 'has_email' | 'no_email'>('all');
  const [showEmailFilterDropdown, setShowEmailFilterDropdown] = useState(false);
  const [selectedLead, setSelectedLead] = useState<LeadLogLeadResponse | null>(null);
  const emailFilterButtonRef = useRef<HTMLButtonElement>(null);
  const emailFilterDropdownRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const tableContainerRef = useRef<HTMLDivElement>(null);
  const leadRowRefs = useRef<(HTMLTableRowElement | null)[]>([]);
  const promptButtonRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const enrichmentPollingRef = useRef<NodeJS.Timeout | null>(null);
  const enrichmentCutoffTimerRef = useRef<NodeJS.Timeout | null>(null);
  /** LogId we're waiting for from leadGenLeadsReady; avoids missing event due to stale currentLogId closure */
  const expectedLogIdRef = useRef<string | null>(null);
  /** LogId we've already shown the "no results / failed" message for — prevents the 1s poll
   *  and page refreshes from appending the same message again. */
  const noResultsShownRef = useRef<string | null>(null);
  /** After leads are ready: show total count first, then open the table. */
  const [pendingRevealCount, setPendingRevealCount] = useState<number | null>(null);
  const revealTimerRef = useRef<number | null>(null);
  const revealInFlightLogIdRef = useRef<string | null>(null);
  /** After 1 min of enrichment, show N/A for any lead still "processing" */
  const [enrichmentCutoffReached, setEnrichmentCutoffReached] = useState(false);

  const scheduleLeadReveal = useCallback(
    (leads: LeadLogLeadResponse[], logId: string, chatTitle?: string | null) => {
      if (!leads.length || !logId) return;
      // Already showing this log's table, or already mid-reveal for it.
      if (revealInFlightLogIdRef.current === logId) return;
      if (currentLogId === logId && currentLeads.length > 0) return;

      revealInFlightLogIdRef.current = logId;
      stopLeadGenPolling();
      expectedLogIdRef.current = null;
      setCurrentLogId(logId);
      if (chatTitle) setResultsTitle(chatTitle);
      setLeadsSaved(false);
      setPendingRevealCount(leads.length);
      // Stay on the chat surface (not the table) until the delay finishes.
      setIsLoadingLeads(true);
      setShowFullPageLoader(true);
      setIsLoading(false);

      const countLabel = leads.length === 1 ? 'lead' : 'leads';
      const countMsg = `I found ${leads.length} ${countLabel}. Opening your results next…`;
      setMessages((prev) => {
        const last = prev[prev.length - 1];
        const isCountPreview =
          last?.type === 'ai' &&
          typeof last.content === 'string' &&
          /^I found \d+ leads?\./i.test(last.content.trim());
        const nextMsg: ChatMessage = {
          type: 'ai',
          content: countMsg,
          timestamp: new Date(),
          data: { lead_count: leads.length } as ChatResponse,
        };
        if (isCountPreview) {
          return [...prev.slice(0, -1), nextMsg];
        }
        return [...prev, nextMsg];
      });

      if (revealTimerRef.current) {
        window.clearTimeout(revealTimerRef.current);
      }
      revealTimerRef.current = window.setTimeout(() => {
        setCurrentLeads(leads);
        setPendingRevealCount(null);
        setIsLoadingLeads(false);
        setShowFullPageLoader(false);
        revealInFlightLogIdRef.current = null;
        revealTimerRef.current = null;
        try {
          const raw = sessionStorage.getItem(LEAD_GEN_STORAGE_KEY);
          const state = raw ? JSON.parse(raw) : {};
          state.currentLogId = logId;
          state.currentLeads = leads;
          if (chatTitle) state.resultsTitle = chatTitle;
          sessionStorage.setItem(LEAD_GEN_STORAGE_KEY, JSON.stringify(state));
        } catch {
          // ignore persistence errors
        }
      }, LEAD_COUNT_REVEAL_DELAY_MS);
    },
    [currentLogId, currentLeads.length],
  );

  useEffect(() => {
    return () => {
      if (revealTimerRef.current) {
        window.clearTimeout(revealTimerRef.current);
        revealTimerRef.current = null;
      }
    };
  }, []);

  // Position email filter dropdown and close when clicking outside
  useEffect(() => {
    if (showEmailFilterDropdown && emailFilterButtonRef.current && emailFilterDropdownRef.current) {
      const buttonRect = emailFilterButtonRef.current.getBoundingClientRect();
      emailFilterDropdownRef.current.style.top = `${buttonRect.bottom + 4}px`;
      emailFilterDropdownRef.current.style.left = `${buttonRect.left}px`;
    }
  }, [showEmailFilterDropdown]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as HTMLElement;
      if (showEmailFilterDropdown && !target.closest('[data-email-filter-dropdown]')) {
        setShowEmailFilterDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showEmailFilterDropdown]);

  useEffect(() => {
    // Search-stage carousel only while an actual lead search is in progress.
    // Conversational turns (e.g. "hii") stay on a simple "Thinking…" label.
    const isSearchBusy = showFullPageLoader || isLoadingLeads || isLeadGenInProgress;
    if (!isSearchBusy) {
      setProgressStageIndex(0);
      return;
    }
    setProgressStageIndex(0);
    const timer = window.setInterval(() => {
      setProgressStageIndex((prev) => (prev + 1) % CHAT_PROGRESS_STAGES_SEARCH.length);
    }, 1300);
    return () => window.clearInterval(timer);
  }, [showFullPageLoader, isLoadingLeads, isLeadGenInProgress]);

  useEffect(() => {
    setCurrentPage(1);
  }, [emailFilter]);

  // Keep ref in sync so we never miss leadGenLeadsReady due to stale closure
  useEffect(() => {
    const waitingFor = currentLogId || generatingLogId;
    if (waitingFor && currentLeads.length === 0 && !leadsSaved) {
      expectedLogIdRef.current = waitingFor;
    } else {
      expectedLogIdRef.current = null;
    }
  }, [currentLogId, generatingLogId, currentLeads.length, leadsSaved]);

  // Listen for leadGenLeadsReady event (from global poller) – count preview, then result table
  const logIdWeAccept = currentLogId || generatingLogId;
  useEffect(() => {
    const handleLeadsReady = (event: CustomEvent) => {
      const { logId, leads, chatTitle } = event.detail;
      const isWaitingForThisLog = logId === logIdWeAccept || logId === expectedLogIdRef.current;
      if (!isWaitingForThisLog || !leads?.length) return;
      console.log('Leads ready from background polling:', leads.length);
      scheduleLeadReveal(leads, logId, chatTitle);
    };

    window.addEventListener('leadGenLeadsReady', handleLeadsReady as EventListener);

    return () => {
      window.removeEventListener('leadGenLeadsReady', handleLeadsReady as EventListener);
    };
  }, [logIdWeAccept, scheduleLeadReveal]);

  // Listen for polling timeout – stop loader, explain what happened, and let the user try again.
  useEffect(() => {
    const handlePollingTimeout = (event: CustomEvent) => {
      const { logId } = event.detail;
      const isWaitingForThisLog = logId === (currentLogId || generatingLogId) || logId === expectedLogIdRef.current;
      if (!isWaitingForThisLog) return;
      stopLeadGenPolling();
      expectedLogIdRef.current = null;
      setShowFullPageLoader(false);
      setIsLoadingLeads(false);
      setIsLoading(false);
      setCurrentLogId(null);
      setLeadGenTimedOut(true);
      window.dispatchEvent(new CustomEvent('leadGenCancelled'));
      if (noResultsShownRef.current !== logId) {
        noResultsShownRef.current = logId;
        setMessages((prev) => [
          ...prev,
          {
            type: 'ai',
            content: "I couldn't get results for that search in time. Please try again, or make the search a little broader with a different location or industry.",
            timestamp: new Date(),
          },
        ]);
      }
    };
    window.addEventListener('leadGenPollingTimeout', handlePollingTimeout as EventListener);
    return () => window.removeEventListener('leadGenPollingTimeout', handlePollingTimeout as EventListener);
  }, [currentLogId, generatingLogId]);

  // Restore state and resume polling when returning to page (or when parent says we're still generating)
  useEffect(() => {
    if (leadGenTimedOut) return; // Don't resume polling if we already timed out
    const logIdToUse = currentLogId || generatingLogId;
    if (!logIdToUse || currentLeads.length > 0 || leadsSaved) return;
    const ownerWhenResume = authUserId;
    console.log('Resuming background polling for logId:', logIdToUse);
    expectedLogIdRef.current = logIdToUse;
    if (!currentLogId && generatingLogId) {
      setCurrentLogId(generatingLogId);
    }
    setIsLoadingLeads(true);
    setShowFullPageLoader(true);
    startLeadGenPolling(logIdToUse, apiService, ownerWhenResume);
    const checkLeadsImmediate = async () => {
      try {
        const leadsResponse = await apiService.getLeadLogById(logIdToUse);
        if (ownerWhenResume && authUserIdRef.current !== ownerWhenResume) {
          return;
        }
        if (leadsResponse.data && leadsResponse.data.leads && leadsResponse.data.leads.length > 0) {
          scheduleLeadReveal(
            leadsResponse.data.leads,
            logIdToUse,
            leadsResponse.data.chat_title || null,
          );
        }
      } catch (error) {
        console.error('Failed to check leads immediately:', error);
      }
    };
    checkLeadsImmediate();
  }, [leadGenTimedOut, authUserId, scheduleLeadReveal]);

  // When banner shows "completed" or user clicked "View": ensure we show results for this logId (fetch if we don't have leads)
  useEffect(() => {
    if (!openWithLogId) return;
    // If we already have leads for this logId, just ensure loader is off and we're showing results
    if (currentLogId === openWithLogId && currentLeads.length > 0) {
      setIsLoadingLeads(false);
      setShowFullPageLoader(false);
      onOpenWithLogIdLoaded?.();
      return;
    }
    const loadResultsForLog = async () => {
      try {
        setIsLoadingLeads(true);
        setShowFullPageLoader(true);
        const response = await apiService.getLeadLogById(openWithLogId);
        if (response?.data?.leads?.length) {
          setCurrentLogId(openWithLogId);
          setCurrentLeads(response.data.leads);
          setResultsTitle(response.data.chat_title || null);
          setLeadsSaved(false);
        }
      } catch (e) {
        console.error('Failed to load results for openWithLogId:', e);
      } finally {
        setIsLoadingLeads(false);
        setShowFullPageLoader(false);
        onOpenWithLogIdLoaded?.();
      }
    };
    loadResultsForLog();
  }, [openWithLogId]); // eslint-disable-line react-hooks/exhaustive-deps -- only run when openWithLogId is set

  // Cleanup polling on unmount or when leads are saved/discarded
  useEffect(() => {
    return () => {
      // Only stop polling if we're not waiting for leads
      if (!currentLogId || leadsSaved) {
        stopLeadGenPolling();
      }
    };
  }, [currentLogId, leadsSaved]);

  const refreshCreditBalance = useCallback(async () => {
    try {
      const res = await apiService.getBillingCreditBalance();
      const leadPool = res.data?.pools?.lead?.balance;
      const bal =
        typeof leadPool === 'number'
          ? leadPool
          : typeof res.data?.balance === 'number'
            ? res.data.balance
            : null;
      if (typeof bal !== 'number') return;
      setCreditBalance(bal);
      window.dispatchEvent(new CustomEvent('evecta:credits-updated'));
      if (bal > 0) {
        setCreditDepletedAfterSend(false);
        setLeadGenBanner((prev) => (prev?.kind === 'credit' ? null : prev));
        setLeadGenBannerDismissed(false);
        setMessages((prev) => {
          if (!prev.some((m) => m.showUpgradePrompt)) return prev;
          return prev.filter((m) => !m.showUpgradePrompt);
        });
      }
    } catch {
      // ignore
    }
  }, []);

  const stripErrorMessagesFromChat = useCallback(
    (msgs: ChatMessage[]) => sanitizeStoredMessages(msgs),
    [],
  );

  const showCreditBanner = useCallback(() => {
    setCreditDepletedAfterSend(true);
    setLeadGenBanner({ kind: 'credit' });
    setLeadGenBannerDismissed(false);
    setMessages((prev) => stripErrorMessagesFromChat(prev));
    void refreshCreditBalance();
  }, [refreshCreditBalance, stripErrorMessagesFromChat]);

  const showErrorBanner = useCallback((rawMessage: string) => {
    const message = stripChatErrorPrefix(rawMessage) || 'Something went wrong. Please try again.';
    setLeadGenBanner({ kind: 'error', message });
    setLeadGenBannerDismissed(false);
    setMessages((prev) => stripErrorMessagesFromChat(prev));
  }, [stripErrorMessagesFromChat]);

  /** When POST /chat times out or 504 HTML is returned, the server may still finish the search and charge credits. Recover the newest matching lead log so results appear. */
  const tryRecoverLeadLogAfterSearchTimeout = useCallback(async (userMessage: string, submittedAtMs: number) => {
    const normalizedUser = userMessage.trim().toLowerCase().replace(/\s+/g, ' ');
    if (!normalizedUser) return null;

    const fetchCandidate = async () => {
      const logsRes = await apiService.getLeadLogs();
      if (!logsRes.data || !Array.isArray(logsRes.data)) return null;

      const cutoffMs = Math.max(Date.now() - 15 * 60 * 1000, submittedAtMs - 30 * 1000);
      const freshWithLeads = logsRes.data.filter((log) => {
        const created = new Date(log.created_at).getTime();
        if (Number.isNaN(created) || created < cutoffMs) return false;
        return (log.lead_count ?? 0) > 0;
      });

      // First try strict query match.
      const strict = freshWithLeads
        .filter((log) => {
          const q = (log.query || '').trim().toLowerCase().replace(/\s+/g, ' ');
          return q === normalizedUser;
        })
        .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

      // Fallback: most recent fresh log with leads (helps follow-up prompts like "in sydney").
      const best = strict[0]
        || freshWithLeads.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())[0];

      if (!best) return null;

      const detail = await apiService.getLeadLogById(best.id);
      if (!detail.data?.leads?.length) return null;
      return { logId: best.id, leads: detail.data.leads, chatTitle: detail.data.chat_title || null };
    };

    // Retry briefly because lead log insert can land just after timeout response reaches client.
    for (let attempt = 0; attempt < 3; attempt++) {
      const hit = await fetchCandidate();
      if (hit) return hit;
      if (attempt < 2) {
        await new Promise((resolve) => setTimeout(resolve, 1200 * (attempt + 1)));
      }
    }
    return null;
  }, []);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      await refreshCreditBalance();
    };
    void run();

    const onVisible = () => {
      if (document.visibilityState === 'visible' && !cancelled) void refreshCreditBalance();
    };
    document.addEventListener('visibilitychange', onVisible);
    const onFocus = () => {
      if (!cancelled) void refreshCreditBalance();
    };
    window.addEventListener('focus', onFocus);

    return () => {
      cancelled = true;
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('focus', onFocus);
    };
  }, [refreshCreditBalance]);

  // After lead results load, sync balance so the credit banner appears if the user spent their last credits.
  useEffect(() => {
    if (currentLeads.length > 0 && !isLoadingLeads && !showFullPageLoader) {
      void refreshCreditBalance();
    }
  }, [currentLeads.length, isLoadingLeads, showFullPageLoader, refreshCreditBalance]);

  // Fallback: while loader is showing and we're waiting for leads, periodically check API and sessionStorage
  // so we always transition from loader → result page when returning (never stuck on loader)
  const logIdWaitingFor = currentLogId || generatingLogId;
  useEffect(() => {
    if (!logIdWaitingFor || currentLeads.length > 0 || leadsSaved) return;
    if (!showFullPageLoader && !isLoadingLeads) return;

    const checkForLeads = async () => {
      try {
        // 1) Check sessionStorage (poller may have written after we mounted)
        const raw = sessionStorage.getItem(LEAD_GEN_STORAGE_KEY);
        if (raw) {
          const parsed = JSON.parse(raw);
          if (authUserId && parsed.userId && parsed.userId !== authUserId) {
            return;
          }
          const storedLogId = parsed.currentLogId;
          const storedLeads = parsed.currentLeads;
          if (storedLogId === logIdWaitingFor && Array.isArray(storedLeads) && storedLeads.length > 0) {
            scheduleLeadReveal(storedLeads, storedLogId, parsed.resultsTitle || null);
            return;
          }
        }
        // 2) Check API
        const res = await apiService.getLeadLogById(logIdWaitingFor);
        const leads = res?.data?.leads || [];
        const logStatus = (res?.data as any)?.status;
        if (leads.length === 0 && (logStatus === 'empty' || logStatus === 'failed')) {
          // Cold-load finished with no results (or failed) → stop the loader and tell the
          // user, instead of spinning on an empty "gathering" log forever.
          setIsLoading(false);
          setIsLoadingLeads(false);
          setShowFullPageLoader(false);
          setPendingRevealCount(null);
          expectedLogIdRef.current = null;
          stopLeadGenPolling();
          // Clear the parent's "generating" banner/flag too, so the "Thinking..." loader
          // (which also keys off isLeadGenInProgress) disappears.
          window.dispatchEvent(new CustomEvent('leadGenCancelled'));
          // Drop the log we were waiting on so a page refresh doesn't restore the loader
          // and re-poll this already-finished empty log (which would re-append the message).
          setCurrentLogId(null);
          // Only ever append the message once per log — the 1s poll and refreshes must not
          // stack duplicate "couldn't find any leads" lines.
          if (noResultsShownRef.current !== logIdWaitingFor) {
            noResultsShownRef.current = logIdWaitingFor;
            const msg = logStatus === 'failed'
              ? 'Something went wrong while loading that area. Please try again, or try another city.'
              : "I couldn't find any leads in that area — try another city, a broader industry, or a wider radius.";
            setMessages((prev) => [...prev, { type: 'ai', content: msg, timestamp: new Date() }]);
          }
          return;
        }
        if (leads.length > 0) {
          scheduleLeadReveal(leads, logIdWaitingFor, res?.data?.chat_title || null);
        }
      } catch {
        // ignore
      }
    };

    const interval = setInterval(checkForLeads, 1000);
    checkForLeads(); // run once immediately

    return () => clearInterval(interval);
  }, [logIdWaitingFor, currentLogId, currentLeads.length, leadsSaved, showFullPageLoader, isLoadingLeads, authUserId, scheduleLeadReveal]);

  // Expose methods to parent via ref
  useImperativeHandle(ref, () => ({
    hasUnsavedLeads: () => currentLeads.length > 0 && !leadsSaved,
    showSaveDialog: () => {
      if (currentLeads.length > 0 && !leadsSaved) {
        setDialogContext('navigation');
        setShowSaveAllDialog(true);
      }
    },
    resetToInitial: () => {
      handleResetToInitial();
    },
    isProcessing: () => showFullPageLoader || isLoadingLeads || isLeadGenInProgress,
    showProcessingDialog: () => {
      if (showFullPageLoader || isLoadingLeads) {
        setShowProcessingDialog(true);
      }
    }
  }));

  // Allow typing while balance is 0 until the user sends once and API returns no credits; then block.
  // Do not use isLeadGenInProgress here: Dashboard "pending/generating" can stay true after reset or stale
  // session while the welcome UI is shown, which incorrectly kept send disabled.
  const chatInputDisabled =
    isLoading || isLoadingLeads || showFullPageLoader || creditDepletedAfterSend;

  const showSubmitSpinner =
    isLoading || isLoadingLeads || showFullPageLoader;

  const examplePrompts = [
    "Find general practitioners in Melbourne with fewer than 15 employees.",
    "Show physiotherapy, chiropractic, and podiatry clinics in Brisbane with an active online presence.",
    "List nutritionists, mental health coaches, and wellness centers in Sydney offering online consultations."
  ];

  // Suggestion tags with their prompts and icons
  const suggestionTags = [
    { label: 'Location', prompt: 'Find real estate companies and brokers in Dubai, UAE actively selling properties.', icon: MapPin },
    { label: 'Find Companies', prompt: 'Find service businesses in Toronto', icon: Building2 },
    { label: 'Find E-Com', prompt: 'E-Commerce Businesses in Miami', icon: ShoppingCart },
    { label: 'Local Business', prompt: 'Local businesses in London', icon: Info }
  ];

  const handlePromptClick = (examplePrompt: string) => {
    if (creditDepletedAfterSend) return;
    setPrompt(examplePrompt);
    // Blur all prompt buttons to prevent grey color
    promptButtonRefs.current.forEach(btn => {
      if (btn) btn.blur();
    });
  };

  const handleSuggestionTagClick = (tagPrompt: string, index: number) => {
    if (creditDepletedAfterSend) return;
    setPrompt(tagPrompt);
    setSelectedSuggestionTag(index);
  };

  // Reset to initial state (show input form)
  const handleResetToInitial = () => {
    // Check if there are unsaved leads
    if (currentLeads.length > 0 && !leadsSaved) {
      setDialogContext('navigation');
      setPendingClickAction(() => () => {
        // After save/discard, reset the state
        resetState();
      });
      setShowSaveAllDialog(true);
      return;
    }
    resetState();
  };

  const resetState = async () => {
    // Call backend reset endpoint to clear chat context
    try {
      await apiService.resetChat();
      console.log("Chat context reset successfully");
    } catch (error) {
      console.error("Error resetting chat context:", error);
      // Continue with local reset even if API call fails
    }

    // Clear enrichment polling
    if (enrichmentPollingRef.current) {
      clearInterval(enrichmentPollingRef.current);
      enrichmentPollingRef.current = null;
    }
    
    // Stop global lead gen polling
    stopLeadGenPolling();

    // Sync Dashboard banner / pending state so send is not left disabled after a local reset
    window.dispatchEvent(new CustomEvent('leadGenCancelled'));
    
    // Clear sessionStorage
    try {
      sessionStorage.removeItem(LEAD_GEN_STORAGE_KEY);
    } catch (e) {
      console.error('Failed to clear chat state from sessionStorage:', e);
    }
    
    setPrompt('');
    setMessages([]);
    setCurrentLeads([]);
    setCurrentLogId(null);
    setResultsTitle(null);
    setSelectedLeads(new Set());
    setActiveTab('all');
    setSearchQuery('');
    setCurrentPage(1);
    setLeadsSaved(false);
    setSavedLeadIds(new Set());
    setShowOnlySaved(false);
    setShowFilters(false);
    setSelectedIndustries(new Set());
    setSelectedLocations(new Set());
    setScoreRange([0, 100]);
    setIsLoading(false);
    setIsLoadingLeads(false);
    setShowFullPageLoader(false);
    setShowSaveAllDialog(false);
    setShowProcessingDialog(false);
    setPendingClickAction(null);
    setDialogContext('navigation');
    setCreditDepletedAfterSend(false);
    setLeadGenBanner(null);
    setLeadGenBannerDismissed(false);
    void refreshCreditBalance();
  };

  const stopProcessing = () => {
    // Stop processing state
    setIsLoadingLeads(false);
    setShowFullPageLoader(false);
    setCurrentLogId(null);
    // Clear any pending polling (handled by state changes)
    setShowProcessingDialog(false);
  };

  /** Clear AI Lead Gen UI state before leaving for Create Campaign. */
  const clearLeadGenStateForCampaignNav = () => {
    setCurrentLeads([]);
    setCurrentLogId(null);
    setSelectedLeads(new Set());
    setSavedLeadIds(new Set());
    setMessages([]);
    setPrompt('');
    try {
      sessionStorage.removeItem(LEAD_GEN_STORAGE_KEY);
    } catch (e) {
      console.error('Failed to clear chat state from sessionStorage:', e);
    }
    onDiscardLeads?.();
  };

  /**
   * Promote log leads → Lead Database, then navigate with real Lead UUIDs.
   * Uses promote response `lead_ids` so Step 2 works even while enrichment emails
   * are still N/A (fuzzy email/name matching used to fail and show an empty list).
   */
  const promoteAndNavigateToCampaign = async (selectedIds?: string[]) => {
    if (!currentLogId) {
      console.error('No log ID available');
      return;
    }
    const response = await apiService.promoteLeadsFromLog(
      currentLogId,
      selectedIds && selectedIds.length > 0 ? selectedIds : undefined,
    );
    if (response.error) {
      const detail =
        typeof response.error === 'string'
          ? response.error
          : response.message || 'Failed to save leads';
      throw new Error(detail);
    }
    stopLeadGenPolling();
    setLeadsSaved(true);

    const databaseLeadIds = persistCampaignLeadSelection(response.data?.lead_ids || []);
    if (databaseLeadIds.length === 0) {
      throw new Error(
        response.message ||
          'Leads were saved but could not be loaded for the campaign. Open Lead Database and try Create Campaign from there.',
      );
    }

    clearLeadGenStateForCampaignNav();
    setTimeout(() => {
      onNavigateToCreateCampaign?.(databaseLeadIds);
    }, 100);
  };

  // Save chat state to sessionStorage whenever it changes
  useEffect(() => {
    if (!authUserId) {
      return;
    }
    try {
      const stateToSave = {
        messages: messages.map(msg => ({
          ...msg,
          timestamp: msg.timestamp.toISOString(), // Convert Date to string for JSON
        })),
        currentLeads,
        currentLogId,
        resultsTitle,
        prompt,
        selectedLeads: Array.from(selectedLeads),
        leadsSaved,
        leadGenTimedOut,
        creditDepletedAfterSend,
        userId: authUserId,
      };
      sessionStorage.setItem(LEAD_GEN_STORAGE_KEY, JSON.stringify(stateToSave));
    } catch (e) {
      console.error('Failed to save chat state to sessionStorage:', e);
    }
  }, [messages, currentLeads, currentLogId, resultsTitle, prompt, selectedLeads, leadsSaved, leadGenTimedOut, creditDepletedAfterSend, authUserId]);

  // Scroll chat content area to bottom when messages change
  useEffect(() => {
    const el = contentRef.current;
    if (!el) return;
    requestAnimationFrame(() => {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    });
  }, [messages]);

  // Toggle lead selection
  const toggleLeadSelection = (leadId: string) => {
    setSelectedLeads(prev => {
      const newSet = new Set(prev);
      if (newSet.has(leadId)) {
        newSet.delete(leadId);
      } else {
        newSet.add(leadId);
      }
      return newSet;
    });
  };

  // Toggle select all leads
  const toggleSelectAll = (leads: LeadLogLeadResponse[]) => {
    if (selectedLeads.size === leads.length && leads.length > 0) {
      setSelectedLeads(new Set());
    } else {
      setSelectedLeads(new Set(leads.map(l => l.id)));
    }
  };

  // Poll enrichment status when we have leads with processing status
  const ENRICHMENT_NA_CUTOFF_MS = 3 * 60 * 1000; // 3 minute: then show N/A for any lead still "processing"
  useEffect(() => {
    if (!currentLogId || currentLeads.length === 0) {
      return;
    }

    // Check if any leads are still processing
    const hasProcessingLeads = currentLeads.some(lead => 
      lead.enrichment_status === 'processing' || (!lead.email || lead.email === 'N/A')
    );

    if (!hasProcessingLeads) {
      // All leads are done, stop polling and reset cutoff
      setEnrichmentCutoffReached(false);
      if (enrichmentPollingRef.current) {
        clearInterval(enrichmentPollingRef.current);
        enrichmentPollingRef.current = null;
      }
      if (enrichmentCutoffTimerRef.current) {
        clearTimeout(enrichmentCutoffTimerRef.current);
        enrichmentCutoffTimerRef.current = null;
      }
      return;
    }

    // After 1 min, show N/A for leads still in "processing"
    setEnrichmentCutoffReached(false);
    if (enrichmentCutoffTimerRef.current) {
      clearTimeout(enrichmentCutoffTimerRef.current);
    }
    enrichmentCutoffTimerRef.current = setTimeout(() => {
      enrichmentCutoffTimerRef.current = null;
      setEnrichmentCutoffReached(true);
    }, ENRICHMENT_NA_CUTOFF_MS);

    // Start polling for enrichment status
    const pollEnrichmentStatus = async () => {
      try {
        const response = await apiService.getEnrichmentStatus(currentLogId);
        
        if (response.data) {
          // Always merge latest rows first — the final response has processing===0 but still
          // includes emails/status; previously we returned early and never updated the table.
          if (response.data.leads?.length) {
            const enrichmentMap = new Map(
              response.data.leads.map((row) => [String(row.id), row])
            );
            setCurrentLeads((prevLeads) =>
              prevLeads.map((lead) => {
                const enrichmentRow = enrichmentMap.get(String(lead.id));
                if (!enrichmentRow) return lead;
                return {
                  ...lead,
                  email: enrichmentRow.email || lead.email || 'N/A',
                  enrichment_status: enrichmentRow.enrichment_status,
                  lead_score: enrichmentRow.lead_score ?? lead.lead_score ?? 0,
                };
              })
            );
          }

          if (response.data.summary && response.data.summary.processing === 0) {
            if (enrichmentPollingRef.current) {
              clearInterval(enrichmentPollingRef.current);
              enrichmentPollingRef.current = null;
            }
          }
        }
      } catch (error) {
        console.error('Failed to fetch enrichment status:', error);
      }
    };

    // Poll immediately, then every 2 seconds
    pollEnrichmentStatus();
    enrichmentPollingRef.current = setInterval(pollEnrichmentStatus, 2000);

    // Cleanup on unmount or when dependencies change
    return () => {
      if (enrichmentPollingRef.current) {
        clearInterval(enrichmentPollingRef.current);
        enrichmentPollingRef.current = null;
      }
      if (enrichmentCutoffTimerRef.current) {
        clearTimeout(enrichmentCutoffTimerRef.current);
        enrichmentCutoffTimerRef.current = null;
      }
    };
  }, [currentLogId, currentLeads]);

  // Click interceptor to show save/discard dialog when clicking anywhere with unsaved leads
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      // Only intercept if there are unsaved leads
      if (!(currentLeads.length > 0 && !leadsSaved)) {
        return;
      }

      // Don't intercept if save dialog or discard confirmation dialog is already open
      if (showSaveAllDialog || showDiscardConfirmDialog) {
        return;
      }

      // Get the clicked element
      const target = e.target as HTMLElement;
      
      // Don't intercept if clicking on excluded elements:
      // - Save dialog elements (check for dialog overlay/container)
      // - Internal table actions (star, select checkboxes, etc.)
      // - Form inputs and textareas
      // - Filter controls
      // - Pagination controls within the table
      // - Save/Export buttons within the results area
      const isExcluded = 
        // Check if clicking inside dialog (check for data attribute)
        target.closest('[data-save-all-dialog]') !== null ||
        target.closest('[data-radix-dialog-content]') !== null ||
        target.closest('[data-slot="dialog-content"]') !== null ||
        target.closest('[data-slot="dialog-footer"]') !== null ||
        target.closest('[data-radix-dialog-footer]') !== null ||
        // Check if button text matches dialog buttons
        (target.closest('button') && (
          target.closest('button')?.innerText?.toLowerCase().includes('discard') ||
          target.closest('button')?.innerText?.toLowerCase().includes('cancel') ||
          target.closest('button')?.innerText?.toLowerCase() === 'save all leads'
        )) ||
        target.closest('input') !== null ||
        target.closest('textarea') !== null ||
        target.closest('select') !== null ||
        target.closest('.dashboard-pagination-fixed') !== null ||
        target.closest('.dashboard-pagination') !== null ||
        target.closest('.lead-generation-table-container') !== null ||
        target.closest('table') !== null ||
        target.closest('thead') !== null ||
        target.closest('tbody') !== null ||
        target.closest('tr') !== null ||
        target.closest('td') !== null ||
        target.closest('th') !== null ||
        target.closest('form') !== null ||
        target.closest('[data-testid*="filter"]') !== null ||
        target.closest('[data-testid*="Filter"]') !== null ||
        target.closest('[aria-label*="star"]') !== null ||
        target.closest('[aria-label*="Star"]') !== null ||
        target.closest('[aria-label*="select"]') !== null ||
        target.closest('[aria-label*="Select"]') !== null ||
        target.closest('svg')?.closest('button')?.getAttribute('aria-label')?.toLowerCase().includes('star') ||
        target.closest('svg')?.closest('button')?.getAttribute('aria-label')?.toLowerCase().includes('select') ||
        // Exclude save/export/create campaign buttons within the results area
        (target.closest('button') && (
          target.closest('button')?.getAttribute('aria-label')?.toLowerCase().includes('save') ||
          target.closest('button')?.innerText?.toLowerCase().includes('save all') ||
          target.closest('button')?.innerText?.toLowerCase().includes('save selected leads') ||
          target.closest('button')?.innerText?.toLowerCase().includes('export') ||
          target.closest('button')?.innerText?.toLowerCase().includes('create campaign') ||
          target.closest('button')?.getAttribute('data-create-campaign-button') === 'true' ||
          target.closest('[data-create-campaign-button]') !== null ||
          target.closest('img')?.getAttribute('alt')?.toLowerCase().includes('create campaign') ||
          target.closest('img')?.getAttribute('src')?.includes('create campaign')
        ));

      if (isExcluded) {
        return;
      }

      // Check if the click is on an interactive element (button, link, etc.)
      const isInteractiveElement = 
        target.tagName === 'BUTTON' ||
        target.tagName === 'A' ||
        target.closest('button') !== null ||
        target.closest('a') !== null ||
        target.closest('[role="button"]') !== null ||
        target.closest('[onclick]') !== null;

      if (isInteractiveElement) {
        // Check if this is a navigation action (like sidebar click)
        // For sidebar clicks, the Dashboard component already handles it
        const isNavigationAction = 
          target.closest('[data-sidebar-item]') !== null ||
          target.closest('nav') !== null ||
          target.closest('.sidebar-navigation') !== null ||
          target.closest('aside') !== null;

        // If it's a navigation action, let Dashboard handle it
        // Otherwise, intercept and show save dialog
        if (!isNavigationAction) {
          e.preventDefault();
          e.stopPropagation();
          
          // Find the actual interactive element
          const interactiveElement = target.closest('button') || target.closest('a') || (target.tagName === 'BUTTON' || target.tagName === 'A' ? target : null);
          
          if (interactiveElement) {
            // Store the original action with element reference
            const originalAction = () => {
              // Re-trigger the click after save/discard
              setTimeout(() => {
                try {
                  // Check if element still exists and is not in dialog
                  if (interactiveElement && document.contains(interactiveElement as Node) && 
                      !(interactiveElement as HTMLElement).closest('[data-radix-dialog-content]') &&
                      !(interactiveElement as HTMLElement).closest('[data-slot="dialog-content"]')) {
                    // Create a new click event to trigger the action
                    const clickEvent = new MouseEvent('click', {
                      bubbles: true,
                      cancelable: true,
                      view: window
                    });
                    (interactiveElement as HTMLElement).dispatchEvent(clickEvent);
                  }
                } catch (error) {
                  console.error('Error re-triggering click:', error);
                }
              }, 150);
            };
            
            setPendingClickAction(() => originalAction);
            setDialogContext('navigation');
            setShowSaveAllDialog(true);
          }
        }
      }
    };

    // Add click listener to the document
    document.addEventListener('click', handleClick, true); // Use capture phase

    return () => {
      document.removeEventListener('click', handleClick, true);
    };
  }, [currentLeads.length, leadsSaved, showSaveAllDialog, showDiscardConfirmDialog]);

  // Calculate visible leads based on container height
  useEffect(() => {
    const calculateVisibleLeads = () => {
      if (!tableContainerRef.current) return;
      
      const container = tableContainerRef.current;
      
      // Use clientHeight which gives the visible height of the scrollable container
      const containerHeight = container.clientHeight;
      
      // Get table header height
      const tableHeader = container.querySelector('thead');
      const headerHeight = tableHeader ? tableHeader.getBoundingClientRect().height : 40;
      
      // Calculate available height for rows (container visible height minus header)
      const availableHeight = containerHeight - headerHeight;
      
      // Approximate row height (including border)
      const rowHeight = 40;
      
      if (availableHeight > 0) {
        // Calculate how many full rows can fit in the visible area without scrolling
        const visibleRows = Math.floor(availableHeight / rowHeight);
        // Ensure at least 3 rows are shown, but use calculated value
        const calculatedCount = Math.max(3, visibleRows);
        setLastVisibleLeadIndex(calculatedCount);
      }
    };

    // Wait a bit for DOM to render, then calculate
    const timeoutId = setTimeout(() => {
      calculateVisibleLeads();
    }, 100);
    
    // Use ResizeObserver to recalculate when container size changes
    let resizeObserver: ResizeObserver | null = null;
    if (tableContainerRef.current) {
      resizeObserver = new ResizeObserver(() => {
        calculateVisibleLeads();
      });
      
      resizeObserver.observe(tableContainerRef.current);
      
      // Also recalculate on window resize
      window.addEventListener('resize', calculateVisibleLeads);
    }
    
    return () => {
      clearTimeout(timeoutId);
      if (resizeObserver) {
        resizeObserver.disconnect();
      }
      window.removeEventListener('resize', calculateVisibleLeads);
    };
  }, [currentLeads.length, activeTab, searchQuery]);

  const parseAIResponse = (message: string, data?: ChatResponse) => {
    // Use lead_count from data if available, otherwise try to extract from message
    let leadCount = data?.lead_count || 0;
    if (leadCount === 0) {
      const leadCountMatch = message.match(/(\d+)\s+lead/i) || message.match(/found\s+(\d+)/i);
      leadCount = leadCountMatch ? parseInt(leadCountMatch[1]) : 0;
    }

    // Extract average lead score from message
    const scoreMatch = message.match(/average.*?score.*?(\d+)%/i) || 
                       message.match(/(\d+)%.*?score/i) ||
                       message.match(/score.*?(\d+)%/i);
    const avgScore = scoreMatch ? parseInt(scoreMatch[1]) : null;

    // Extract industries - try multiple patterns
    let industries: string[] = [];
    const industriesMatch1 = message.match(/industries?:?\s*([^.]*?)(?:\.|$|and|with)/i);
    const industriesMatch2 = message.match(/(?:industries|types):\s*([^.]*?)(?:\.|$)/i);
    const industriesMatch = industriesMatch1 || industriesMatch2;
    
    if (industriesMatch) {
      const industriesText = industriesMatch[1].trim();
      industries = industriesText
        .split(/[,&]/)
        .map(i => i.trim())
        .filter(i => i.length > 0 && !i.match(/^(across|with|and)$/i));
    }

    // Extract location if available
    const location = data?.context?.location || '';

    return {
      leadCount,
      avgScore,
      industries,
      location,
      message
    };
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim() || chatInputDisabled) return;
    await submitChatMessage(prompt.trim());
  };

  const handleRecoveryAction = async (action: { id: string; label: string; message: string }) => {
    if (chatInputDisabled) return;
    if (action.id === 'open_billing') {
      navigate('/dashboard/settings/billing');
      return;
    }
    // Prefer stable action ids so backend can clear/repair slots correctly.
    let text = (action.message || '').trim();
    if (action.id === 'change_location') {
      text = 'change city';
    } else if (action.id === 'start_over') {
      text = 'start over';
    }
    // Never submit incomplete "industry in " stubs from older recovery payloads.
    if (/\bin\s*$/i.test(text) && text.split(/\s+/).length <= 4) {
      text = 'change city';
    }
    if (!text) return;
    await submitChatMessage(text);
  };

  const submitChatMessage = async (userMessage: string) => {
    const submitUserId = authUserId;
    if (!submitUserId) {
      return;
    }

    const submitStartedAtMs = Date.now();
    setPrompt('');
    setSelectedSuggestionTag(null);
    
    // Reset leads state when starting a new search
    setCurrentLeads([]);
    setCurrentLogId(null);
    setResultsTitle(null);
    setSelectedLeads(new Set());
    setActiveTab('all');
    setSearchQuery('');
    setCurrentPage(1);
    setItemsPerPage(10);
    setLeadsSaved(false); // Reset saved state when starting new search
    setSavedLeadIds(new Set());
    setShowOnlySaved(false);
    
    // Only show "Thinking..." until we know if it's lead gen (keeps normal chat fast)
    setLeadGenTimedOut(false);
    setIsLoading(true);

    const userMsg: ChatMessage = {
      type: 'user',
      content: userMessage,
      timestamp: new Date()
    };
    setMessages(prev => [...prev, userMsg]);

    // Persist user message immediately so it's saved if user navigates away during "Thinking..."
    try {
      const raw = sessionStorage.getItem(LEAD_GEN_STORAGE_KEY);
      const state = raw ? JSON.parse(raw) : {};
      const prevMessages = Array.isArray(state.messages) ? state.messages : [];
      const serializedUser = { ...userMsg, timestamp: userMsg.timestamp.toISOString() };
      state.messages = [...prevMessages, serializedUser];
      state.currentLeads = state.currentLeads ?? [];
      state.currentLogId = state.currentLogId ?? null;
      state.prompt = state.prompt ?? '';
      state.selectedLeads = state.selectedLeads ?? [];
      state.leadsSaved = state.leadsSaved ?? false;
      state.leadGenTimedOut = state.leadGenTimedOut ?? false;
      state.userId = submitUserId;
      sessionStorage.setItem(LEAD_GEN_STORAGE_KEY, JSON.stringify(state));
    } catch (err) {
      console.error('Failed to persist user message:', err);
    }

    // Streaming: Thinking… until the first token, then grow the same AI bubble
    // with a ChatGPT-style typewriter (tokens can arrive in bursts; we reveal
    // characters smoothly so the reply never "pops" in all at once).
    let streamedContent = '';
    let aiMessageStarted = false;
    let displayedContent = '';
    let typewriterTimer: ReturnType<typeof setInterval> | null = null;
    let typewriterDoneResolve: (() => void) | null = null;

    const stopTypewriter = () => {
      if (typewriterTimer != null) {
        clearInterval(typewriterTimer);
        typewriterTimer = null;
      }
    };

    const flushTypewriter = (): Promise<void> => {
      if (displayedContent.length >= streamedContent.length) {
        stopTypewriter();
        return Promise.resolve();
      }
      return new Promise((resolve) => {
        typewriterDoneResolve = resolve;
        // Speed up remaining text so finalize isn't delayed too long
        if (typewriterTimer == null) {
          typewriterTimer = setInterval(tickTypewriter, 12);
        }
      });
    };

    const tickTypewriter = () => {
      if (displayedContent.length >= streamedContent.length) {
        stopTypewriter();
        if (typewriterDoneResolve) {
          const r = typewriterDoneResolve;
          typewriterDoneResolve = null;
          r();
        }
        return;
      }
      // Reveal a few characters per tick for a smooth typewriter feel
      const remaining = streamedContent.length - displayedContent.length;
      const step = remaining > 80 ? 4 : remaining > 20 ? 2 : 1;
      displayedContent = streamedContent.slice(0, displayedContent.length + step);
      upsertStreamedAiMessage(displayedContent);
    };

    const ensureTypewriter = () => {
      if (typewriterTimer != null) return;
      typewriterTimer = setInterval(tickTypewriter, 18);
    };

    const discardPartialStreamedReply = () => {
      stopTypewriter();
      typewriterDoneResolve = null;
      if (!aiMessageStarted) return;
      aiMessageStarted = false;
      setMessages((prev) => {
        if (prev.length === 0) return prev;
        const last = prev[prev.length - 1];
        if (last?.type !== 'ai') return prev;
        return prev.slice(0, -1);
      });
    };

    const upsertStreamedAiMessage = (content: string, data?: ChatResponse) => {
      if (!aiMessageStarted) {
        aiMessageStarted = true;
        // First visible token — drop Thinking… so text grows in the bubble instead
        setIsLoading(false);
        setMessages((prev) => [
          ...prev,
          { type: 'ai', content, timestamp: new Date(), ...(data ? { data } : {}) },
        ]);
        return;
      }
      setMessages((prev) => {
        if (prev.length === 0) return prev;
        const next = [...prev];
        const last = next[next.length - 1];
        if (last?.type !== 'ai') return prev;
        next[next.length - 1] = { ...last, content, ...(data ? { data } : {}) };
        return next;
      });
    };

    try {
      const response = await apiService.sendChatMessageStream(userMessage, (token) => {
        if (authUserIdRef.current !== submitUserId) return;
        streamedContent += token;
        ensureTypewriter();
        // Kick first paint immediately so Thinking… disappears without waiting a tick
        if (!aiMessageStarted) {
          tickTypewriter();
        }
      });
      await flushTypewriter();
      if (authUserIdRef.current !== submitUserId) {
        return;
      }

      console.log('Chat response:', response);
      console.log('Response data:', response.data);
      console.log('Lead count:', response.data?.lead_count);
      console.log('Log ID:', response.data?.log_id);
      console.log('Status:', response.data?.status);
      
      if (response.error) {
        discardPartialStreamedReply();
        // No lead generation - hide the "Processing" banner
        window.dispatchEvent(new CustomEvent('leadGenCancelled'));
        const depleted =
          response.insufficientCredits === true ||
          isCreditDepletionText(String(response.error || ''));
        setIsLoading(false);
        setIsLoadingLeads(false);
        setShowFullPageLoader(false);
        if (depleted) {
          showCreditBanner();
        } else {
          const errStr = String(response.error || '');
          const maybeSearchTimeout =
            /time is out for searching|timed out|request timed out|timeout/i.test(errStr);

          let recovered: { logId: string; leads: LeadLogLeadResponse[]; chatTitle: string | null } | null = null;
          if (maybeSearchTimeout) {
            try {
              recovered = await tryRecoverLeadLogAfterSearchTimeout(userMessage, submitStartedAtMs);
            } catch (e) {
              console.warn('[LeadGeneration] Post-timeout lead log recovery failed:', e);
            }
          }

          if (recovered && recovered.leads.length > 0) {
            expectedLogIdRef.current = recovered.logId;
            scheduleLeadReveal(recovered.leads, recovered.logId, recovered.chatTitle);
            void refreshCreditBalance();
          } else {
            void refreshCreditBalance();
            showErrorBanner(String(response.error || 'Something went wrong. Please try again.'));
          }
        }
      } else if (response.data) {
        const status = response.data.status || '';

        if (status === 'insufficient_credits') {
          // Fixed system message — no typing effect; drop any partial bubble and show banner
          discardPartialStreamedReply();
          window.dispatchEvent(new CustomEvent('leadGenCancelled'));
          showCreditBanner();
          setIsLoading(false);
          setIsLoadingLeads(false);
          setShowFullPageLoader(false);
        } else if (status === 'error' && !(response.data.actions && response.data.actions.length > 0)) {
          discardPartialStreamedReply();
          window.dispatchEvent(new CustomEvent('leadGenCancelled'));
          showErrorBanner(
            String(response.data.message || 'Something went wrong. Please try again.'),
          );
          setIsLoading(false);
          setIsLoadingLeads(false);
          setShowFullPageLoader(false);
        } else {
        // Check if leads were generated FIRST, before showing message
        const leadCount = response.data.lead_count || 0;
        const logId = response.data.log_id;
        
        console.log('Checking lead generation:', { leadCount, logId, status });
        
        // Check if leads are being generated:
        // If log_id exists, it means leads are being generated (backend only returns log_id when processing leads)
        const isGeneratingLeads = !!logId;
        
        console.log('Is generating leads?', isGeneratingLeads);

        // Finalize from done payload (canonical text). Prefer the full server message so a
        // clipped/partial token stream (e.g. "t industry you're interested in?") never wins.
        const canonicalMessage =
          typeof response.data.message === 'string' ? response.data.message.trim() : '';
        const messageContent =
          canonicalMessage || streamedContent.trim() || 'No response received';
        const aiMsg: ChatMessage = {
          type: 'ai',
          content: messageContent,
          timestamp: new Date(),
          data: response.data,
        };
        if (aiMessageStarted) {
          upsertStreamedAiMessage(messageContent, response.data);
        } else {
          // Zero-token success (rare) — show final text at once
          setMessages((prev) => [...prev, aiMsg]);
        }
        
        if (isGeneratingLeads) {
          // Leads are being generated - keep loader showing
          expectedLogIdRef.current = logId;
          setCurrentLogId(logId);
          setIsLoadingLeads(true);
          setShowFullPageLoader(true);
          setIsLoading(false);

          // Save logId + full messages (user + AI) so when user returns they see both question and answer
          try {
            const currentState = sessionStorage.getItem(LEAD_GEN_STORAGE_KEY);
            const stateToSave = currentState ? JSON.parse(currentState) : {};
            stateToSave.currentLogId = logId;
            stateToSave.currentLeads = [];
            const prevMsgs = Array.isArray(stateToSave.messages) ? stateToSave.messages : [];
            // Replace last AI entry if we streamed it; otherwise append
            const withoutTrailingAi =
              prevMsgs.length > 0 && prevMsgs[prevMsgs.length - 1]?.type === 'ai'
                ? prevMsgs.slice(0, -1)
                : prevMsgs;
            stateToSave.messages = [
              ...withoutTrailingAi,
              { ...aiMsg, timestamp: aiMsg.timestamp.toISOString() },
            ];
            stateToSave.userId = submitUserId;
            sessionStorage.setItem(LEAD_GEN_STORAGE_KEY, JSON.stringify(stateToSave));
            window.dispatchEvent(new CustomEvent('leadGenLogIdSaved', { detail: { logId } }));
          } catch (e) {
            console.error('Failed to save logId to sessionStorage:', e);
          }

          const event = new CustomEvent('leadGenStarted', { detail: { logId, isTemporary: false } });
          window.dispatchEvent(event);
          console.log('[LeadGeneration] Dispatched leadGenStarted event with real logId:', logId);
          
          // Start global background polling (continues even if user navigates away)
          // Note: startLeadGenPolling also dispatches leadGenStarted, but we dispatch it early above
          startLeadGenPolling(logId, apiService, submitUserId);
          void refreshCreditBalance();
          
          // Also try immediate fetch in case leads are already ready
          const fetchLeadsImmediate = async () => {
            try {
              const leadsResponse = await apiService.getLeadLogById(logId);
              if (authUserIdRef.current !== submitUserId) {
                return;
              }
              if (leadsResponse.data && leadsResponse.data.leads && leadsResponse.data.leads.length > 0) {
                scheduleLeadReveal(
                  leadsResponse.data.leads,
                  logId,
                  leadsResponse.data.chat_title || null,
                );
              }
            } catch (error) {
              console.error('Failed to fetch leads immediately:', error);
              // Continue with background polling
            }
          };
          
          // Try immediate fetch
          fetchLeadsImmediate();
        } else {
          // Normal conversation - no leads being generated (e.g. "hi", "what can you do?")
          window.dispatchEvent(new CustomEvent('leadGenCancelled'));
          // Hide loader immediately so normal chat feels fast
          setIsLoading(false);
          setIsLoadingLeads(false);
          setShowFullPageLoader(false);
          // Persist full conversation (user + AI) so it's there if user navigated away and came back
          try {
            const raw = sessionStorage.getItem(LEAD_GEN_STORAGE_KEY);
            const state = raw ? JSON.parse(raw) : {};
            const prevMessages = Array.isArray(state.messages) ? state.messages : [];
            const withoutTrailingAi =
              prevMessages.length > 0 && prevMessages[prevMessages.length - 1]?.type === 'ai'
                ? prevMessages.slice(0, -1)
                : prevMessages;
            const serializedAi = { ...aiMsg, timestamp: aiMsg.timestamp.toISOString() };
            state.messages = [...withoutTrailingAi, serializedAi];
            state.userId = submitUserId;
            sessionStorage.setItem(LEAD_GEN_STORAGE_KEY, JSON.stringify(state));
          } catch (err) {
            console.error('Failed to persist AI message:', err);
          }
        }
        }
      }
    } catch (error) {
      if (authUserIdRef.current !== submitUserId) {
        return;
      }
      discardPartialStreamedReply();
      window.dispatchEvent(new CustomEvent('leadGenCancelled'));
      const errMsg = error instanceof Error ? error.message : 'Unknown error';
      const maybeSearchTimeout =
        /time is out for searching|timed out|request timed out|timeout|aborted|abort/i.test(errMsg);

      let recoveredCatch: { logId: string; leads: LeadLogLeadResponse[]; chatTitle: string | null } | null = null;
      if (maybeSearchTimeout) {
        try {
          recoveredCatch = await tryRecoverLeadLogAfterSearchTimeout(userMessage, submitStartedAtMs);
        } catch (e) {
          console.warn('[LeadGeneration] Post-timeout recovery (catch) failed:', e);
        }
      }

      if (recoveredCatch && recoveredCatch.leads.length > 0) {
        expectedLogIdRef.current = recoveredCatch.logId;
        scheduleLeadReveal(recoveredCatch.leads, recoveredCatch.logId, recoveredCatch.chatTitle);
        void refreshCreditBalance();
      } else {
        void refreshCreditBalance();
        if (isCreditDepletionText(errMsg)) {
          showCreditBanner();
        } else {
          const friendlyNetwork =
            /network error|failed to fetch|load failed|internet|offline|connection/i.test(errMsg);
          showErrorBanner(
            friendlyNetwork
              ? 'Connection issue — please check your network and try again.'
              : errMsg,
          );
        }
        setIsLoading(false);
        setIsLoadingLeads(false);
        setShowFullPageLoader(false);
      }
    }
  };

  const sidebarPx = Math.max(0, Number(layoutSidebarWidthPx) || 0);

  const layoutCssVars = {
    ['--sidebar-width' as string]: `${sidebarPx}px`,
    ['--main-content-width' as string]: `calc(100vw - ${sidebarPx}px)`,
  } as React.CSSProperties;

  return (
    <div className="lead-generation-main-container" style={layoutCssVars}>
      {/* Main Content Area */}
      <div 
        ref={contentRef}
        className="mobile-content-area lead-generation-content-area"
      >
          {(messages.length === 0 && !(showFullPageLoader || isLoadingLeads || isLoading)) ? (
          /* Welcome section - only when no messages and not loading */
          <div className="welcome-section-container lead-generation-welcome-container">
            <>
              {/* Main Prompt Section */}
              <div
                className="lead-generation-main-prompt-section"
                data-lead-gen-welcome="true"
              >
                <div
                  className="lead-generation-main-prompt-header"
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    gap: '10px',
                    margin: 0,
                    padding: 0,
                  }}
                >
                  <div className="lead-generation-main-prompt-eyebrow">Find Here!</div>
                  <h2
                    className="urbanist-heading lead-generation-main-prompt-title"
                    style={{
                      fontSize: '34px',
                      fontWeight: 500,
                      lineHeight: '120%',
                      margin: 0,
                      padding: 0,
                      textAlign: 'center',
                    }}
                  >
                    What can I help you with?
                  </h2>
                </div>
                {/* Exact 30px between headline block and chat bar (margin collapse–safe) */}
                <div className="lead-generation-welcome-spacer-30" aria-hidden />
                <div className="lead-generation-large-input-container">
                  <form ref={formRef} onSubmit={handleSubmit} className="lead-generation-main-input-form">
                    <div className="lead-generation-main-input-wrapper">
                      <Search className="lead-generation-input-icon" size={12} strokeWidth={2} />
                      <Textarea
                        value={prompt}
                        onChange={(e) => setPrompt(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' && !e.shiftKey) {
                            e.preventDefault();
                            if (prompt.trim()) formRef.current?.requestSubmit();
                          }
                        }}
                        placeholder={
                          creditDepletedAfterSend
                            ? 'Add credits in Billing to continue…'
                            : 'Find general practitioners in Melbourne with fewer than 15 employees.'
                        }
                        disabled={chatInputDisabled}
                        className="lead-generation-main-input lead-generation-main-textarea"
                        rows={1}
                      />
                      <Button
                        variant="default"
                        type="submit"
                        disabled={!prompt.trim() || chatInputDisabled}
                        className={`rounded-full lead-generation-main-input-submit${prompt.trim() ? ' lead-generation-main-input-submit-filled' : ''}`}
                      >
                        {showSubmitSpinner ? (
                          <Loader2 className="animate-spin" aria-hidden />
                        ) : (
                          <Slack aria-hidden strokeWidth={2} />
                        )}
                      </Button>
                    </div>
                  </form>
                </div>
                <div className="lead-generation-suggestion-tags" style={{ gap: gap8 }}>
                  {suggestionTags.map((tag, index) => {
                    const TagIcon = tag.icon;
                    return (
                      <button
                        key={index}
                        type="button"
                        className={`lead-generation-suggestion-tag ${selectedSuggestionTag === index ? 'lead-generation-suggestion-tag-selected' : ''}`}
                        disabled={creditDepletedAfterSend}
                        onClick={() => handleSuggestionTagClick(tag.prompt, index)}
                      >
                        <TagIcon className="lead-generation-tag-icon" size={14} />
                        <span className="lead-generation-tag-label">{tag.label}</span>
                        <ChevronUp className="lead-generation-tag-chevron" size={14} />
                      </button>
                    );
                  })}
                </div>
              </div>
            </>
          </div>
        ) : (currentLeads.length > 0) ? (
          <div className="lead-generation-results-container">
            {/* Ai Generation Results - content scrolls, pagination fixed at bottom */}
            <div className="lead-generation-results-wrapper dashboard-content-with-pagination">
                  {/* Header Section: Title, Stats, and Buttons */}
                  <div className="lead-generation-results-header-section" style={{ gap: gap4 }}>
                    {/* Title, Stats and Buttons on same line */}
                    <div className="lead-generation-results-header-row" style={{ gap: gap8 }}>
                      {/* Left side: Title and Stats */}
                      <div className="lead-generation-results-title-section">
                        {/* Title - lead log chat_title (what was actually searched); the last
                            user message is only a fallback since it can be a confirmation reply
                            like "yes" from the confirm gate */}
                        <div className="lead-generation-results-title-text">
                          {resultsTitle || (() => {
                            const lastUserMessage = messages.filter(msg => msg.type === 'user').pop();
                            return lastUserMessage?.content || prompt || 'Ai Generation Results';
                          })()}
                        </div>
                        {/* Stats */}
                        <span className="lead-generation-results-stats-text">
                          {currentLeads.length} total leads
                        </span>
                      </div>
                      {/* Right side: Buttons */}
                      <div className="lead-generation-results-actions" style={{ gap: gap8 }}>
                      {/* Conditionally show Save Selected Leads or Save All Leads */}
                      {selectedLeads.size > 0 ? (
                        <>
                          {/* Save Selected Leads — secondary (outline) */}
                          <Button
                            type="button"
                            variant="outline"
                            onClick={async () => {
                              if (!currentLogId || selectedLeads.size === 0) {
                                console.error('No log ID available or no leads selected');
                                return;
                              }
                              try {
                                // Promote selected leads from Search History to Lead Database
                                const selectedIds = Array.from(selectedLeads);
                                await apiService.promoteLeadsFromLog(currentLogId, selectedIds);
                                stopLeadGenPolling(); // Stop polling when leads are saved
                                setLeadsSaved(true);
                                console.log('Selected leads saved to Lead Database');
                                
                                // Clear state and sessionStorage to ensure fresh page when returning
                                setCurrentLeads([]);
                                setCurrentLogId(null);
                                setSelectedLeads(new Set());
                                setSavedLeadIds(new Set());
                                setMessages([]);
                                setPrompt('');
                                try {
                                  sessionStorage.removeItem(LEAD_GEN_STORAGE_KEY);
                                } catch (e) {
                                  console.error('Failed to clear chat state from sessionStorage:', e);
                                }
                                // Clear banner so returning to AI Lead Gen won't auto-load these leads
                                onDiscardLeads?.();
                                
                                // Small delay to ensure state is updated before navigation
                                setTimeout(() => {
                                  // Navigate to Lead Database page
                                  if (onNavigateToLeads) {
                                    onNavigateToLeads();
                                  }
                                }, 100);
                              } catch (error) {
                                console.error('Failed to save selected leads:', error);
                              }
                            }}
                            disabled={!currentLogId || selectedLeads.size === 0}
                            className="lead-generation-results-action-btn"
                          >
                            <Check size={16} className="lead-generation-results-action-btn-icon" strokeWidth={2} aria-hidden />
                            Save Selected Leads
                          </Button>
                          {/* Create Campaign Button - same style as Lead Log (Search History) */}
                          <Button 
                            data-create-campaign-button="true"
                            variant="default"
                            onClick={async (e) => {
                              e.stopPropagation();
                              if (!currentLogId || currentLeads.length === 0 || selectedLeads.size === 0) {
                                console.error('No log ID available, no leads available, or no leads selected');
                                return;
                              }
                              try {
                                await promoteAndNavigateToCampaign(Array.from(selectedLeads));
                              } catch (error) {
                                console.error('Failed to save leads before creating campaign:', error);
                                alert(error instanceof Error ? error.message : 'Failed to save leads before creating campaign.');
                              }
                            }}
                            disabled={!currentLogId || currentLeads.length === 0 || selectedLeads.size === 0}
                            className="lead-generation-results-action-btn"
                          >
                            <Plus size={16} className="lead-generation-results-action-btn-icon" strokeWidth={2} aria-hidden />
                            Create Campaign
                          </Button>
                        </>
                      ) : (
                        <>
                          {/* Save All Leads — secondary (outline) */}
                          <Button
                            variant="outline"
                            onClick={async () => {
                              if (!currentLogId) {
                                console.error('No log ID available');
                                return;
                              }
                              try {
                                // Promote all leads from Search History to Lead Database
                                await apiService.promoteLeadsFromLog(currentLogId);
                                stopLeadGenPolling(); // Stop polling when leads are saved
                                setLeadsSaved(true);
                                console.log('All leads saved to Lead Database');
                                
                                // Clear state and sessionStorage to ensure fresh page when returning
                                setCurrentLeads([]);
                                setCurrentLogId(null);
                                setSelectedLeads(new Set());
                                setSavedLeadIds(new Set());
                                setMessages([]);
                                setPrompt('');
                                try {
                                  sessionStorage.removeItem(LEAD_GEN_STORAGE_KEY);
                                } catch (e) {
                                  console.error('Failed to clear chat state from sessionStorage:', e);
                                }
                                // Clear banner so returning to AI Lead Gen won't auto-load these leads
                                onDiscardLeads?.();
                                
                                // Small delay to ensure state is updated before navigation
                                setTimeout(() => {
                                  // Navigate to Lead Database page
                                  if (onNavigateToLeads) {
                                    onNavigateToLeads();
                                  }
                                }, 100);
                              } catch (error) {
                                console.error('Failed to save leads:', error);
                              }
                            }}
                            disabled={!currentLogId || leadsSaved}
                            className="lead-generation-results-action-btn"
                          >
                            <Inbox size={16} className="lead-generation-results-action-btn-icon" strokeWidth={2} aria-hidden />
                            {leadsSaved ? 'Saved' : 'Save All Leads'}
                          </Button>
                          {/* Create Campaign — primary */}
                          <Button 
                            data-create-campaign-button="true"
                            variant="default"
                            onClick={async (e) => {
                              e.stopPropagation();
                              if (!currentLogId || currentLeads.length === 0) {
                                console.error('No log ID available or no leads available');
                                return;
                              }
                              try {
                                const selectedIds =
                                  selectedLeads.size > 0 ? Array.from(selectedLeads) : undefined;
                                await promoteAndNavigateToCampaign(selectedIds);
                              } catch (error) {
                                console.error('Failed to save leads before creating campaign:', error);
                                alert(error instanceof Error ? error.message : 'Failed to save leads before creating campaign.');
                              }
                            }}
                            disabled={!currentLogId || currentLeads.length === 0}
                            className="lead-generation-results-action-btn"
                          >
                            <Plus size={16} className="lead-generation-results-action-btn-icon" strokeWidth={2} aria-hidden />
                            Create Campaign
                          </Button>
                        </>
                      )}
                      </div>
                    </div>
                  </div>

                  {/* Table - Scrollable, pagination at bottom */}
                    {(() => {
                      // Start with all current leads
                      let baseLeads = currentLeads;
                      
                      // Apply tab and search filters
                      let filtered = baseLeads.filter(l => 
                            !searchQuery || 
                            l.business_name?.toLowerCase().includes(searchQuery.toLowerCase()) ||
                            l.email?.toLowerCase().includes(searchQuery.toLowerCase()) ||
                            l.contact_number != null &&
                              String(l.contact_number).toLowerCase().includes(searchQuery.toLowerCase()) ||
                            l.address?.toLowerCase().includes(searchQuery.toLowerCase()) ||
                            l.website?.toLowerCase().includes(searchQuery.toLowerCase())
                          );
                      // Apply email filter
                      if (emailFilter === 'has_email') {
                        filtered = filtered.filter(l => l.email && l.email !== 'N/A' && String(l.email).trim() !== '');
                      } else if (emailFilter === 'no_email') {
                        filtered = filtered.filter(l => !l.email || l.email === 'N/A' || String(l.email).trim() === '');
                      }
                      const filteredLeads = filtered;
                      // Apply pagination to show only the current page's leads
                      const startIndex = (currentPage - 1) * itemsPerPage;
                      const endIndex = startIndex + itemsPerPage;
                      const visibleLeads = filteredLeads.slice(startIndex, endIndex);
                      
                      return (
                        <div 
                          ref={tableContainerRef}
                          className="lead-generation-table-wrapper dashboard-data-table dashboard-pagination-scroll-area"
                        >
                          <Table className="lead-database-table lead-generation-table-element">
                            <TableHeader className="lead-generation-table-header-bg">
                              <TableRow>
                                <TableHead className="lead-generation-table-head-checkbox">
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      toggleSelectAll(visibleLeads);
                                    }}
                                    className="lead-generation-table-checkbox-button"
                                  >
                                    <div className={`lead-generation-table-checkbox-box ${selectedLeads.size === visibleLeads.length && visibleLeads.length > 0 ? 'checked' : ''}`}>
                                      {selectedLeads.size === visibleLeads.length && visibleLeads.length > 0 && (
                                        <Check className="lead-generation-table-checkbox-check" />
                                      )}
                                    </div>
                                  </button>
                                </TableHead>
                                <TableHead className="lead-generation-table-head-company">Company Name</TableHead>
                                <TableHead className="lead-generation-table-head-email">
                                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', position: 'relative' }}>
                                    <span>Email</span>
                                    <div style={{ position: 'relative' }} data-email-filter-dropdown>
                                      <button
                                        ref={emailFilterButtonRef}
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          setShowEmailFilterDropdown(!showEmailFilterDropdown);
                                        }}
                                        style={{
                                          background: 'none',
                                          border: 'none',
                                          cursor: 'pointer',
                                          padding: '2px',
                                          display: 'flex',
                                          alignItems: 'center',
                                          color: emailFilter !== 'all' ? '#4B5563' : '#6B7280'
                                        }}
                                        title="Filter by email"
                                      >
                                        <Filter size={14} />
                                      </button>
                                      {showEmailFilterDropdown && (
                                        <div
                                          ref={emailFilterDropdownRef}
                                          style={{
                                            position: 'fixed',
                                            backgroundColor: '#FFFFFF',
                                            border: '1px solid #E5E7EB',
                                            borderRadius: '4px',
                                            boxShadow: '0 2px 4px rgba(0, 0, 0, 0.08)',
                                            zIndex: 10000
                                          }}
                                          onMouseLeave={() => setShowEmailFilterDropdown(false)}
                                          data-email-filter-dropdown
                                        >
                                          <button
                                            type="button"
                                            className={emailFilter === 'all' ? 'email-filter-dropdown-option-active' : undefined}
                                            onClick={() => { setEmailFilter('all'); setShowEmailFilterDropdown(false); }}
                                          >
                                            <span className="email-filter-dropdown-check-slot">
                                              {emailFilter === 'all' ? <Check size={12} /> : null}
                                            </span>
                                            All Emails
                                          </button>
                                          <button
                                            type="button"
                                            className={emailFilter === 'has_email' ? 'email-filter-dropdown-option-active' : undefined}
                                            onClick={() => { setEmailFilter('has_email'); setShowEmailFilterDropdown(false); }}
                                          >
                                            <span className="email-filter-dropdown-check-slot">
                                              {emailFilter === 'has_email' ? <Check size={12} /> : null}
                                            </span>
                                            Has Email
                                          </button>
                                          <button
                                            type="button"
                                            className={emailFilter === 'no_email' ? 'email-filter-dropdown-option-active' : undefined}
                                            onClick={() => { setEmailFilter('no_email'); setShowEmailFilterDropdown(false); }}
                                          >
                                            <span className="email-filter-dropdown-check-slot">
                                              {emailFilter === 'no_email' ? <Check size={12} /> : null}
                                            </span>
                                            No Email
                                          </button>
                                        </div>
                                      )}
                                    </div>
                                  </div>
                                </TableHead>
                                <TableHead className="lead-generation-table-head-location">Location</TableHead>
                                <TableHead className="lead-generation-table-head-website">Website</TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {filteredLeads.length === 0 ? (
                                <TableRow>
                                  <TableCell
                                    colSpan={5}
                                    style={{
                                      textAlign: 'center',
                                      padding: '40px 20px',
                                      color: '#6B7280',
                                      width: '100%'
                                    }}
                                  >
                                    <p style={{ margin: 0, fontSize: '14px', fontWeight: 500, textAlign: 'center' }}>
                                      No leads match your current filters
                                    </p>
                                  </TableCell>
                                </TableRow>
                              ) : (
                              visibleLeads.map((lead, index) => {
                                return (
                                  <TableRow 
                                    key={lead.id} 
                                    ref={(el) => {
                                      if (el) {
                                        leadRowRefs.current[index] = el;
                                      }
                                    }}
                                    onClick={() => setSelectedLead(lead)}
                                    style={{
                                      cursor: 'pointer',
                                      backgroundColor: selectedLead?.id === lead.id ? '#F3E8FF' : undefined,
                                    }}
                                    className={`lead-generation-table-row-base lead-generation-table-row-no-hover !transition-none ${selectedLead?.id === lead.id ? 'lead-generation-table-row-selected' : '!hover:bg-white'}`}>
                                  <TableCell className="lead-generation-table-cell-checkbox">
                                    <button
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        toggleLeadSelection(lead.id);
                                      }}
                                      className="lead-generation-table-checkbox-button"
                                    >
                                      <div className={`lead-generation-table-checkbox-box ${selectedLeads.has(lead.id) ? 'checked' : ''}`}>
                                        {selectedLeads.has(lead.id) && (
                                          <Check className="lead-generation-table-checkbox-check" />
                                        )}
                                      </div>
                                    </button>
                                  </TableCell>
                                  <TableCell className="lead-generation-table-cell-base lead-generation-table-cell-company" title={lead.business_name || 'N/A'}>
                                    <span className="dashboard-table-cell-text-clip">{lead.business_name || 'N/A'}</span>
                                  </TableCell>
                                  <TableCell className="lead-generation-table-cell-base lead-generation-table-cell-email" title={lead.email || 'N/A'}>
                                    {(() => {
                                      const isProcessing = lead.enrichment_status === 'processing' || 
                                                           ((!lead.email || lead.email === 'N/A') && 
                                                            lead.enrichment_status !== 'failed' &&
                                                            lead.enrichment_status !== 'done');
                                      // After 1 min of enrichment, show N/A instead of "Processing" for leads still pending
                                      if (isProcessing && enrichmentCutoffReached) {
                                        return 'N/A';
                                      }
                                      if (isProcessing) {
                                        return (
                                          <div className="lead-generation-table-processing-container" style={{ gap: gap6 }}>
                                            <Loader2 
                                              size={12} 
                                              className="animate-spin lead-generation-table-processing-loader"
                                            />
                                            <span className="lead-generation-table-processing-text">Processing</span>
                                          </div>
                                        );
                                      }
                                      
                                      return <span className="dashboard-table-cell-text-clip">{lead.email || 'N/A'}</span>;
                                    })()}
                                  </TableCell>
                                  <TableCell className="lead-generation-table-cell-base lead-generation-table-cell-address" title={lead.address || 'N/A'}>
                                    <span className="dashboard-table-cell-text-clip">{lead.address || 'N/A'}</span>
                                  </TableCell>
                                  <TableCell className="lead-generation-table-cell-base lead-generation-table-cell-website" title={lead.website || 'N/A'}>
                                    <span className="lead-generation-table-cell-website-inner dashboard-table-cell-text-clip">
                                      {lead.website && lead.website !== 'N/A' ? (
                                        <a 
                                          href={lead.website.startsWith('http') ? lead.website : `https://${lead.website}`} 
                                          target="_blank" 
                                          rel="noopener noreferrer"
                                          className="lead-generation-table-cell-website-link"
                                        >
                                          {lead.website}
                                        </a>
                                      ) : 'N/A'}
                                    </span>
                                  </TableCell>
                                </TableRow>
                                );
                              })
                              )}
                            </TableBody>
                          </Table>
                        </div>
                      );
                    })()}

                  {/* Pagination fixed at bottom - shared design */}
                  <div className="dashboard-pagination-fixed">
                    {(() => {
                      let baseLeads = currentLeads;
                      let filtered = baseLeads.filter(l => 
                        !searchQuery || 
                        l.business_name?.toLowerCase().includes(searchQuery.toLowerCase()) ||
                        l.email?.toLowerCase().includes(searchQuery.toLowerCase()) ||
                        l.contact_number != null &&
                          String(l.contact_number).toLowerCase().includes(searchQuery.toLowerCase()) ||
                        l.address?.toLowerCase().includes(searchQuery.toLowerCase()) ||
                        l.website?.toLowerCase().includes(searchQuery.toLowerCase())
                      );
                      if (emailFilter === 'has_email') {
                        filtered = filtered.filter(l => l.email && l.email !== 'N/A' && String(l.email).trim() !== '');
                      } else if (emailFilter === 'no_email') {
                        filtered = filtered.filter(l => !l.email || l.email === 'N/A' || String(l.email).trim() === '');
                      }
                      const filteredLeads = filtered;
                      return (
                        <DashboardPagination
                          totalItems={filteredLeads.length}
                          currentPage={currentPage}
                          itemsPerPage={itemsPerPage}
                          onPageChange={setCurrentPage}
                          onItemsPerPageChange={(v) => { setItemsPerPage(v); setCurrentPage(1); }}
                          itemLabel="leads"
                          leftExtra={selectedLeads.size > 0 ? (
                            <span className="lead-generation-selected-leads-badge">
                              <Check className="lead-generation-selected-leads-badge-icon" size={12} />
                              {selectedLeads.size} {selectedLeads.size === 1 ? 'lead' : 'leads'} selected
                            </span>
                          ) : undefined}
                        />
                      );
                    })()}
                  </div>
                    
            </div>
          </div>
        ) : (
          // Show chat messages only for normal conversation (not during lead generation)
          <div className="messages-container-mobile lead-generation-messages-container" style={{ gap: gap16 }}>
            <>
              {/* Chat Messages - Only shown for normal conversation */}
              {messages.map((msg, index) => {
                if (isChatErrorMessage(msg)) {
                  return null;
                }
                // Only hide messages when leads table is showing (not during loading - we want user + loader visible)
                const shouldHideMessages = currentLeads.length > 0;
                
                if (msg.type === 'user') {
                  // Hide user message when loader is showing or when table is ready to show
                  if (shouldHideMessages) {
                    return null;
                  }
                  return (
                    <div key={index} className="lead-generation-user-message-container" style={{ gap: gap8 }}>
                      <div className="lead-generation-user-message-bubble">
                        <p className="lead-generation-user-message-text">
                          {msg.content}
                        </p>
                      </div>
                    </div>
                  );
                } else {
                  const parsed = parseAIResponse(msg.content, msg.data);
                  const leadCount = parsed.leadCount || msg.data?.lead_count || 0;
                  
                  // Only show message text if no leads were generated (i.e., it's asking for more info)
                  // When leads are generated (leadCount > 0), skip showing the asking message
                  const shouldShowMessage = leadCount === 0;
                  
                  // Hide AI message when table is ready to show (same logic as user message)
                  if (shouldHideMessages && leadCount > 0) {
                    return null;
                  }
                  
                  // Show paragraph answer: always show for normal chat, or during loading/lead generation
                  const shouldShowParagraph = leadCount === 0 || showFullPageLoader || isLoadingLeads || (leadCount > 0 && currentLeads.length === 0);
                  
                  return (
                    <div key={index} className="lead-generation-ai-message-container" style={{ gap: gap12 }}>
                      {/* AI Response Message - Always show for normal chat, hide after loader finishes for leads */}
                      {shouldShowParagraph && (
                      <div className="lead-generation-ai-message-bubble">
                          {/* Show message text for normal chat (no leads) or when leads are being generated */}
                          {shouldShowMessage && (
                        <p 
                          className={`lead-generation-ai-message-text ${leadCount > 0 ? 'lead-generation-ai-message-text-with-leads' : 'lead-generation-ai-message-text-no-leads'}`}
                        >
                          {parsed.message}
                        </p>
                          )}

                          {/* TEMP (backend-verification): exhaustion deep-link to the
                              user's most recent matching search log. Backend sends it as
                              data.exhausted.log_id. Frontend dev to redesign this. */}
                          {msg.data?.exhausted?.log_id ? (
                            <button
                              type="button"
                              style={{
                                background: 'none', border: 'none', padding: 0,
                                marginTop: 8, color: '#7c3aed', textDecoration: 'underline',
                                cursor: 'pointer', textAlign: 'left', font: 'inherit',
                              }}
                              onClick={async () => {
                                const lid = msg.data?.exhausted?.log_id as string;
                                try {
                                  setIsLoadingLeads(true);
                                  setShowFullPageLoader(true);
                                  const res = await apiService.getLeadLogById(lid);
                                  if (res?.data?.leads?.length) {
                                    setCurrentLogId(lid);
                                    setCurrentLeads(res.data.leads);
                                    setResultsTitle(res.data.chat_title || null);
                                    setLeadsSaved(false);
                                  }
                                } catch (e) {
                                  console.error('Failed to open exhaustion log:', e);
                                } finally {
                                  setIsLoadingLeads(false);
                                  setShowFullPageLoader(false);
                                }
                              }}
                            >
                              View the leads you already pulled →
                            </button>
                          ) : null}

                          {Array.isArray(msg.data?.actions) && msg.data.actions.length > 0 ? (
                            <div className="lead-generation-recovery-actions" role="group" aria-label="Suggested next steps">
                              {msg.data.actions.map((action) => (
                                <button
                                  key={action.id}
                                  type="button"
                                  className="lead-generation-recovery-action"
                                  disabled={chatInputDisabled}
                                  onClick={() => void handleRecoveryAction(action)}
                                >
                                  {action.label}
                                </button>
                              ))}
                            </div>
                          ) : null}

                          {msg.showUpgradePrompt ? (
                            <Button
                              type="button"
                              variant="default"
                              className="lead-generation-upgrade-cta"
                              onClick={() => navigate('/dashboard/settings/billing')}
                            >
                              Upgrade plan
                            </Button>
                          ) : null}

                          {/* Lead stats and "Generated X leads" - hidden per design */}
                      </div>
                      )}
                    </div>
                  );
                }
              })}

              {/* Count-first reveal: announce total leads before opening the table */}
              {pendingRevealCount != null && currentLeads.length === 0 && (
                <div className="lead-generation-ai-message-container" style={{ gap: gap12 }}>
                  <div className="lead-generation-count-reveal" role="status" aria-live="polite">
                    <p className="lead-generation-count-reveal-eyebrow">Search complete</p>
                    <p className="lead-generation-count-reveal-number">
                      {pendingRevealCount}
                    </p>
                    <p className="lead-generation-count-reveal-label">
                      {pendingRevealCount === 1 ? 'lead found' : 'leads found'}
                    </p>
                    <p className="lead-generation-count-reveal-hint">Opening your results…</p>
                  </div>
                </div>
              )}

              {/* ChatGPT-style: Loader on left when processing (including when generation continues in background) */}
              {(showFullPageLoader || isLoadingLeads || isLoading || isLeadGenInProgress) &&
                pendingRevealCount == null && (
                <div className="lead-generation-ai-message-container" style={{ gap: gap12 }}>
                  <div className="lead-generation-loader-bubble">
                    <Slack className="lead-generation-inline-loader-icon lead-generation-loader-pulse" size={20} />
                    <span className="lead-generation-loader-text">
                    {showFullPageLoader || isLoadingLeads || isLeadGenInProgress
                      ? CHAT_PROGRESS_STAGES_SEARCH[progressStageIndex]
                      : CHAT_PROGRESS_REPLY}
                      <span className="lead-generation-loader-dots">
                        <span>.</span><span>.</span><span>.</span>
                      </span>
                    </span>
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </>
          </div>
        )}
      </div>

      {messages.length > 0 && currentLeads.length === 0 && (
        <div className="lead-generation-bottom-input-container">
          <div className="lead-generation-bottom-input-wrapper">
            {showLeadGenBanner && leadGenBanner?.kind === 'credit' ? (
              <div className="lead-generation-credit-limit-banner" role="status" aria-live="polite">
                <button
                  type="button"
                  className="lead-generation-credit-limit-banner-close"
                  onClick={() => setLeadGenBannerDismissed(true)}
                  aria-label="Dismiss upgrade notice"
                >
                  <X size={16} strokeWidth={2} aria-hidden />
                </button>
                <h3 className="lead-generation-credit-limit-banner-title">Upgrade to Pro</h3>
                <p className="lead-generation-credit-limit-banner-text">
                  It looks like you&apos;ve reached your maximum credit limit for the time being. Please
                  view our plans
                </p>
                <div className="lead-generation-credit-limit-banner-footer">
                  <button
                    type="button"
                    className="lead-generation-credit-limit-banner-cta"
                    onClick={() => navigate('/dashboard/settings/billing')}
                  >
                    View plans
                  </button>
                </div>
              </div>
            ) : null}
            {showLeadGenBanner && leadGenBanner?.kind === 'error' ? (
              <div className="lead-generation-credit-limit-banner" role="alert" aria-live="polite">
                <button
                  type="button"
                  className="lead-generation-credit-limit-banner-close"
                  onClick={() => setLeadGenBannerDismissed(true)}
                  aria-label="Dismiss error notice"
                >
                  <X size={16} strokeWidth={2} aria-hidden />
                </button>
                <h3 className="lead-generation-credit-limit-banner-title">Something went wrong</h3>
                <p className="lead-generation-credit-limit-banner-text">{leadGenBanner.message}</p>
                {/* Same footer slot as credit banner so heights match */}
                <div className="lead-generation-credit-limit-banner-footer" aria-hidden />
              </div>
            ) : null}
            <form ref={formRef} onSubmit={handleSubmit} className="lead-generation-main-input-form">
              <div className="lead-generation-main-input-wrapper">
                <Search className="lead-generation-input-icon" size={12} strokeWidth={2} />
                <Textarea
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      if (prompt.trim()) formRef.current?.requestSubmit();
                    }
                  }}
                  placeholder={
                    creditDepletedAfterSend
                      ? 'Add credits in Billing to continue…'
                      : 'Find general practitioners in Melbourne with fewer than 15 employees.'
                  }
                  disabled={chatInputDisabled}
                  className="lead-generation-main-input lead-generation-main-textarea"
                  rows={1}
                />
                <div className="lead-generation-submit-column">
                  <Button
                    variant="default"
                    type="submit"
                    disabled={!prompt.trim() || chatInputDisabled}
                    className={`rounded-full lead-generation-main-input-submit${prompt.trim() ? ' lead-generation-main-input-submit-filled' : ''}`}
                  >
                    {showSubmitSpinner ? (
                      <Loader2 className="animate-spin" aria-hidden />
                    ) : (
                      <Slack aria-hidden strokeWidth={2} />
                    )}
                  </Button>
                  <LeadCreditHint />
                </div>
              </div>
            </form>
            <p className="lead-generation-chatbar-disclaimer">
              Evecta can make mistakes. Check important info.
            </p>
          </div>
        </div>
      )}

      {/* Processing Dialog - shown when navigating away during lead processing */}
      {false && showProcessingDialog && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 'var(--sidebar-width, 0)',
            right: 0,
            bottom: 0,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 100000,
            padding: '40px 16px',
            pointerEvents: 'none',
            width: 'calc(100% - var(--sidebar-width, 0))'
          }}
        >
          {/* Dialog */}
          <div
            data-processing-dialog="true"
            onClick={(e) => e.stopPropagation()}
            style={{
              backgroundColor: 'white',
              borderRadius: '12px',
              padding: window.innerWidth <= 767 ? '20px 16px' : '20px',
              boxShadow: '0 10px 25px rgba(0, 0, 0, 0.2)',
              width: window.innerWidth <= 767 ? 'calc(100% - 32px)' : '320px',
              maxWidth: window.innerWidth <= 767 ? '90%' : '320px',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              pointerEvents: 'auto'
            }}
          >
            <h2 style={{
              fontSize: window.innerWidth <= 767 ? '16px' : '16px',
              fontWeight: 600,
              color: '#111827',
              margin: '0 0 12px 0',
              fontFamily: 'Urbanist',
              textAlign: 'center'
            }}>
              Stop Processing?
            </h2>
            <p style={{
              fontSize: window.innerWidth <= 767 ? '13px' : '12px',
              color: '#6B7280',
              margin: '0 0 16px 0',
              fontFamily: 'Urbanist',
              lineHeight: window.innerWidth <= 767 ? '1.5' : '18px',
              textAlign: 'center'
            }}>
              Lead generation is in progress. Leaving this page will stop it and require a restart.

            </p>
            <div style={{
              display: 'flex',
              gap: gap8,
              justifyContent: 'center',
              marginTop: 0
            }}>
              <Button
                variant="default"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  stopProcessing();
                  if (onNavigationAttempt) {
                    setTimeout(() => {
                      onNavigationAttempt(() => {});
                    }, 100);
                  }
                }}
              >
                Proceed
              </Button>
              <Button
                variant="outline"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setShowProcessingDialog(false);
                }}
              >
                Cancel
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Save All Leads Dialog - shown when navigating away with unsaved leads */}
      {showSaveAllDialog && (
        <>
          {/* Overlay */}
          <div
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              setShowSaveAllDialog(false);
              setPendingClickAction(null);
            }}
            className="evecta-dialog-overlay lead-generation-save-all-overlay"
          />
          {/* Dialog */}
          <div
            data-save-all-dialog="true"
            onClick={(e) => e.stopPropagation()}
            className="evecta-dialog lead-generation-save-all-dialog"
          >
            <div className="evecta-dialog-header lead-generation-save-all-dialog-header">
              <h2 id="save-all-leads-dialog-title" className="evecta-dialog-title lead-generation-save-all-dialog-title">
                Save All Leads?
              </h2>
              <button
                type="button"
                aria-label="Close"
                onClick={() => {
                  setShowSaveAllDialog(false);
                  setPendingClickAction(null);
                }}
                className="evecta-dialog-close lead-generation-save-all-dialog-close"
              >
                <X className="evecta-dialog-close-x" aria-hidden strokeWidth={2} size={18} />
              </button>
            </div>
            <p className="evecta-dialog-description lead-generation-save-all-dialog-text">
              You have unsaved leads. Save all leads to the Lead Database before leaving?
            </p>
            <div className="evecta-dialog-actions lead-generation-save-all-dialog-actions">
              <button
                type="button"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setShowSaveAllDialog(false);
                  // If there's a pending navigation action, proceed with it
                  if (pendingClickAction) {
                    // User is discarding from navigation - reset state and navigate
                    const action = pendingClickAction;
                    setPendingClickAction(null);
                    // Reset state and set leadsSaved to true to prevent dialog from showing again
                    stopLeadGenPolling(); // Stop polling when leads are discarded
                    setCurrentLeads([]);
                    setCurrentLogId(null);
                    setSelectedLeads(new Set());
                    setLeadsSaved(true);
                    setSavedLeadIds(new Set());
                    setMessages([]);
                    setPrompt('');
                    // Clear sessionStorage to ensure fresh state when returning
                    try {
                      sessionStorage.removeItem(LEAD_GEN_STORAGE_KEY);
                    } catch (e) {
                      console.error('Failed to clear chat state from sessionStorage:', e);
                    }
                    onDiscardLeads?.(); // So Dashboard stops passing openWithLogId and table doesn't reappear
                    setTimeout(() => {
                      action();
                    }, 100);
                    // Notify parent to proceed with navigation
                    if (onNavigationAttempt) {
                      setTimeout(() => {
                        onNavigationAttempt(() => {});
                      }, 100);
                    }
                  } else {
                    // No pending navigation - user clicked Discard directly
                    // Show confirmation dialog - store that this is a direct discard (not navigation)
                    setShowSaveAllDialog(false);
                    // Use setTimeout to ensure state updates properly
                    setTimeout(() => {
                      setShowDiscardConfirmDialog(true);
                    }, 50);
                  }
                }}
                className="evecta-dialog-btn evecta-dialog-btn--secondary lead-generation-save-all-dialog-discard-btn"
              >
                Discard
              </button>
              <button
                type="button"
                onClick={async (e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  if (!currentLogId) {
                    console.error('No log ID available');
                    setShowSaveAllDialog(false);
                    if (dialogContext === 'navigation' && onNavigationAttempt) {
                      onNavigationAttempt(() => {});
                    }
                    return;
                  }
                  try {
                    // Save selected leads or all leads if none selected
                    const leadIdsToSave = selectedLeads.size > 0 
                      ? Array.from(selectedLeads)
                      : undefined; // undefined means save all
                    
                    await apiService.promoteLeadsFromLog(currentLogId, leadIdsToSave);
                    stopLeadGenPolling(); // Stop polling when leads are saved
                    // Update state to mark leads as saved
                    setLeadsSaved(true);
                    setShowSaveAllDialog(false);
                    console.log('Leads saved to Lead Database');
                    
                    // Clear state and sessionStorage to ensure fresh page when returning
                    setCurrentLeads([]);
                    setCurrentLogId(null);
                    setSelectedLeads(new Set());
                    setSavedLeadIds(new Set());
                    setMessages([]);
                    setPrompt('');
                    try {
                      sessionStorage.removeItem(LEAD_GEN_STORAGE_KEY);
                    } catch (e) {
                      console.error('Failed to clear chat state from sessionStorage:', e);
                    }
                    // Clear banner so returning to AI Lead Gen won't auto-load these leads
                    onDiscardLeads?.();
                    
                    // Execute pending click action if any
                    if (pendingClickAction) {
                      pendingClickAction();
                      setPendingClickAction(null);
                    }
                    // Notify parent to proceed with navigation
                    if (onNavigationAttempt) {
                      setTimeout(() => {
                        onNavigationAttempt(() => {});
                      }, 100);
                    }
                    
                    // Navigate to Lead Database after saving (similar to direct Save All Leads button)
                    setTimeout(() => {
                      if (onNavigateToLeads) {
                        onNavigateToLeads();
                      }
                    }, 150);
                  } catch (error) {
                    console.error('Failed to save leads:', error);
                    setShowSaveAllDialog(false);
                  }
                }}
                className="evecta-dialog-btn evecta-dialog-btn--primary lead-generation-save-all-dialog-save-btn"
              >
                Save All Leads
              </button>
            </div>
          </div>
        </>
      )}

      {/* Discard Confirmation Dialog - match Save All Leads dialog styling */}
      {showDiscardConfirmDialog && (
        <>
          {/* Overlay */}
          <div
            className="evecta-dialog-overlay lead-generation-save-all-overlay"
            onClick={(e) => {
              if (e.target === e.currentTarget) {
                setShowDiscardConfirmDialog(false);
                setShowSaveAllDialog(true);
              }
            }}
          />
          {/* Dialog */}
          <div
            data-save-all-dialog="true"
            onClick={(e) => e.stopPropagation()}
            className="evecta-dialog lead-generation-save-all-dialog"
          >
            <div className="evecta-dialog-header lead-generation-save-all-dialog-header">
              <h2 className="evecta-dialog-title lead-generation-save-all-dialog-title">
                Discard All Leads?
              </h2>
              <button
                type="button"
                aria-label="Close"
                onClick={() => {
                  setShowDiscardConfirmDialog(false);
                  setShowSaveAllDialog(true);
                }}
                className="evecta-dialog-close lead-generation-save-all-dialog-close"
              >
                <X className="evecta-dialog-close-x" aria-hidden strokeWidth={2} size={18} />
              </button>
            </div>
            <p className="evecta-dialog-description lead-generation-save-all-dialog-text">
              Are you sure you want to discard all unsaved leads? This action cannot be undone.
            </p>
            <div className="evecta-dialog-actions lead-generation-save-all-dialog-actions">
              <button
                type="button"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setShowDiscardConfirmDialog(false);
                  setShowSaveAllDialog(true);
                }}
                className="evecta-dialog-btn evecta-dialog-btn--secondary lead-generation-save-all-dialog-discard-btn"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setShowDiscardConfirmDialog(false);
                  
                  // Check if there's a pending navigation action
                  if (pendingClickAction) {
                    // User was trying to navigate - discard and navigate to that page
                    const action = pendingClickAction;
                    setPendingClickAction(null);
                    // Reset state first - set leadsSaved to true to prevent dialog from showing again
                    stopLeadGenPolling(); // Stop polling when leads are discarded
                    setCurrentLeads([]);
                    setCurrentLogId(null);
                    setSelectedLeads(new Set());
                    setLeadsSaved(true); // Set to true so dialog won't show again
                    setSavedLeadIds(new Set());
                    setMessages([]);
                    setPrompt('');
                    // Clear sessionStorage to ensure fresh state when returning
                    try {
                      sessionStorage.removeItem(LEAD_GEN_STORAGE_KEY);
                    } catch (e) {
                      console.error('Failed to clear chat state from sessionStorage:', e);
                    }
                    onDiscardLeads?.(); // So Dashboard stops passing openWithLogId and table doesn't reappear
                    // Then navigate
                    setTimeout(() => {
                      action();
                    }, 100);
                    // Notify parent to proceed with navigation
                    if (onNavigationAttempt) {
                      setTimeout(() => {
                        onNavigationAttempt(() => {});
                      }, 100);
                    }
                  } else {
                    // No navigation - user clicked discard directly
                    // Reset to new/empty AI Lead Gen page
                    stopLeadGenPolling(); // Stop polling when leads are discarded
                    setCurrentLeads([]);
                    setCurrentLogId(null);
                    setSelectedLeads(new Set());
                    setLeadsSaved(true); // Set to true so dialog won't show again
                    setSavedLeadIds(new Set());
                    setMessages([]);
                    setPendingClickAction(null);
                    // Clear the prompt to show a fresh page
                    setPrompt('');
                    // Clear sessionStorage to ensure fresh state when returning
                    try {
                      sessionStorage.removeItem(LEAD_GEN_STORAGE_KEY);
                    } catch (e) {
                      console.error('Failed to clear chat state from sessionStorage:', e);
                    }
                    onDiscardLeads?.(); // So Dashboard stops passing openWithLogId and table doesn't reappear
                  }
                }}
                className="evecta-dialog-btn evecta-dialog-btn--primary lead-generation-save-all-dialog-save-btn"
              >
                Discard All Leads
              </button>
            </div>
          </div>
        </>
      )}

      {/* Lead Detail Panel - when a lead row is clicked */}
      {selectedLead && (
        <LeadDetailPanel
          lead={{
            id: selectedLead.id,
            business_name: selectedLead.business_name,
            email: selectedLead.email,
            contact_number: selectedLead.contact_number,
            address: selectedLead.address,
            industry: selectedLead.industry,
            lead_score: selectedLead.lead_score,
            outreach_status: selectedLead.outreach_status,
            last_contacted: selectedLead.last_contacted,
          }}
          onClose={() => setSelectedLead(null)}
        />
      )}

    </div>
  );
});

export const LeadGeneration = LeadGenerationComponent;