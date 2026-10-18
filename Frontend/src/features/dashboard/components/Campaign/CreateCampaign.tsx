import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { useLocation } from 'react-router-dom';
import { Check, Search, Filter, SlidersHorizontal, Sparkles } from 'lucide-react';
import { DashboardPagination } from '../ui/DashboardPagination';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Textarea } from '../ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';
import { apiService, CampaignGoal } from '../../../../shared/services/api';
import { toast } from 'sonner';
import { DetailCampaignScreen } from './DetailCampaignScreen';
import { CampaignEmailScreen, CampaignEmailScreenHandle, Step3UiState } from './CampaignEmailScreen';
import { SelectEmailAccount } from './SelectEmailAccount';
import { PreviewCampaignDetail } from './PreviewCampaignDetail';
import {
  clearCampaignLeadSelection,
  persistCampaignLeadSelection,
  resolveCampaignLeadSelection,
} from '../../../../shared/utils/campaignLeadSelection';
import './CreateCampaign.css';

interface CreateCampaignProps {
  onToggleSidebar?: () => void;
  onBack?: () => void;
  onNext?: (campaignId: string) => void;
  preselectedLeadIds?: string[];
  editCampaignId?: string; // For editing existing draft campaigns
  onNavigateToGenerate?: () => void; // Step-2 CTA when there are no leads
}

type Step = 1 | 2 | 3 | 4 | 5;

interface GoalSuggestion {
  description: string;
  bestFor: string;
  approach: string;
}

// Suggestions shown in the description field based on the selected campaign goal (keyed by goal name)
const GOAL_SUGGESTIONS: Record<string, GoalSuggestion> = {
  'Generate Replies': {
    description: 'Start conversations with these leads and encourage them to respond.',
    bestFor: 'Cold leads, first-time outreach, sales prospecting.',
    approach: 'Smart Follow-up Sequence',
  },
  'Book Meetings': {
    description: 'Encourage leads to schedule a call, demo, or consultation.',
    bestFor: 'Sales calls, service consultations, demos.',
    approach: 'Smart Follow-up Sequence',
  },
  'Promote a Service': {
    description: 'Introduce your service and explain how it can help these leads.',
    bestFor: 'Agencies, IT companies, B2B service providers.',
    approach: 'Smart Follow-up Sequence',
  },
  'Sell a Product': {
    description: 'Promote a product, package, or offer to selected leads.',
    bestFor: 'Product campaigns, B2B sales, limited-time offers.',
    approach: 'Quick Outreach or Smart Sequence',
  },
  'Reconnect with Old Leads': {
    description: 'Reach out to leads who were contacted before but did not convert.',
    bestFor: 'Old databases, inactive prospects, previous inquiries.',
    approach: 'Smart Follow-up Sequence',
  },
  'Start Partnership Conversation': {
    description: 'Contact potential partners, resellers, distributors, or collaborators.',
    bestFor: 'Partnerships, channel sales, distributor outreach.',
    approach: 'Smart Follow-up Sequence',
  },
  'Send Announcement': {
    description: 'Share a company update, event invite, product launch, or notice.',
    bestFor: 'One-time updates, invitations, simple announcements.',
    approach: 'Quick Outreach',
  },
  'Test Message Angle': {
    description:
      'Send a simple message to test how this audience responds before creating a larger campaign.',
    bestFor: 'New markets, small lead groups, message testing.',
    approach: 'Quick Outreach',
  },
};

export function CreateCampaign({ onToggleSidebar, onBack, onNext, preselectedLeadIds, editCampaignId: editCampaignIdProp, onNavigateToGenerate }: CreateCampaignProps) {
  const location = useLocation();
  // Fallback: read campaign ID from URL path (/dashboard/campaigns/:id/edit) or query (?campaign_id=) when parent hasn't passed it yet
  const editMatch = location.pathname.match(/\/dashboard\/campaigns\/([^\/]+)\/edit/);
  const campaignIdFromPath = editMatch ? editMatch[1] : null;
  const campaignIdFromQuery = new URLSearchParams(location.search).get('campaign_id');
  const editCampaignId = editCampaignIdProp || campaignIdFromPath || campaignIdFromQuery || undefined;
  console.log('[DEBUG] CreateCampaign component render - editCampaignId prop:', editCampaignIdProp, 'from path:', campaignIdFromPath, 'from query:', campaignIdFromQuery, 'resolved:', editCampaignId);
  
  // Ref to access CampaignEmailScreen's handleNext
  const emailScreenRef = useRef<CampaignEmailScreenHandle | null>(null);
  // Ref to access DetailCampaignScreen's openAddManualLeadModal function
  const openAddManualLeadModalRef = useRef<(() => void) | null>(null);
  // Ref to track if we're handling OAuth callback (prevents draft loading from overriding step)
  const isOAuthCallbackRef = useRef<boolean>(false);
  
  // Initialize step: start at step 1, will be updated after loading draft data if editing
  const [currentStep, setCurrentStep] = useState<Step>(1);
  // Track the highest step reached - once user reaches a step, they can navigate back to it
  const [highestStepReached, setHighestStepReached] = useState<Step>(1);
  console.log('[DEBUG] CreateCampaign initial state - currentStep: 1 (will be updated after loading draft data)');
  const [campaignId, setCampaignId] = useState<string | null>(editCampaignId || null);
  const [finalPreselectedLeadIds, setFinalPreselectedLeadIds] = useState<string[] | undefined>(
    () => resolveCampaignLeadSelection(preselectedLeadIds),
  );
  const [searchQuery, setSearchQuery] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(10);
  const [totalLeads, setTotalLeads] = useState(0);
  const [selectedLeadsCount, setSelectedLeadsCount] = useState(0);
  const [selectedLeadIds, setSelectedLeadIds] = useState<string[]>([]); // Store selected lead IDs
  const [showFilters, setShowFilters] = useState(false);
  const [isEmailValid, setIsEmailValid] = useState(false);
  /** Step 3 spam comparison (Original vs Improved) — hide wizard Back/Next while open */
  const [isEmailSpamComparisonVisible, setIsEmailSpamComparisonVisible] = useState(false);
  const [step3UiState, setStep3UiState] = useState<Step3UiState>({
    creationMethod: 'ai',
    phase: 'compose',
    isGenerating: false,
    hasGenerated: false,
    canGenerate: false,
    isEmailValid: false,
    isSavingDraft: false,
    isLeadGenerationComplete: false,
    allLeadEmailsSpamReady: false,
    readyForOutreachCount: 0,
    partialGenerationAccepted: false,
  });
  const [emailSubject, setEmailSubject] = useState<string>('');
  const [emailContent, setEmailContent] = useState<string>('');
  // Store email data in ref to ensure it's available immediately (synchronous)
  const emailDataRef = useRef<{ subject: string; content: string }>({ subject: '', content: '' });
  const [selectedEmailAccount, setSelectedEmailAccount] = useState<'system' | 'existing' | null>(null);
  const [selectedEmailType, setSelectedEmailType] = useState<'system' | 'gmail' | 'imap' | null>(null);
  
  // Form fields
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [goalId, setGoalId] = useState<string>('');
  const [goalInput, setGoalInput] = useState('');
  
  // Dropdown options
  const [goals, setGoals] = useState<CampaignGoal[]>([]);
  const [loadingGoals, setLoadingGoals] = useState(false);
  // Start with true when editing - prevents blank page from rendering before draft loads
  const [isLoadingDraft, setIsLoadingDraft] = useState(!!editCampaignId);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [goalDropdownOpen, setGoalDropdownOpen] = useState(false);
  const [showAllGoals, setShowAllGoals] = useState(false);
  const [showAddGoalInput, setShowAddGoalInput] = useState(false);
  const leadSyncTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const lastSyncedLeadIdsKeyRef = useRef<string>('');
 
  // Fetch goals on mount
  useEffect(() => {
    fetchGoals();
  }, []);

  useEffect(() => {
    if (currentStep !== 3) {
      setIsEmailSpamComparisonVisible(false);
    }
  }, [currentStep]);

  // Handle Gmail OAuth callback and IMAP connection callback when returning from authentication
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const gmailConnected = urlParams.get('gmail_connected');
    const imapConnected = urlParams.get('imap_connected');
    const gmailError = urlParams.get('gmail_error');
    const campaignIdFromURL = urlParams.get('campaign_id');
    // IMPORTANT: `campaignEmailAccountStep` is a global key and can be stale from a different campaign.
    // When resuming/editing a specific draft (editCampaignId provided), only trust the campaign-scoped key.
    const storedEditCampaignId = sessionStorage.getItem('editCampaignId');
    const campaignIdFromStorage = editCampaignId
      ? sessionStorage.getItem(`campaignEmailAccountStep_${editCampaignId}`)
      : (sessionStorage.getItem('campaignEmailAccountStep') ||
          (storedEditCampaignId ? sessionStorage.getItem(`campaignEmailAccountStep_${storedEditCampaignId}`) : null));
    
    // Use campaign ID from URL (preferred) or from sessionStorage
    const campaignIdToUse = campaignIdFromURL || campaignIdFromStorage;
    
    // Check if we're coming from email setup loading page
    const emailSetupGoToStep5 = sessionStorage.getItem('emailSetupGoToStep5') === 'true';
    const emailSetupCampaignId = emailSetupGoToStep5 ? (sessionStorage.getItem('emailSetupCampaignId') || editCampaignId) : null;
    const finalCampaignId = campaignIdToUse || emailSetupCampaignId;
    
    if ((gmailConnected === 'true' || imapConnected === 'true') && campaignIdToUse) {
      // Mark that we're handling OAuth callback
      isOAuthCallbackRef.current = true;
      
      // Set the campaign ID so the component knows we're editing this campaign
      setCampaignId(campaignIdToUse);
      // Store it as editCampaignId in sessionStorage so Dashboard component can pick it up
      sessionStorage.setItem('editCampaignId', campaignIdToUse);
      
      // User successfully connected email account and we have a campaign ID stored
      setSelectedEmailAccount('existing');
      setSelectedEmailType(gmailConnected === 'true' ? 'gmail' : 'imap');
      // Set email sending mode to USER for this specific campaign in the database
      if (campaignIdToUse) {
        apiService.updateCampaign(campaignIdToUse, { email_sending_mode: 'USER' }).catch(err => {
          console.error('Failed to set email sending mode:', err);
        });
      }
      // Also set user preference for USER mode
      apiService.updateEmailSendingMode('USER').catch(err => {
        console.error('Failed to update email sending mode:', err);
      });
      
      const successMessage = gmailConnected === 'true' 
        ? 'Gmail account connected successfully!'
        : 'IMAP account connected successfully!';
      toast.success(successMessage);
      
      // Clean up URL parameters and sessionStorage
      window.history.replaceState({}, '', window.location.pathname);
      if (campaignIdFromStorage) {
        sessionStorage.removeItem('campaignEmailAccountStep');
        // Also remove campaign-scoped key if we can infer campaign id
        sessionStorage.removeItem(`campaignEmailAccountStep_${campaignIdFromStorage}`);
      }
      
      // Move to next step (preview) - use setTimeout to ensure this happens after state updates
      setTimeout(() => {
        setCurrentStep(5);
        setHighestStepReached(5); // Ensure progress is tracked
        console.log('[DEBUG] OAuth/IMAP callback: Set step to 5');
      }, 100);
    } else if (emailSetupGoToStep5 && finalCampaignId) {
      // Coming from email account setup loading page - go to step 5 (preview)
      setCampaignId(finalCampaignId);
      sessionStorage.setItem('editCampaignId', finalCampaignId);
      // Set email account type to system
      setSelectedEmailAccount('system');
      setSelectedEmailType('system');
      // Clear the flags
      sessionStorage.removeItem('emailSetupGoToStep5');
      sessionStorage.removeItem('emailSetupCampaignId');
      // Move to step 5 (preview) - use setTimeout to ensure this happens after state updates
      setTimeout(() => {
        setCurrentStep(5);
        setHighestStepReached(5); // Ensure progress is tracked
        console.log('[DEBUG] Email setup redirect: Set step to 5');
      }, 100);
    } else if (gmailError === 'true' && campaignIdToUse) {
      // Set the campaign ID so we stay on the right campaign
      setCampaignId(campaignIdToUse);
      sessionStorage.setItem('editCampaignId', campaignIdToUse);
      // Gmail connection failed
      const errorMessage = urlParams.get('message') || 'Failed to connect Gmail account. Please try again.';
      toast.error(errorMessage);
      // Clean up URL parameters and sessionStorage
      window.history.replaceState({}, '', window.location.pathname);
      if (campaignIdFromStorage) {
        sessionStorage.removeItem('campaignEmailAccountStep');
        sessionStorage.removeItem(`campaignEmailAccountStep_${campaignIdFromStorage}`);
      }
      // Stay on step 4 to allow retry
      setCurrentStep(4);
    } else if (
      campaignIdFromStorage &&
      !gmailConnected &&
      !imapConnected &&
      !gmailError &&
      // If we're editing a specific campaign, never let a stale storage value override it.
      (!editCampaignId || campaignIdFromStorage === editCampaignId)
    ) {
      // User navigated to OAuth page but came back without completing (no callback params)
      // Stay on step 4 to allow them to complete the email account selection
      setCampaignId(campaignIdFromStorage);
      sessionStorage.setItem('editCampaignId', campaignIdFromStorage);
      setCurrentStep(4);
      console.log('[DEBUG] User returned from OAuth without completing - staying on step 4');
    }
  }, []);

  // Load draft campaign data if editing existing campaign
  useEffect(() => {
    
    // Check if we're returning from OAuth callback - if so, don't reset step or load draft
    const urlParams = new URLSearchParams(window.location.search);
    const gmailConnected = urlParams.get('gmail_connected');
    const imapConnected = urlParams.get('imap_connected');
    const gmailError = urlParams.get('gmail_error');
    const campaignIdFromURL = urlParams.get('campaign_id');
    
    // Check if user is in the middle of OAuth flow (has campaignEmailAccountStep but no callback params)
    const storedEditCampaignId = sessionStorage.getItem('editCampaignId');
    const campaignIdFromStorage = editCampaignId
      ? sessionStorage.getItem(`campaignEmailAccountStep_${editCampaignId}`)
      : (sessionStorage.getItem('campaignEmailAccountStep') ||
          (storedEditCampaignId ? sessionStorage.getItem(`campaignEmailAccountStep_${storedEditCampaignId}`) : null));
    const hasOAuthCallbackInURL = gmailConnected === 'true' || imapConnected === 'true' || gmailError === 'true';
    const campaignIdToCheck = campaignIdFromURL || campaignIdFromStorage;
    
    // Check both URL params and ref (ref persists even after URL cleanup)
    const isOAuthCallback = isOAuthCallbackRef.current || 
      ((gmailConnected === 'true' || imapConnected === 'true' || gmailError === 'true') && campaignIdToCheck);
    
    // Check if user started OAuth but came back without completing (has campaignEmailAccountStep but no callback)
    const isOAuthInProgress =
      campaignIdFromStorage &&
      !hasOAuthCallbackInURL &&
      !isOAuthCallbackRef.current &&
      // Never treat OAuth as "in progress" for a different campaign than the one being edited
      (!editCampaignId || campaignIdFromStorage === editCampaignId);
    
    // Check if we're coming from email setup loading page
    const isEmailSetupRedirect = sessionStorage.getItem('emailSetupGoToStep5') === 'true';
    
    // If returning from OAuth or email setup redirect, don't reset step or load draft (let handler set it to step 5)
    if (isOAuthCallback || isEmailSetupRedirect) {
      console.log('[DEBUG] Returning from OAuth or email setup, skipping step reset and draft loading');
      // editCampaignId is truthy (from the campaign_id query param), so isLoadingDraft
      // initialized to true. The OAuth handler moves us to step 5 directly, so we must
      // clear the loading flag here — otherwise the full-page spinner stays up forever.
      setIsLoadingDraft(false);
      // Reset the ref after a delay to allow handler to complete
      setTimeout(() => {
        isOAuthCallbackRef.current = false;
      }, 1000);
      return;
    }
    
    // If OAuth is in progress (user started but didn't complete), stay on step 4
    if (isOAuthInProgress && campaignIdFromStorage) {
      console.log('[DEBUG] OAuth in progress - staying on step 4');
      setCampaignId(campaignIdFromStorage);
      sessionStorage.setItem('editCampaignId', campaignIdFromStorage);
      setCurrentStep(4);
      setIsLoadingDraft(false);
      return;
    }
    
    if (!editCampaignId) {
      // Creating new campaign - clear any leftover sessionStorage and ensure we're on step 1
      // BUT: Don't clear preselectedLeadIds here - it will be read by the useEffect below
      // Clear ALL leftover campaign-related sessionStorage to prevent interference
      sessionStorage.removeItem('editCampaignId');
      sessionStorage.removeItem('campaignEmailAccountStep');
      sessionStorage.removeItem('campaignEmailAccountChoice');
      sessionStorage.removeItem('openExistingEmailsTab');
      sessionStorage.removeItem('cameFromCampaign');
      // DON'T clear preselectedLeadIds here - let the useEffect below handle it after reading
    
      sessionStorage.removeItem('showImapForm');
      sessionStorage.removeItem('emailSetupGoToStep5');
      sessionStorage.removeItem('emailSetupCampaignId');
      // Clear any campaign-specific sessionStorage keys (pattern: campaignEmailAccountStep_${campaignId})
      Object.keys(sessionStorage).forEach(key => {
        if (key.startsWith('campaignEmailAccountStep_') || 
            key.startsWith('campaignEmailAccountChoice_') ||
            key.startsWith('spamCheckContentHash_') ||
            key.startsWith('spamCheckPassed_') ||
            key.startsWith('spamCheckScore_')) {
          sessionStorage.removeItem(key);
        }
      });
      
      // Reset component state to initial values for new campaign
      setCurrentStep(1);
      setHighestStepReached(1);
      setCampaignId(null);
      setSelectedEmailAccount(null);
      setSelectedEmailType(null);
      setName('');
      setDescription('');
      setGoalId('');
      setEmailSubject('');
      setEmailContent('');
      emailDataRef.current = { subject: '', content: '' };
      setSelectedLeadIds([]);
      setSelectedLeadsCount(0);
      console.log('[DEBUG] No editCampaignId, resetting to step 1 and clearing all campaign state');
      return;
    }

    // Editing existing campaign - reset local wizard state first so we don't
    // accidentally show data from the previously opened campaign while loading.
    // Clear shared sessionStorage keys that could leak data from another campaign
    clearCampaignLeadSelection();
    setCurrentStep(1);
    setHighestStepReached(1);
    setSelectedLeadIds([]);
    setSelectedLeadsCount(0);
    setFinalPreselectedLeadIds(undefined);
    setSelectedEmailAccount(null);
    setSelectedEmailType(null);
    setEmailSubject('');
    setEmailContent('');
    emailDataRef.current = { subject: '', content: '' };

    // Then load data for this specific campaign and decide which step to show.
    const loadDraftCampaign = async () => {
      setIsLoadingDraft(true);
      try {
        // Load campaign details
        const campaignResponse = await apiService.getCampaignById(editCampaignId);
        if (campaignResponse.data) {
          const campaign = campaignResponse.data;
          
          // Load name and description from backend
          // The useEffect only runs when editCampaignId changes (on mount or when switching campaigns),
          // so it's safe to load data here. User edits are preserved by auto-save functionality.
          setName(campaign.name || '');
          setDescription(campaign.description || '');
          
          // Always update goal as it's less likely to be actively edited
          setGoalId(campaign.goal_id || '');
          setCampaignId(editCampaignId);
          
          // Set selected email account type if available
          // IMPORTANT: email_sending_mode might be auto-set by backend when user connects email accounts elsewhere
          // We should only pre-select if we're certain user explicitly selected it in Step 4
          // For now, we'll check sessionStorage to see if user made a choice in Step 4
          let hasEmailAccount = false;
          const hasStep4Choice = sessionStorage.getItem(`campaignEmailAccountStep_${editCampaignId}`) === editCampaignId ||
                                 sessionStorage.getItem(`campaignEmailAccountChoice_${editCampaignId}`) ||
                                 sessionStorage.getItem('campaignEmailAccountChoice');
          
          if (campaign.email_sending_mode && hasStep4Choice) {
            // email_sending_mode is set AND user has a Step 4 choice stored - they explicitly selected it
            hasEmailAccount = true;
            const accountType = campaign.email_sending_mode === 'SYSTEM' ? 'system' : 'existing';
            setSelectedEmailAccount(accountType);
            if (campaign.email_sending_mode === 'SYSTEM') {
              setSelectedEmailType('system');
            }
          } else if (campaign.email_sending_mode && !hasStep4Choice) {
            // email_sending_mode is set but no Step 4 choice - it was likely auto-set by backend
            // Don't pre-select - let user choose in Step 4
            hasEmailAccount = false;
            setSelectedEmailAccount(null);
            setSelectedEmailType(null);
            console.log('[DEBUG] email_sending_mode exists but no Step 4 choice - likely auto-set, not pre-selecting');
          }
          
          // Check if email content exists
          let hasEmailContent = false;
          if (campaign.email_subject && campaign.email_content) {
            setEmailSubject(campaign.email_subject);
            setEmailContent(campaign.email_content);
            emailDataRef.current = { subject: campaign.email_subject, content: campaign.email_content };
            hasEmailContent = true;
          } else {
            // Try to load from draft API
            try {
              const draftResponse = await apiService.getCampaignDraft(editCampaignId);
              if (draftResponse.data) {
                if (draftResponse.data.email_subject && draftResponse.data.email_subject.trim()) {
                  setEmailSubject(draftResponse.data.email_subject);
                  emailDataRef.current.subject = draftResponse.data.email_subject;
                }
                if (draftResponse.data.email_content && draftResponse.data.email_content.trim()) {
                  setEmailContent(draftResponse.data.email_content);
                  emailDataRef.current.content = draftResponse.data.email_content;
                  hasEmailContent = true;
                }
              }
            } catch (error) {
              console.error('Failed to load email draft:', error);
            }
          }
          
          // Check if leads exist
          let hasLeads = false;
          try {
            const leadsResponse = await apiService.getCampaignLeads(editCampaignId);
            if (leadsResponse.data && Array.isArray(leadsResponse.data) && leadsResponse.data.length > 0) {
              const leadIds = leadsResponse.data.map((lead: any) => {
                return typeof lead === 'string' ? lead : lead.lead_id || lead.id;
              }).filter((id: any) => id);
              if (leadIds.length > 0) {
                hasLeads = true;
                setSelectedLeadIds(leadIds);
                setFinalPreselectedLeadIds(leadIds);
                setSelectedLeadsCount(leadIds.length);
              }
            }
          } catch (error) {
            console.error('Failed to load campaign leads:', error);
          }
          
          // Determine which step to show based on what data exists
          // Logic: Resume from the first incomplete step, or Step 5 if all steps are complete
          // IMPORTANT: email_sending_mode might be auto-set by backend when user connects email accounts elsewhere
          // We should only consider Step 4 complete if user explicitly selected it in Step 4
          // To be safe, we'll be conservative: if email_sending_mode exists but user hasn't completed Step 3,
          // we'll still show Step 4 for them to review/confirm their selection
          
          // Step 1: Campaign Setup (name, description) - checked by campaign existence
          // Step 2: Select Leads - checked by hasLeads
          // Step 3: Outreach Email Draft - checked by hasEmailContent
          // Step 4: Email Setup - should be explicitly selected by user in Step 4
          // Step 5: Review & Launch - shown when all previous steps are complete
          
          let targetStep: Step = 1; // Start from Step 1

          // Step 3 completion should only be considered "done" when the user has explicitly
          // progressed from Step 3 to Step 4 (i.e. clicked Next after a successful spam check),
          // not merely when email content exists in the database.
          //
          // We track this with a lightweight sessionStorage flag that is set when the user
          // successfully completes Step 3. If the flag is missing, we conservatively assume
          // Step 3 is still in progress and resume there.
          const step3CompletionKey = campaign.id
            ? `campaignStep3Completed_${campaign.id}`
            : editCampaignId
              ? `campaignStep3Completed_${editCampaignId}`
              : null;
          const hasStep3CompletionFlag =
            !!step3CompletionKey && sessionStorage.getItem(step3CompletionKey) === 'true';
          
          // Check Step 1 completion: Campaign Setup (name and description)
          const hasStep1Complete = campaign.name && campaign.name.trim() !== '';
          
          if (!hasStep1Complete) {
            // Step 1 incomplete - user was on Step 1
            targetStep = 1;
          } else if (!hasLeads) {
            // Step 1 complete, but Step 2 incomplete - user was on Step 2
            targetStep = 2;
          } else if (!hasEmailContent || !hasStep3CompletionFlag) {
            // Steps 1-2 complete, but Step 3 incomplete (no content or user never completed Step 3)
            // Resume the user on Step 3 so they can finish drafting and/or spam-check their email
            targetStep = 3;
          } else if (!campaign.email_sending_mode) {
            // Steps 1-3 complete, but Step 4 incomplete - user was on Step 4
            targetStep = 4;
          } else {
            // email_sending_mode is set - but we need to check if user explicitly selected it in Step 4
            // If email_sending_mode was auto-set by backend (when connecting email accounts elsewhere),
            // we should still show Step 4 so user can review/confirm their selection
            // However, if all steps 1-3 are complete AND email_sending_mode is set,
            // it's likely the user did complete Step 4, so we can go to Step 5
            // BUT: To be safe and prevent the issue where user didn't select in Step 4,
            // we'll check if there's any indication they visited Step 4
            
            // Check if user has a stored choice from Step 4 (sessionStorage flag)
            const hasStep4Choice = sessionStorage.getItem(`campaignEmailAccountStep_${editCampaignId}`) === editCampaignId ||
                                   sessionStorage.getItem(`campaignEmailAccountChoice_${editCampaignId}`) ||
                                   sessionStorage.getItem('campaignEmailAccountChoice');
            
            // If email_sending_mode is set but no Step 4 choice is stored, it was likely auto-set
            // In this case, show Step 4 so user can review/confirm
            if (!hasStep4Choice && campaign.email_sending_mode) {
              // email_sending_mode was likely auto-set by backend - show Step 4 for review
              targetStep = 4;
              console.log('[DEBUG] email_sending_mode exists but no Step 4 choice found - likely auto-set, showing Step 4 for review');
            } else {
              // User likely completed Step 4 - go to Step 5
              targetStep = 5;
            }
          }
          
          console.log('[DEBUG] Draft campaign loaded - Resuming at step:', targetStep, {
            hasStep1Complete,
            hasLeads,
            hasEmailContent,
            hasEmailSendingMode: !!campaign.email_sending_mode,
            hasStep4Choice: sessionStorage.getItem(`campaignEmailAccountStep_${editCampaignId}`) === editCampaignId ||
                           sessionStorage.getItem(`campaignEmailAccountChoice_${editCampaignId}`) ||
                           sessionStorage.getItem('campaignEmailAccountChoice')
          });
          
          setCurrentStep(targetStep);
          // Set highest step reached when loading draft
          setHighestStepReached(targetStep);
        }
      } catch (error) {
        console.error('Failed to load draft campaign:', error);
        toast.error('Failed to load campaign data');
      } finally {
        setIsLoadingDraft(false);
      }
    };
    
    loadDraftCampaign();
  }, [editCampaignId]);

  // Restore email account selection when entering step 4 (e.g. after returning from OAuth or from step 5)
  // So Gmail/IMAP/System choice and Next button state are correct
  // Use campaign-specific keys to avoid showing another campaign's selection
  useEffect(() => {
    if (currentStep !== 4 || !campaignId) return;
    const choice = sessionStorage.getItem(`campaignEmailAccountChoice_${campaignId}`) ||
                   sessionStorage.getItem('campaignEmailAccountChoice');
    const type = sessionStorage.getItem(`campaignEmailType_${campaignId}`);
    if (choice === 'managed' || type === 'system') {
      setSelectedEmailAccount('system');
      setSelectedEmailType('system');
    } else if (choice === 'existing' || type === 'gmail' || type === 'imap') {
      setSelectedEmailAccount('existing');
      if (type === 'gmail') {
        setSelectedEmailType('gmail');
      } else if (type === 'imap') {
        setSelectedEmailType('imap');
      } else {
        // Older sessions may only have choice=existing without campaignEmailType
        setSelectedEmailType('imap');
      }
    }
  }, [currentStep, campaignId]);

  // Check for preselected leads from sessionStorage or props (Lead Gen / Lead DB / Lead Log)
  useEffect(() => {
    // When editing an existing campaign (draft), always rely on the leads loaded
    // from the backend (getCampaignLeads). sessionStorage-based preselection is
    // only for brand new campaigns started from Lead Gen / Lead Database / Lead Log.
    if (editCampaignId) {
      return;
    }

    const resolved = resolveCampaignLeadSelection(preselectedLeadIds);
    console.log('[DEBUG] CreateCampaign: Resolving preselected leads', {
      propCount: preselectedLeadIds?.length || 0,
      resolvedCount: resolved?.length || 0,
      currentFinalCount: finalPreselectedLeadIds?.length || 0,
    });

    if (resolved && resolved.length > 0) {
      const prev = finalPreselectedLeadIds ? JSON.stringify([...finalPreselectedLeadIds].sort()) : '';
      const next = JSON.stringify([...resolved].sort());
      if (prev !== next) {
        setFinalPreselectedLeadIds(resolved);
      }
      // Keep both storage keys in sync until Step 2 has loaded them
      persistCampaignLeadSelection(resolved);
      return;
    }

    // Props explicitly empty → show all leads
    if (Array.isArray(preselectedLeadIds) && preselectedLeadIds.length === 0) {
      clearCampaignLeadSelection();
      if (finalPreselectedLeadIds !== undefined) {
        setFinalPreselectedLeadIds(undefined);
      }
      return;
    }

    // Prop undefined but we already resolved once — keep selection
    if (preselectedLeadIds === undefined && finalPreselectedLeadIds !== undefined) {
      return;
    }

    // Nothing selected from any source
    clearCampaignLeadSelection();
    if (finalPreselectedLeadIds !== undefined) {
      setFinalPreselectedLeadIds(undefined);
    }
  }, [preselectedLeadIds, editCampaignId]);

  const fetchGoals = async () => {
    setLoadingGoals(true);
    try {
      const response = await apiService.getCampaignGoals();
      if (response.data) {
        setGoals(response.data);
      }
    } catch (error) {
      console.error('Failed to fetch campaign goals:', error);
      toast.error('Failed to load campaign goals');
    } finally {
      setLoadingGoals(false);
    }
  };

  const handleGenerateNewLeadsFromStep2 = useCallback(() => {
    if (!campaignId) return;
    // Used by Dashboard when navigating from Lead Gen -> campaign-creation.
    // This lets us resume the same draft campaign instead of starting fresh.
    sessionStorage.setItem('resumeCampaignId', campaignId);
    onNavigateToGenerate?.();
  }, [campaignId, onNavigateToGenerate]);

  const handleAddGoal = async () => {
    if (!goalInput.trim()) return;
    
    try {
      const response = await apiService.createCampaignGoal({ name: goalInput.trim() });
      if (response.data) {
        // Add new goal at the top of the list
        setGoals([response.data, ...goals]);
        setGoalId(response.data.id);
        setGoalInput('');
        setShowAddGoalInput(false);
        toast.success('Goal added successfully');
      }
    } catch (error: any) {
      console.error('Failed to add goal:', error);
      toast.error(error?.message || 'Failed to add goal');
    }
  };

  const handleGoalInputKeyPress = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleAddGoal();
    } else if (e.key === 'Escape') {
      setShowAddGoalInput(false);
      setGoalInput('');
    }
  };

  const handleNext = async () => {
    // For step 3, call CampaignEmailScreen's handleNext
    if (currentStep === 3) {
      if (emailScreenRef.current) {
        await emailScreenRef.current.handleNext();
      }
      return;
    }
    
    // For step 4, allow manual navigation if email account is selected
    if (currentStep === 4) {
      if (isStep4Valid && campaignId) {
        // Navigate to step 5 if email account is selected
        setCurrentStep(5);
      } else {
        // Show error if no account selected
        toast.error('Please select an email account to continue');
      }
      return;
    }
    
    // Validate step 1 fields
    if (currentStep === 1) {
      // Check for missing required fields and show helpful messages
      const missingFields: string[] = [];
      if (!name.trim()) {
        missingFields.push('Campaign Name');
      }
      if (!description.trim()) {
        missingFields.push('Description');
      }

      if (missingFields.length > 0) {
        toast.error(`Please complete the required fields: ${missingFields.join(', ')}`, {
          duration: 4000,
        });
        return;
      }

      const payload = {
        name: name.trim(),
        description: description.trim(),
        goal_id: goalId || undefined,
      };

      setIsSubmitting(true);
      try {
        // Reuse existing draft when user goes back to step 1 and clicks Next again (no duplicate campaigns)
        if (campaignId) {
          const response = await apiService.updateCampaign(campaignId, payload);
          if (response.error) {
            toast.error(response.error || response.message || 'Failed to update campaign');
            return;
          }
          requestAnimationFrame(() => {
            setTimeout(() => {
              setCurrentStep(2);
            }, 200);
          });
          if (onNext) {
            onNext(campaignId);
          }
        } else {
          // First time: create a single draft campaign
          const response = await apiService.createCampaign(payload);
          if (response.error) {
            toast.error(response.error || response.message || 'Failed to create campaign');
            return;
          }
          if (response.data) {
            setCampaignId(response.data.id);
            toast.success('Campaign successfully configured', {
              id: 'campaign-creation-complete',
              duration: 3000,
            });
            requestAnimationFrame(() => {
              setTimeout(() => {
                setCurrentStep(2);
              }, 200);
            });
            if (onNext) {
              onNext(response.data.id);
            }
          } else {
            toast.error('Failed to create campaign');
          }
        }
      } catch (error: any) {
        console.error('Failed to create/update campaign:', error);
        const errorMessage = error?.error ||
                            error?.message ||
                            error?.response?.error ||
                            error?.response?.message ||
                            error?.detail ||
                            'Failed to create campaign';
        toast.error(errorMessage);
      } finally {
        setIsSubmitting(false);
      }
    }
    
    if (currentStep === 2) {
      // Validate step 2 - check if leads are selected
      if (selectedLeadsCount === 0) {
        toast.error('Please select at least one lead to continue', {
          duration: 4000,
        });
        return;
      }
      // Move to step 3
      setCurrentStep(3);
    }
  };

  // Memoize the onSelectedLeadsChange callback to prevent unnecessary re-renders
  // This callback receives the count, but we also need to track the actual IDs
  const handleSelectedLeadsChange = useCallback((count: number) => {
    console.log('[DEBUG] CreateCampaign: Received onSelectedLeadsChange callback with count:', count);
    setSelectedLeadsCount(count);
    console.log('[DEBUG] CreateCampaign: Updated selectedLeadsCount to:', count);
    console.log('[DEBUG] CreateCampaign: isStep2Valid will be:', count > 0);
  }, []);

  // Callback to receive selected lead IDs from DetailCampaignScreen
  // Only update selectedLeadIds state, NOT finalPreselectedLeadIds to prevent infinite loops
  // finalPreselectedLeadIds is only updated when:
  // 1. User clicks Next (in onNext callback)
  // 2. User goes back from Step 3 (in handleBack)
  const handleSelectedLeadIdsChange = useCallback((leadIds: string[]) => {
    console.log('[DEBUG] CreateCampaign: Received selected lead IDs:', leadIds);
    setSelectedLeadIds(prevIds => {
      // Only update if IDs actually changed
      const prevIdsString = JSON.stringify([...prevIds].sort());
      const newIdsString = JSON.stringify([...leadIds].sort());
      if (prevIdsString === newIdsString) {
        console.log('[DEBUG] CreateCampaign: IDs unchanged, skipping update');
        return prevIds;
      }
      console.log('[DEBUG] CreateCampaign: IDs changed, updating selectedLeadIds only');
      return leadIds;
    });
    // IMPORTANT: Don't update finalPreselectedLeadIds here!
    // Updating it would change the prop, which triggers useEffect in DetailCampaignScreen,
    // which calls this callback again, creating an infinite loop
  }, []);

  const syncSelectedLeadsToCampaign = useCallback(async (leadIds: string[]) => {
    if (!campaignId) return;
    const realLeadIds = (leadIds || []).filter((id) => id && !id.startsWith('manual-'));
    if (realLeadIds.length === 0) return;
    const uniqueSorted = Array.from(new Set(realLeadIds)).sort();
    const syncKey = `${campaignId}:${JSON.stringify(uniqueSorted)}`;
    if (lastSyncedLeadIdsKeyRef.current === syncKey) return;
    try {
      const response = await apiService.syncCampaignLeads(campaignId, uniqueSorted);
      if (!response.error) {
        lastSyncedLeadIdsKeyRef.current = syncKey;
      }
    } catch (error) {
      console.error('[DEBUG] CreateCampaign: Failed to sync selected leads:', error);
    }
  }, [campaignId]);

  // Safety net: persist Step-2 selections even if user exits quickly before child debounce completes.
  useEffect(() => {
    if (!campaignId || currentStep < 2) return;
    const idsToSync = selectedLeadIds.length > 0 ? selectedLeadIds : (finalPreselectedLeadIds || []);
    const realCount = idsToSync.filter((id) => id && !id.startsWith('manual-')).length;
    if (realCount === 0) return;

    if (leadSyncTimeoutRef.current) {
      clearTimeout(leadSyncTimeoutRef.current);
    }
    leadSyncTimeoutRef.current = setTimeout(() => {
      void syncSelectedLeadsToCampaign(idsToSync);
    }, 250);

    return () => {
      if (leadSyncTimeoutRef.current) {
        clearTimeout(leadSyncTimeoutRef.current);
      }
    };
  }, [campaignId, currentStep, selectedLeadIds, finalPreselectedLeadIds, syncSelectedLeadsToCampaign]);

  const loadStep1FromBackend = useCallback(async (id: string) => {
    try {
      const campaignResponse = await apiService.getCampaignById(id);
      if (campaignResponse.data) {
        const campaign = campaignResponse.data;
        setName(campaign.name || '');
        setDescription(campaign.description || '');
        setGoalId(campaign.goal_id || '');
        return campaign;
      }
    } catch (error) {
      console.error('Failed to load Step 1 data:', error);
    }
    return null;
  }, []);

  /** Only persist Step 1 when local state has data — avoids wiping the DB from empty wizard state on steps 2–5. */
  const saveStep1IfPresent = useCallback(async (id: string) => {
    if (!name.trim() && !description.trim() && !goalId) {
      return;
    }
    try {
      await apiService.updateCampaign(id, {
        name: name.trim(),
        description: description.trim(),
        goal_id: goalId || undefined,
      });
    } catch (error) {
      console.error('Failed to auto-save Step 1 data:', error);
    }
  }, [name, description, goalId]);

  const handleBack = async () => {
    if (currentStep === 1) {
      // If user exits from campaign creation after selecting leads, force a final sync.
      const idsToSync = selectedLeadIds.length > 0 ? selectedLeadIds : (finalPreselectedLeadIds || []);
      if (campaignId && idsToSync.length > 0) {
        await syncSelectedLeadsToCampaign(idsToSync);
      }
      // Go back to previous page
      if (onBack) {
        onBack();
      }
    } else if (currentStep === 2 && campaignId) {
      await saveStep1IfPresent(campaignId);
      setCurrentStep(1);
      await loadStep1FromBackend(campaignId);
    } else if (currentStep === 3 && campaignId) {
      if (step3UiState.phase === 'lead-generation') {
        emailScreenRef.current?.requestBackFromLeadGeneration();
        return;
      }
      await saveStep1IfPresent(campaignId);
      // When going back from Step 3 to Step 2, use stored selectedLeadIds first
      // Then try to fetch from backend as a fallback/verification
      if (selectedLeadIds.length > 0) {
        console.log('[DEBUG] Going back to Step 2, using stored selected lead IDs:', selectedLeadIds);
        setFinalPreselectedLeadIds(selectedLeadIds);
        setSelectedLeadsCount(selectedLeadIds.length);
      } else {
        // If no stored IDs, try fetching from backend
        try {
          console.log('[DEBUG] Going back to Step 2, fetching synced leads for campaign:', campaignId);
          const leadsResponse = await apiService.getCampaignLeads(campaignId);
          if (leadsResponse.data && Array.isArray(leadsResponse.data)) {
            const leadIds = leadsResponse.data.map((lead: any) => {
              if (typeof lead === 'string') return lead;
              // Use lead_id (actual lead) or lead.lead?.id (from nested/snapshot), NOT lead.id (campaign_lead row id)
              return lead.lead_id || lead.lead?.id || lead.id;
            }).filter((id: any) => id); // Filter out any null/undefined
            
            console.log('[DEBUG] Fetched synced lead IDs from backend:', leadIds);
            if (leadIds.length > 0) {
              setSelectedLeadIds(leadIds);
              setFinalPreselectedLeadIds(leadIds);
              setSelectedLeadsCount(leadIds.length);
            }
          }
        } catch (error) {
          console.error('Failed to fetch synced leads when going back:', error);
        }
      }
      // Go to previous step
      setCurrentStep((currentStep - 1) as Step);
    } else if (currentStep === 4 && campaignId) {
      await saveStep1IfPresent(campaignId);
      // When at Step 4 (Select Email Account), going back should go to Step 3
      setCurrentStep(3);
    } else if (currentStep === 5 && campaignId) {
      await saveStep1IfPresent(campaignId);
      // When at Step 5 (Preview), going back should go to Step 4
      setCurrentStep(4);
    } else {
      // Go to previous step
      setCurrentStep((currentStep - 1) as Step);
    }
  };

  // Check if step 1 is valid (all required fields filled)
  const isStep1Valid = name.trim() !== '' && description.trim() !== '';
  // For step 2, check if leads are selected
  const isStep2Valid = selectedLeadsCount > 0;
  // For step 3, check if email is valid
  const isStep3Valid = isEmailValid;
  // For step 4, check if email account is selected
  const isStep4Valid = selectedEmailAccount !== null;
  const isNextButtonReady = !isSubmitting && (
    currentStep === 1 ? isStep1Valid : 
    currentStep === 2 ? isStep2Valid : 
    currentStep === 3 ? isStep3Valid :
    currentStep === 4 ? isStep4Valid :
    true
  );
  
  // Debug logging for Step 2 button state
  useEffect(() => {
    if (currentStep === 2) {
      console.log('[DEBUG] CreateCampaign Step 2 state:', {
        selectedLeadsCount,
        isStep2Valid,
        isNextButtonReady,
        isSubmitting
      });
    }
  }, [currentStep, selectedLeadsCount, isStep2Valid, isNextButtonReady, isSubmitting]);

  // Update highest step reached when current step changes forward
  useEffect(() => {
    if (currentStep > highestStepReached) {
      setHighestStepReached(currentStep);
    }
  }, [currentStep, highestStepReached]);

  // Load step 1 data when navigating to step 1 (if data is missing)
  // Use a ref to track if we're already loading to prevent duplicate requests
  const isLoadingStep1DataRef = useRef(false);
  
  useEffect(() => {
    // Only load if:
    // 1. We're on step 1
    // 2. We have a campaignId (campaign exists)
    // 3. Name and description are empty (data might be missing)
    // 4. We're not already loading
    // 5. Add a small delay to let handleStepClick run first (if it was triggered)
    if (currentStep === 1 && campaignId && (!name.trim() || !description.trim()) && !isLoadingStep1DataRef.current) {
      console.log('[DEBUG] Step 1: Detected empty fields after navigation, loading from backend as backup...');
      isLoadingStep1DataRef.current = true;
      
      // Add a small delay to ensure handleStepClick has a chance to load data first
      const timeoutId = setTimeout(async () => {
        // Double-check that fields are still empty (handleStepClick might have loaded them)
        if (!name.trim() || !description.trim()) {
          try {
            await loadStep1FromBackend(campaignId);
            console.log('[DEBUG] Step 1: Data loaded from backend in useEffect (backup)');
          } catch (error) {
            console.error('Failed to load Step 1 data in useEffect:', error);
          } finally {
            isLoadingStep1DataRef.current = false;
          }
        } else {
          // Fields are no longer empty, handleStepClick must have loaded them
          console.log('[DEBUG] Step 1: Fields are no longer empty, skipping useEffect load');
          isLoadingStep1DataRef.current = false;
        }
      }, 100); // Small delay to let handleStepClick run first
      
      return () => {
        clearTimeout(timeoutId);
        isLoadingStep1DataRef.current = false;
      };
    }
  }, [currentStep, campaignId]); // Only depend on currentStep and campaignId

  // Auto-save Step 1 data when user is on step 1 and changes name/description (debounced)
  useEffect(() => {
    // Only auto-save if:
    // 1. We're on step 1
    // 2. We have a campaignId (campaign exists)
    // 3. Name or description has content
    if (currentStep === 1 && campaignId && (name.trim() || description.trim())) {
      const timeoutId = setTimeout(async () => {
        try {
          const payload = {
            name: name.trim(),
            description: description.trim(),
            goal_id: goalId || undefined,
          };
          await apiService.updateCampaign(campaignId, payload);
          console.log('[DEBUG] Step 1 data auto-saved (debounced)');
        } catch (error) {
          console.error('Failed to auto-save Step 1 data:', error);
        }
      }, 1000); // Wait 1 second after user stops typing

      return () => clearTimeout(timeoutId);
    }
  }, [name, description, goalId, currentStep, campaignId]);

  // Handle stepper step click - allow navigation to any step up to the highest step reached
  const handleStepClick = async (stepNumber: Step) => {
    // Don't allow navigation if clicking the current step
    if (stepNumber === currentStep) {
      return;
    }

    if (stepNumber >= 3 && selectedLeadsCount === 0) {
      toast.error('Please select at least one lead before continuing');
      return;
    }

    // Allow navigation to any step up to the highest step reached
    if (stepNumber <= highestStepReached) {
      // If navigating to step 1 from another step, reload data from backend first
      if (stepNumber === 1 && campaignId && currentStep !== 1) {
        console.log('[DEBUG] Navigating to step 1, loading data from backend...');
        try {
          // Always reload campaign data from backend to ensure form fields are populated
          // This ensures data is shown even if state was lost
          const campaignResponse = await apiService.getCampaignById(campaignId);
          if (campaignResponse.data) {
            const campaign = campaignResponse.data;
            console.log('[DEBUG] Step 1 data received from backend:', {
              name: campaign.name || 'EMPTY',
              description: campaign.description || 'EMPTY',
              goalId: campaign.goal_id || 'EMPTY',
            });
            
            // Update all state variables together, then change step
            // React will batch these updates, but we'll use requestAnimationFrame to ensure
            // the state is set before the step changes
            setName(campaign.name || '');
            setDescription(campaign.description || '');
            setGoalId(campaign.goal_id || '');
            
            // Use requestAnimationFrame to ensure state updates are flushed before changing step
            requestAnimationFrame(() => {
              setCurrentStep(stepNumber);
              console.log('[DEBUG] Step changed to 1 after data loaded');
            });
            return; // Exit early since we've already set the step
          } else {
            console.warn('[DEBUG] No campaign data received from backend');
            setCurrentStep(stepNumber);
            return;
          }
        } catch (error) {
          console.error('Failed to reload Step 1 data:', error);
          // Even if reload fails, still navigate to step 1
          setCurrentStep(stepNumber);
          return;
        }
      }
      
      // If navigating to step 2, restore selected leads
      if (stepNumber === 2 && campaignId) {
        // First, try to use stored selectedLeadIds
        if (selectedLeadIds.length > 0) {
          console.log('[DEBUG] Navigating to Step 2, restoring selected leads from state:', selectedLeadIds);
          setFinalPreselectedLeadIds(selectedLeadIds);
          setSelectedLeadsCount(selectedLeadIds.length);
        } else {
          // If no stored IDs, fetch from backend
          try {
            console.log('[DEBUG] Navigating to Step 2, fetching leads from backend for campaign:', campaignId);
            const leadsResponse = await apiService.getCampaignLeads(campaignId);
            if (leadsResponse.data && Array.isArray(leadsResponse.data)) {
              const leadIds = leadsResponse.data.map((lead: any) => {
                return typeof lead === 'string' ? lead : lead.lead_id || lead.id;
              }).filter((id: any) => id);
              
              if (leadIds.length > 0) {
                console.log('[DEBUG] Fetched lead IDs from backend when navigating to Step 2:', leadIds);
                setSelectedLeadIds(leadIds);
                setFinalPreselectedLeadIds(leadIds);
                setSelectedLeadsCount(leadIds.length);
              }
            }
          } catch (error) {
            console.error('Failed to fetch leads when navigating to Step 2:', error);
          }
        }
      }
      
      // If navigating to step 3, ensure email data is loaded
      if (stepNumber === 3 && campaignId) {
        // Check if email data exists in state/ref, if not, try to load from backend
        if (!emailContent && !emailDataRef.current.content) {
          try {
            const campaignResponse = await apiService.getCampaignById(campaignId);
            if (campaignResponse.data) {
              const campaign = campaignResponse.data;
              if (campaign.email_subject || campaign.email_content) {
                setEmailSubject(campaign.email_subject || '');
                setEmailContent(campaign.email_content || '');
                emailDataRef.current = {
                  subject: campaign.email_subject || '',
                  content: campaign.email_content || ''
                };
                console.log('[DEBUG] Email data reloaded from backend when navigating to Step 3');
              } else {
                // Try to load from draft API
                try {
                  const draftResponse = await apiService.getCampaignDraft(campaignId);
                  if (draftResponse.data) {
                    if (draftResponse.data.email_subject || draftResponse.data.email_content) {
                      setEmailSubject(draftResponse.data.email_subject || '');
                      setEmailContent(draftResponse.data.email_content || '');
                      emailDataRef.current = {
                        subject: draftResponse.data.email_subject || '',
                        content: draftResponse.data.email_content || ''
                      };
                      console.log('[DEBUG] Email data reloaded from draft API when navigating to Step 3');
                    }
                  }
                } catch (error) {
                  console.error('Failed to load email draft when navigating to Step 3:', error);
                }
              }
            }
          } catch (error) {
            console.error('Failed to reload email data when navigating to Step 3:', error);
          }
        }
      }
      
      setCurrentStep(stepNumber);
    } else {
      // Show a message that they need to complete previous steps first
      toast.error(`Please complete the previous steps before navigating to step ${stepNumber}`);
    }
  };

  // Check if a step is clickable (any step up to highestStepReached, except current step)
  const isStepClickable = (stepNumber: Step): boolean => {
    // Current step is not clickable (already there)
    if (stepNumber === currentStep) {
      return false;
    }

    // Do not allow jumping past Step 2 until at least one lead is selected
    if (stepNumber >= 3 && selectedLeadsCount === 0) {
      return false;
    }

    // Allow navigation to any step up to the highest step reached
    return stepNumber <= highestStepReached;
  };

  // On goal change, pre-fill the description with the goal's suggestion so the
  // user can keep or edit it — but never overwrite text the user typed themselves.
  const handleGoalChange = (newGoalId: string) => {
    setGoalId(newGoalId);
    const goal = goals.find((g) => g.id === newGoalId);
    const suggestion = goal ? GOAL_SUGGESTIONS[goal.name] : undefined;
    const isUserTyped =
      description.trim() !== '' &&
      !Object.values(GOAL_SUGGESTIONS).some(
        (s) => s.description === description.trim()
      );
    if (!isUserTyped) {
      setDescription(suggestion ? suggestion.description : '');
    }
  };

  const renderStepContent = () => {
    switch (currentStep) {
      case 1: {
        const selectedGoal = goals.find((goal) => goal.id === goalId);
        const goalSuggestion = selectedGoal ? GOAL_SUGGESTIONS[selectedGoal.name] : undefined;
        return (
          <div className="create-campaign-form">
            <div className="form-section">
              <h3 className="form-section-title heading-m">Campaign Setup</h3>
              <p className="form-section-subtitle">
                Set up your campaign details, goals, and settings in one place
              </p>

              {/* Campaign name + goal — same row on desktop */}
              <div className="form-fields-horizontal">
                <div className="form-field">
                  <label className="form-label">
                    Campaign Name <span className="required">*</span>
                  </label>
                  <Input
                    type="text"
                    placeholder="e.g., Q4 Fintech Outreach"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className="form-input campaign-form-input-style"
                    style={{
                      backgroundColor: '#F8F8FA',
                      borderRadius: 12,
                      minHeight: 44,
                      height: 44,
                    }}
                  />
                </div>

                <div className="form-field">
                  <label className="form-label">Campaign Goal</label>
                  <div className="category-field-wrapper">
                    <Select
                      value={goalId || undefined}
                      onValueChange={handleGoalChange}
                      open={goalDropdownOpen}
                      onOpenChange={(open) => {
                        setGoalDropdownOpen(open);
                        if (!open) setShowAllGoals(false);
                      }}
                    >
                      <SelectTrigger className="form-select">
                        <SelectValue placeholder="Select campaign goal" />
                      </SelectTrigger>
                      <SelectContent>
                        {loadingGoals ? (
                          <SelectItem value="loading" disabled>
                            Loading...
                          </SelectItem>
                        ) : goals.length === 0 ? (
                          <SelectItem value="none" disabled>
                            No goals available
                          </SelectItem>
                        ) : (
                          (() => {
                            // Keep the selected goal visible even when collapsed
                            const visibleGoals = showAllGoals
                              ? goals
                              : goals.filter(
                                  (goal, index) => index < 3 || goal.id === goalId
                                );
                            return (
                              <>
                                {visibleGoals.map((goal) => (
                                  <SelectItem key={goal.id} value={goal.id}>
                                    {goal.name}
                                  </SelectItem>
                                ))}
                                {!showAllGoals && goals.length > visibleGoals.length && (
                                  <button
                                    type="button"
                                    className="goal-show-more-btn"
                                    onClick={(e) => {
                                      e.preventDefault();
                                      e.stopPropagation();
                                      setShowAllGoals(true);
                                    }}
                                  >
                                    Show more
                                  </button>
                                )}
                              </>
                            );
                          })()
                        )}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              </div>

              {/* Description */}
              <div className="form-field">
                <label className="form-label">
                  Description <span className="required">*</span>
                </label>
                <Textarea
                  placeholder={
                    goalSuggestion?.description ||
                    'Describe the purpose and goals of this campaign..'
                  }
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  className="form-textarea campaign-form-input-style"
                  style={{
                    backgroundColor: '#F8F8FA',
                    borderRadius: 12,
                  }}
                />
                {goalSuggestion && (
                  <div className="goal-suggestion-hint">
                    <p>
                      <span className="goal-suggestion-label">Best for:</span>{' '}
                      {goalSuggestion.bestFor}
                    </p>
                    <p>
                      <span className="goal-suggestion-label">Recommended approach:</span>{' '}
                      {goalSuggestion.approach}
                    </p>
                  </div>
                )}
              </div>
            </div>
          </div>
        );
      }
      case 2:
        if (!campaignId) {
          return (
            <div className="create-campaign-form">
              <div className="form-section">
                <p className="form-placeholder-text">Loading...</p>
              </div>
            </div>
          );
        }
        return (
          <DetailCampaignScreen
            key={`step2-${campaignId}-${finalPreselectedLeadIds ? JSON.stringify(finalPreselectedLeadIds.sort()) : 'none'}`} // Force remount only when campaignId or preselected leads change, not when selecting leads
            campaignId={campaignId}
            preselectedLeadIds={finalPreselectedLeadIds}
            searchQuery={searchQuery}
            currentPage={currentPage}
            itemsPerPage={itemsPerPage}
            onPageChange={setCurrentPage}
            onItemsPerPageChange={setItemsPerPage}
            onTotalLeadsChange={setTotalLeads}
            onToggleSidebar={onToggleSidebar}
            onBack={handleBack}
            showFilters={showFilters}
            onToggleFilters={setShowFilters}
            onNext={(selectedLeadIdsFromStep2) => {
              // Store the selected lead IDs when moving to step 3
              console.log('[DEBUG] Step 2 -> Step 3: Storing selected lead IDs:', selectedLeadIdsFromStep2);
              const leadIds = selectedLeadIdsFromStep2 || [];
              setSelectedLeadIds(leadIds);
              setFinalPreselectedLeadIds(leadIds);
              setSelectedLeadsCount(leadIds.length);
              
              // Toast is already shown in DetailCampaignScreen, just move to next step
              // Move to step 3 after a delay to ensure toast is visible
              setTimeout(() => {
                console.log('[DEBUG] Changing to Step 3');
                setCurrentStep(3);
              }, 150);
            }}
            onSelectedLeadsChange={handleSelectedLeadsChange}
            onSelectedLeadIdsChange={handleSelectedLeadIdsChange}
            onAddManualLeadRef={(openModal) => {
              // Store the function in ref so we can call it from the button
              openAddManualLeadModalRef.current = openModal;
            }}
            onGenerateNewLeads={handleGenerateNewLeadsFromStep2}
          />
        );
      case 3:
        if (!campaignId) {
          return (
            <div className="create-campaign-form">
              <div className="form-section">
                <p className="form-placeholder-text">Loading...</p>
              </div>
            </div>
          );
        }
        return (
          <CampaignEmailScreen
            ref={emailScreenRef}
            campaignId={campaignId}
            wizardStep={currentStep}
            onBack={handleBack}
            onStep3UiStateChange={setStep3UiState}
            onSpamComparisonViewChange={setIsEmailSpamComparisonVisible}
            onEmailValidationChange={setIsEmailValid}
            onNext={(subject?: string, content?: string) => {
              console.log('📥 CreateCampaign: Received onNext callback with:', {
                subject: subject || 'undefined',
                content: content ? content.substring(0, 50) + '...' : 'undefined',
                subjectType: typeof subject,
                contentType: typeof content,
                subjectLength: subject?.length || 0,
                contentLength: content?.length || 0
              });
              
              const trimmedSubject = (subject || '').trim();
              const trimmedContent = (content || '').trim();
              
              console.log('📥 CreateCampaign: After trimming:', {
                trimmedSubject: trimmedSubject || 'EMPTY',
                trimmedContent: trimmedContent ? trimmedContent.substring(0, 50) + '...' : 'EMPTY',
                trimmedSubjectLength: trimmedSubject.length,
                trimmedContentLength: trimmedContent.length
              });
              
              // Only require content - subject can be empty (templates might not have subject)
              if (!trimmedContent || trimmedContent.trim().length === 0) {
                console.error('❌ CreateCampaign: Email content is missing!', {
                  trimmedSubject,
                  trimmedContent,
                  hasSubject: !!trimmedSubject,
                  hasContent: !!trimmedContent,
                  subjectLength: trimmedSubject.length,
                  contentLength: trimmedContent.length
                });
                toast.error('Email content is missing. Please go back and enter your email content.');
                return;
              }
              
              // Subject is optional, but log if it's missing
              if (!trimmedSubject || trimmedSubject.trim().length === 0) {
                console.warn('⚠️ CreateCampaign: Email subject is empty, but proceeding with content only');
              }
              
              // Store email data immediately in ref (synchronous - happens immediately)
              emailDataRef.current = { subject: trimmedSubject, content: trimmedContent };
              
              // Verify ref is set BEFORE any React updates
              console.log('✅ CreateCampaign: Email data stored in REF (synchronous):', {
                refSubject: emailDataRef.current.subject,
                refContent: emailDataRef.current.content.substring(0, 50) + '...',
                refSubjectLength: emailDataRef.current.subject.length,
                refContentLength: emailDataRef.current.content.length,
                refObject: JSON.stringify(emailDataRef.current),
                refVerified: emailDataRef.current.subject === trimmedSubject
              });
              
              // Mark Step 3 as explicitly completed in this browser session.
              // This distinguishes "user actually advanced from Step 3" from the case
              // where email content exists only because a template/AI draft was saved.
              try {
                if (campaignId) {
                  sessionStorage.setItem(`campaignStep3Completed_${campaignId}`, 'true');
                }
              } catch (e) {
                console.error('Failed to persist Step 3 completion flag:', e);
              }

              // Update state first
              setEmailSubject(trimmedSubject);
              setEmailContent(trimmedContent);
              
              toast.dismiss('campaign-creation-complete');
              toast.dismiss('campaign-lead-selection-complete');
              toast.success('Campaign email content has been completed', {
                id: 'campaign-email-written-complete',
              });
              
              // Use a small delay to ensure state is set and toast is visible, then change step
              // This ensures the ref is definitely set before React renders step 4
              setTimeout(() => {
                requestAnimationFrame(() => {
                  console.log('🔄 CreateCampaign: Changing step in requestAnimationFrame, ref check:', {
                    refSubject: emailDataRef.current.subject,
                    refContent: emailDataRef.current.content.substring(0, 30) + '...',
                    refHasData: !!emailDataRef.current.subject && !!emailDataRef.current.content
                  });
                  setCurrentStep(4);
                  console.log('✅ CreateCampaign: Step changed to 4 (Select Email Account)');
                });
              }, 100);
            }}
          />
        );
      case 4:
        if (!campaignId) {
          return (
            <div className="create-campaign-form">
              <div className="form-section">
                <p className="form-placeholder-text">Loading...</p>
              </div>
            </div>
          );
        }
        return (
          <SelectEmailAccount
            campaignId={campaignId}
            onBack={handleBack}
            onNext={() => {
              // Move to step 5 (Preview)
              setCurrentStep(5);
            }}
            onEmailAccountSelected={(accountType, detailedType) => {
              setSelectedEmailAccount(accountType);
              if (detailedType) {
                setSelectedEmailType(detailedType);
              } else if (accountType === 'system') {
                setSelectedEmailType('system');
              } else if (accountType === 'existing') {
                setSelectedEmailType('imap');
              }
            }}
            selectedAccountType={selectedEmailType}
          />
        );
      case 5:
        if (!campaignId) {
          return (
            <div className="create-campaign-form">
              <div className="form-section">
                <p className="form-placeholder-text">Loading...</p>
              </div>
            </div>
          );
        }
        // Get email data from ref (most reliable, synchronous) or state
        // Read ref directly - it's updated synchronously before setCurrentStep(4)
        // Use ref first (most up-to-date), then state, then empty string
        // CRITICAL: Read ref directly - it's updated synchronously before setCurrentStep(4)
        console.log('🔍 Step 5: Reading ref and state:', {
          refExists: !!emailDataRef.current,
          refKeys: emailDataRef.current ? Object.keys(emailDataRef.current) : 'no ref',
          refSubjectRaw: emailDataRef.current?.subject,
          refContentRaw: emailDataRef.current?.content?.substring(0, 30),
          stateSubjectRaw: emailSubject,
          stateContentRaw: emailContent?.substring(0, 30)
        });
        
        const refSubject = emailDataRef.current?.subject || '';
        const refContent = emailDataRef.current?.content || '';
        const stateSubject = emailSubject || '';
        const stateContent = emailContent || '';
        
        // Prioritize ref over state since ref is updated synchronously
        const finalEmailSubject = refSubject || stateSubject || '';
        const finalEmailContent = refContent || stateContent || '';
        
        console.log('🎯 Rendering PreviewCampaignDetail (Step 5):', {
          refSubject: refSubject || 'EMPTY',
          refContent: refContent ? refContent.substring(0, 50) + '...' : 'EMPTY',
          stateSubject: stateSubject || 'EMPTY',
          stateContent: stateContent ? stateContent.substring(0, 50) + '...' : 'EMPTY',
          finalSubject: finalEmailSubject || 'EMPTY',
          finalContent: finalEmailContent ? finalEmailContent.substring(0, 50) + '...' : 'EMPTY',
          refHasData: !!refSubject && !!refContent,
          stateHasData: !!stateSubject && !!stateContent,
          finalHasData: !!finalEmailSubject && !!finalEmailContent,
          refObject: JSON.stringify(emailDataRef.current),
          refCurrentExists: !!emailDataRef.current,
          refCurrentKeys: emailDataRef.current ? Object.keys(emailDataRef.current) : 'no ref'
        });
        
        // Always pass email data from state/ref, even if empty (PreviewCampaignDetail will fetch from API as fallback)
        // The email data should be available from Step 3, but if not, PreviewCampaignDetail will fetch it
        const emailDataKey = `${finalEmailSubject}-${finalEmailContent?.substring(0, 20)}`;
        
        console.log('📤 CreateCampaign: Passing email props to PreviewCampaignDetail:', {
          finalEmailSubject: finalEmailSubject || 'EMPTY',
          finalEmailContent: finalEmailContent ? finalEmailContent.substring(0, 50) + '...' : 'EMPTY',
          hasSubject: !!finalEmailSubject,
          hasContent: !!finalEmailContent
        });
        
        return (
          <PreviewCampaignDetail
            key={`preview-${campaignId}-${emailDataKey}`}
            campaignId={campaignId}
            onBack={handleBack}
            onSaveAsDraft={onBack}
            onNext={onBack}
            selectedLeadsCount={selectedLeadsCount}
            selectedLeadIds={selectedLeadIds}
            emailSubject={finalEmailSubject}
            emailContent={finalEmailContent}
          />
        );
      default:
        // Fallback to step 1 if currentStep is invalid
        return (
          <div className="create-campaign-form">
            <div className="form-section">
              <h3 className="form-section-title heading-m">Campaign Setup</h3>
              <p className="form-section-subtitle">
                Set up your campaign details, goals, and settings in one place
              </p>
            </div>
          </div>
        );
    }
  };

  if (isLoadingDraft) {
    return (
      <div className="create-campaign-container create-campaign-loading-container">
        <div className="create-campaign-loading-spinner" />
      </div>
    );
  }

  return (
    <div id="create-campaign-root" className="create-campaign-container">
      {/* Sticky Header Section - Contains header, search/filter, and pagination */}
      <div className="create-campaign-sticky-header">
        {/* Header with Title, Subtitle, and Stepper */}
        <div className="create-campaign-header">
          <div className="create-campaign-header-top">
            <h1 className="create-campaign-title heading-xl">Create Campaign</h1>
          </div>
          <div className="create-campaign-header-content">
            <p className="create-campaign-subtitle">
              Set up a new outreach campaign with email sequences
            </p>
            <div className="stepper-container">
              <div className="stepper">
                {/* Step 1 - Always show as completed when editing draft (Step 5) */}
                <div 
                  className={`stepper-step ${currentStep > 1 || (editCampaignId && currentStep === 5) ? 'completed' : ''} ${currentStep === 1 ? 'active' : ''} ${isStepClickable(1) ? 'clickable' : ''}`}
                  onClick={() => handleStepClick(1)}
                >
                  <div className="stepper-number">
                    {currentStep > 1 || (editCampaignId && currentStep === 5) ? <Check className="stepper-check-icon" /> : '1'}
                  </div>
                  <div className="stepper-content">
                    <div className="stepper-title">Campaign Setup</div>
                    <div className="stepper-subtitle">Name, goals & settings</div>
                  </div>
                </div>
                <div className={`stepper-line ${currentStep > 1 || (editCampaignId && currentStep === 5) ? 'active' : ''}`}></div>
                {/* Step 2 - Always show as completed when editing draft (Step 5) */}
                <div 
                  className={`stepper-step ${currentStep > 2 || (editCampaignId && currentStep === 5) ? 'completed' : ''} ${currentStep === 2 ? 'active' : ''} ${isStepClickable(2) ? 'clickable' : ''}`}
                  onClick={() => handleStepClick(2)}
                >
                  <div className="stepper-number">
                    {currentStep > 2 || (editCampaignId && currentStep === 5) ? <Check className="stepper-check-icon" /> : '2'}
                  </div>
                  <div className="stepper-content">
                    <div className="stepper-title">Select Leads</div>
                    <div className="stepper-subtitle">Choose target leads</div>
                  </div>
                </div>
                <div className={`stepper-line ${currentStep > 2 || (editCampaignId && currentStep === 5) ? 'active' : ''}`}></div>
                {/* Step 3 - Always show as completed when editing draft (Step 5) */}
                <div 
                  className={`stepper-step ${currentStep > 3 || (editCampaignId && currentStep === 5) ? 'completed' : ''} ${currentStep === 3 ? 'active' : ''} ${isStepClickable(3) ? 'clickable' : ''}`}
                  onClick={() => handleStepClick(3)}
                >
                  <div className="stepper-number">
                    {currentStep > 3 || (editCampaignId && currentStep === 5) ? <Check className="stepper-check-icon" /> : '3'}
                  </div>
                  <div className="stepper-content">
                    <div className="stepper-title">Outreach Email Draft</div>
                    <div className="stepper-subtitle">Draft your first outreach</div>
                  </div>
                </div>
                <div className={`stepper-line ${currentStep > 3 || (editCampaignId && currentStep >= 4) ? 'active' : ''}`}></div>
                {/* Step 4 - Select Email Account */}
                <div 
                  className={`stepper-step ${currentStep > 4 || (editCampaignId && currentStep === 5) ? 'completed' : ''} ${currentStep === 4 ? 'active' : ''} ${isStepClickable(4) ? 'clickable' : ''}`}
                  onClick={() => handleStepClick(4)}
                >
                  <div className="stepper-number">
                    {currentStep > 4 || (editCampaignId && currentStep === 5) ? <Check className="stepper-check-icon" /> : '4'}
                  </div>
                  <div className="stepper-content">
                    <div className="stepper-title">Email Setup</div>
                    <div className="stepper-subtitle">Configure Email</div>
                  </div>
                </div>
                <div className={`stepper-line ${currentStep > 4 || (editCampaignId && currentStep === 5) ? 'active' : ''}`}></div>
                {/* Step 5 - Preview */}
                <div 
                  className={`stepper-step ${currentStep === 5 ? 'active' : ''} ${isStepClickable(5) ? 'clickable' : ''}`}
                  onClick={() => handleStepClick(5)}
                >
                  <div className="stepper-number">5</div>
                  <div className="stepper-content">
                    <div className="stepper-title">Review & Launch</div>
                    <div className="stepper-subtitle">Final review & create</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Search and Filter Controls - Only show on step 2 */}
        {currentStep === 2 && (
          <>
            {/* Exact Lead Database style: outer container + inner search/filter row */}
            <div
              className="lead-log-search-filter-outer"
              style={{ marginBottom: '0px', flexShrink: 0, paddingTop: '8px', width: '100%' }}
            >
              <div
                className="lead-log-search-filter-container"
                style={{
                  display: 'flex',
                  alignItems: 'stretch',
                  gap: '24px',
                  paddingTop: '12px',
                  paddingBottom: '12px',
                  paddingLeft: '12px',
                  paddingRight: '16px',
                  border: '1px solid #D1D5DB',
                  borderRadius: '16px',
                  backgroundColor: '#FFFFFF',
                  width: '100%',
                  boxSizing: 'border-box',
                }}
              >
                {/* Search Input (Lead Database style) */}
                <div className="lead-log-search-wrapper lead-log-search-wrapper-connected" style={{ width: '300px', flexShrink: 0 }}>
                  <div className="lead-log-search-input-container lead-log-page-search" style={{ gap: 10, padding: '0 14px', height: '36px', backgroundColor: '#FFFFFF', border: '1px solid #E5E7EB', borderRadius: '6px' }}>
                    <Search className="lead-log-search-icon" size={16} strokeWidth={2} style={{ color: '#6B7280', flexShrink: 0 }} />
                    <Input
                      placeholder="Search leads"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className="lead-log-search-input"
                      style={{ flex: 1, border: 'none', backgroundColor: 'transparent', outline: 'none', fontSize: '14px', fontWeight: 500, color: '#111827', fontFamily: 'Urbanist, sans-serif' }}
                    />
                  </div>
                </div>

                {/* Spacer between search and right-side controls */}
                <div style={{ flex: 1, minWidth: 0 }} />

                {/* Right-side controls: Filter + Add Lead Manually (purple) */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  {/* Filter button that opens side panel (same as Lead Database) */}
                  <button
                    type="button"
                    onClick={() => setShowFilters(true)}
                    className="lead-database-filter-bar-button dashboard-header-btn-style"
                  >
                    <SlidersHorizontal size={18} className="dashboard-header-btn-icon" />
                    Filter
                  </button>

                  {/* Add Lead Manually – styled like Create Campaign button (purple) */}
                  <button
                    type="button"
                    onClick={() => {
                      if (openAddManualLeadModalRef.current) {
                        openAddManualLeadModalRef.current();
                      }
                    }}
                    className="lead-database-create-campaign-btn"
                    style={{
                      height: '36px',
                      padding: '0 16px',
                      backgroundColor: '#9164FF',
                      color: '#FFFFFF',
                      fontSize: '14px',
                      fontWeight: 500,
                      borderRadius: '6px',
                      border: 'none',
                      fontFamily: 'Urbanist, sans-serif',
                      cursor: 'pointer'
                    }}
                  >
                    Add Lead Manually
                  </button>
                </div>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Main Content */}
      <div
        className={`create-campaign-content${currentStep === 4 ? ' create-campaign-content-step-email' : ''}${currentStep === 5 ? ' create-campaign-content-step5' : ''}`}
      >
        {currentStep === 4 ? (
          <>
            {/* Step 4 - Select Email Account: No wrapper card, SelectEmailAccount uses EmailAccounts styling */}
            {renderStepContent()}
            {/* Action Buttons - Below content for step 4 */}
            <div className="create-campaign-actions create-campaign-actions-step4">
              <button
                onClick={handleBack}
                className="evecta-secondary-btn"
                type="button"
                title="Go back"
              >
                Back
              </button>
              <button
                onClick={handleNext}
                disabled={isSubmitting || !isStep4Valid}
                className="evecta-primary-btn"
                type="button"
                title={!isStep4Valid ? 'Please select an email account to continue' : 'Continue to next step'}
              >
                Next
              </button>
            </div>
          </>
        ) : currentStep === 5 ? (
          <>
            {/* Step 5 - Preview: No wrapper card, PreviewCampaignDetail has its own */}
            {renderStepContent()}
          </>
        ) : (
          <>
            {/* Form Card - for step 2: content scrolls, pagination fixed at bottom */}
            <div className={`create-campaign-card ${currentStep === 2 ? 'dashboard-content-with-pagination' : ''}`} style={currentStep === 2 ? { flex: 1, minHeight: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' } : undefined}>
              {currentStep === 2 ? (
                <div className="dashboard-pagination-scroll-area" style={{ flex: 1, minHeight: 0 }}>
                  {renderStepContent()}
                </div>
              ) : (
                renderStepContent()
              )}
              {currentStep === 2 && totalLeads > 0 && (
                <div className="dashboard-pagination-fixed">
                  <DashboardPagination
                    totalItems={totalLeads}
                    currentPage={currentPage}
                    itemsPerPage={itemsPerPage}
                    onPageChange={setCurrentPage}
                    onItemsPerPageChange={(v) => {
                      if (!isNaN(v) && v > 0) {
                        setItemsPerPage(v);
                        setCurrentPage(1);
                      }
                    }}
                    itemLabel="leads"
                    leftExtra={selectedLeadsCount > 0 ? (
                      <span className="create-campaign-selected-leads-badge">
                        <Check className="create-campaign-selected-leads-badge-icon" />
                        {selectedLeadsCount} {selectedLeadsCount === 1 ? 'lead' : 'leads'} selected
                      </span>
                    ) : undefined}
                  />
                </div>
              )}
            </div>

            {/* Action Buttons — hidden on step 3 while spam Original/Improved comparison is open */}
            {!(currentStep === 3 && isEmailSpamComparisonVisible) && (
              currentStep === 3 ? (
                <div className="create-campaign-actions create-campaign-actions-step3">
                  <button
                    onClick={handleBack}
                    className="evecta-secondary-btn"
                    type="button"
                    title="Go back"
                  >
                    Back
                  </button>
                  <div className="create-campaign-actions-step3-right">
                    {step3UiState.phase === 'compose' &&
                      step3UiState.creationMethod === 'ai' && (
                      <button
                        onClick={() => emailScreenRef.current?.handleGenerateEmail()}
                        disabled={
                          isSubmitting ||
                          step3UiState.isGenerating ||
                          !step3UiState.canGenerate
                        }
                        className="evecta-primary-btn create-campaign-generate-email-btn"
                        type="button"
                        title="Generate email with AI"
                      >
                        <Sparkles size={16} aria-hidden />
                        {step3UiState.isGenerating ? 'Generating…' : 'Generate Email'}
                      </button>
                    )}
                    {(step3UiState.phase === 'lead-generation' ||
                      (step3UiState.phase === 'compose' &&
                        step3UiState.creationMethod === 'manual')) && (
                      <button
                        onClick={handleNext}
                        disabled={
                          isSubmitting ||
                          (step3UiState.phase === 'lead-generation'
                            ? !step3UiState.isEmailValid
                            : !isNextButtonReady)
                        }
                        className="evecta-primary-btn"
                        type="button"
                        title={
                          step3UiState.phase === 'lead-generation' &&
                          step3UiState.readyForOutreachCount <= 0
                            ? 'Wait for at least one email to be ready, or click Cancel on the table'
                            : step3UiState.phase === 'lead-generation' &&
                                !step3UiState.allLeadEmailsSpamReady
                              ? 'Pass spam checks for ready emails before continuing'
                              : step3UiState.phase === 'compose' && !isNextButtonReady
                                ? 'Complete the spam email test before continuing'
                                : 'Continue to next step'
                        }
                      >
                        Next
                      </button>
                    )}
                  </div>
                </div>
              ) : (
              <div className="create-campaign-actions">
                <button
                  onClick={handleBack}
                  className="evecta-secondary-btn"
                  type="button"
                  title="Go back"
                >
                  Back
                </button>
                <button
                  onClick={handleNext}
                  disabled={isSubmitting || !isNextButtonReady}
                  className="evecta-primary-btn"
                  type="button"
                  title={
                    (currentStep === 1 && !isStep1Valid)
                      ? 'Please complete Campaign Name and Description to continue'
                      : ((currentStep as Step) === 4 && !isStep4Valid)
                      ? 'Please select an email account to continue'
                      : 'Continue to next step'
                  }
                >
                  Next
                </button>
              </div>
              )
            )}
          </>
        )}
      </div>
    </div>
  );
}

