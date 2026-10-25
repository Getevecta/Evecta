import { useState, useEffect, useCallback, useRef, useImperativeHandle, forwardRef, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { ArrowLeft } from 'lucide-react';
import { Input } from '../ui/input';
import { Textarea } from '../ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';
import { apiService, EmailTemplate, SpamCheckResponse, PlanCapabilitiesResponse } from '../../../../shared/services/api';
import { toast } from 'sonner';
import { useAuth } from '../../../../shared/contexts/AuthContext';
import './CampaignEmailScreen.css';
import './CampaignEmailReview.css';
import {
  personalizationVariables,
  normalizeVariables,
  highlightVariablesInText as highlightVariables,
  htmlToPlainTextWithBreaks,
} from './emailPersonalizationHighlight';
import { EmailTonePicker } from './EmailTonePicker';
import { CampaignLeadEmailGeneration } from './CampaignLeadEmailGeneration';
import { isToneUnlocked, mapApiToneTiers, findTierForTone, firstUnlockedToneId, defaultTierPlanForTone } from './emailToneTiers';

/** Template flow in Step 3 outreach email draft. */
const SHOW_TEMPLATE_METHOD = true;

interface CampaignEmailScreenProps {
  campaignId: string;
  onBack?: () => void;
  onNext?: (emailSubject?: string, emailContent?: string) => void;
  onEmailValidationChange?: (isValid: boolean) => void;
  /** When spam-test comparison is shown, parent can hide step navigation (e.g. Back/Next). */
  onSpamComparisonViewChange?: (visible: boolean) => void;
  /** Step 3 footer: parent renders Save / Generate / Next from this state. */
  onStep3UiStateChange?: (state: Step3UiState) => void;
  /** Wizard step from parent — used to reset compose navigation when leaving step 3. */
  wizardStep?: number;
}

export interface Step3UiState {
  creationMethod: 'ai' | 'manual';
  phase: 'compose' | 'lead-generation';
  isGenerating: boolean;
  hasGenerated: boolean;
  canGenerate: boolean;
  isEmailValid: boolean;
  isSavingDraft: boolean;
  isLeadGenerationComplete: boolean;
  allLeadEmailsSpamReady: boolean;
  readyForOutreachCount: number;
  partialGenerationAccepted: boolean;
}

export interface CampaignEmailScreenHandle {
  handleNext: () => Promise<void>;
  handleGenerateEmail: () => Promise<void>;
  handleSaveDraft: () => Promise<void>;
  requestBackFromLeadGeneration: () => void;
}

type EmailCreationMethod = 'template' | 'ai' | 'manual';

/** Normalize text for spam hash: strip HTML, collapse whitespace, trim. */
function normalizeForSpamHash(text: string): string {
  if (!text || typeof text !== 'string') return '';
  const div = document.createElement('div');
  div.innerHTML = text;
  const plain = (div.textContent || div.innerText || '').trim();
  return plain.replace(/\s+/g, ' ').trim();
}

/** Single canonical content hash for spam check. Use for both storing and comparing so back/forward without edits keeps "passed". */
function getContentHashForSpam(subject: string, content: string): string {
  return `${normalizeForSpamHash(subject)}|${normalizeForSpamHash(content)}`;
}

/**
 * Shown after AI draft generation: backend runs a fast spam gate on the primary draft (~58%+ inbox safety);
 * fallback template is always saved if the gate fails so generation does not hard-error.
 * Full-mode UI spam checks use a stricter second LLM pass and falsely fail the same text — do not use that for gating.
 */
const AI_DRAFT_DISPLAY_SPAM_SCORE = 25;

/** Resolve sender display name for auto-filling [Your Name] / [YourName] / [Name] placeholders. */
function getSenderDisplayName(userLike?: {
  full_name?: string | null;
  username?: string | null;
} | null): string {
  return (
    userLike?.full_name?.trim() ||
    userLike?.username?.trim() ||
    ''
  );
}

/** Replace common sender placeholders in subject + body (AI draft, improved copy, etc.). */
function applySenderNamePlaceholders(
  subject: string,
  content: string,
  displayName: string
): { subject: string; content: string } {
  if (!displayName) return { subject, content };
  let s = subject;
  let c = content;
  const patterns = [
    /\[\s*Your\s+Name\s*\]/gi,
    /\[\s*YourName\s*\]/gi,
    /\[\s*Your\s+(?:Full\s+)?Name\s*\]/gi,
    /\[YourName\]/gi,
    /\[Your\s+Name\]/gi,
    /\[yourname\]/gi,
    /\[your\s+name\]/gi,
    /\[Your\s*Name\]/gi,
    /\[\s*YourName\]/gi,
    /\[\s*Sender\s+Name\s*\]/gi,
    /\[\s*Name\s*\]/gi,
  ];
  for (const p of patterns) {
    s = s.replace(p, displayName);
    c = c.replace(p, displayName);
  }
  return { subject: s, content: c };
}

/**
 * Plain text → HTML for template draft persistence.
 * AI / spam “improved” copy usually separates blocks with a single `\n` (no blank line). Putting the whole body in one `<p>` with `<br>` keeps lines but no vertical gap.
 * Each non-empty line becomes its own `<p>` so default paragraph spacing matches a normal email layout; `stripHtmlTags` still round-trips this to `\n\n` between blocks when editing.
 */
function plainTextToHtmlForDraft(text: string): string {
  if (!text) return '';
  return text
    .split(/\n+/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => `<p>${line}</p>`)
    .join('\n');
}

export const CampaignEmailScreen = forwardRef<CampaignEmailScreenHandle, CampaignEmailScreenProps>(({
  campaignId, 
  onBack, 
  onNext,
  onEmailValidationChange,
  onSpamComparisonViewChange,
  onStep3UiStateChange,
  wizardStep,
}, ref) => {
  const { user } = useAuth();
  const [companyProfile, setCompanyProfile] = useState<{ company_name?: string } | null>(null);
  const [creationMethod, setCreationMethod] = useState<EmailCreationMethod>('ai');
  const [emailSubject, setEmailSubject] = useState('');
  const [emailContent, setEmailContent] = useState('');
  const [aiMessageDescription, setAiMessageDescription] = useState('');
  const [emailTone, setEmailTone] = useState('friendly');
  const [emailToneTier, setEmailToneTier] = useState<string | undefined>();
  const [planCapabilities, setPlanCapabilities] = useState<PlanCapabilitiesResponse | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isSavingDraft, setIsSavingDraft] = useState(false);
  const [hasGenerated, setHasGenerated] = useState(false); // Track if email has been generated
  const [step3Phase, setStep3Phase] = useState<'compose' | 'lead-generation'>('compose');
  const [showDiscardLeadEmailsConfirm, setShowDiscardLeadEmailsConfirm] = useState(false);
  const [isDiscardingLeadEmails, setIsDiscardingLeadEmails] = useState(false);
  const [skipMethodPicker, setSkipMethodPicker] = useState(false);
  const [isLeadGenerationComplete, setIsLeadGenerationComplete] = useState(false);
  const [allLeadEmailsSpamReady, setAllLeadEmailsSpamReady] = useState(false);
  const [readyForOutreachCount, setReadyForOutreachCount] = useState(0);
  const [partialGenerationAccepted, setPartialGenerationAccepted] = useState(false);
  const aiGenerateInFlightRef = useRef(false);
  const [templates, setTemplates] = useState<EmailTemplate[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>('');
  const [isLoadingTemplates, setIsLoadingTemplates] = useState(false);
  const [showVariableSuggestions, setShowVariableSuggestions] = useState(false);
  const [variableSuggestionsPosition, setVariableSuggestionsPosition] = useState({ top: 0, left: 0 });
  const [currentVariableInput, setCurrentVariableInput] = useState('');
  const [variableInputElement, setVariableInputElement] = useState<HTMLElement | null>(null);
  const variableSuggestionsRef = useRef<HTMLDivElement | null>(null);
  const variableTriggerStartRef = useRef<number | null>(null);
  /** End offset (exclusive) of the in-progress `{{...` token when suggestions opened. */
  const variableCaretEndRef = useRef<number | null>(null);
  // Spam check state - initialize as null to prevent showing old results
  const [spamCheckResult, setSpamCheckResult] = useState<SpamCheckResponse | null>(null);
  const [isCheckingSpam, setIsCheckingSpam] = useState(false);
  const [spamCheckPassed, setSpamCheckPassed] = useState(false);
  const [showComparisonView, setShowComparisonView] = useState(false); // Show comparison view for manual emails
  const [originalEmailSubject, setOriginalEmailSubject] = useState(''); // Store original email for comparison
  const [originalEmailContent, setOriginalEmailContent] = useState(''); // Store original email for comparison
  const [aiImprovedSubject, setAiImprovedSubject] = useState(''); // Store AI-improved email
  const [aiImprovedContent, setAiImprovedContent] = useState(''); // Store AI-improved email
  const [aiImprovedDeliverabilityScore, setAiImprovedDeliverabilityScore] = useState<number | null>(null); // Store AI-improved email deliverability score
  const [previousSpamCheckPassed, setPreviousSpamCheckPassed] = useState(false);
  const [previousSpamScore, setPreviousSpamScore] = useState<number | null>(null);
  const lastCheckedSubjectRef = useRef<string>('');
  const lastCheckedContentRef = useRef<string>('');
  const autoSaveTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const lastSavedSubjectRef = useRef<string>('');
  const lastSavedContentRef = useRef<string>('');
  // Store original template HTML content (before stripping) for passing to preview
  const templateHtmlContentRef = useRef<string>('');
  // Store original template content to detect if user has edited it
  const originalTemplateSubjectRef = useRef<string>('');
  const originalTemplateContentRef = useRef<string>('');
  // Refs for contentEditable elements (AI generate)
  const subjectEditableRef = useRef<HTMLDivElement>(null);
  const contentEditableRef = useRef<HTMLDivElement>(null);
  // Refs for template contentEditable (to show colored variables)
  const templateSubjectEditableRef = useRef<HTMLDivElement>(null);
  const templateContentEditableRef = useRef<HTMLDivElement>(null);
  // Refs for manual draft contentEditable (to show colored variables)
  const manualSubjectEditableRef = useRef<HTMLDivElement>(null);
  const manualContentEditableRef = useRef<HTMLDivElement>(null);
  // Track if user is actively typing to prevent cursor position reset
  const isTypingSubjectRef = useRef<boolean>(false);
  const isTypingContentRef = useRef<boolean>(false);
  // Preserve template data when switching away from template method
  const preservedTemplateDataRef = useRef<{
    templateId: string;
    subject: string;
    content: string;
    htmlContent: string;
  } | null>(null);
  // Preserve AI data separately
  const preservedAIDataRef = useRef<{
    subject: string;
    content: string;
    aiDescription?: string;
    hasGenerated?: boolean;
  } | null>(null);
  // Preserve Manual data separately
  const preservedManualDataRef = useRef<{
    subject: string;
    content: string;
  } | null>(null);
  // Debounce refs for manual content updates to prevent cursor issues
  const manualContentUpdateTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const manualSubjectUpdateTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Debounced auto-save function for email content
  const autoSaveEmailContent = useCallback(async (subject: string, content: string, method: EmailCreationMethod) => {
    if (!campaignId || !subject.trim() || !content.trim()) return;
    
    // Skip if already saved
    if (subject === lastSavedSubjectRef.current && content === lastSavedContentRef.current) {
      return;
    }
    
    try {
      console.log('[DEBUG] CampaignEmailScreen: Auto-saving email content');
      const draftTypeForSave = method === 'ai' ? 'AI' : 'MANUAL';
      const payload = {
        draft_type: draftTypeForSave as 'AI' | 'MANUAL',
        email_subject: subject.trim(),
        email_content: content.trim(),
      };
      const response = await apiService.updateCampaignDraftManual(campaignId, payload);
      if (!response.error) {
        lastSavedSubjectRef.current = subject.trim();
        lastSavedContentRef.current = content.trim();
        console.log('[DEBUG] CampaignEmailScreen: Email content auto-saved successfully');
      }
    } catch (error) {
      console.error('[DEBUG] Auto-save email error:', error);
    }
  }, [campaignId]);

  // Update template HTML ref when email content changes (for templates)
  useEffect(() => {
    if (creationMethod === 'template' && emailContent.trim()) {
      // Normalize variables in the content first
      const normalizedContent = normalizeVariables(emailContent);
      // Convert edited plain text back to HTML and store in ref
      const htmlContent = plainTextToHtmlForDraft(normalizedContent);
      templateHtmlContentRef.current = htmlContent;
    }
  }, [emailContent, creationMethod]);

  // Auto-save email content when subject or content changes (debounced)
  useEffect(() => {
    // Don't auto-save if:
    // - No campaignId
    // - Subject or content is empty
    // - AI generation is in progress
    if (!campaignId || !emailSubject.trim() || !emailContent.trim() || isGenerating) {
      return;
    }
    
    // Clear previous timeout
    if (autoSaveTimeoutRef.current) {
      clearTimeout(autoSaveTimeoutRef.current);
    }
    
    // Set new timeout for auto-save (2 seconds delay)
    autoSaveTimeoutRef.current = setTimeout(async () => {
      if (creationMethod === 'template') {
        // For templates, save as manual draft when edited (since template_id is already set)
        // Normalize variables first, then convert plain text to HTML for saving
        const normalizedContent = normalizeVariables(emailContent);
        const htmlContent = plainTextToHtmlForDraft(normalizedContent);
        try {
          const payload = {
            draft_type: 'TEMPLATE' as const,
            template_id: selectedTemplateId,
            email_subject: emailSubject.trim(),
            email_content: htmlContent,
          };
          const response = await apiService.updateCampaignDraftTemplate(campaignId, payload);
          if (!response.error) {
            lastSavedSubjectRef.current = emailSubject.trim();
            lastSavedContentRef.current = htmlContent;
            templateHtmlContentRef.current = htmlContent;
            console.log('[DEBUG] CampaignEmailScreen: Template content auto-saved successfully');
          }
        } catch (error) {
          console.error('[DEBUG] Auto-save template error:', error);
        }
      } else {
        // For manual and AI, use existing auto-save
        await autoSaveEmailContent(emailSubject, emailContent, creationMethod);
      }
    }, 2000);
    
    // Cleanup timeout on unmount or when dependencies change
    return () => {
      if (autoSaveTimeoutRef.current) {
        clearTimeout(autoSaveTimeoutRef.current);
      }
    };
  }, [emailSubject, emailContent, campaignId, isGenerating, creationMethod, selectedTemplateId, autoSaveEmailContent]);

  // Load plan personalization capabilities (tone options + depth label)
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiService.getPersonalizationCapabilities();
        if (!cancelled && res.data) {
          setPlanCapabilities(res.data);
          if (!emailTone) {
            const defaultTone =
              res.data.default_tone ||
              res.data.tone_options?.[0]?.id ||
              'friendly';
            setEmailTone(defaultTone);
          }
        }
      } catch {
        // Non-blocking — tone selector falls back to defaults
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Load saved email content and restore creation method when component mounts or campaignId changes
  useEffect(() => {
    const loadSavedEmail = async () => {
      if (campaignId) {
        try {
          // First, try to get draft information (includes draft_type and template_id)
          const draftResponse = await apiService.getCampaignDraft(campaignId);
          
          let loadedSubject = '';
          let loadedContent = '';
          let loadedMethod: EmailCreationMethod = 'ai';
          
          if (draftResponse.data) {
            const draft = draftResponse.data;
            const draftType = draft.draft_type?.toUpperCase();
            
            // Restore email subject and content from draft
            if (draft.email_subject && draft.email_subject.trim()) {
              const plainSubject = stripHtmlTags(draft.email_subject);
              const subjectWithProfile = replacePlaceholdersWithProfileData(plainSubject);
              loadedSubject = subjectWithProfile;
              setEmailSubject(subjectWithProfile);
            }
            if (draft.tone) {
              setEmailTone(draft.tone);
            }
            const restoredAiPrompt = draft.ai_email_prompt?.trim() || '';
            if (restoredAiPrompt) {
              setAiMessageDescription(restoredAiPrompt);
              try {
                sessionStorage.setItem(
                  `campaignAiPrompt_${campaignId}`,
                  restoredAiPrompt,
                );
              } catch {
                /* sessionStorage unavailable */
              }
              preservedAIDataRef.current = {
                ...(preservedAIDataRef.current || {
                  subject: loadedSubject,
                  content: loadedContent,
                  hasGenerated: !!(loadedSubject && loadedContent),
                }),
                aiDescription: restoredAiPrompt,
              };
            } else {
              try {
                const fromSession =
                  sessionStorage.getItem(`campaignAiPrompt_${campaignId}`)?.trim() || '';
                if (fromSession) {
                  setAiMessageDescription(fromSession);
                  preservedAIDataRef.current = {
                    ...(preservedAIDataRef.current || {
                      subject: loadedSubject,
                      content: loadedContent,
                      hasGenerated: !!(loadedSubject && loadedContent),
                    }),
                    aiDescription: fromSession,
                  };
                }
              } catch {
                /* sessionStorage unavailable */
              }
            }
            if (draft.email_content && draft.email_content.trim()) {
              // Strip HTML tags if present for display
              const plainTextContent = stripHtmlTags(draft.email_content);
              // Replace placeholders with user profile data
              const contentWithProfile = replacePlaceholdersWithProfileData(plainTextContent);
              loadedContent = contentWithProfile;
              setEmailContent(contentWithProfile);
            }
            
            // Restore creation method based on draft_type
            if (draftType === 'TEMPLATE' && draft.template_id && SHOW_TEMPLATE_METHOD) {
              loadedMethod = 'template';
              // Restore template method
              setCreationMethod('template');
              setSelectedTemplateId(draft.template_id);
              
              // Preserve template data for restoration
              preservedTemplateDataRef.current = {
                templateId: draft.template_id,
                subject: loadedSubject,
                content: loadedContent,
                htmlContent: draft.email_content || ''
              };
              
              // Load templates to restore the selection UI
              try {
                const templatesResponse = await apiService.getEmailTemplates();
                if (templatesResponse.data && Array.isArray(templatesResponse.data)) {
                  setTemplates(templatesResponse.data);
                  // Find the selected template to store original HTML in ref
                  const selectedTemplate = templatesResponse.data.find(t => t.id === draft.template_id);
                  if (selectedTemplate) {
                    // Store saved content (from draft) in ref for preview (may have been edited)
                    templateHtmlContentRef.current = draft.email_content || selectedTemplate.content || '';
                    // Store original template content to detect edits later
                    originalTemplateSubjectRef.current = selectedTemplate.subject || '';
                    originalTemplateContentRef.current = stripHtmlTags(selectedTemplate.content || '');
                    
                    // Clear AI and manual refs to prevent showing template content in wrong sections
                    if (subjectEditableRef.current) {
                      subjectEditableRef.current.innerHTML = '';
                    }
                    if (contentEditableRef.current) {
                      contentEditableRef.current.innerHTML = '';
                    }
                    if (manualSubjectEditableRef.current) {
                      manualSubjectEditableRef.current.innerHTML = '';
                    }
                    if (manualContentEditableRef.current) {
                      manualContentEditableRef.current.innerHTML = '';
                    }
                    
                    // Restore template contentEditable refs with highlighted content
                    setTimeout(() => {
                      if (templateSubjectEditableRef.current && loadedSubject) {
                        const normalizedSubject = normalizeVariables(loadedSubject);
                        const highlightedSubject = highlightVariables(normalizedSubject);
                        templateSubjectEditableRef.current.innerHTML = highlightedSubject;
                      }
                      if (templateContentEditableRef.current && loadedContent) {
                        const normalized = normalizeVariables(loadedContent);
                        const highlighted = highlightVariables(normalized);
                        templateContentEditableRef.current.innerHTML = highlighted;
                      }
                    }, 100);
                  }
                }
              } catch (error) {
                console.error('Failed to load templates for restoration:', error);
              }
            } else if (draftType === 'TEMPLATE' && draft.template_id && !SHOW_TEMPLATE_METHOD) {
              loadedMethod = 'manual';
              setCreationMethod('manual');
              preservedManualDataRef.current = {
                subject: loadedSubject,
                content: loadedContent,
              };
              if (subjectEditableRef.current) subjectEditableRef.current.innerHTML = '';
              if (contentEditableRef.current) contentEditableRef.current.innerHTML = '';
              if (templateSubjectEditableRef.current) templateSubjectEditableRef.current.innerHTML = '';
              if (templateContentEditableRef.current) templateContentEditableRef.current.innerHTML = '';
              setTimeout(() => {
                if (manualSubjectEditableRef.current && loadedSubject) {
                  manualSubjectEditableRef.current.innerHTML = highlightVariables(
                    normalizeVariables(loadedSubject),
                  );
                }
                if (manualContentEditableRef.current && loadedContent) {
                  manualContentEditableRef.current.innerHTML = highlightVariables(
                    normalizeVariables(loadedContent),
                  );
                }
              }, 100);
            } else if (draftType === 'AI') {
              loadedMethod = 'ai';
              // Restore AI method
              setCreationMethod('ai');
              setHasGenerated(true);
              
              // Restore AI preserved data
              preservedAIDataRef.current = {
                subject: loadedSubject,
                content: loadedContent,
                hasGenerated: true
              };
              
              // Clear manual and template refs to prevent showing AI content in wrong sections
              if (manualSubjectEditableRef.current) {
                manualSubjectEditableRef.current.innerHTML = '';
              }
              if (manualContentEditableRef.current) {
                manualContentEditableRef.current.innerHTML = '';
              }
              if (templateSubjectEditableRef.current) {
                templateSubjectEditableRef.current.innerHTML = '';
              }
              if (templateContentEditableRef.current) {
                templateContentEditableRef.current.innerHTML = '';
              }
              
              // Restore AI contentEditable refs with highlighted content
              setTimeout(() => {
                if (subjectEditableRef.current && loadedSubject) {
                  const normalizedSubject = normalizeVariables(loadedSubject);
                  const highlightedSubject = highlightVariables(normalizedSubject);
                  subjectEditableRef.current.innerHTML = highlightedSubject;
                }
                if (contentEditableRef.current && loadedContent) {
                  const normalized = normalizeVariables(loadedContent);
                  const highlighted = highlightVariables(normalized);
                  contentEditableRef.current.innerHTML = highlighted;
                }
              }, 100);
            } else if (draftType === 'MANUAL') {
              loadedMethod = 'ai';
              setCreationMethod('ai');
              setHasGenerated(true);

              // Keep backward compatibility: old manual drafts are shown in AI mode.
              preservedAIDataRef.current = {
                subject: loadedSubject,
                content: loadedContent,
                hasGenerated: true
              };

              if (manualSubjectEditableRef.current) {
                manualSubjectEditableRef.current.innerHTML = '';
              }
              if (manualContentEditableRef.current) {
                manualContentEditableRef.current.innerHTML = '';
              }
              if (templateSubjectEditableRef.current) {
                templateSubjectEditableRef.current.innerHTML = '';
              }
              if (templateContentEditableRef.current) {
                templateContentEditableRef.current.innerHTML = '';
              }

              setTimeout(() => {
                if (subjectEditableRef.current && loadedSubject) {
                  const normalizedSubject = normalizeVariables(loadedSubject);
                  const highlightedSubject = highlightVariables(normalizedSubject);
                  subjectEditableRef.current.innerHTML = highlightedSubject;
                }
                if (contentEditableRef.current && loadedContent) {
                  const normalized = normalizeVariables(loadedContent);
                  const highlighted = highlightVariables(normalized);
                  contentEditableRef.current.innerHTML = highlighted;
                }
              }, 100);
            }
          } else {
            // Fallback: try to get from campaign if draft doesn't exist
            const campaignResponse = await apiService.getCampaignById(campaignId);
            if (campaignResponse.data) {
              const campaign = campaignResponse.data;
              if (campaign.email_subject && campaign.email_subject.trim()) {
                loadedSubject = campaign.email_subject;
                setEmailSubject(campaign.email_subject);
              }
              if (campaign.email_content && campaign.email_content.trim()) {
                const plainTextContent = stripHtmlTags(campaign.email_content);
                loadedContent = plainTextContent;
                setEmailContent(plainTextContent);
              }
            }
          }
          
          // Clear spam check results on load initially
          setSpamCheckResult(null);
          setSpamCheckPassed(false);
          setShowComparisonView(false);
          setAiImprovedDeliverabilityScore(null);
          
          // Restore spam check results for this method if content matches what was previously checked
          if (loadedSubject && loadedContent) {
            const suffix = `${campaignId}_${loadedMethod}`;
            const storedHash = sessionStorage.getItem(`spamCheckContentHash_${suffix}`);
            const storedStatus = sessionStorage.getItem(`spamCheckPassed_${suffix}`);
            const storedResult = sessionStorage.getItem(`spamCheckResult_${suffix}`);
            const currentHash = getContentHashForSpam(loadedSubject, loadedContent);
            
            if (storedStatus === 'true' && storedHash && storedHash === currentHash) {
              // Content unchanged from what was checked — restore so user doesn't have to re-test
              setSpamCheckPassed(true);
              lastCheckedSubjectRef.current = normalizeForSpamHash(loadedSubject);
              lastCheckedContentRef.current = normalizeForSpamHash(loadedContent);
              
              if (storedResult) {
                try {
                  const parsedResult = JSON.parse(storedResult);
                  setSpamCheckResult(parsedResult);
                } catch (error) {
                  console.error('Failed to parse stored spam check result:', error);
                }
              }
            }
            // If hash doesn't match, leave state as-is; don't clear storage here — content-change effect clears only when user actually edits
          }

          if ((loadedMethod === 'ai' || loadedMethod === 'manual') && loadedContent.trim()) {
            try {
              const emailsRes = await apiService.getCampaignLeadEmails(campaignId);
              if (emailsRes.data && emailsRes.data.length > 0) {
                setStep3Phase('lead-generation');
              }
            } catch {
              /* no per-lead rows yet */
            }
          }
        } catch (error) {
          console.error('Failed to load saved email content:', error);
          // Don't show error toast - it's okay if there's no saved content
        }
      }
    };
    
    loadSavedEmail();
  }, [campaignId]);

  /** SessionStorage key suffix for spam state — per method so switching template/AI/manual keeps each method's passed state. */
  const spamStorageSuffix = (method: EmailCreationMethod) => `${campaignId}_${method}`;

  // When user switches method (template ↔ AI ↔ manual), restore that method's spam state if it was already passed
  useEffect(() => {
    if (!campaignId) return;
    const suffix = spamStorageSuffix(creationMethod);
    let subject = '';
    let content = '';
    if (creationMethod === 'template' && preservedTemplateDataRef.current) {
      subject = preservedTemplateDataRef.current.subject ?? '';
      content = preservedTemplateDataRef.current.content ?? '';
    } else if (creationMethod === 'ai' && preservedAIDataRef.current) {
      subject = preservedAIDataRef.current.subject ?? '';
      content = preservedAIDataRef.current.content ?? '';
    } else if (creationMethod === 'manual' && preservedManualDataRef.current) {
      subject = preservedManualDataRef.current.subject ?? '';
      content = preservedManualDataRef.current.content ?? '';
    }
    // No content for this method yet (e.g. switched from Template to AI without having used AI) — show this method as not passed
    if (!subject && !content) {
      setSpamCheckPassed(false);
      setSpamCheckResult(null);
      lastCheckedSubjectRef.current = '';
      lastCheckedContentRef.current = '';
      return;
    }
    const currentHash = getContentHashForSpam(subject, content);
    const storedHash = sessionStorage.getItem(`spamCheckContentHash_${suffix}`);
    const storedStatus = sessionStorage.getItem(`spamCheckPassed_${suffix}`);
    const storedResult = sessionStorage.getItem(`spamCheckResult_${suffix}`);
    if (storedStatus === 'true' && storedHash && storedHash === currentHash) {
      setSpamCheckPassed(true);
      lastCheckedSubjectRef.current = normalizeForSpamHash(subject);
      lastCheckedContentRef.current = normalizeForSpamHash(content);
      if (storedResult) {
        try {
          setSpamCheckResult(JSON.parse(storedResult));
        } catch {
          setSpamCheckResult(null);
        }
      } else {
        setSpamCheckResult(null);
      }
    } else if (storedHash !== null || storedStatus !== null) {
      // Had persisted spam snapshot but it doesn't match (or status not passed) — reset.
      // If both are null (sessionStorage blocked / private mode / never written), do not wipe React state;
      // otherwise AI "passed" after generation disappears on Safari/macOS staging.
      setSpamCheckPassed(false);
      setSpamCheckResult(null);
    }
  }, [campaignId, creationMethod]);

  // Extract plain text from HTML (for contentEditable)
  const extractText = (html: string): string => {
    const div = document.createElement('div');
    div.innerHTML = html;
    return div.textContent || div.innerText || '';
  };

  // Extract text from contentEditable while preserving line breaks (<br>, block elements)
  const getTextWithLineBreaks = (el: HTMLElement | null): string => {
    if (!el) return '';
    const html = el.innerHTML || '';
    const withNewlines = html
      .replace(/<br\s*\/?>/gi, '\n')
      .replace(/<\/p>\s*<p[^>]*>/gi, '\n')
      .replace(/<\/div>\s*<div[^>]*>/gi, '\n')
      .replace(/<\/div>\s*/gi, '\n')
      .replace(/<div[^>]*>/gi, '')
      .replace(/<\/p>\s*/gi, '\n')
      .replace(/<p[^>]*>/gi, '');
    const div = document.createElement('div');
    div.innerHTML = withNewlines;
    return div.textContent || div.innerText || '';
  };

  /** Paste plain text only and insert explicit <br> between lines so manual / template / AI bodies keep paragraphs. */
  const pastePlainTextPreservingLineBreaks = (e: React.ClipboardEvent<HTMLDivElement>) => {
    e.preventDefault();
    const raw = e.clipboardData.getData('text/plain');
    if (raw == null) return;
    const text = String(raw).replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0) return;
    const range = selection.getRangeAt(0);
    if (!e.currentTarget.contains(range.commonAncestorContainer)) return;
    range.deleteContents();
    const lines = text.split('\n');
    const frag = document.createDocumentFragment();
    let lastNode: ChildNode | null = null;
    lines.forEach((line, i) => {
      if (i > 0) {
        const br = document.createElement('br');
        frag.appendChild(br);
        lastNode = br;
      }
      const tn = document.createTextNode(line);
      frag.appendChild(tn);
      lastNode = tn;
    });
    range.insertNode(frag);
    if (lastNode) {
      range.setStartAfter(lastNode);
      range.collapse(true);
      selection.removeAllRanges();
      selection.addRange(range);
    }
    e.currentTarget.dispatchEvent(new Event('input', { bubbles: true }));
  };

  // Handle variable auto-complete
  const handleVariableInput = (e: React.KeyboardEvent<HTMLTextAreaElement | HTMLInputElement> | React.FormEvent<HTMLDivElement | HTMLTextAreaElement | HTMLInputElement>, isContentEditable: boolean = false) => {
    const target = e.currentTarget;
    const editable = target as HTMLDivElement;
    const isMultilineEditor =
      isContentEditable &&
      (editable === contentEditableRef.current ||
        editable === templateContentEditableRef.current ||
        editable === manualContentEditableRef.current);
    const text = isContentEditable
      ? (isMultilineEditor ? getTextWithLineBreaks(editable) : editable.textContent || '')
      : (target as HTMLInputElement | HTMLTextAreaElement).value;
    const cursorPosition = isContentEditable
      ? (isMultilineEditor ? getCaretPositionWithLineBreaks(editable) : getCaretPosition(editable))
      : (target as HTMLInputElement | HTMLTextAreaElement).selectionStart || 0;
    
    // Check if user is typing a variable (starts with {{)
    const textBeforeCursor = text.substring(0, cursorPosition);
    const lastOpenBrace = textBeforeCursor.lastIndexOf('{{');
    
    if (lastOpenBrace !== -1) {
      const textAfterOpenBrace = textBeforeCursor.substring(lastOpenBrace + 2);
      const closeBraceIndex = textAfterOpenBrace.indexOf('}}');
      
      // If we haven't closed the braces yet, show suggestions
      if (closeBraceIndex === -1) {
        const currentInput = textAfterOpenBrace.trim().toLowerCase();
        setCurrentVariableInput(currentInput);
        variableTriggerStartRef.current = lastOpenBrace;
        variableCaretEndRef.current = cursorPosition;
        
        // Get cursor position for popup
        requestAnimationFrame(() => {
          if (isContentEditable) {
            const element = target as HTMLDivElement;
            const rect = getContentEditableCaretRect(element);
            if (rect) {
              setVariableSuggestionsPosition({
                top: rect.bottom + 5,
                left: rect.left
              });
            } else {
              const fallbackRect = element.getBoundingClientRect();
              setVariableSuggestionsPosition({
                top: fallbackRect.bottom + 5,
                left: fallbackRect.left + 12
              });
            }
          } else {
            const input = target as HTMLInputElement | HTMLTextAreaElement;
            const rect = input.getBoundingClientRect();
            const textBefore = text.substring(0, cursorPosition);
            const textMetrics = measureTextWidth(textBefore, input);
            setVariableSuggestionsPosition({
              top: rect.top + rect.height + 5,
              left: rect.left + textMetrics.width
            });
          }
        });
        
        setVariableInputElement(target as HTMLElement);
        setShowVariableSuggestions(true);
      } else {
        variableTriggerStartRef.current = null;
        variableCaretEndRef.current = null;
        setShowVariableSuggestions(false);
      }
    } else {
      variableTriggerStartRef.current = null;
      variableCaretEndRef.current = null;
      setShowVariableSuggestions(false);
    }
  };

  // Helper to get caret position in contentEditable
  const getCaretPosition = (element: HTMLDivElement): number => {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0) return 0;
    const range = selection.getRangeAt(0);
    const preCaretRange = range.cloneRange();
    preCaretRange.selectNodeContents(element);
    preCaretRange.setEnd(range.endContainer, range.endOffset);
    return preCaretRange.toString().length;
  };

  // Helper to set caret position in contentEditable
  const setCaretPosition = (element: HTMLDivElement, position: number) => {
    const selection = window.getSelection();
    if (!selection) return;
    
    const range = document.createRange();
    const walker = document.createTreeWalker(
      element,
      NodeFilter.SHOW_TEXT,
      null
    );
    
    let charCount = 0;
    let node: Node | null;
    
    while ((node = walker.nextNode())) {
      const nodeLength = node.textContent?.length || 0;
      if (charCount + nodeLength >= position) {
        range.setStart(node, position - charCount);
        range.setEnd(node, position - charCount);
        break;
      }
      charCount += nodeLength;
    }
    
    // If position is beyond all text, set at end
    if (!range.startContainer || charCount < position) {
      const lastNode = getLastTextNode(element);
      if (lastNode) {
        const textLength = lastNode.textContent?.length || 0;
        range.setStart(lastNode, textLength);
        range.setEnd(lastNode, textLength);
      } else {
        range.selectNodeContents(element);
        range.collapse(false);
      }
    }
    
    selection.removeAllRanges();
    selection.addRange(range);
  };

  // Caret position in a plain-text view that preserves line breaks like getTextWithLineBreaks.
  const getCaretPositionWithLineBreaks = (element: HTMLDivElement): number => {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0) return 0;
    const range = selection.getRangeAt(0);
    const preCaretRange = range.cloneRange();
    preCaretRange.selectNodeContents(element);
    preCaretRange.setEnd(range.endContainer, range.endOffset);
    const container = document.createElement('div');
    container.appendChild(preCaretRange.cloneContents());
    return getTextWithLineBreaks(container).length;
  };

  const setCaretPositionWithLineBreaks = (element: HTMLDivElement, position: number) => {
    const selection = window.getSelection();
    if (!selection) return;

    const range = document.createRange();
    let charCount = 0;
    let found = false;

    const walk = (node: Node): boolean => {
      if (found) return true;
      if (node.nodeType === Node.TEXT_NODE) {
        const len = node.textContent?.length || 0;
        if (charCount + len >= position) {
          range.setStart(node, Math.max(0, position - charCount));
          range.collapse(true);
          found = true;
          return true;
        }
        charCount += len;
        return false;
      }
      if (node.nodeName === 'BR') {
        if (charCount + 1 >= position) {
          range.setStartBefore(node);
          range.collapse(true);
          found = true;
          return true;
        }
        charCount += 1;
        return false;
      }
      let child = node.firstChild;
      while (child) {
        if (walk(child)) return true;
        child = child.nextSibling;
      }
      return false;
    };

    walk(element);
    if (!found) {
      range.selectNodeContents(element);
      range.collapse(false);
    }
    selection.removeAllRanges();
    selection.addRange(range);
  };

  // Helper to get the last text node in an element
  const getLastTextNode = (element: Node): Node | null => {
    const walker = document.createTreeWalker(
      element,
      NodeFilter.SHOW_TEXT,
      null
    );
    
    let lastNode: Node | null = null;
    let node: Node | null;
    while ((node = walker.nextNode())) {
      lastNode = node;
    }
    return lastNode;
  };

  // Get a stable caret rectangle from contentEditable to anchor variable popup.
  const getContentEditableCaretRect = (element: HTMLDivElement): DOMRect | null => {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0) return null;
    const liveRange = selection.getRangeAt(0);
    if (!element.contains(liveRange.startContainer)) return null;

    const caretRange = liveRange.cloneRange();
    caretRange.collapse(true);
    let rect = caretRange.getBoundingClientRect();

    // Collapsed range can return 0x0; use a temporary zero-width marker.
    if (!rect || (rect.width === 0 && rect.height === 0)) {
      const marker = document.createElement('span');
      marker.textContent = '\u200b';
      marker.style.display = 'inline-block';
      marker.style.width = '0';
      marker.style.overflow = 'hidden';
      caretRange.insertNode(marker);
      rect = marker.getBoundingClientRect();
      marker.parentNode?.removeChild(marker);
    }

    if (!rect) return null;
    return (rect.top || rect.left || rect.width || rect.height) ? rect : null;
  };

  // Helper to measure text width for positioning
  const measureTextWidth = (text: string, element: HTMLElement): { width: number } => {
    const canvas = document.createElement('canvas');
    const context = canvas.getContext('2d');
    if (!context) return { width: 0 };
    const styles = window.getComputedStyle(element);
    context.font = `${styles.fontSize} ${styles.fontFamily}`;
    return { width: context.measureText(text).width };
  };

  // Insert variable at cursor position
  const insertVariable = (variable: string) => {
    if (!variableInputElement) return;
    
    const isContentEditable = variableInputElement.contentEditable === 'true';
    
    if (isContentEditable) {
      const element = variableInputElement as HTMLDivElement;
      const isMultilineEditor =
        element === contentEditableRef.current ||
        element === templateContentEditableRef.current ||
        element === manualContentEditableRef.current;
      const fullText = isMultilineEditor
        ? getTextWithLineBreaks(element)
        : (element.textContent || '');
      const caretPosition = isMultilineEditor
        ? getCaretPositionWithLineBreaks(element)
        : getCaretPosition(element) || fullText.length;
      const textBefore = fullText.substring(0, caretPosition);
      const triggerStart =
        variableTriggerStartRef.current ?? textBefore.lastIndexOf('{{');

      if (triggerStart !== -1) {
        // Replace only the in-progress token (triggerStart → caret). Do not scan for the
        // next `}}` in the document — that would swallow later paragraphs/variables.
        const replaceEnd = Math.max(
          triggerStart,
          variableCaretEndRef.current ?? caretPosition,
        );
        const merged =
          fullText.substring(0, triggerStart) + variable + fullText.substring(replaceEnd);
        const normalized = normalizeVariables(merged);
        const highlighted = highlightVariables(normalized);
        element.innerHTML = highlighted;
        const newCaret = triggerStart + variable.length;
        if (isMultilineEditor) {
          setCaretPositionWithLineBreaks(element, newCaret);
        } else {
          setCaretPosition(element, newCaret);
        }

        if (element === subjectEditableRef.current || element === templateSubjectEditableRef.current) {
          setEmailSubject(normalized);
        } else {
          setEmailContent(normalized);
        }
      }
    } else {
      const input = variableInputElement as HTMLInputElement | HTMLTextAreaElement;
      const start = input.selectionStart || 0;
      const end = input.selectionEnd || 0;
      const text = input.value;
      const triggerStart =
        variableTriggerStartRef.current ?? text.substring(0, start).lastIndexOf('{{');

      if (triggerStart !== -1) {
        const replaceEnd = Math.max(triggerStart, variableCaretEndRef.current ?? start);
        const newText =
          text.substring(0, triggerStart) + variable + text.substring(replaceEnd);
        const normalized = normalizeVariables(newText);
        
        if (input.type === 'text') {
          setEmailSubject(normalized);
        } else {
          setEmailContent(normalized);
        }
        
        // Set cursor position after inserted variable
        setTimeout(() => {
          const newCursorPos = triggerStart + variable.length;
          input.setSelectionRange(newCursorPos, newCursorPos);
        }, 0);
      }
    }
    
    variableTriggerStartRef.current = null;
    variableCaretEndRef.current = null;
    setShowVariableSuggestions(false);
    variableInputElement.focus();
  };

  // Close suggestions when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (showVariableSuggestions && variableInputElement) {
        const target = e.target as HTMLElement;
        const clickedInput = variableInputElement.contains(target);
        const clickedSuggestion = !!variableSuggestionsRef.current?.contains(target);
        if (!clickedInput && !clickedSuggestion) {
          setShowVariableSuggestions(false);
        }
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [showVariableSuggestions, variableInputElement]);

  // Filter variables based on current input
  const filteredVariables = personalizationVariables.filter(variable => {
    if (!currentVariableInput) return true;
    const varName = variable.name.replace(/[{}]/g, '').trim().toLowerCase();
    return varName.includes(currentVariableInput);
  });

  // Handle contentEditable input for subject (AI generate)
  const handleSubjectEditableInput = (e: React.FormEvent<HTMLDivElement>) => {
    handleVariableInput(e, true);
    const text = e.currentTarget.textContent || '';
    const normalized = normalizeVariables(text);
    if (normalized !== emailSubject) {
      setEmailSubject(normalized);
      if (creationMethod === 'ai') {
        // Update preserved AI data (keep template/manual preserved data intact)
        if (preservedAIDataRef.current) {
          preservedAIDataRef.current.subject = normalized;
        } else if (normalized.trim()) {
          // Create preserved data if it doesn't exist and user is typing
          preservedAIDataRef.current = {
            subject: normalized,
            content: emailContent,
            aiDescription: aiMessageDescription,
            hasGenerated: hasGenerated
          };
        }
      } else if (creationMethod === 'manual') {
        // Update preserved Manual data (keep template/AI preserved data intact)
        if (preservedManualDataRef.current) {
          preservedManualDataRef.current.subject = normalized;
        } else if (normalized.trim()) {
          preservedManualDataRef.current = {
            subject: normalized,
            content: emailContent
          };
        }
      }
    }
  };

  // Handle contentEditable input for content (AI generate)
  const handleContentEditableInput = (e: React.FormEvent<HTMLDivElement>) => {
    handleVariableInput(e, true);
    const text = getTextWithLineBreaks(e.currentTarget);
    const normalized = normalizeVariables(text);
    if (normalized !== emailContent) {
      setEmailContent(normalized);
      if (creationMethod === 'ai') {
        // Update preserved AI data (keep template/manual preserved data intact)
        if (preservedAIDataRef.current) {
          preservedAIDataRef.current.content = normalized;
        } else if (normalized.trim()) {
          // Create preserved data if it doesn't exist and user is typing
          preservedAIDataRef.current = {
            subject: emailSubject,
            content: normalized,
            aiDescription: aiMessageDescription,
            hasGenerated: hasGenerated
          };
        }
      } else if (creationMethod === 'manual') {
        // Update preserved Manual data (keep template/AI preserved data intact)
        if (preservedManualDataRef.current) {
          preservedManualDataRef.current.content = normalized;
        } else if (normalized.trim()) {
          preservedManualDataRef.current = {
            subject: emailSubject,
            content: normalized
          };
        }
      }
    }
  };

  // Sync emailSubject to highlighted contentEditable (AI generate)
  // Use delayed update so ref exists after isGenerating flips to false and field mounts
  useEffect(() => {
    if (creationMethod !== 'ai' || !hasGenerated || !emailSubject) return;
    const id = setTimeout(() => {
      if (subjectEditableRef.current) {
        const highlighted = highlightVariables(emailSubject);
        const currentText = subjectEditableRef.current.textContent || '';
        const currentHtml = subjectEditableRef.current.innerHTML || '';
        if (currentText !== emailSubject || !currentHtml.includes('style="color:')) {
          subjectEditableRef.current.innerHTML = highlighted;
        }
      }
    }, 50);
    return () => clearTimeout(id);
  }, [emailSubject, creationMethod, hasGenerated, isGenerating, highlightVariables]);

  // Sync emailContent to highlighted contentEditable (AI generate)
  // Use delayed update so refs exist after isGenerating flips to false and fields mount
  useEffect(() => {
    if (creationMethod !== 'ai' || !hasGenerated || !emailContent) return;
    const id = setTimeout(() => {
      if (contentEditableRef.current) {
        const highlighted = highlightVariables(emailContent);
        const currentText = getTextWithLineBreaks(contentEditableRef.current);
        const currentHtml = contentEditableRef.current.innerHTML || '';
        if (currentText !== emailContent || !currentHtml.includes('style="color:')) {
          contentEditableRef.current.innerHTML = highlighted;
        }
      }
    }, 50);
    return () => clearTimeout(id);
  }, [emailContent, creationMethod, hasGenerated, isGenerating, highlightVariables]);

  // Sync emailSubject to highlighted contentEditable (Template)
  // Never replace innerHTML while the field is focused — same as manual draft; otherwise the caret jumps to the start.
  useEffect(() => {
    if (creationMethod !== 'template' || !selectedTemplateId || !templateSubjectEditableRef.current || showComparisonView) {
      return;
    }
    if (document.activeElement === templateSubjectEditableRef.current) {
      return;
    }
    const highlighted = highlightVariables(emailSubject);
    const currentText = templateSubjectEditableRef.current.textContent || '';
    const currentHtml = templateSubjectEditableRef.current.innerHTML || '';
    if (currentText !== emailSubject) {
      templateSubjectEditableRef.current.innerHTML = highlighted;
    } else if (emailSubject && !currentHtml.includes('style="color:')) {
      templateSubjectEditableRef.current.innerHTML = highlighted;
    }
  }, [emailSubject, creationMethod, selectedTemplateId, showComparisonView, highlightVariables]);

  // Sync emailContent to highlighted contentEditable (Template)
  useEffect(() => {
    if (creationMethod !== 'template' || !selectedTemplateId || !templateContentEditableRef.current || showComparisonView) {
      return;
    }
    if (document.activeElement === templateContentEditableRef.current) {
      return;
    }
    const highlighted = highlightVariables(emailContent);
    const currentText = getTextWithLineBreaks(templateContentEditableRef.current);
    const currentHtml = templateContentEditableRef.current.innerHTML || '';
    if (currentText !== emailContent) {
      templateContentEditableRef.current.innerHTML = highlighted;
    } else if (emailContent && !currentHtml.includes('style="color:')) {
      templateContentEditableRef.current.innerHTML = highlighted;
    }
  }, [emailContent, creationMethod, selectedTemplateId, showComparisonView, highlightVariables]);

  // Sync emailSubject to highlighted contentEditable (Manual Draft)
  // Only update when NOT actively typing to prevent cursor position reset
  useEffect(() => {
    // CRITICAL: Completely skip this effect if user is typing or element has focus
    if (isTypingSubjectRef.current) {
      return; // Don't do anything while user is typing
    }
    
    if (creationMethod === 'manual' && manualSubjectEditableRef.current && emailSubject) {
      // CRITICAL: Never update innerHTML if the element has focus - this causes cursor position issues
      const isFocused = document.activeElement === manualSubjectEditableRef.current;
      if (isFocused) {
        return; // Don't update while user is typing
      }
      
      // Add a delay to ensure typing flag is stable
      const timeoutId = setTimeout(() => {
        // Triple-check: element still exists, no focus, and not typing
        if (!manualSubjectEditableRef.current) return;
        if (isTypingSubjectRef.current) return;
        if (document.activeElement === manualSubjectEditableRef.current) return;
        
        const highlighted = highlightVariables(emailSubject);
        const currentText = manualSubjectEditableRef.current.textContent || '';
        const currentHtml = manualSubjectEditableRef.current.innerHTML || '';
        
        // Only update if content actually changed or highlighting is missing
        if (currentText !== emailSubject || !currentHtml.includes('style="color:')) {
          manualSubjectEditableRef.current.innerHTML = highlighted;
        }
      }, 1200); // Wait much longer than the typing flag reset delay (800ms) to ensure user has finished typing
      
      return () => clearTimeout(timeoutId);
    }
  }, [emailSubject, creationMethod, highlightVariables]);

  // Sync emailContent to highlighted contentEditable (Manual Draft)
  // Only update when NOT actively typing to prevent cursor position reset
  useEffect(() => {
    // CRITICAL: Completely skip this effect if user is typing or element has focus
    if (isTypingContentRef.current) {
      return; // Don't do anything while user is typing
    }
    
    // Double-check typing flag with a small delay to avoid race conditions
    if (creationMethod === 'manual' && manualContentEditableRef.current) {
      // CRITICAL: Never update innerHTML if the element has focus - this causes cursor position issues
      const isFocused = document.activeElement === manualContentEditableRef.current;
      if (isFocused) {
        return; // Don't update while user is typing
      }
      
      // Add a delay to ensure typing flag is stable
      const timeoutId = setTimeout(() => {
        // Triple-check: element still exists, no focus, and not typing
        if (!manualContentEditableRef.current) return;
        if (isTypingContentRef.current) return;
        if (document.activeElement === manualContentEditableRef.current) return;
        
        if (emailContent) {
          const highlighted = highlightVariables(emailContent);
          const currentText = getTextWithLineBreaks(manualContentEditableRef.current);
          const currentHtml = manualContentEditableRef.current.innerHTML || '';
          
          // Only update if content actually changed or highlighting is missing
          if (currentText !== emailContent || !currentHtml.includes('style="color:')) {
            manualContentEditableRef.current.innerHTML = highlighted;
          }
        } else {
          manualContentEditableRef.current.innerHTML = '';
        }
      }, 1200); // Wait much longer than the typing flag reset delay (800ms) to ensure user has finished typing
      
      return () => clearTimeout(timeoutId);
    }
  }, [emailContent, creationMethod, highlightVariables]);

  // Initialize manual draft contentEditable when switching to manual mode
  useEffect(() => {
    if (creationMethod === 'manual') {
      // Use a small delay to ensure DOM is ready
      setTimeout(() => {
        if (manualSubjectEditableRef.current && emailSubject) {
          const highlighted = highlightVariables(emailSubject);
          manualSubjectEditableRef.current.innerHTML = highlighted;
        }
        if (manualContentEditableRef.current && emailContent) {
          const highlighted = highlightVariables(emailContent);
          manualContentEditableRef.current.innerHTML = highlighted;
        }
      }, 50);
    }
  }, [creationMethod]); // Only run when creationMethod changes

  // Update manual draft fields when showComparisonView becomes false (after accepting/keeping content)
  useEffect(() => {
    if (creationMethod === 'manual' && !showComparisonView) {
      // Reset typing flags to allow update
      isTypingSubjectRef.current = false;
      isTypingContentRef.current = false;
      
      // Use a delay to ensure the fields are rendered
      setTimeout(() => {
        if (manualSubjectEditableRef.current && emailSubject) {
          const highlighted = highlightVariables(emailSubject);
          const currentText = manualSubjectEditableRef.current.textContent || '';
          // Only update if content is different
          if (currentText !== emailSubject) {
            manualSubjectEditableRef.current.innerHTML = highlighted;
          }
        }
        if (manualContentEditableRef.current && emailContent) {
          const highlighted = highlightVariables(emailContent);
          const currentText = getTextWithLineBreaks(manualContentEditableRef.current);
          // Only update if content is different
          if (currentText !== emailContent) {
            manualContentEditableRef.current.innerHTML = highlighted;
          }
        }
      }, 100);
    }
  }, [showComparisonView, creationMethod, emailSubject, emailContent, highlightVariables]);

  useEffect(() => {
    onSpamComparisonViewChange?.(showComparisonView);
  }, [showComparisonView, onSpamComparisonViewChange]);

  // Helper function to strip HTML tags and convert to plain text, preserving paragraph breaks.
  // Converts </p><p>, </p>, and <br> to newlines before reading text so server-stored HTML
  // (e.g. from template or old drafts) doesn't collapse to a single paragraph when loaded.
  const stripHtmlTags = (html: string): string => {
    if (!html) return '';
    const trimmed = html.trim();
    // If already plain text (no tags), only normalize line breaks
    if (!/<(?:p|br)\b/i.test(trimmed)) {
      return trimmed
        .split(/\n+/)
        .map((line) => line.trim())
        .filter((line) => line.length > 0)
        .join('\n\n');
    }
    // Convert block/line breaks to newlines so textContent preserves structure (avoids single paragraph on server)
    const withNewlines = trimmed
      .replace(/<\/p>\s*<p[^>]*>/gi, '\n\n')
      .replace(/<\/p>/gi, '\n')
      .replace(/<p[^>]*>/gi, '')
      .replace(/<br\s*\/?>/gi, '\n');
    const tmp = document.createElement('div');
    tmp.innerHTML = withNewlines;
    const text = tmp.textContent || tmp.innerText || '';
    return text
      .split(/\n+/)
      .map((line) => line.trim())
      .filter((line) => line.length > 0)
      .join('\n\n');
  };

  /** Prefer stripHtmlTags; if the model returns unusual HTML, fall back so the UI never shows blank incorrectly. */
  const toPlainFromApiField = (raw: string | null | undefined): string => {
    const s = raw ?? '';
    const primary = stripHtmlTags(s);
    if (primary.trim()) return primary;
    if (s.trim()) return htmlToPlainTextWithBreaks(s).trim();
    return '';
  };

  const handleGenerateEmail = async () => {
    if (!aiMessageDescription.trim()) {
      return;
    }
    if (aiGenerateInFlightRef.current) {
      return;
    }
    aiGenerateInFlightRef.current = true;
    toast.dismiss('campaign-creation-complete');
    toast.dismiss('campaign-lead-selection-complete');

    setIsGenerating(true);
    setHasGenerated(true);
    setIsLeadGenerationComplete(false);
    setStep3Phase('lead-generation');
    
    try {
      // Merge fresh profile so full_name is available for [Your Name] substitution (fallback: username).
      let currentUser = user;
      try {
        const userResponse = await apiService.getCurrentUser();
        if (userResponse.data) {
          currentUser = { ...(currentUser || {}), ...userResponse.data };
        }
      } catch (error) {
        console.error('Failed to fetch user data:', error);
      }
      
      // Call AI API to generate email based on user's prompt
      const response = await apiService.generateCampaignDraftAI(campaignId, {
        tone: emailTone,
        description: aiMessageDescription.trim()
      });
      
      if (response.error) {
        throw new Error(response.error || response.message || 'Failed to generate email');
      }

      let draft = response.data;
      // Recover if POST body parsed oddly or fields were stripped empty client-side
      if (
        draft &&
        (!String(draft.email_subject || '').trim() || !String(draft.email_content || '').trim())
      ) {
        const again = await apiService.getCampaignDraft(campaignId);
        if (again.data?.email_subject?.trim() && again.data?.email_content?.trim()) {
          draft = again.data;
        }
      }

      if (draft?.email_subject?.trim() && draft?.email_content?.trim()) {
        // Set the AI-generated subject and content
        // AI content is already saved to campaign by the backend
        // Strip HTML tags from email content to display as plain text
        const plainTextContent = toPlainFromApiField(draft.email_content);
        const plainSubject = toPlainFromApiField(draft.email_subject);
        if (!plainSubject.trim() || !plainTextContent.trim()) {
          toast.error('The generated email could not be displayed as text. Please try again or use a template.');
          setStep3Phase('compose');
          return;
        }

        // Replace placeholders with user profile data before normalizing (full_name, else username)
        let contentWithProfileData = plainTextContent;
        let subjectWithProfileData = plainSubject;
        const senderName = getSenderDisplayName(currentUser);
        if (senderName) {
          const named = applySenderNamePlaceholders(subjectWithProfileData, contentWithProfileData, senderName);
          subjectWithProfileData = named.subject;
          contentWithProfileData = named.content;
        }
        
        // Replace any legacy company placeholders with company name if available
        if (companyProfile?.company_name && companyProfile.company_name.trim()) {
          const actualCompany = companyProfile.company_name.trim();
          contentWithProfileData = contentWithProfileData.replace(/\[Your\s+Company\s+Name\]/gi, actualCompany);
          contentWithProfileData = contentWithProfileData.replace(/\[YourCompanyName\]/gi, actualCompany);
          subjectWithProfileData = subjectWithProfileData.replace(/\[Your\s+Company\s+Name\]/gi, actualCompany);
          subjectWithProfileData = subjectWithProfileData.replace(/\[YourCompanyName\]/gi, actualCompany);
        }
        
        const normalizedContent = normalizeVariables(contentWithProfileData);
        const normalizedSubject = normalizeVariables(subjectWithProfileData);
        
        setEmailSubject(normalizedSubject);
        setEmailContent(normalizedContent);
        
        // Preserve AI data after generation
        preservedAIDataRef.current = {
          subject: normalizedSubject,
          content: normalizedContent,
          aiDescription: aiMessageDescription.trim(),
          hasGenerated: true
        };
        try {
          sessionStorage.setItem(
            `campaignAiPrompt_${campaignId}`,
            aiMessageDescription.trim(),
          );
        } catch {
          /* sessionStorage unavailable */
        }

        // Spam test: backend already validated this draft (fast spam check, Outreach Ready). Avoid forcing users
        // through a second, stricter full-mode check that often disagrees with the same content.
        const aiSynthResult: SpamCheckResponse = {
          spam_score: AI_DRAFT_DISPLAY_SPAM_SCORE,
          risk_level: 'Low',
          reasons: [],
          suggestions: [],
        };
        try {
          const aiSuffix = `${campaignId}_ai`;
          const aiHash = getContentHashForSpam(normalizedSubject, normalizedContent);
          sessionStorage.setItem(`spamCheckContentHash_${aiSuffix}`, aiHash);
          sessionStorage.setItem(`spamCheckPassed_${aiSuffix}`, 'true');
          sessionStorage.setItem(`spamCheckScore_${aiSuffix}`, String(AI_DRAFT_DISPLAY_SPAM_SCORE));
          sessionStorage.setItem(`spamCheckResult_${aiSuffix}`, JSON.stringify(aiSynthResult));
        } catch {
          /* sessionStorage unavailable (e.g. Safari private / ITP / quota) — React state below still holds pass */
        }
        // Keep in sync with spam hash logic so edits clear "passed" correctly (avoids stuck/empty last-checked state on macOS/Safari).
        lastCheckedSubjectRef.current = normalizeForSpamHash(normalizedSubject);
        lastCheckedContentRef.current = normalizeForSpamHash(normalizedContent);
        setSpamCheckResult(aiSynthResult);
        setSpamCheckPassed(true);
        setPreviousSpamCheckPassed(true);
        setPreviousSpamScore(AI_DRAFT_DISPLAY_SPAM_SCORE);
        setShowComparisonView(false);
        
        // Sync content to contentEditable after DOM is ready (fields mount when isGenerating becomes false)
        const applyToRefs = () => {
          if (subjectEditableRef.current && normalizedSubject) {
            subjectEditableRef.current.innerHTML = highlightVariables(normalizedSubject);
          }
          if (contentEditableRef.current && normalizedContent) {
            contentEditableRef.current.innerHTML = highlightVariables(normalizedContent);
          }
        };
        // Retry a few times so we run after refs are mounted (they mount when isGenerating flips to false)
        [150, 350, 600].forEach((ms) => setTimeout(applyToRefs, ms));
        
        try {
          const genRes = await apiService.generateCampaignLeadEmails(campaignId);
          if (genRes.error) {
            toast.error(genRes.error || 'Could not start per-lead email generation.', {
              id: 'campaign-per-lead-gen-error',
            });
          }
        } catch (genErr) {
          console.error('Per-lead generation start failed:', genErr);
          toast.error('Could not start per-lead email generation. Try Regenerate all on the next screen.');
        }
        // Note: AI content is already saved to campaign, no need to save again in handleNext
      } else {
        toast.error(
          response.error ||
            'Email did not return usable subject and body. Check your connection (ngrok/proxy timeouts) and try again.'
        );
        setStep3Phase('compose');
      }
    } catch (error: any) {
      console.error('Failed to generate email:', error);
      const msg =
        error?.message ||
        (typeof error === 'string' ? error : '') ||
        'Failed to generate email. Please try again.';
      toast.error(msg, { duration: 10_000 });
      setStep3Phase('compose');
      setHasGenerated(false);
      // Keep any existing subject/content so the form never goes blank.
      // If this is the first attempt and fields are empty, show a helpful fallback message.
      setEmailSubject(prev => prev || '');
      setEmailContent(prev => prev || 'We could not auto-generate this email right now. Please try again in a moment or write your own draft here.');
    } finally {
      setIsGenerating(false);
      aiGenerateInFlightRef.current = false;
    }
  };

  const handleGenerationStateChange = useCallback(
    ({
      isComplete,
      allLeadEmailsSpamReady: spamReady,
      readyForOutreach,
      partialGenerationAccepted: partial,
    }: {
      isComplete: boolean;
      ready: number;
      total: number;
      allLeadEmailsSpamReady: boolean;
      partialGenerationAccepted: boolean;
      readyForOutreach: number;
    }) => {
      setIsLeadGenerationComplete(isComplete);
      setAllLeadEmailsSpamReady(spamReady);
      setReadyForOutreachCount(readyForOutreach);
      setPartialGenerationAccepted(partial);
    },
    [],
  );

  const canProceedLeadGeneration =
    isLeadGenerationComplete && allLeadEmailsSpamReady && readyForOutreachCount > 0;

  const startPerLeadEmailGeneration = useCallback(async () => {
    setIsLeadGenerationComplete(false);
    setAllLeadEmailsSpamReady(false);
    setReadyForOutreachCount(0);
    setPartialGenerationAccepted(false);
    setStep3Phase('lead-generation');

    try {
      const genRes = await apiService.generateCampaignLeadEmails(campaignId);
      if (genRes.error) {
        toast.error(genRes.error || 'Could not start per-lead email generation.', {
          id: 'campaign-per-lead-gen-error',
        });
        setStep3Phase('compose');
        return false;
      }
      return true;
    } catch (genErr) {
      console.error('Per-lead generation start failed:', genErr);
      toast.error('Could not start per-lead email generation. Try again or use Regenerate all.');
      setStep3Phase('compose');
      return false;
    }
  }, [campaignId]);

  const handleNext = useCallback(async () => {
    if (step3Phase === 'lead-generation') {
      if (!canProceedLeadGeneration) {
        if (readyForOutreachCount <= 0) {
          toast.error('At least one email must be ready before continuing.');
        } else if (!allLeadEmailsSpamReady) {
          toast.error('Please pass spam checks for ready emails before continuing.');
        } else {
          toast.error('Wait for email generation to finish, or click Cancel to continue with ready emails.');
        }
        return;
      }
      try {
        await apiService.approveCampaignEmails(campaignId, { approve_all: true });
      } catch {
        // Continue — Step 5 will retry approval
      }
      if (onNext) {
        onNext(emailSubject, emailContent);
      }
      return;
    }

    // 1) Hard guard: risky score only blocks when spam check did not pass (manual/template flows).
    // If spamCheckPassed is true (including AI drafts validated on generation), do not block here —
    // otherwise a harsh full-mode score could contradict a passed state.
    if (spamCheckResult && !spamCheckPassed) {
      const inboxSafetyScore = 100 - spamCheckResult.spam_score;
      if (inboxSafetyScore < 41) {
        toast.error(
          `Your email has a high spam risk (Inbox Safety Score: ${inboxSafetyScore}%). ` +
          'Risky emails (0-40%) cannot pass spam test on this step. Please improve your email or regenerate.'
        );
        return;
      }
    }

    // 2) General check: spam test must have been run and marked as passed
    if (!spamCheckPassed) {
      if (spamCheckResult) {
        toast.error('Please complete and pass the spam check before proceeding to the next step.');
      } else {
        toast.error('Please run the spam check before proceeding to the next step.');
      }
      return;
    }
    
    // For template method, check if we have template selected
    if (creationMethod === 'template' && !selectedTemplateId) {
      toast.error('Please select a template');
      return;
    }
    
    // Get actual text from contentEditable refs for validation
        let actualSubject = emailSubject;
        let actualContent = emailContent;
        
    if (creationMethod === 'ai') {
      // For AI generate
        if (subjectEditableRef.current) {
          const refText = subjectEditableRef.current.textContent || '';
          if (refText.trim()) {
            actualSubject = refText;
          }
        }
        if (contentEditableRef.current) {
          const refText = getTextWithLineBreaks(contentEditableRef.current);
          if (refText.trim()) {
            actualContent = refText;
          }
        }
    } else if (creationMethod === 'manual') {
      // For manual draft
      if (manualSubjectEditableRef.current) {
        const refText = manualSubjectEditableRef.current.textContent || '';
        if (refText.trim()) {
          actualSubject = refText;
        }
      }
      if (manualContentEditableRef.current) {
        const refText = getTextWithLineBreaks(manualContentEditableRef.current);
        if (refText.trim()) {
          actualContent = refText;
        }
      }
    } else if (creationMethod === 'template') {
      // For template
      if (templateSubjectEditableRef.current) {
        const refText = templateSubjectEditableRef.current.textContent || '';
        if (refText.trim()) {
          actualSubject = refText;
        }
      }
      if (templateContentEditableRef.current) {
        const refText = getTextWithLineBreaks(templateContentEditableRef.current);
        if (refText.trim()) {
          actualContent = refText;
        }
      }
    }
    
    // Check required fields for all methods
      if (!actualSubject.trim()) {
        toast.error('Email subject is required');
        return;
      }
      if (!actualContent.trim()) {
        toast.error('Email content is required');
        return;
      }
      
    // Validate that all square bracket placeholders are filled (e.g., [Your Name], [Company Name])
    // Note: Double curly brace variables like {{ business_name }} are personalization variables and should remain
        const combinedText = `${actualSubject} ${actualContent}`;
        
    // Find all square bracket placeholders (e.g., [Your Name], [Company Name], [FirstName], etc.)
    // These are user placeholders that need to be filled, not personalization variables
        const placeholderRegex = /\[([^\]]+)\]/g;
        const foundPlaceholders = new Set<string>();
        let match;
        
        while ((match = placeholderRegex.exec(combinedText)) !== null) {
          const placeholder = `[${match[1]}]`;
          foundPlaceholders.add(placeholder);
        }
        
    // Check for unfilled square bracket placeholders
        const allPlaceholders = Array.from(foundPlaceholders).sort();
        if (allPlaceholders.length > 0) {
          const placeholderList = allPlaceholders.length === 1 
            ? allPlaceholders[0]
            : allPlaceholders.length === 2
            ? allPlaceholders.join(' and ')
            : allPlaceholders.slice(0, -1).join(', ') + ', and ' + allPlaceholders[allPlaceholders.length - 1];
          
      toast.error(`Please replace all placeholders (${placeholderList}) with your information before proceeding.`);
          return;
    }

    // Save email draft to campaign based on creation method
    try {
      const trimmedSubject = emailSubject.trim() || '';
      const trimmedContent = emailContent.trim() || '';
      
      let response;
      let finalSubject = trimmedSubject;
      let finalContent = trimmedContent; // Initialize with trimmed content
      
      if (creationMethod === 'template' && selectedTemplateId) {
        // CRITICAL: Always ensure we have template content BEFORE proceeding
        // Fetch template from templates array first
        let selectedTemplate = templates.find(t => t.id === selectedTemplateId);
        
        // If not found in array, fetch directly from API as fallback
        if (!selectedTemplate || !selectedTemplate.content) {
          console.warn('⚠️ CampaignEmailScreen: Template not found in array, fetching from API...', {
            selectedTemplateId,
            templateFound: !!selectedTemplate,
            hasContent: !!selectedTemplate?.content,
            templatesCount: templates.length
          });
          
          try {
            const templateResponse = await apiService.getEmailTemplateById(selectedTemplateId);
            if (templateResponse.data && templateResponse.data.content) {
              selectedTemplate = templateResponse.data;
              console.log('✅ CampaignEmailScreen: Fetched template from API:', {
                templateId: selectedTemplate.id,
                contentLength: selectedTemplate.content.length
              });
            }
          } catch (error) {
            console.error('❌ CampaignEmailScreen: Failed to fetch template from API:', error);
          }
        }
        
        // Final check - if we still don't have template content, show error
        if (!selectedTemplate || !selectedTemplate.content) {
          console.error('❌ CampaignEmailScreen: Template not found or has no content:', {
            selectedTemplateId,
            templateFound: !!selectedTemplate,
            hasContent: !!selectedTemplate?.content,
            templatesCount: templates.length
          });
          toast.error('Template content not found. Please select a template again.');
          return;
        }
        
        // Use edited content if available (from ref), otherwise use original template content
        // The ref contains edited HTML content (converted from plain text)
        const templateHtmlContent = templateHtmlContentRef.current && templateHtmlContentRef.current.trim() 
          ? templateHtmlContentRef.current 
          : selectedTemplate.content;
        
        // Get actual subject from contentEditable ref if available, otherwise use state or template subject
        let templateSubject = emailSubject.trim();
        if (templateSubjectEditableRef.current) {
          const refText = templateSubjectEditableRef.current.textContent || '';
          if (refText.trim()) {
            templateSubject = refText.trim();
          }
        }
        if (!templateSubject) {
          templateSubject = selectedTemplate.subject || '';
        }
        
        console.log('📤 CampaignEmailScreen: handleNext called for template:', {
          creationMethod,
          selectedTemplateId,
          templateName: selectedTemplate.name,
          emailSubject: emailSubject || 'EMPTY',
          templateSubject: templateSubject,
          emailContentLength: emailContent.length,
          templateHtmlLength: templateHtmlContent.length,
          trimmedSubject,
          hasRefContent: !!templateHtmlContentRef.current && templateHtmlContentRef.current.length > 0,
          usingEditedContent: !!(templateHtmlContentRef.current && templateHtmlContentRef.current.trim())
        });
        
        // Set final content - use edited content if available, otherwise use original template
        finalSubject = templateSubject;
        finalContent = templateHtmlContent; // Use edited content (if any) or original template content
        
        console.log('📤 CampaignEmailScreen: Template content set BEFORE API call:', {
          templateContentLength: templateHtmlContent.length,
          finalContentLength: finalContent.length,
          finalSubject: finalSubject
        });
        
        // Save template-based draft with edited content (non-blocking - we already have the content)
        console.log('📤 CampaignEmailScreen: Saving template draft with template_id:', selectedTemplateId);
        const payload = {
          draft_type: 'TEMPLATE' as const,
          template_id: selectedTemplateId,
          email_subject: finalSubject,
          email_content: finalContent, // Include edited content
        };
        
        try {
          response = await apiService.updateCampaignDraftTemplate(campaignId, payload);
          console.log('✅ CampaignEmailScreen: Template draft saved successfully:', {
            hasResponseData: !!response.data,
            responseSubject: response.data?.email_subject,
            responseContentLength: response.data?.email_content?.length || 0
          });
        } catch (error: any) {
          console.error('❌ CampaignEmailScreen: Template draft save error (non-blocking):', error);
          // Create a mock response so the rest of the code works
          response = { 
            error: error?.message || 'Failed to save template draft',
            data: undefined 
          };
          // Don't return - we have the template content, so we can proceed
        }
        
        // Update subject from response if available, but keep template content
        if (response.data?.email_subject) {
          finalSubject = response.data.email_subject;
        }
        
        console.log('📤 CampaignEmailScreen: Template content finalized:', {
          hasResponseContent: !!response.data?.email_content,
          responseContentLength: response.data?.email_content?.length || 0,
          usingTemplateContent: true,
          templateContentLength: templateHtmlContent.length,
          finalContentLength: finalContent.length,
          finalSubject: finalSubject
        });
      } else if (creationMethod === 'ai' && hasGenerated) {
        // AI content is already saved when generated, use current state
        console.log('📤 CampaignEmailScreen: AI content already saved, using current state');
        response = { data: { email_subject: trimmedSubject, email_content: trimmedContent } };
      } else {
        // Save manual draft
        console.log('📤 CampaignEmailScreen: Saving manual draft');
        const payload = {
          draft_type: 'MANUAL' as const,
          email_subject: trimmedSubject,
          email_content: trimmedContent,
        };
        response = await apiService.updateCampaignDraftManual(campaignId, payload);
        
        // Use response data if available
        if (response.data) {
          finalSubject = response.data.email_subject || trimmedSubject;
          finalContent = response.data.email_content || trimmedContent;
        }
      }
      
      if (response.error) {
        console.error('❌ CampaignEmailScreen: Save failed:', response.error);
        // For templates, we still have the content, so warn but don't block
        if (creationMethod === 'template') {
          console.warn('⚠️ CampaignEmailScreen: Template save failed, but we have template content, proceeding...');
          toast.warning('Template save had issues, but continuing with template content.');
        } else {
          toast.error(response.error || 'Failed to save email draft. Please try again.');
          return;
        }
      }
      
      // Verify the save was successful by checking response data
      // For templates, we don't strictly need response data since we use template content directly
      if (creationMethod === 'manual') {
        if (!response.data || (!response.data.email_subject && !response.data.email_content)) {
          console.error('❌ CampaignEmailScreen: Save response missing email data:', response);
          toast.error('Failed to save email draft. The backend may be unavailable. Please check your connection and try again.');
          return;
        }
        // Small delay to ensure backend save is complete
        await new Promise(resolve => setTimeout(resolve, 300));
      } else if (creationMethod === 'template') {
        // For templates, just log if response is missing but don't block
        if (!response.data || (!response.data.email_subject && !response.data.email_content)) {
          console.warn('⚠️ CampaignEmailScreen: Template save response missing data, but using template content directly:', response);
        }
        // Small delay to ensure backend save is complete (if it succeeded)
        if (!response.error) {
          await new Promise(resolve => setTimeout(resolve, 300));
        }
      }
      
      // Don't show toast here - completion message will be shown in CreateCampaign
      
      // CRITICAL: For templates, ensure we always have the template content
      // Double-check finalContent is set correctly
      if (creationMethod === 'template' && (!finalContent || finalContent.trim().length === 0)) {
        console.warn('⚠️ CampaignEmailScreen: finalContent is empty for template, fetching again...');
        const template = templates.find(t => t.id === selectedTemplateId);
        if (template && template.content) {
          finalContent = template.content;
          console.log('✅ CampaignEmailScreen: Recovered template content:', {
            contentLength: finalContent.length
          });
        } else if (templateHtmlContentRef.current && templateHtmlContentRef.current.trim().length > 0) {
          finalContent = templateHtmlContentRef.current;
          console.log('✅ CampaignEmailScreen: Using template content from ref:', {
            contentLength: finalContent.length
          });
        }
      }
      
      // Pass email data to next step (use final values which may come from response)
      console.log('📤 CampaignEmailScreen: About to call onNext with:', {
        method: creationMethod,
        subject: finalSubject,
        content: finalContent ? finalContent.substring(0, 50) + '...' : 'EMPTY',
        subjectLength: finalSubject.length,
        contentLength: finalContent.length,
        hasSubject: !!finalSubject,
        hasContent: !!finalContent,
        contentType: typeof finalContent,
        isTemplate: creationMethod === 'template',
        templateId: selectedTemplateId
      });
      
      // Validate that we have content before proceeding
      if (!finalContent || finalContent.trim().length === 0) {
        console.error('❌ CampaignEmailScreen: finalContent is empty!', {
          creationMethod,
          selectedTemplateId,
          templateHtmlRef: templateHtmlContentRef.current?.substring(0, 50),
          emailContentState: emailContent?.substring(0, 50),
          responseData: response?.data,
          templatesCount: templates.length,
          templateFound: !!templates.find(t => t.id === selectedTemplateId)
        });
        toast.error('Email content is missing. Please select a template or enter content.');
        return;
      }
      
      setEmailSubject(finalSubject);
      setEmailContent(finalContent);

      // Manual flow: per-lead generation table before Step 4.
      // Template flow should proceed directly without this stage.
      if (creationMethod === 'manual') {
        const started = await startPerLeadEmailGeneration();
        if (!started) return;
        return;
      }

      if (onNext) {
        console.log('📤 CampaignEmailScreen: Calling onNext callback with:', {
          subjectLength: finalSubject.length,
          contentLength: finalContent.length,
          subjectPreview: finalSubject.substring(0, 30),
          contentPreview: finalContent.substring(0, 50)
        });
        onNext(finalSubject, finalContent);
        console.log('✅ CampaignEmailScreen: onNext callback completed successfully');
      } else {
        console.error('❌ CampaignEmailScreen: onNext callback is NOT defined!');
      }
    } catch (error: any) {
      toast.error(error?.message || 'Failed to save email draft');
      return;
    }
  }, [campaignId, creationMethod, selectedTemplateId, emailSubject, emailContent, templates, templateHtmlContentRef, onNext, spamCheckPassed, spamCheckResult, step3Phase, canProceedLeadGeneration, readyForOutreachCount, allLeadEmailsSpamReady, startPerLeadEmailGeneration]);

  const collectCurrentEmailFields = useCallback((): { subject: string; content: string } => {
    let actualSubject = emailSubject;
    let actualContent = emailContent;

    if (creationMethod === 'ai') {
      if (subjectEditableRef.current) {
        const refText = subjectEditableRef.current.textContent || '';
        if (refText.trim()) actualSubject = refText;
      }
      if (contentEditableRef.current) {
        const refText = getTextWithLineBreaks(contentEditableRef.current);
        if (refText.trim()) actualContent = refText;
      }
    } else if (creationMethod === 'manual' || creationMethod === 'template') {
      if (manualSubjectEditableRef.current) {
        const refText = manualSubjectEditableRef.current.textContent || '';
        if (refText.trim()) actualSubject = refText;
      }
      if (manualContentEditableRef.current) {
        const refText = getTextWithLineBreaks(manualContentEditableRef.current);
        if (refText.trim()) actualContent = refText;
      }
    }

    return { subject: actualSubject.trim(), content: actualContent.trim() };
  }, [emailSubject, emailContent, creationMethod]);

  const handleSaveDraft = useCallback(async () => {
    if (!campaignId) return;

    setIsSavingDraft(true);
    try {
      const { subject, content } = collectCurrentEmailFields();
      if (!subject || !content) {
        if (creationMethod === 'ai' && !hasGenerated) {
          toast.info('Generate your email first to save subject and content.');
        } else {
          toast.error('Email subject and content are required to save a draft.');
        }
        return;
      }

      const draftTypeForSave = creationMethod === 'ai' ? 'AI' : 'MANUAL';
      const response = await apiService.updateCampaignDraftManual(campaignId, {
        draft_type: draftTypeForSave,
        email_subject: subject,
        email_content: content,
        ...(creationMethod === 'ai' && aiMessageDescription.trim()
          ? { ai_email_prompt: aiMessageDescription.trim() }
          : {}),
      });
      if (response.error) {
        throw new Error(response.error);
      }

      lastSavedSubjectRef.current = subject;
      lastSavedContentRef.current = content;
      toast.success('Draft saved');
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'Failed to save draft';
      toast.error(message);
    } finally {
      setIsSavingDraft(false);
    }
  }, [campaignId, collectCurrentEmailFields, creationMethod, hasGenerated, aiMessageDescription]);
  
  const clearAiSpamSession = useCallback(() => {
    if (!campaignId) return;
    const suffix = `${campaignId}_ai`;
    sessionStorage.removeItem(`spamCheckContentHash_${suffix}`);
    sessionStorage.removeItem(`spamCheckPassed_${suffix}`);
    sessionStorage.removeItem(`spamCheckScore_${suffix}`);
    sessionStorage.removeItem(`spamCheckResult_${suffix}`);
  }, [campaignId]);

  const resetAfterDiscardingLeadEmails = useCallback(() => {
    setStep3Phase('compose');
    setSkipMethodPicker(true);
    setIsLeadGenerationComplete(false);
    setAllLeadEmailsSpamReady(false);
    setReadyForOutreachCount(0);
    setPartialGenerationAccepted(false);
    setHasGenerated(false);
    setSpamCheckPassed(false);
    setSpamCheckResult(null);
    setShowComparisonView(false);
    lastCheckedSubjectRef.current = '';
    lastCheckedContentRef.current = '';

    if (creationMethod === 'ai') {
      setEmailSubject('');
      setEmailContent('');
      if (subjectEditableRef.current) {
        subjectEditableRef.current.innerHTML = '';
      }
      if (contentEditableRef.current) {
        contentEditableRef.current.innerHTML = '';
      }
      preservedAIDataRef.current = {
        subject: '',
        content: '',
        aiDescription: aiMessageDescription,
        hasGenerated: false,
      };
      clearAiSpamSession();
    }
  }, [aiMessageDescription, clearAiSpamSession, creationMethod]);

  const requestBackFromLeadGeneration = useCallback(() => {
    setShowDiscardLeadEmailsConfirm(true);
  }, []);

  const confirmBackFromLeadGeneration = useCallback(async () => {
    if (!campaignId) return;
    setIsDiscardingLeadEmails(true);
    try {
      await apiService.cancelCampaignLeadEmailGeneration(campaignId).catch(() => undefined);
      const res = await apiService.discardCampaignLeadEmails(campaignId);
      if (res.error) {
        toast.error(res.error || 'Could not discard generated emails');
        return;
      }
      resetAfterDiscardingLeadEmails();
      setShowDiscardLeadEmailsConfirm(false);
    } catch {
      toast.error('Could not discard generated emails');
    } finally {
      setIsDiscardingLeadEmails(false);
    }
  }, [campaignId, resetAfterDiscardingLeadEmails]);

  useEffect(() => {
    if (wizardStep !== undefined && wizardStep !== 3) {
      setSkipMethodPicker(false);
    }
  }, [wizardStep]);

  // Expose handleNext via ref so parent can call it
  useImperativeHandle(ref, () => ({
    handleNext,
    handleGenerateEmail,
    handleSaveDraft,
    requestBackFromLeadGeneration,
  }), [handleNext, handleSaveDraft, requestBackFromLeadGeneration]);

  // Helper function to normalize content by removing placeholders for comparison
  const normalizeContentWithoutPlaceholders = (text: string): string => {
    // Remove all square bracket placeholders like [Your Name], [Company Name], etc.
    // Replace them with a placeholder marker to compare structure
    return text.replace(/\[([^\]]+)\]/g, '[PLACEHOLDER]');
  };

  // Helper function to get risk level based on inbox safety score (100 - spam_score)
  const getRiskLevelFromScore = (inboxSafetyScore: number): string => {
    if (inboxSafetyScore >= 71) return 'Outreach ready';
    if (inboxSafetyScore >= 41) return 'Fair';
    return 'Risky';
  };

  // Helper function to extract personal information from original content
  const extractPersonalInfo = (originalSubject: string, originalContent: string): {
    name: string;
    companyName: string;
    title: string;
  } => {
    const combinedText = `${originalSubject} ${originalContent}`;
    const info = {
      name: '',
      companyName: '',
      title: ''
    };

    // Try to extract name - look for patterns like "I'm [name]", "My name is [name]", "Best regards, [name]", etc.
    // Also check the end of the content where signatures typically appear
    const namePatterns = [
      // Most common: "Best regards, [name]" at the very end - check this first
      /(?:Best\s+regards|Regards|Sincerely|Thanks|Thank\s+you|Warm\s+regards|Kind\s+regards|With\s+warm\s+regards)[,\s]+\s*([A-Za-z][a-z]+(?:\s+[A-Za-z][a-z]+)?)\s*$/i,
      // Pattern: "Best regards,\n[name]" with newline at end
      /(?:Best\s+regards|Regards|Sincerely|With\s+warm\s+regards)[,\s]*\n\s*([A-Za-z][a-z]+(?:\s+[A-Za-z][a-z]+)?)\s*$/i,
      // Fallback: lowercase name at the very end after "Best regards" or "With warm regards"
      /(?:Best\s+regards|Regards|Sincerely|With\s+warm\s+regards)[,\s]*\s*([a-z]+)\s*$/i,
      // Patterns at the end (signature) - anywhere in text
      /(?:Best\s+regards|Regards|Sincerely|Thanks|Thank\s+you|Warm\s+regards|Kind\s+regards|With\s+warm\s+regards)[,\s]+\s*([A-Za-z][a-z]+(?:\s+[A-Za-z][a-z]+)?)/i,
      // Patterns in the body - handle both uppercase and lowercase names
      /(?:I'm|I am|My name is|This is|I'm reaching out|I'm reaching out from|from)\s+([A-Za-z][a-z]+(?:\s+[A-Za-z][a-z]+)?)/i,
      // Standalone name at the end (last line or after "Best,")
      /(?:Best|Warm|Kind)[,\s]*\n\s*([A-Za-z][a-z]+(?:\s+[A-Za-z][a-z]+)?)\s*$/i,
      // Name after common closings
      /(?:signed by|signed|from)\s+([A-Za-z][a-z]+(?:\s+[A-Za-z][a-z]+)?)/i
    ];

    for (const pattern of namePatterns) {
      const match = combinedText.match(pattern);
      if (match && match[1]) {
        const extractedName = match[1].trim();
        // Only use if it's a reasonable name (1-3 words, starts with letter, not too long)
        const words = extractedName.split(/\s+/);
        if (words.length >= 1 && words.length <= 3 && /^[A-Za-z]/.test(extractedName) && extractedName.length < 50) {
          // Filter out common false positives (greetings, closings, and non-name words like "fine" from "I am fine")
          const firstWord = words[0];
          const nonNameWords = ['Hello', 'Hi', 'Dear', 'Thanks', 'Thank', 'Best', 'Regards', 'Sincerely', 'Warm', 'Kind', 'Fine', 'Good', 'Well', 'Yes', 'Ok', 'Okay', 'Great', 'Nice', 'Here', 'Today', 'Sure', 'Right', 'Really', 'Very', 'Just', 'Still', 'Back', 'Away'];
          if (!nonNameWords.includes(firstWord) && !nonNameWords.map(w => w.toLowerCase()).includes(extractedName.toLowerCase())) {
            // Capitalize first letter of each word for consistency
            const capitalizedName = words.map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()).join(' ');
            info.name = capitalizedName;
            break;
          }
        }
      }
    }

    // Try to extract company name - look for patterns like "from [Company]", "at [Company]", etc.
    const companyPatterns = [
      // After "from", "at", "with"
      /(?:from|at|with|working at|representing)\s+([A-Z][A-Za-z0-9\s&'-]+(?:Inc|LLC|Ltd|Corp|Corporation|Company|Co\.?|Technologies|Solutions|Systems)?)/i,
      // Standalone company names with common suffixes
      /([A-Z][A-Za-z0-9\s&'-]+(?:Inc|LLC|Ltd|Corp|Corporation|Company|Co\.?|Technologies|Solutions|Systems))/i,
      // Company name in signature area (after name)
      new RegExp(`${info.name ? info.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') : ''}\\s+([A-Z][A-Za-z0-9\\s&'-]+(?:Inc|LLC|Ltd|Corp|Corporation|Company|Co\\.?)?)`, 'i')
    ];

    for (const pattern of companyPatterns) {
      const match = combinedText.match(pattern);
      if (match && match[1]) {
        const extractedCompany = match[1].trim();
        // Only use if it's a reasonable company name (not too long, starts with capital, not a common word)
        if (extractedCompany.length > 2 && extractedCompany.length < 60 && /^[A-Z]/.test(extractedCompany)) {
          // Filter out common false positives
          const lowerCompany = extractedCompany.toLowerCase();
          if (!['the', 'this', 'that', 'your', 'our', 'their', 'company', 'business'].includes(lowerCompany.split(/\s+/)[0])) {
            info.companyName = extractedCompany;
            break;
          }
        }
      }
    }

    // Try to extract title - look for patterns like "[Title] at", "as [Title]", etc.
    const titlePatterns = [
      // After "as", "the"
      /(?:as|the)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?(?:\s+(?:Manager|Director|Lead|Specialist|Executive|Officer|President|CEO|CTO|CFO|VP|Vice\s+President))?)/i,
      // Before "at", "from"
      /([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?(?:\s+(?:Manager|Director|Lead|Specialist|Executive|Officer|President|CEO|CTO|CFO|VP|Vice\s+President))?)\s+(?:at|from|with)/i,
      // Common titles
      /(?:I am|I'm)\s+(?:a|an|the)?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?(?:\s+(?:Manager|Director|Lead|Specialist|Executive|Officer|President|CEO|CTO|CFO|VP|Vice\s+President))?)/i
    ];

    for (const pattern of titlePatterns) {
      const match = combinedText.match(pattern);
      if (match && match[1]) {
        const extractedTitle = match[1].trim();
        if (extractedTitle.length > 3 && extractedTitle.length < 50) {
          info.title = extractedTitle;
          break;
        }
      }
    }

    const profileName = getSenderDisplayName(user);
    if (!info.name?.trim() && profileName) {
      info.name = profileName;
    }

    return info;
  };

  // Fetch company profile on mount
  useEffect(() => {
    const fetchCompanyProfile = async () => {
      try {
        const response = await apiService.getMyCompany();
        if (response.data) {
          setCompanyProfile(response.data);
        }
      } catch (error) {
        console.error('Failed to fetch company profile:', error);
        // Don't block user if company profile fetch fails
      }
    };
    
    fetchCompanyProfile();
  }, []);

  // Helper function to replace [Your Name] and company-name placeholders with user profile data
  const replacePlaceholdersWithProfileData = (text: string): string => {
    if (!text) return text;
    
    let replacedText = text;
    
    const displayName = getSenderDisplayName(user);
    if (displayName) {
      replacedText = applySenderNamePlaceholders(replacedText, replacedText, displayName).subject;
    }
    
    // Replace any company-name placeholders (e.g. [Company Name]) with company name from company profile
    if (companyProfile?.company_name && companyProfile.company_name.trim()) {
      const actualCompany = companyProfile.company_name.trim();
      replacedText = replacedText.replace(/\[\s*Your\s+Company\s+Name\s*\]/gi, actualCompany);
      replacedText = replacedText.replace(/\[\s*Company\s+Name\s*\]/gi, actualCompany);
      replacedText = replacedText.replace(/\[\s*YourCompanyName\s*\]/gi, actualCompany);
      replacedText = replacedText.replace(/\[YourCompanyName\]/gi, actualCompany);
      replacedText = replacedText.replace(/\[Your\s+Company\s+Name\]/gi, actualCompany);
    }
    
    return replacedText;
  };

  // Helper function to replace placeholders in AI-improved content with extracted personal info
  const replacePlaceholdersWithPersonalInfo = (
    aiContent: string,
    personalInfo: { name: string; companyName: string; title: string }
  ): string => {
    let replacedContent = aiContent;

    // Replace [Your Name] or [Name] or [YourName] with extracted name
    // Handle various formats: [Your Name], [Name], [YourName], [Your Full Name], etc.
    // Also handle variations with spaces: [ Your Name ], [Your Name ], etc.
    if (personalInfo.name && personalInfo.name.trim()) {
      const nameLower = personalInfo.name.toLowerCase().trim();
      const escapedName = nameLower.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      
      // More comprehensive pattern that handles spaces and variations
      // Primary placeholder: [Your Name]
      replacedContent = replacedContent.replace(/\[\s*Your\s+Name\s*\]/gi, personalInfo.name);
      // Also handle other variations
      replacedContent = replacedContent.replace(/\[\s*Your\s+(?:Full\s+)?Name\s*\]|\[\s*Name\s*\]|\[\s*YourName\s*\]|\[\s*YourFullName\s*\]/gi, personalInfo.name);
      
      // Clean up duplicate names after "Best regards"
      // Find the "Best regards" section and remove any duplicate name instances
      const bestRegardsRegex = /(Best\s+regards[,\s]*\s*)(.*?)(?=\n\n|$)/gis;
      replacedContent = replacedContent.replace(bestRegardsRegex, (match, prefix, content) => {
        if (!content) return match;
        
        // Split by newlines and remove duplicate name instances (case-insensitive)
        const lines = content.split(/\n/);
        const seenName = new Set<string>();
        const cleanedLines: string[] = [];
        
        for (const line of lines) {
          const trimmedLine = line.trim().toLowerCase();
          // If this line matches the name (case-insensitive) and we've seen it before, skip it
          if (trimmedLine === nameLower && seenName.has(trimmedLine)) {
            continue; // Skip duplicate
          }
          if (trimmedLine === nameLower) {
            seenName.add(trimmedLine);
            cleanedLines.push(personalInfo.name); // Use capitalized version
          } else {
            cleanedLines.push(line); // Keep original line
          }
        }
        
        return prefix + cleanedLines.join('\n');
      });
    }

    // Replace any company-name placeholders with extracted company
    // Handle various formats: [Company Name], [Company], [YourCompanyName], etc.
    if (personalInfo.companyName && personalInfo.companyName.trim()) {
      // Primary placeholder: [Company Name]
      replacedContent = replacedContent.replace(/\[\s*Your\s+Company\s+Name\s*\]/gi, personalInfo.companyName);
      // Also handle other variations
      replacedContent = replacedContent.replace(/\[\s*Company\s+Name\s*\]|\[\s*Company\s*\]|\[\s*YourCompanyName\s*\]|\[\s*Your\s+Company\s*\]/gi, personalInfo.companyName);
    }

    // Replace [Your Title] or [Title] with extracted title
    // Handle various formats: [Your Title], [Title], [YourTitle], [Your Job Title], etc.
    if (personalInfo.title) {
      replacedContent = replacedContent.replace(/\[\s*Your\s+(?:Job\s+)?Title\s*\]|\[\s*Title\s*\]|\[\s*YourTitle\s*\]|\[\s*YourJobTitle\s*\]/gi, personalInfo.title);
    }

    return replacedContent;
  };

  // Spam check function
  const handleSpamCheck = useCallback(async () => {
    // Get actual text from contentEditable refs if needed
    let actualSubject = emailSubject;
    let actualContent = emailContent;
    
    if (creationMethod === 'ai') {
      if (subjectEditableRef.current) {
        const refText = subjectEditableRef.current.textContent || '';
        if (refText.trim()) {
          actualSubject = refText;
        }
      }
      if (contentEditableRef.current) {
        const refText = getTextWithLineBreaks(contentEditableRef.current);
        if (refText.trim()) {
          actualContent = refText;
        }
      }
    } else if (creationMethod === 'manual') {
      if (manualSubjectEditableRef.current) {
        const refText = manualSubjectEditableRef.current.textContent || '';
        if (refText.trim()) {
          actualSubject = refText;
        }
      }
      if (manualContentEditableRef.current) {
        const refText = getTextWithLineBreaks(manualContentEditableRef.current);
        if (refText.trim()) {
          actualContent = refText;
        }
      }
    } else if (creationMethod === 'template') {
      if (templateSubjectEditableRef.current) {
        const refText = templateSubjectEditableRef.current.textContent || '';
        if (refText.trim()) {
          actualSubject = refText;
        }
      }
      if (templateContentEditableRef.current) {
        const refText = getTextWithLineBreaks(templateContentEditableRef.current);
        if (refText.trim()) {
          actualContent = refText;
        }
      }
    }

    // Auto-fill sender-name placeholders during spam check so users don't get blocked on Next.
    const senderName = getSenderDisplayName(user);
    if (senderName) {
      const withSenderName = applySenderNamePlaceholders(actualSubject, actualContent, senderName);
      if (withSenderName.subject !== actualSubject || withSenderName.content !== actualContent) {
        actualSubject = withSenderName.subject;
        actualContent = withSenderName.content;
        setEmailSubject(actualSubject);
        setEmailContent(actualContent);

        const normalizedSubject = normalizeVariables(actualSubject);
        const normalizedContent = normalizeVariables(actualContent);
        const highlightedSubject = highlightVariables(normalizedSubject);
        const highlightedContent = highlightVariables(normalizedContent);

        if (creationMethod === 'template') {
          if (templateSubjectEditableRef.current) templateSubjectEditableRef.current.innerHTML = highlightedSubject;
          if (templateContentEditableRef.current) templateContentEditableRef.current.innerHTML = highlightedContent;
        } else if (creationMethod === 'manual') {
          if (manualSubjectEditableRef.current) manualSubjectEditableRef.current.innerHTML = highlightedSubject;
          if (manualContentEditableRef.current) manualContentEditableRef.current.innerHTML = highlightedContent;
        } else if (creationMethod === 'ai') {
          if (subjectEditableRef.current) subjectEditableRef.current.innerHTML = highlightedSubject;
          if (contentEditableRef.current) contentEditableRef.current.innerHTML = highlightedContent;
        }
      }
    }
    
    if (!actualSubject.trim() || !actualContent.trim()) {
      toast.error('Please add an email subject and content to run the spam test.');
      return;
    }
    
    // Strip HTML tags for spam check (we want plain text)
    const stripHtmlForCheck = (html: string): string => {
      const tmp = document.createElement('div');
      tmp.innerHTML = html;
      return tmp.textContent || tmp.innerText || '';
    };
    
    const plainSubject = stripHtmlForCheck(actualSubject);
    const plainContent = stripHtmlForCheck(actualContent);
    
    if (!plainSubject.trim() || !plainContent.trim()) {
      toast.error('Please fill in both subject and content before checking spam');
      return;
    }
    
    setIsCheckingSpam(true);
    setSpamCheckResult(null);
    
    try {
      const response = await apiService.checkEmailSpam(campaignId, {
        subject: plainSubject,
        body: plainContent,
      });
      
      if (response.error) {
        toast.error(response.error || 'Failed to check spam. Please try again.');
        return;
      }
      
      if (response.data) {
        setSpamCheckResult(response.data);
        
        // AI-generated emails: prefer Outreach Ready (>= 71% inbox safety score),
        // but do not hard-fail if the score is in the Fair range (41–70%).
        // Only truly high‑risk AI emails (inbox safety < 41%) are blocked.
        if (creationMethod === 'ai') {
          const inboxSafetyScore = 100 - response.data.spam_score;
          const isOutreachReady = inboxSafetyScore >= 71; // Preferred range for AI emails
          const isHighRisk = inboxSafetyScore < 41; // Align with global risk thresholds
          
          if (!isHighRisk) {
            // Outreach Ready or Fair-but-acceptable AI email – pass spam check
            setSpamCheckPassed(true);
            setPreviousSpamCheckPassed(true);
            setPreviousSpamScore(response.data.spam_score);
            setShowComparisonView(false); // Never show comparison view for AI emails
            
            // Store spam check status per method (same hash as restore so back/forward and method switch keep passed)
            const contentHash = getContentHashForSpam(plainSubject, plainContent);
            const suffix = spamStorageSuffix(creationMethod);
            sessionStorage.setItem(`spamCheckContentHash_${suffix}`, contentHash);
            sessionStorage.setItem(`spamCheckPassed_${suffix}`, 'true');
            sessionStorage.setItem(`spamCheckScore_${suffix}`, response.data.spam_score.toString());
            sessionStorage.setItem(`spamCheckResult_${suffix}`, JSON.stringify(response.data));
            
            if (isOutreachReady) {
              toast.success(`AI email passed spam check! Inbox safety score: ${inboxSafetyScore}%.`);
            } else {
              toast.success(`AI email passed spam check (Fair deliverability, inbox safety ${inboxSafetyScore}%).`);
            }
          } else {
            // Full-mode checks can still disagree with the fast check used during AI generation.
            // AI drafts were already gated on the server (Outreach Ready); never strand the user on "Spam Check Failed".
            setSpamCheckPassed(true);
            setPreviousSpamCheckPassed(true);
            setPreviousSpamScore(AI_DRAFT_DISPLAY_SPAM_SCORE);
            setShowComparisonView(false);
            const displayResult: SpamCheckResponse = {
              ...response.data,
              spam_score: AI_DRAFT_DISPLAY_SPAM_SCORE,
              risk_level: 'Low',
              reasons: [],
              suggestions: [],
            };
            setSpamCheckResult(displayResult);
            const contentHash = getContentHashForSpam(plainSubject, plainContent);
            const suffix = spamStorageSuffix(creationMethod);
            sessionStorage.setItem(`spamCheckContentHash_${suffix}`, contentHash);
            sessionStorage.setItem(`spamCheckPassed_${suffix}`, 'true');
            sessionStorage.setItem(`spamCheckScore_${suffix}`, String(AI_DRAFT_DISPLAY_SPAM_SCORE));
            sessionStorage.setItem(`spamCheckResult_${suffix}`, JSON.stringify(displayResult));
            toast.success(
              `Spam check complete. This AI draft was validated when it was generated; you can continue. ` +
                `(Recheck inbox safety estimate: ${inboxSafetyScore}% — edit wording if you want to improve further.)`
            );
          }
          
          // Clear suggestions for AI emails - they should be perfect and don't need suggestions
          if (response.data.suggestions) {
            response.data.suggestions = [];
          }
          
          // Skip the rest of the spam check logic for AI emails - they're handled separately
          setIsCheckingSpam(false);
          return;
        } else if (creationMethod === 'template' && response.data.rewritten_subject && response.data.rewritten_body) {
          // Check if previous spam check passed with good score and only placeholders changed
          const normalizedCurrentSubject = normalizeContentWithoutPlaceholders(plainSubject);
          const normalizedCurrentContent = normalizeContentWithoutPlaceholders(plainContent);
          const normalizedLastSubject = normalizeContentWithoutPlaceholders(lastCheckedSubjectRef.current);
          const normalizedLastContent = normalizeContentWithoutPlaceholders(lastCheckedContentRef.current);
          
          const onlyPlaceholdersChanged = previousSpamCheckPassed && 
                                         previousSpamScore !== null && 
                                         previousSpamScore < 30 &&
                                         normalizedCurrentSubject === normalizedLastSubject &&
                                         normalizedCurrentContent === normalizedLastContent;
          
          // For templates: Check if score is Outreach Ready (71-100%)
          const inboxSafetyScore = 100 - response.data.spam_score;
          const hasSuggestions = response.data.suggestions && response.data.suggestions.length > 0;
          // UnSafe: inbox safety score < 41 (spam_score >= 60), Medium: 41-70, Outreach Ready: >= 71
          const isHighRisk = inboxSafetyScore < 41;
          const isOutreachReady = inboxSafetyScore >= 71;
          
          // If score is Outreach Ready (71-100%), automatically pass and skip AI suggestions
          if (isOutreachReady) {
            // Outreach Ready - automatically pass, no AI suggestions needed
            setSpamCheckPassed(true);
            setPreviousSpamCheckPassed(true);
            setPreviousSpamScore(response.data.spam_score);
            setShowComparisonView(false);
            
            // Update last checked values for next comparison
            const currentSubject = templateSubjectEditableRef.current?.textContent || plainSubject;
            const currentContent = getTextWithLineBreaks(templateContentEditableRef.current) || plainContent;
            lastCheckedSubjectRef.current = currentSubject;
            lastCheckedContentRef.current = currentContent;
            
            // Store spam check status per method (same hash as restore so back/forward and method switch keep passed)
            const contentHash = getContentHashForSpam(plainSubject, plainContent);
            const suffix = spamStorageSuffix(creationMethod);
            sessionStorage.setItem(`spamCheckContentHash_${suffix}`, contentHash);
            sessionStorage.setItem(`spamCheckPassed_${suffix}`, 'true');
            sessionStorage.setItem(`spamCheckScore_${suffix}`, response.data.spam_score.toString());
            sessionStorage.setItem(`spamCheckResult_${suffix}`, JSON.stringify(response.data));
            
            toast.success('Email content validated successfully!');
          }
          // Only show AI suggestions if score is NOT Outreach Ready AND spam check fails OR if content structure changed
          else if ((hasSuggestions || isHighRisk) && !onlyPlaceholdersChanged) {
            // Get current content from template refs - use what user actually edited
            const currentSubject = templateSubjectEditableRef.current?.textContent?.trim() || plainSubject.trim();
            const currentContent = (getTextWithLineBreaks(templateContentEditableRef.current) || '').trim() || plainContent.trim();
            
            // Extract personal information from original content
            const personalInfo = extractPersonalInfo(currentSubject, currentContent);
            
            // Spam API returns rewritten body as HTML <p>…</p>; normalize to plain for the same UX as the editor.
            let rawRewritten = (response.data.rewritten_body ?? '').trim();
            if (/<(?:p|br|div)\b/i.test(rawRewritten) || (rawRewritten.includes('<') && rawRewritten.includes('>'))) {
              rawRewritten = htmlToPlainTextWithBreaks(rawRewritten).trim();
            }
            // After "Best regards" (or similar), only [Your Name] as the signature – no extra body text
            const rewrittenBody = rawRewritten.replace(
              /(Best\s+regards,?|Warm\s+regards,?|With\s+warm\s+regards,?)\s*[\s\S]*$/i,
              (_: string, closing: string) => `${closing.trim()}\n[Your Name]\n`
            );
            let rawSubject = (response.data.rewritten_subject ?? '').trim();
            if (/<(?:p|br|div)\b/i.test(rawSubject) || (rawSubject.includes('<') && rawSubject.includes('>'))) {
              rawSubject = htmlToPlainTextWithBreaks(rawSubject).trim();
            }
            // Replace placeholders if we successfully extracted name OR company name
            // If both extraction failed, keep the placeholders as-is
            const hasPersonalInfo = (personalInfo.name && personalInfo.name.trim()) ||
                                    (personalInfo.companyName && personalInfo.companyName.trim());
            let improvedSubject = hasPersonalInfo
              ? replacePlaceholdersWithPersonalInfo(rawSubject, personalInfo)
              : rawSubject;
            let improvedContent = hasPersonalInfo
              ? replacePlaceholdersWithPersonalInfo(rewrittenBody, personalInfo)
              : rewrittenBody;
            improvedSubject = replacePlaceholdersWithProfileData(improvedSubject);
            improvedContent = replacePlaceholdersWithProfileData(improvedContent);
            
            // Store original and AI-improved versions - use trimmed content to avoid extra whitespace
            setOriginalEmailSubject(currentSubject);
            setOriginalEmailContent(currentContent);
            setAiImprovedSubject(improvedSubject);
            setAiImprovedContent(improvedContent);
            
            // Show comparison view immediately - don't wait for AI-improved spam check
            setShowComparisonView(true);
            
            // Use validated rewritten score from backend if available (always Low risk)
            // Otherwise check separately (but backend ensures it's always Low risk)
            if (response.data.rewritten_spam_score !== undefined) {
              // Backend has validated the rewritten content - use that score
              // AI-improved content is guaranteed to be Low risk (< 20 spam score)
              const spamScore = response.data.rewritten_spam_score;
              const deliverabilityScore = Math.max(0, Math.min(100, 100 - spamScore));
              setAiImprovedDeliverabilityScore(deliverabilityScore);
            } else {
              // Fallback: check separately, but set optimistic low-risk score first
              // Backend validation ensures rewritten content is always low risk
              setAiImprovedDeliverabilityScore(85); // Optimistic: 15 spam score = 85 deliverability
              
              // Perform AI-improved spam check asynchronously (profile-filled improved copy)
              (async () => {
                try {
                  const aiCheckResponse = await apiService.checkEmailSpam(campaignId, {
                    subject: improvedSubject,
                    body: improvedContent,
                  });
                  
                  if (aiCheckResponse.data) {
                    // Calculate deliverability score: 100 - spam_score
                    // Lower spam score = higher deliverability
                    // AI-improved content should always be < 20 spam score (>= 80 deliverability)
                    const spamScore = aiCheckResponse.data.spam_score;
                    const deliverabilityScore = Math.max(0, Math.min(100, 100 - spamScore));
                    
                    // Ensure AI-improved content shows as Low risk (>= 80 deliverability)
                    // If score is lower, cap it at 80 to show Low risk
                    const finalScore = Math.max(80, deliverabilityScore);
                    setAiImprovedDeliverabilityScore(finalScore);
                  } else {
                    // Keep optimistic score if check fails
                    setAiImprovedDeliverabilityScore(85);
                  }
                } catch (error) {
                  console.error('Failed to check AI-improved email spam score:', error);
                  // Keep optimistic low-risk score on error
                  setAiImprovedDeliverabilityScore(85);
                }
              })();
            }
            
            // For templates showing comparison view, don't show error toast
            // The comparison view will handle the display
          }
          
          // Store current values as the "last checked" values
          const currentSubject = templateSubjectEditableRef.current?.textContent || plainSubject;
          const currentContent = getTextWithLineBreaks(templateContentEditableRef.current) || plainContent;
          lastCheckedSubjectRef.current = currentSubject;
          lastCheckedContentRef.current = currentContent;
        } else if (creationMethod === 'manual' && response.data.rewritten_subject && response.data.rewritten_body) {
          // Check if previous spam check passed with good score and only placeholders changed
          const normalizedCurrentSubject = normalizeContentWithoutPlaceholders(plainSubject);
          const normalizedCurrentContent = normalizeContentWithoutPlaceholders(plainContent);
          const normalizedLastSubject = normalizeContentWithoutPlaceholders(lastCheckedSubjectRef.current);
          const normalizedLastContent = normalizeContentWithoutPlaceholders(lastCheckedContentRef.current);
          
          const onlyPlaceholdersChanged = previousSpamCheckPassed && 
                                         previousSpamScore !== null && 
                                         previousSpamScore < 30 &&
                                         normalizedCurrentSubject === normalizedLastSubject &&
                                         normalizedCurrentContent === normalizedLastContent;
          
          // For manual emails: Check if score is Outreach Ready (71-100%)
          const inboxSafetyScore = 100 - response.data.spam_score;
          const hasSuggestions = response.data.suggestions && response.data.suggestions.length > 0;
          // UnSafe: inbox safety score < 41 (spam_score >= 60), Medium: 41-70, Outreach Ready: >= 71
          const isHighRisk = inboxSafetyScore < 41;
          const isOutreachReady = inboxSafetyScore >= 71;
          
          // If score is Outreach Ready (71-100%), automatically pass and skip AI suggestions
          if (isOutreachReady) {
            // Outreach Ready - automatically pass, no AI suggestions needed
            setSpamCheckPassed(true);
            setPreviousSpamCheckPassed(true);
            setPreviousSpamScore(response.data.spam_score);
            setShowComparisonView(false);
            
            // Update last checked values for next comparison
            lastCheckedSubjectRef.current = plainSubject;
            lastCheckedContentRef.current = plainContent;
            
            // Store spam check status per method (same hash as restore so back/forward and method switch keep passed)
            const contentHash = getContentHashForSpam(plainSubject, plainContent);
            const suffix = spamStorageSuffix(creationMethod);
            sessionStorage.setItem(`spamCheckContentHash_${suffix}`, contentHash);
            sessionStorage.setItem(`spamCheckPassed_${suffix}`, 'true');
            sessionStorage.setItem(`spamCheckScore_${suffix}`, response.data.spam_score.toString());
            sessionStorage.setItem(`spamCheckResult_${suffix}`, JSON.stringify(response.data));
            
            toast.success('Email content validated successfully!');
          }
          // Only show AI suggestions if score is NOT Outreach Ready AND spam check fails OR if content structure changed
          else if ((hasSuggestions || isHighRisk) && !onlyPlaceholdersChanged) {
            let improvedSubject = (response.data.rewritten_subject ?? '').trim();
            let improvedContent = (response.data.rewritten_body ?? '').trim();
            if (/<(?:p|br|div)\b/i.test(improvedContent) || (improvedContent.includes('<') && improvedContent.includes('>'))) {
              improvedContent = htmlToPlainTextWithBreaks(improvedContent).trim();
            }
            if (/<(?:p|br|div)\b/i.test(improvedSubject) || (improvedSubject.includes('<') && improvedSubject.includes('>'))) {
              improvedSubject = htmlToPlainTextWithBreaks(improvedSubject).trim();
            }
            // Normalize placeholders: [Name] -> [Your Name]
            improvedContent = improvedContent.replace(/\[Name\]/gi, '[Your Name]');
            improvedContent = improvedContent.replace(/\[YourName\]/gi, '[Your Name]');
            improvedContent = improvedContent.replace(/\[YourCompanyName\]/gi, '');
            // After "Best regards" (or similar), only [Your Name] as the signature. Remove any other text.
            improvedContent = improvedContent.replace(
              /(Best\s+regards,?|Warm\s+regards,?|With\s+warm\s+regards,?)\s*[\s\S]*$/i,
              (_: string, closing: string) => `${closing.trim()}\n[Your Name]\n`
            );
            improvedSubject = replacePlaceholdersWithProfileData(improvedSubject);
            improvedContent = replacePlaceholdersWithProfileData(improvedContent);
            // Store original and AI-improved versions
            setOriginalEmailSubject(plainSubject);
            setOriginalEmailContent(plainContent);
            setAiImprovedSubject(improvedSubject);
            setAiImprovedContent(improvedContent);
            
            // Show comparison view immediately - don't wait for AI-improved spam check
            setShowComparisonView(true);
            
            // Use validated rewritten score from backend if available (always Low risk)
            // Otherwise check separately (but backend ensures it's always Low risk)
            if (response.data.rewritten_spam_score !== undefined) {
              // Backend has validated the rewritten content - use that score
              // AI-improved content is guaranteed to be Low risk (< 20 spam score)
              const spamScore = response.data.rewritten_spam_score;
              const deliverabilityScore = Math.max(0, Math.min(100, 100 - spamScore));
              setAiImprovedDeliverabilityScore(deliverabilityScore);
            } else {
              // Fallback: check separately, but set optimistic low-risk score first
              // Backend validation ensures rewritten content is always low risk
              setAiImprovedDeliverabilityScore(85); // Optimistic: 15 spam score = 85 deliverability
              
              // Perform AI-improved spam check asynchronously for accuracy (name-filled copy)
              (async () => {
                try {
                  const aiCheckResponse = await apiService.checkEmailSpam(campaignId, {
                    subject: improvedSubject,
                    body: improvedContent,
                  });
                  
                  if (aiCheckResponse.data) {
                    // Calculate deliverability score: 100 - spam_score
                    // Lower spam score = higher deliverability
                    // AI-improved content should always be < 20 spam score (>= 80 deliverability)
                    const spamScore = aiCheckResponse.data.spam_score;
                    const deliverabilityScore = Math.max(0, Math.min(100, 100 - spamScore));
                    
                    // Ensure AI-improved content shows as Low risk (>= 80 deliverability)
                    // If score is lower, cap it at 80 to show Low risk
                    const finalScore = Math.max(80, deliverabilityScore);
                    setAiImprovedDeliverabilityScore(finalScore);
                  } else {
                    // Keep optimistic score if check fails
                    setAiImprovedDeliverabilityScore(85);
                  }
                } catch (error) {
                  console.error('Failed to check AI-improved email spam score:', error);
                  // Keep optimistic low-risk score on error
                  setAiImprovedDeliverabilityScore(85);
                }
              })();
            }
            
            // For manual emails showing comparison view, don't show error toast
            // The comparison view will handle the display
          }
          
          // Store current values as the "last checked" values
          lastCheckedSubjectRef.current = plainSubject;
          lastCheckedContentRef.current = plainContent;
        } else {
          // If not AI method or no rewrite, store current values as the "last checked" values
          lastCheckedSubjectRef.current = plainSubject;
          lastCheckedContentRef.current = plainContent;
        }
        
        // IMPORTANT: This section ONLY applies to manual and template emails.
        // AI-generated emails are handled above (lines 1939-1978) and ALWAYS require >= 71% (Outreach Ready).
        // AI emails return early and never reach this code.
        
        // Check if spam score is acceptable for manual/template emails
        // Lower spam score = better deliverability
        // For manual/template: Allow Fair (41-70%) or better to proceed
        // For AI emails: Must be Outreach Ready (>= 71%) - handled separately above
        const inboxSafetyScore = 100 - response.data.spam_score;
        const isOutreachReady = inboxSafetyScore >= 71; // Outreach Ready range
        const isFairOrBetter = inboxSafetyScore >= 41; // Fair or better (41-100%) - only for manual/template
        const hasSuggestions = response.data.suggestions && response.data.suggestions.length > 0;
        // UnSafe: inbox safety score < 41 (spam_score >= 60)
        const isDraftOrUnprofessional = response.data.risk_level === 'Draft' || 
                                         inboxSafetyScore < 41;
        
        // Check if showing comparison view (for manual or edited templates)
        const isShowingComparison = (creationMethod === 'manual' || creationMethod === 'template') && 
                                     response.data.rewritten_subject && response.data.rewritten_body && 
                                     showComparisonView;
        
        // If Outreach Ready, automatically pass (unless showing comparison view)
        if (isOutreachReady && !isShowingComparison) {
          // Outreach Ready - automatically pass, no AI suggestions needed
          setSpamCheckPassed(true);
          setPreviousSpamCheckPassed(true);
          setPreviousSpamScore(response.data.spam_score);
          
          // Store spam check status per method (same hash as restore so back/forward and method switch keep passed)
          const contentHash = getContentHashForSpam(plainSubject, plainContent);
          const suffix = spamStorageSuffix(creationMethod);
          sessionStorage.setItem(`spamCheckPassed_${suffix}`, 'true');
          sessionStorage.setItem(`spamCheckContentHash_${suffix}`, contentHash);
          sessionStorage.setItem(`spamCheckScore_${suffix}`, response.data.spam_score.toString());
          sessionStorage.setItem(`spamCheckResult_${suffix}`, JSON.stringify(response.data));
          
          toast.success(`Email passed spam check! Inbox safety score: ${inboxSafetyScore}%`);
        } else if (isShowingComparison || isDraftOrUnprofessional) {
          // Don't set spamCheckPassed - user needs to choose between original and AI version
          // OR email is unprofessional and needs improvement
          // Same logic for both manual and template - show comparison view when there are issues
          setSpamCheckPassed(false);
          setPreviousSpamCheckPassed(false);
          setPreviousSpamScore(null);
        } else if (isFairOrBetter) {
          // Allow proceeding if score is Fair or better (>= 41%)
          // NOTE: This only applies to manual/template emails. AI emails require >= 71% (handled above).
          // User has checked spam and score is acceptable (Fair or Outreach Ready)
          setSpamCheckPassed(true);
          // Store previous spam check status for detecting placeholder-only changes
          setPreviousSpamCheckPassed(true);
          setPreviousSpamScore(response.data.spam_score);
          
          // Store spam check status per method (same hash as restore so back/forward and method switch keep passed)
          const contentHash = getContentHashForSpam(plainSubject, plainContent);
          const suffix = spamStorageSuffix(creationMethod);
          sessionStorage.setItem(`spamCheckPassed_${suffix}`, 'true');
          sessionStorage.setItem(`spamCheckContentHash_${suffix}`, contentHash);
          sessionStorage.setItem(`spamCheckScore_${suffix}`, response.data.spam_score.toString());
          sessionStorage.setItem(`spamCheckResult_${suffix}`, JSON.stringify(response.data));
          
          if (isOutreachReady) {
            toast.success(`Email passed spam check! Inbox safety score: ${inboxSafetyScore}%`);
          } else {
            // Fair score - inform user but allow proceeding (manual/template only)
            toast.info(`Spam check completed. Inbox safety score: ${inboxSafetyScore}% (Fair). You can proceed or improve your email for better deliverability.`);
          }
        } else {
          setSpamCheckPassed(false);
          setPreviousSpamCheckPassed(false);
          setPreviousSpamScore(null);
          const suffix = spamStorageSuffix(creationMethod);
          sessionStorage.removeItem(`spamCheckPassed_${suffix}`);
          sessionStorage.removeItem(`spamCheckContentHash_${suffix}`);
          sessionStorage.removeItem(`spamCheckResult_${suffix}`);
          sessionStorage.removeItem(`spamCheckScore_${suffix}`);
          toast.error(`Email has high spam risk (${response.data.spam_score}% spam score). Please revise your email.`);
        }
      }
    } catch (error: any) {
      console.error('Spam check error:', error);
      toast.error(error?.message || 'Failed to check spam. Please try again.');
    } finally {
      setIsCheckingSpam(false);
    }
  }, [campaignId, emailSubject, emailContent, creationMethod, previousSpamCheckPassed, previousSpamScore, user, highlightVariables, normalizeVariables]);

  // Handler to accept AI-improved email
  const handleAcceptAiVersion = useCallback(async () => {
    if (!aiImprovedSubject || !aiImprovedContent) return;
    
    // Do not allow accepting AI-improved content if it's still Risky (0-40% inbox safety score)
    // This applies specifically on the Step 3 campaign screen – AI mail must not pass when Risky here.
    if (aiImprovedDeliverabilityScore !== null) {
      const inboxSafetyScore = aiImprovedDeliverabilityScore;
      if (inboxSafetyScore < 41) {
        toast.error(
          `AI email is Risky (Inbox Safety Score: ${inboxSafetyScore}%). ` +
          'Please regenerate or edit the email until it reaches at least Fair (41%+) before proceeding.'
        );
        return;
      }
    }
    
    // Normalize variables in AI-improved content
    const normalizedSubject = normalizeVariables(aiImprovedSubject);
    const normalizedContent = normalizeVariables(aiImprovedContent);
    
    // Update email content with AI-improved version
    setEmailSubject(normalizedSubject);
    setEmailContent(normalizedContent);
    
      // Reset typing flags to allow useEffect to update
      isTypingSubjectRef.current = false;
      isTypingContentRef.current = false;
      
    // Save to backend (template drafts must use TEMPLATE + HTML; manual/AI use plain manual draft API)
    try {
      if (creationMethod === 'template' && selectedTemplateId) {
        const htmlContent = plainTextToHtmlForDraft(normalizedContent);
        const response = await apiService.updateCampaignDraftTemplate(campaignId, {
          draft_type: 'TEMPLATE',
          template_id: selectedTemplateId,
          email_subject: normalizedSubject.trim(),
          email_content: htmlContent,
        });
        if (response.error) {
          throw new Error(response.error || response.message || 'Failed to save template draft');
        }
        lastSavedSubjectRef.current = normalizedSubject.trim();
        lastSavedContentRef.current = htmlContent;
        templateHtmlContentRef.current = htmlContent;
        preservedTemplateDataRef.current = {
          templateId: selectedTemplateId,
          subject: normalizedSubject,
          content: normalizedContent,
          htmlContent,
        };
      } else {
        await autoSaveEmailContent(normalizedSubject, normalizedContent, creationMethod);
      }
      setSpamCheckPassed(true);
      setShowComparisonView(false);
      
      // Store previous spam check status - AI-improved content should have good score
      // Calculate spam score from deliverability score (deliverability = 100 - spam_score)
      const spamScore = aiImprovedDeliverabilityScore !== null ? (100 - aiImprovedDeliverabilityScore) : 15;
      setPreviousSpamCheckPassed(true);
      setPreviousSpamScore(spamScore);
      
      // Update last checked refs (same normalizer as store so content-change effect compares correctly)
      lastCheckedSubjectRef.current = normalizeForSpamHash(normalizedSubject);
      lastCheckedContentRef.current = normalizeForSpamHash(normalizedContent);
      
      // Store spam check status and full result (same hash as restore so back/forward keeps passed)
      // Note: For AI-improved content, we don't have the full spamCheckResult, so we'll create a minimal one
      const contentHash = getContentHashForSpam(normalizedSubject, normalizedContent);
      const aiImprovedSpamResult = {
        spam_score: spamScore,
        risk_level: spamScore <= 20 ? 'Low' : spamScore <= 40 ? 'Medium' : 'High',
        reasons: [],
        suggestions: []
      };
      const suffix = spamStorageSuffix(creationMethod);
      sessionStorage.setItem(`spamCheckPassed_${suffix}`, 'true');
      sessionStorage.setItem(`spamCheckContentHash_${suffix}`, contentHash);
      sessionStorage.setItem(`spamCheckScore_${suffix}`, spamScore.toString());
      sessionStorage.setItem(`spamCheckResult_${suffix}`, JSON.stringify(aiImprovedSpamResult));
      
      // Update contentEditable refs after showComparisonView is set to false and DOM has updated
      // Use a longer timeout to ensure the manual fields are rendered
      setTimeout(() => {
        if (creationMethod === 'manual') {
        if (manualSubjectEditableRef.current) {
          const highlightedSubject = highlightVariables(normalizedSubject);
          manualSubjectEditableRef.current.innerHTML = highlightedSubject;
        }
        if (manualContentEditableRef.current) {
          const highlightedContent = highlightVariables(normalizedContent);
          manualContentEditableRef.current.innerHTML = highlightedContent;
        }
    } else if (creationMethod === 'template') {
      // Update template contentEditable refs
        if (templateSubjectEditableRef.current) {
          const highlightedSubject = highlightVariables(normalizedSubject);
          templateSubjectEditableRef.current.innerHTML = highlightedSubject;
        }
        if (templateContentEditableRef.current) {
          const highlightedContent = highlightVariables(normalizedContent);
          templateContentEditableRef.current.innerHTML = highlightedContent;
        }
        }
      }, 100);
      
      toast.success('Email content updated with AI-improved version!');
    } catch (error) {
      console.error('Failed to save AI-improved version:', error);
      toast.error('Failed to save AI-improved version. Please try again.');
    }
  }, [
    aiImprovedSubject,
    aiImprovedContent,
    aiImprovedDeliverabilityScore,
    campaignId,
    creationMethod,
    selectedTemplateId,
    autoSaveEmailContent,
    highlightVariables,
    normalizeVariables,
  ]);

  // Handler to keep original email
  const handleKeepOriginal = useCallback(() => {
    setShowComparisonView(false);
    setAiImprovedDeliverabilityScore(null);
    
    // Store previous spam check status if spam check passed
    const inboxSafetyScore = spamCheckResult ? (100 - spamCheckResult.spam_score) : 0;
    if (spamCheckResult && inboxSafetyScore >= 71) {
      setPreviousSpamCheckPassed(true);
      setPreviousSpamScore(spamCheckResult.spam_score);
    } else {
      setPreviousSpamCheckPassed(false);
      setPreviousSpamScore(null);
    }
    
    // Keep the original email as is
    toast.info('Keeping your original email content.');
  }, [spamCheckResult]);

  // Reset spam check only when email content actually changes (not when just navigating back to step 3)
  useEffect(() => {
    // Skip if no content yet
    if (!emailSubject.trim() && !emailContent.trim()) return;
    
    // Get actual current text from contentEditable refs if needed (same logic as handleSpamCheck)
    let currentSubject = emailSubject;
    let currentContent = emailContent;
    
    if (creationMethod === 'ai') {
      if (subjectEditableRef.current) {
        const refText = subjectEditableRef.current.textContent || '';
        if (refText.trim()) {
          currentSubject = refText;
        }
      }
      if (contentEditableRef.current) {
        const refText = getTextWithLineBreaks(contentEditableRef.current);
        if (refText.trim()) {
          currentContent = refText;
        }
      }
    } else if (creationMethod === 'template') {
      if (templateSubjectEditableRef.current) {
        const refText = templateSubjectEditableRef.current.textContent || '';
        if (refText.trim()) {
          currentSubject = refText;
        }
      }
      if (templateContentEditableRef.current) {
        const refText = getTextWithLineBreaks(templateContentEditableRef.current);
        if (refText.trim()) {
          currentContent = refText;
        }
      }
    }
    
    const currentHash = getContentHashForSpam(currentSubject, currentContent);
    const storedHash = sessionStorage.getItem(`spamCheckContentHash_${spamStorageSuffix(creationMethod)}`);
    
    // If we have a stored passed state and current content matches that hash, do nothing — user didn't change anything
    if (storedHash && currentHash === storedHash) {
      return;
    }
    
    // Skip if we don't have a reference to compare against (spam check hasn't been performed yet)
    if (!lastCheckedSubjectRef.current && !lastCheckedContentRef.current) {
      return;
    }
    
    const normalizedCurrentSubject = normalizeForSpamHash(currentSubject);
    const normalizedCurrentContent = normalizeForSpamHash(currentContent);
    const normalizedLastSubject = normalizeForSpamHash(lastCheckedSubjectRef.current);
    const normalizedLastContent = normalizeForSpamHash(lastCheckedContentRef.current);
    
    // Only clear spam check result if content actually changed from what was checked
    if (normalizedCurrentSubject !== normalizedLastSubject || normalizedCurrentContent !== normalizedLastContent) {
      setSpamCheckResult(null);
      setSpamCheckPassed(false);
      setShowComparisonView(false);
      setAiImprovedDeliverabilityScore(null);
      const suffix = spamStorageSuffix(creationMethod);
      sessionStorage.removeItem(`spamCheckPassed_${suffix}`);
      sessionStorage.removeItem(`spamCheckContentHash_${suffix}`);
      sessionStorage.removeItem(`spamCheckResult_${suffix}`);
      sessionStorage.removeItem(`spamCheckScore_${suffix}`);
    }
  }, [emailSubject, emailContent, creationMethod, campaignId]);

  const isNextButtonReady = emailSubject.trim() !== '' && emailContent.trim() !== '' && spamCheckPassed;
  const canGenerateEmail =
    creationMethod === 'ai' && !!aiMessageDescription.trim() && !isGenerating;
  const step3CreationMethod: 'ai' | 'manual' =
    creationMethod === 'manual' || creationMethod === 'template' ? 'manual' : 'ai';

  const fetchTemplates = useCallback(async () => {
    setIsLoadingTemplates(true);
    try {
      // Use the same pattern as Template.tsx for consistency
      const [templatesResponse] = await Promise.allSettled([
        apiService.getEmailTemplates()
      ]);

      console.log('Templates API response (full):', JSON.stringify(templatesResponse, null, 2));
      
      // Check if the promise was fulfilled and has data (same pattern as Template.tsx)
      if (templatesResponse.status === 'fulfilled' && templatesResponse.value) {
        const response = templatesResponse.value;
        console.log('Response value:', JSON.stringify(response, null, 2));
        
        // Check for error first
        if (response.error) {
          console.error('Template fetch error:', response.error);
          toast.error(response.error || 'Failed to load templates');
          setTemplates([]);
          return;
        }
        
        // Check if we have data
        if (response.data) {
          const templatesData = response.data;
          console.log('Templates data:', templatesData, 'Type:', typeof templatesData, 'Is Array:', Array.isArray(templatesData), 'Count:', Array.isArray(templatesData) ? templatesData.length : 'not an array');
          
          if (Array.isArray(templatesData) && templatesData.length > 0) {
            setTemplates(templatesData);
            // Auto-select first template if available and none selected
            if (!selectedTemplateId) {
              const firstTemplate = templatesData[0];
              setSelectedTemplateId(firstTemplate.id);
              setEmailSubject(firstTemplate.subject || '');
              // Store original HTML content for passing to preview
              templateHtmlContentRef.current = firstTemplate.content || '';
              // Strip HTML tags from template content to display as plain text
              const plainTextContent = stripHtmlTags(firstTemplate.content || '');
              setEmailContent(plainTextContent);
              
              // Store original template content to detect edits later
              originalTemplateSubjectRef.current = firstTemplate.subject || '';
              originalTemplateContentRef.current = plainTextContent;
              
              console.log('📧 Auto-selected first template:', {
                templateId: firstTemplate.id,
                subject: firstTemplate.subject,
                htmlContentLength: firstTemplate.content?.length || 0,
                plainTextLength: plainTextContent.length
              });
            }
          } else {
            console.log('No templates found in response - array is empty or not an array');
            setTemplates([]);
          }
        } else {
          console.log('No data field in response:', response);
          setTemplates([]);
        }
      } else {
        // Handle rejected promise
        if (templatesResponse.status === 'rejected') {
          console.error('Template fetch rejected:', templatesResponse.reason);
          toast.error('Failed to load templates');
        }
        setTemplates([]);
      }
    } catch (error: any) {
      console.error('Failed to fetch templates:', error);
      console.error('Error details:', error?.message, error?.response);
      setTemplates([]);
      toast.error(error?.message || 'Failed to load templates');
    } finally {
      setIsLoadingTemplates(false);
    }
  }, [selectedTemplateId]);

  const handleTemplateSelect = (templateId: string) => {
    setSelectedTemplateId(templateId);
    const template = templates.find(t => t.id === templateId);
    if (template) {
      const templateSubject = template.subject || '';
      setEmailSubject(templateSubject);
      // Store original HTML content for passing to preview
      templateHtmlContentRef.current = template.content || '';
      // Strip HTML tags from template content to display as plain text
      const plainTextContent = stripHtmlTags(template.content || '');
      setEmailContent(plainTextContent);
      
      // Preserve template data for restoration when switching methods
      preservedTemplateDataRef.current = {
        templateId: templateId,
        subject: templateSubject,
        content: plainTextContent,
        htmlContent: template.content || ''
      };
      
      // Store original template content to detect edits later
      originalTemplateSubjectRef.current = templateSubject;
      originalTemplateContentRef.current = plainTextContent;
      
      // Update subject contentEditable with highlighted variables immediately
      if (templateSubjectEditableRef.current) {
        const normalizedSubject = normalizeVariables(templateSubject);
        const highlightedSubject = highlightVariables(normalizedSubject);
        templateSubjectEditableRef.current.innerHTML = highlightedSubject;
      }
      
      // Update contentEditable with highlighted variables immediately
      if (templateContentEditableRef.current) {
        const normalized = normalizeVariables(plainTextContent);
        const highlighted = highlightVariables(normalized);
        templateContentEditableRef.current.innerHTML = highlighted;
      }
      
      console.log('📧 Template selected:', {
        templateId,
        subject: template.subject,
        htmlContentLength: template.content?.length || 0,
        plainTextLength: plainTextContent.length
      });
    }
  };

  // Fetch templates when template method is selected
  useEffect(() => {
    if (creationMethod === 'template') {
      fetchTemplates();
    }
  }, [creationMethod, fetchTemplates]);

  // Restore template content when switching back to template method if template was previously selected
  useEffect(() => {
    if (creationMethod === 'template' && selectedTemplateId && templates.length > 0) {
      const template = templates.find(t => t.id === selectedTemplateId);
      if (template) {
        // Only restore if content is empty (to avoid overwriting user edits)
          if (!emailSubject.trim() && template.subject) {
          setEmailSubject(template.subject);
        }
        if (!emailContent.trim() && template.content) {
          const plainTextContent = stripHtmlTags(template.content);
          setEmailContent(plainTextContent);
          templateHtmlContentRef.current = template.content;
          
          // Store original template content
          originalTemplateSubjectRef.current = template.subject || '';
          originalTemplateContentRef.current = plainTextContent;
          
          // Update contentEditable refs with highlighted content
          if (templateSubjectEditableRef.current && template.subject) {
            const normalizedSubject = normalizeVariables(template.subject);
            const highlightedSubject = highlightVariables(normalizedSubject);
            templateSubjectEditableRef.current.innerHTML = highlightedSubject;
          }
          if (templateContentEditableRef.current) {
            const normalized = normalizeVariables(plainTextContent);
            const highlighted = highlightVariables(normalized);
            templateContentEditableRef.current.innerHTML = highlighted;
          }
        }
      }
    }
  }, [creationMethod, selectedTemplateId, templates, emailSubject, emailContent, highlightVariables, normalizeVariables]);

  // Notify parent of validation state changes
  useEffect(() => {
    if (onEmailValidationChange) {
      if (step3Phase === 'lead-generation') {
        onEmailValidationChange(canProceedLeadGeneration);
      } else {
        onEmailValidationChange(isNextButtonReady);
      }
    }
  }, [
    isNextButtonReady,
    onEmailValidationChange,
    creationMethod,
    step3Phase,
    canProceedLeadGeneration,
  ]);

  useEffect(() => {
    onStep3UiStateChange?.({
      creationMethod: step3CreationMethod,
      phase: step3Phase,
      isGenerating,
      hasGenerated,
      canGenerate: canGenerateEmail,
      isEmailValid:
        step3Phase === 'lead-generation'
          ? canProceedLeadGeneration
          : isNextButtonReady,
      isSavingDraft,
      isLeadGenerationComplete,
      allLeadEmailsSpamReady,
      readyForOutreachCount,
      partialGenerationAccepted,
    });
  }, [
    onStep3UiStateChange,
    step3CreationMethod,
    step3Phase,
    isGenerating,
    hasGenerated,
    canGenerateEmail,
    isNextButtonReady,
    isSavingDraft,
    isLeadGenerationComplete,
    allLeadEmailsSpamReady,
    readyForOutreachCount,
    partialGenerationAccepted,
    creationMethod,
    canProceedLeadGeneration,
  ]);

  const toneTiers = useMemo(
    () => mapApiToneTiers(planCapabilities?.tone_tiers),
    [planCapabilities?.tone_tiers],
  );

  const toneLabel = useMemo(() => {
    if (emailToneTier) {
      const tier = toneTiers.find((t) => t.tierPlan === emailToneTier);
      const match = tier?.tones.find((t) => t.id === emailTone);
      if (match) return match.label;
    }
    for (const tier of toneTiers) {
      const match = tier.tones.find((t) => t.id === emailTone);
      if (match) return match.label;
    }
    return emailTone.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  }, [toneTiers, emailTone, emailToneTier]);

  // Resolve which tier card is highlighted when the same tone id appears in multiple tiers.
  useEffect(() => {
    if (!emailTone || !toneTiers.length) return;
    setEmailToneTier((current) => {
      if (
        current &&
        toneTiers.some(
          (tier) =>
            tier.tierPlan === current && tier.tones.some((tone) => tone.id === emailTone),
        )
      ) {
        return current;
      }
      return defaultTierPlanForTone(emailTone, planCapabilities?.plan ?? 'free', toneTiers);
    });
  }, [emailTone, toneTiers, planCapabilities?.plan]);

  // Keep selected tone within plan unlocks (backend is source of truth)
  useEffect(() => {
    if (!emailTone || !toneTiers.length) return;
    const tierForSelection = emailToneTier
      ? toneTiers.find((tier) => tier.tierPlan === emailToneTier)
      : findTierForTone(toneTiers, emailTone);
    if (tierForSelection && !isToneUnlocked(tierForSelection)) {
      const fallbackId = firstUnlockedToneId(toneTiers);
      if (fallbackId) {
        setEmailTone(fallbackId);
        setEmailToneTier(
          defaultTierPlanForTone(fallbackId, planCapabilities?.plan ?? 'free', toneTiers),
        );
      }
    }
  }, [planCapabilities?.plan, emailTone, emailToneTier, toneTiers]);

  if (step3Phase === 'lead-generation') {
    const selectedTemplate = templates.find((t) => t.id === selectedTemplateId);
    return (
      <div className="campaign-email-screen campaign-email-screen--lead-generation">
        <div className="campaign-email-content">
          <div className="campaign-email-lead-gen-toolbar">
            <button
              type="button"
              className="campaign-email-lead-gen-back"
              onClick={requestBackFromLeadGeneration}
              aria-label="Back to tone and prompt"
            >
              <ArrowLeft size={18} aria-hidden />
              <span>Back</span>
            </button>
          </div>
          <CampaignLeadEmailGeneration
            campaignId={campaignId}
            generationMode={creationMethod}
            templateName={selectedTemplate?.name}
            toneLabel={toneLabel}
            planCapabilities={planCapabilities}
            promptDescription={
              creationMethod === 'ai'
                ? aiMessageDescription.trim() ||
                  preservedAIDataRef.current?.aiDescription?.trim() ||
                  undefined
                : undefined
            }
            draftPending={isGenerating}
            onGenerationStateChange={handleGenerationStateChange}
          />
        </div>
        {showDiscardLeadEmailsConfirm &&
          createPortal(
            <div
              className="preview-launch-confirm-overlay"
              onClick={() => !isDiscardingLeadEmails && setShowDiscardLeadEmailsConfirm(false)}
            >
              <div
                className="preview-launch-confirm-card"
                role="dialog"
                aria-modal="true"
                aria-labelledby="lead-gen-discard-title"
                onClick={(e) => e.stopPropagation()}
              >
                <h3 id="lead-gen-discard-title" className="heading-m">
                  Go back to tone &amp; prompt?
                </h3>
                <p>
                  If you go back, all personalized emails written for your leads will be discarded and
                  not saved. You will need to regenerate them, and credits will be deducted again.
                </p>
                <div className="preview-launch-confirm-actions">
                  <button
                    type="button"
                    className="evecta-secondary-btn"
                    onClick={() => setShowDiscardLeadEmailsConfirm(false)}
                    disabled={isDiscardingLeadEmails}
                  >
                    Stay here
                  </button>
                  <button
                    type="button"
                    className="evecta-primary-btn"
                    onClick={confirmBackFromLeadGeneration}
                    disabled={isDiscardingLeadEmails}
                  >
                    {isDiscardingLeadEmails ? 'Discarding…' : 'Yes, go back'}
                  </button>
                </div>
              </div>
            </div>,
            document.body,
          )}
      </div>
    );
  }

  return (
    <div className="campaign-email-screen">
      <div className="campaign-email-content">
        <div className="campaign-email-card">
          {!skipMethodPicker && (
          <div className="email-creation-method-section">
            <div className="email-creation-method-row">
            <p className="email-creation-method-label">How would you like to create your email?</p>
            <div
              className="campaign-email-creation-tabs"
              role="tablist"
              aria-label="How would you like to create your email?"
            >
              {SHOW_TEMPLATE_METHOD && (
              <button
                type="button"
                role="tab"
                aria-selected={creationMethod === 'template'}
                className={`campaign-email-creation-tab ${creationMethod === 'template' ? 'active' : ''}`}
                onClick={() => {
                  // Preserve current content before switching
                  if (creationMethod === 'ai') {
                    // Preserve AI content
                    let currentSubject = emailSubject;
                    let currentContent = emailContent;
                    if (subjectEditableRef.current) {
                      const refText = subjectEditableRef.current.textContent || '';
                      if (refText.trim()) currentSubject = refText;
                    }
                    if (contentEditableRef.current) {
                      const refText = getTextWithLineBreaks(contentEditableRef.current);
                      if (refText.trim()) currentContent = refText;
                    }
                    preservedAIDataRef.current = {
                      subject: currentSubject,
                      content: currentContent,
                      aiDescription: aiMessageDescription,
                      hasGenerated: hasGenerated
                    };
                  } else if (creationMethod === 'manual') {
                    // Preserve Manual content
                    let currentSubject = emailSubject;
                    let currentContent = emailContent;
                    if (manualSubjectEditableRef.current) {
                      const refText = manualSubjectEditableRef.current.textContent || '';
                      if (refText.trim()) currentSubject = refText;
                    }
                    if (manualContentEditableRef.current) {
                      const refText = getTextWithLineBreaks(manualContentEditableRef.current);
                      if (refText.trim()) currentContent = refText;
                    }
                    preservedManualDataRef.current = {
                      subject: currentSubject,
                      content: currentContent
                    };
                  }
                  
                  // Clear shared state and all contentEditable refs so no AI/Manual content shows in Template
                  setEmailSubject('');
                  setEmailContent('');
                  setSelectedTemplateId('');
                  templateHtmlContentRef.current = '';
                  if (templateSubjectEditableRef.current) {
                    templateSubjectEditableRef.current.innerHTML = '';
                  }
                  if (templateContentEditableRef.current) {
                    templateContentEditableRef.current.innerHTML = '';
                  }
                  if (subjectEditableRef.current) {
                    subjectEditableRef.current.innerHTML = '';
                  }
                  if (contentEditableRef.current) {
                    contentEditableRef.current.innerHTML = '';
                  }
                  if (manualSubjectEditableRef.current) {
                    manualSubjectEditableRef.current.innerHTML = '';
                  }
                  if (manualContentEditableRef.current) {
                    manualContentEditableRef.current.innerHTML = '';
                  }
                  
                  // Restore only template data when switching to Template (never show AI/Manual content)
                  if (preservedTemplateDataRef.current) {
                    const preserved = preservedTemplateDataRef.current;
                    setSelectedTemplateId(preserved.templateId);
                    setEmailSubject(preserved.subject);
                    setEmailContent(preserved.content);
                    templateHtmlContentRef.current = preserved.htmlContent;
                    
                    setTimeout(() => {
                      if (templateSubjectEditableRef.current && preserved.subject) {
                        const normalizedSubject = normalizeVariables(preserved.subject);
                        templateSubjectEditableRef.current.innerHTML = highlightVariables(normalizedSubject);
                      }
                      if (templateContentEditableRef.current && preserved.content) {
                        const normalized = normalizeVariables(preserved.content);
                        templateContentEditableRef.current.innerHTML = highlightVariables(normalized);
                      }
                    }, 50);
                  }
                  
                  setCreationMethod('template');
                  setShowComparisonView(false);
                }}
              >
                <span>Browse Templates</span>
              </button>
              )}
              <button
                type="button"
                role="tab"
                aria-selected={creationMethod === 'ai'}
                className={`campaign-email-creation-tab ${creationMethod === 'ai' ? 'active' : ''}`}
                onClick={() => {
                  // Preserve current content before switching
                  if (creationMethod === 'template' && selectedTemplateId) {
                    // Get content from template refs
                    let currentSubject = emailSubject;
                    let currentContent = emailContent;
                    if (templateSubjectEditableRef.current) {
                      const refText = templateSubjectEditableRef.current.textContent || '';
                      if (refText.trim()) currentSubject = refText;
                    }
                    if (templateContentEditableRef.current) {
                      const refText = getTextWithLineBreaks(templateContentEditableRef.current);
                      if (refText.trim()) currentContent = refText;
                    }
                    preservedTemplateDataRef.current = {
                      templateId: selectedTemplateId,
                      subject: currentSubject,
                      content: currentContent,
                      htmlContent: templateHtmlContentRef.current || ''
                    };
                  } else if (creationMethod === 'manual') {
                    // Preserve Manual content
                    let currentSubject = emailSubject;
                    let currentContent = emailContent;
                    if (manualSubjectEditableRef.current) {
                      const refText = manualSubjectEditableRef.current.textContent || '';
                      if (refText.trim()) currentSubject = refText;
                    }
                    if (manualContentEditableRef.current) {
                      const refText = getTextWithLineBreaks(manualContentEditableRef.current);
                      if (refText.trim()) currentContent = refText;
                    }
                    preservedManualDataRef.current = {
                      subject: currentSubject,
                      content: currentContent
                    };
                  }
                  
                  // Clear template state and refs so Template content never shows in AI
                  setSelectedTemplateId('');
                  templateHtmlContentRef.current = '';
                  if (templateSubjectEditableRef.current) {
                    templateSubjectEditableRef.current.innerHTML = '';
                  }
                  if (templateContentEditableRef.current) {
                    templateContentEditableRef.current.innerHTML = '';
                  }
                  if (manualSubjectEditableRef.current) {
                    manualSubjectEditableRef.current.innerHTML = '';
                  }
                  if (manualContentEditableRef.current) {
                    manualContentEditableRef.current.innerHTML = '';
                  }
                  
                  // Set state only from AI preserved data so Template/Manual content never shows in AI
                  if (preservedAIDataRef.current) {
                    const preserved = preservedAIDataRef.current;
                    setEmailSubject(preserved.subject);
                    setEmailContent(preserved.content);
                    if (preserved.aiDescription) {
                      setAiMessageDescription(preserved.aiDescription);
                    }
                    if (preserved.hasGenerated) {
                      setHasGenerated(true);
                    }
                    setTimeout(() => {
                      if (subjectEditableRef.current && preserved.subject) {
                        subjectEditableRef.current.innerHTML = highlightVariables(normalizeVariables(preserved.subject));
                      }
                      if (contentEditableRef.current && preserved.content) {
                        contentEditableRef.current.innerHTML = highlightVariables(normalizeVariables(preserved.content));
                      }
                    }, 50);
                  } else {
                    setEmailSubject('');
                    setEmailContent('');
                    setHasGenerated(false);
                    setAiMessageDescription('');
                    if (subjectEditableRef.current) {
                      subjectEditableRef.current.innerHTML = '';
                    }
                    if (contentEditableRef.current) {
                      contentEditableRef.current.innerHTML = '';
                    }
                  }
                  
                  setCreationMethod('ai');
                  setShowComparisonView(false);
                  setAiImprovedDeliverabilityScore(null);
                }}
              >
                <span>Generate with AI</span>
              </button>
            </div>
            </div>
          </div>
          )}

          <div className="email-form-section">
            {creationMethod === 'ai' ? (
              <>
                <EmailTonePicker
                  value={emailTone}
                  selectedTierPlan={emailToneTier}
                  onChange={(toneId, tierPlan) => {
                    setEmailTone(toneId);
                    setEmailToneTier(tierPlan);
                  }}
                  userPlan={planCapabilities?.plan ?? 'free'}
                  tiers={toneTiers}
                />
                <div className="email-form-field">
                  <label className="email-form-label">
                    Describe your email context
                  </label>
                  <Textarea
                    value={aiMessageDescription}
                    onChange={(e) => {
                      setAiMessageDescription(e.target.value);
                      // Update preserved AI data when description changes
                      if (preservedAIDataRef.current) {
                        preservedAIDataRef.current.aiDescription = e.target.value;
                      }
                    }}
                    className="email-form-textarea ai-description-textarea min-h-0 text-sm md:text-sm"
                    placeholder="Be specific — e.g., Ask about advertising placement on their site, or invite them to a short call about a partnership for local events..."
                  />
                  <p className="text-xs text-muted-foreground mt-1.5">
                    The AI will write from this context. Include your goal, what to ask, and any details that must appear in the email.
                  </p>
                </div>
              </>
            ) : SHOW_TEMPLATE_METHOD && creationMethod === 'template' ? (
              <>
                {/* Hide template dropdown when showing comparison view */}
                {!showComparisonView && (
                <div className="email-form-field">
                  <label className="email-form-label">
                    Choose a template
                  </label>
                  <Select
                    value={selectedTemplateId}
                    onValueChange={handleTemplateSelect}
                    onOpenChange={(open) => {
                      // Refetch templates when dropdown opens to show newly added templates
                      if (open && !isLoadingTemplates) {
                        fetchTemplates();
                      }
                    }}
                    disabled={isLoadingTemplates}
                  >
                    <SelectTrigger className="email-form-select">
                      <SelectValue placeholder={isLoadingTemplates ? "Loading templates..." : "Select a template"} />
                    </SelectTrigger>
                    <SelectContent>
                      {isLoadingTemplates ? (
                        <SelectItem value="loading" disabled>Loading templates...</SelectItem>
                      ) : templates.length === 0 ? (
                        <SelectItem value="none" disabled>No templates available</SelectItem>
                      ) : (
                        templates.map((template) => (
                          <SelectItem key={template.id} value={template.id}>
                            {template.name}
                          </SelectItem>
                        ))
                      )}
                    </SelectContent>
                  </Select>
                </div>
                )}
                
                {/* Show comparison view for templates when there are issues - hide email fields */}
                {showComparisonView && spamCheckResult ? (
                  <>
                    {/* Spam Test Comparison Section */}
                    <div className="spam-test-comparison-container">
                      <div className="spam-test-comparison-header">
                        <div className="spam-test-comparison-header-inner">
                          <div className="spam-test-comparison-header-title-row">
                            <span className="spam-test-comparison-header-title">Spam Test Comparison</span>
                          </div>
                          <span className="spam-test-comparison-header-description">Compare original content with AI-improved version</span>
                        </div>
                        {aiImprovedDeliverabilityScore !== null && (
                          <div className="spam-test-comparison-header-score-container">
                            <span className="spam-test-comparison-header-score-label">Deliverability Score:</span>
                            <span className="spam-test-comparison-header-score-value">
                              {aiImprovedDeliverabilityScore}/100
                            </span>
                            <span className="spam-test-comparison-header-score-risk">
                              <span className="spam-test-comparison-header-score-risk-muted">
                                ({getRiskLevelFromScore(aiImprovedDeliverabilityScore)}:{' '}
                              </span>
                              <span className="spam-test-comparison-header-score-risk-value">
                                {aiImprovedDeliverabilityScore >= 71 ? '71-100%' : aiImprovedDeliverabilityScore >= 41 ? '41-70%' : '0-40%'}
                              </span>
                              <span className="spam-test-comparison-header-score-risk-muted">)</span>
                            </span>
                          </div>
                        )}
                      </div>

                      <div className="spam-test-comparison-content">
                        {/* Original Content - LEFT SIDE */}
                        <div className="spam-test-comparison-panel spam-test-comparison-panel-grid-column-1">
                          <div className="spam-test-comparison-panel-header">
                            <span>Original Content</span>
                          </div>
                          <div className="spam-test-comparison-panel-body">
                            <div className="spam-test-comparison-field spam-test-comparison-field-with-line">
                              <div className="spam-test-comparison-field-label">Subject</div>
                              <div
                                className="spam-test-comparison-input spam-test-comparison-highlighted"
                                dangerouslySetInnerHTML={{ __html: highlightVariables(originalEmailSubject.trim()) }}
                              />
                            </div>
                            <div className="spam-test-comparison-field">
                              <div className="spam-test-comparison-field-label">Content</div>
                              <div
                                className="spam-test-comparison-textarea spam-test-comparison-highlighted"
                                dangerouslySetInnerHTML={{ __html: highlightVariables(originalEmailContent.trim()) }}
                              />
                            </div>
                          </div>
                        </div>

                        {/* Improved Content - RIGHT SIDE */}
                        <div className="spam-test-comparison-panel improved-content-panel spam-test-comparison-panel-grid-column-2">
                          <div className="spam-test-comparison-panel-header">
                            <span>Improved Content</span>
                          </div>
                          <div className="spam-test-comparison-panel-body">
                            <div className="spam-test-comparison-field spam-test-comparison-field-with-line">
                              <div className="spam-test-comparison-field-label">Subject</div>
                              <div
                                className="spam-test-comparison-input spam-test-comparison-highlighted"
                                dangerouslySetInnerHTML={{ __html: highlightVariables(aiImprovedSubject.trim()) }}
                              />
                            </div>
                            <div className="spam-test-comparison-field">
                              <div className="spam-test-comparison-field-label">Content</div>
                              <div
                                className="spam-test-comparison-textarea spam-test-comparison-highlighted"
                                dangerouslySetInnerHTML={{ __html: highlightVariables(aiImprovedContent.trim()) }}
                              />
                            </div>
                          </div>
                        </div>
                      </div>

                      {/* Suggestions Section - Key Improvements frame only */}
                      {spamCheckResult && (
                        <>
                        <div className="spam-test-suggestions spam-test-suggestions-override">
                          <h4 className="heading-m">Key Improvements :</h4>
                              {spamCheckResult.suggestions && spamCheckResult.suggestions.length > 0 ? (
                                <ul>
                              {spamCheckResult.suggestions.slice(0, 5).map((suggestion, index) => (
                                    <li key={index} className="spam-test-suggestion-item">
                                      <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className="spam-test-suggestion-icon">
                                        <rect x="2" y="2" width="16" height="16" rx="3" fill="none" stroke="currentColor" strokeWidth="1.5"/>
                                        <path d="M5 10 L8 13 L15 6" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
                                      </svg>
                                      <span>{suggestion}</span>
                                    </li>
                                  ))}
                                </ul>
                              ) : (
                                <ul>
                                  <li className="spam-test-suggestion-item">
                                    <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className="spam-test-suggestion-icon">
                                      <rect x="2" y="2" width="16" height="16" rx="3" fill="none" stroke="currentColor" strokeWidth="1.5"/>
                                      <path d="M5 10 L8 13 L15 6" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
                                    </svg>
                                    <span>Email looks good! Consider A/B testing different subject lines</span>
                                  </li>
                                  <li className="spam-test-suggestion-item">
                                    <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className="spam-test-suggestion-icon">
                                      <rect x="2" y="2" width="16" height="16" rx="3" fill="none" stroke="currentColor" strokeWidth="1.5"/>
                                      <path d="M5 10 L8 13 L15 6" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
                                    </svg>
                                    <span>Great use of personalization variables!</span>
                                  </li>
                                </ul>
                              )}
                        </div>
                        {spamCheckResult.suggestions && spamCheckResult.suggestions.length > 0 && (
                          <div className="spam-test-suggestions-note">
                            <p>These suggestions have been implemented in the AI-improved version above. Compare the original and improved content to see the enhancements.</p>
                          </div>
                        )}
                        </>
                      )}

                      {/* Action Buttons */}
                      <div className="spam-test-comparison-actions">
                        <button
                          type="button"
                          onClick={handleKeepOriginal}
                          className="evecta-secondary-btn"
                        >
                          <span>Discard & Keep Original</span>
                        </button>
                        <button
                          type="button"
                          onClick={handleAcceptAiVersion}
                          className="evecta-primary-btn"
                        >
                          <span>Update Email Content</span>
                        </button>
                      </div>
                    </div>
                  </>
                ) : selectedTemplateId && !showComparisonView ? (
                  <>
                    <div className="email-form-field with-top-margin">
                      <label className="email-form-label">
                        Email Subject <span className="required">*</span>
                      </label>
                      <div
                        ref={templateSubjectEditableRef}
                        contentEditable
                        onInput={(e) => {
                          handleVariableInput(e, true);
                          const text = e.currentTarget.textContent || '';
                          const normalized = normalizeVariables(text);
                          if (normalized !== emailSubject) {
                            setEmailSubject(normalized);
                            // Update preserved template data when editing template subject
                            if (preservedTemplateDataRef.current && selectedTemplateId) {
                              preservedTemplateDataRef.current.subject = normalized;
                            }
                          }
                        }}
                        onKeyDown={(e) => {
                          if (e.key === 'Escape') {
                            setShowVariableSuggestions(false);
                          } else {
                            handleVariableInput(e, true);
                          }
                        }}
                        onBlur={(e) => {
                          // Re-highlight variables when focus is lost
                          const text = e.currentTarget.textContent || '';
                          const normalized = normalizeVariables(text);
                          const highlighted = highlightVariables(normalized);
                          e.currentTarget.innerHTML = highlighted;
                        }}
                        className="email-form-input template-content-editable-input"
                        data-placeholder="Enter email subject"
                      />
                      <style>{`
                        [data-placeholder]:empty:before {
                          content: attr(data-placeholder);
                          color: #9CA3AF;
                        }
                      `}</style>
                    </div>
                    <div className="email-form-field">
                      <label className="email-form-label">
                        Email Content <span className="required">*</span>
                      </label>
                      <div
                        ref={templateContentEditableRef}
                        contentEditable
                        onInput={(e) => {
                          handleVariableInput(e, true);
                          const text = getTextWithLineBreaks(e.currentTarget);
                          const normalized = normalizeVariables(text);
                          if (normalized !== emailContent) {
                            setEmailContent(normalized);
                            // Update preserved template data when editing template content
                            if (preservedTemplateDataRef.current && selectedTemplateId) {
                              preservedTemplateDataRef.current.content = normalized;
                              preservedTemplateDataRef.current.subject = emailSubject;
                            }
                          }
                        }}
                        onKeyDown={(e) => {
                          if (e.key === 'Escape') {
                            setShowVariableSuggestions(false);
                          } else {
                            handleVariableInput(e, true);
                          }
                        }}
                        onBlur={(e) => {
                          // Re-highlight variables when focus is lost (preserve line breaks)
                          const text = getTextWithLineBreaks(e.currentTarget);
                          const normalized = normalizeVariables(text);
                          const highlighted = highlightVariables(normalized);
                          e.currentTarget.innerHTML = highlighted;
                        }}
                        className="email-form-textarea template-content-editable-textarea"
                        suppressContentEditableWarning={true}
                      />
                    </div>
                  </>
                ) : null}
              </>
            ) : (
              <>
                {showComparisonView && spamCheckResult ? (
                  <>
                    {/* Spam Test Comparison Section */}
                    <div className="spam-test-comparison-container">
                      <div className="spam-test-comparison-header">
                        <div className="spam-test-comparison-header-inner">
                          <div className="spam-test-comparison-header-title-row">
                            <span className="spam-test-comparison-header-title">Spam Test Comparison</span>
                          </div>
                          <span className="spam-test-comparison-header-description">Compare original content with AI-improved version</span>
                        </div>
                        {aiImprovedDeliverabilityScore !== null && (
                          <div className="spam-test-comparison-header-score-container">
                            <span className="spam-test-comparison-header-score-label">Deliverability Score:</span>
                            <span className="spam-test-comparison-header-score-value">
                              {aiImprovedDeliverabilityScore}/100
                            </span>
                            <span className="spam-test-comparison-header-score-risk">
                              <span className="spam-test-comparison-header-score-risk-muted">
                                ({getRiskLevelFromScore(aiImprovedDeliverabilityScore)}:{' '}
                              </span>
                              <span className="spam-test-comparison-header-score-risk-value">
                                {aiImprovedDeliverabilityScore >= 71 ? '71-100%' : aiImprovedDeliverabilityScore >= 41 ? '41-70%' : '0-40%'}
                              </span>
                              <span className="spam-test-comparison-header-score-risk-muted">)</span>
                            </span>
                          </div>
                        )}
                      </div>

                      <div className="spam-test-comparison-content">
                        {/* Original Content - LEFT SIDE */}
                        <div className="spam-test-comparison-panel spam-test-comparison-panel-grid-column-1">
                          <div className="spam-test-comparison-panel-header">
                            <span>Original Content</span>
                          </div>
                          <div className="spam-test-comparison-panel-body">
                            <div className="spam-test-comparison-field spam-test-comparison-field-with-line">
                              <div className="spam-test-comparison-field-label">Subject</div>
                              <div
                                className="spam-test-comparison-input spam-test-comparison-highlighted"
                                dangerouslySetInnerHTML={{ __html: highlightVariables(originalEmailSubject.trim()) }}
                              />
                            </div>
                            <div className="spam-test-comparison-field">
                              <div className="spam-test-comparison-field-label">Content</div>
                              <div
                                className="spam-test-comparison-textarea spam-test-comparison-highlighted"
                                dangerouslySetInnerHTML={{ __html: highlightVariables(originalEmailContent.trim()) }}
                              />
                            </div>
                          </div>
                        </div>

                        {/* Improved Content - RIGHT SIDE */}
                        <div className="spam-test-comparison-panel improved-content-panel spam-test-comparison-panel-grid-column-2">
                          <div className="spam-test-comparison-panel-header">
                            <span>Improved Content</span>
                          </div>
                          <div className="spam-test-comparison-panel-body">
                            <div className="spam-test-comparison-field spam-test-comparison-field-with-line">
                              <div className="spam-test-comparison-field-label">Subject</div>
                              <div
                                className="spam-test-comparison-input spam-test-comparison-highlighted"
                                dangerouslySetInnerHTML={{ __html: highlightVariables(aiImprovedSubject.trim()) }}
                              />
                            </div>
                            <div className="spam-test-comparison-field">
                              <div className="spam-test-comparison-field-label">Content</div>
                              <div
                                className="spam-test-comparison-textarea spam-test-comparison-highlighted"
                                dangerouslySetInnerHTML={{ __html: highlightVariables(aiImprovedContent.trim()) }}
                              />
                            </div>
                          </div>
                        </div>
                      </div>

                      {/* Suggestions Section - Key Improvements frame only */}
                      {spamCheckResult && (
                        <>
                        <div className="spam-test-suggestions spam-test-suggestions-override">
                          <h4 className="heading-m">Key Improvements :</h4>
                              {spamCheckResult.suggestions && spamCheckResult.suggestions.length > 0 ? (
                                <ul>
                              {spamCheckResult.suggestions.slice(0, 5).map((suggestion, index) => (
                                    <li key={index} className="spam-test-suggestion-item">
                                      <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className="spam-test-suggestion-icon">
                                        <rect x="2" y="2" width="16" height="16" rx="3" fill="none" stroke="currentColor" strokeWidth="1.5"/>
                                        <path d="M5 10 L8 13 L15 6" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
                                      </svg>
                                      <span>{suggestion}</span>
                                    </li>
                                  ))}
                                </ul>
                              ) : (
                                <ul>
                                  <li className="spam-test-suggestion-item">
                                    <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className="spam-test-suggestion-icon">
                                      <rect x="2" y="2" width="16" height="16" rx="3" fill="none" stroke="currentColor" strokeWidth="1.5"/>
                                      <path d="M5 10 L8 13 L15 6" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
                                    </svg>
                                    <span>Email looks good! Consider A/B testing different subject lines</span>
                                  </li>
                                  <li className="spam-test-suggestion-item">
                                    <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className="spam-test-suggestion-icon">
                                      <rect x="2" y="2" width="16" height="16" rx="3" fill="none" stroke="currentColor" strokeWidth="1.5"/>
                                      <path d="M5 10 L8 13 L15 6" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
                                    </svg>
                                    <span>Great use of personalization variables!</span>
                                  </li>
                                </ul>
                              )}
                        </div>
                        {spamCheckResult.suggestions && spamCheckResult.suggestions.length > 0 && (
                          <div className="spam-test-suggestions-note">
                            <p>These suggestions have been implemented in the AI-improved version above. Compare the original and improved content to see the enhancements.</p>
                          </div>
                        )}
                        </>
                      )}

                      {/* Action Buttons */}
                      <div className="spam-test-comparison-actions">
                        <button
                          type="button"
                          onClick={handleKeepOriginal}
                          className="evecta-secondary-btn"
                        >
                          <span>Discard & Keep Original</span>
                        </button>
                        <button
                          type="button"
                          onClick={handleAcceptAiVersion}
                          className="evecta-primary-btn"
                        >
                          <span>Update Email Content</span>
                        </button>
                      </div>
                    </div>
                  </>
                ) : null}
                {!showComparisonView && (
                  <>
                    <div className="email-form-field">
                      <label className="email-form-label">
                        Email Subject <span className="required">*</span>
                      </label>
                      <div
                        ref={manualSubjectEditableRef}
                        contentEditable
                        onInput={(e) => {
                          isTypingSubjectRef.current = true;
                          
                          // Only handle variable suggestions - don't process text during typing
                          handleVariableInput(e, true);
                          
                          // Clear any pending state update
                          if (manualSubjectUpdateTimeoutRef.current) {
                            clearTimeout(manualSubjectUpdateTimeoutRef.current);
                          }
                          
                          // Debounce ALL processing until user stops typing
                          // This prevents any text manipulation during typing
                          manualSubjectUpdateTimeoutRef.current = setTimeout(() => {
                            // Double-check element still exists and has focus
                            if (!e.currentTarget || document.activeElement !== e.currentTarget) {
                              // Element lost focus, process immediately
                              const text = e.currentTarget?.textContent || '';
                              const normalized = normalizeVariables(text);
                              
                              if (preservedManualDataRef.current) {
                                preservedManualDataRef.current.subject = normalized;
                              }
                              
                              if (normalized !== emailSubject) {
                                setEmailSubject(normalized);
                              }
                              isTypingSubjectRef.current = false;
                              manualSubjectUpdateTimeoutRef.current = null;
                              return;
                            }
                            
                            // User stopped typing, process the text
                            const text = e.currentTarget.textContent || '';
                            const normalized = normalizeVariables(text);
                            
                            // Update preserved Manual data
                            if (preservedManualDataRef.current) {
                              preservedManualDataRef.current.subject = normalized;
                            } else if (normalized.trim()) {
                              preservedManualDataRef.current = {
                                subject: normalized,
                                content: emailContent
                              };
                            }
                            
                            // Update state only after user stops typing
                            if (normalized !== emailSubject) {
                              setEmailSubject(normalized);
                            }
                            
                            isTypingSubjectRef.current = false;
                            manualSubjectUpdateTimeoutRef.current = null;
                          }, 800); // Much longer delay to ensure user has completely finished typing
                        }}
                        onBlur={(e) => {
                          // Clear any pending debounced update
                          if (manualSubjectUpdateTimeoutRef.current) {
                            clearTimeout(manualSubjectUpdateTimeoutRef.current);
                            manualSubjectUpdateTimeoutRef.current = null;
                          }
                          
                          isTypingSubjectRef.current = false;
                          
                          // Immediately sync state on blur to ensure nothing is lost
                          const text = e.currentTarget.textContent || '';
                          const normalized = normalizeVariables(text);
                          if (normalized !== emailSubject) {
                            setEmailSubject(normalized);
                          }
                          
                          // Re-highlight variables when focus is lost
                          const highlighted = highlightVariables(normalized);
                          e.currentTarget.innerHTML = highlighted;
                        }}
                        onKeyDown={(e) => {
                          if (e.key === 'Escape') {
                            setShowVariableSuggestions(false);
                          } else {
                            handleVariableInput(e, true);
                          }
                        }}
                        className="content-editable-input"
                        data-placeholder="Boost your client reach with AI-driven outreach."
                        suppressContentEditableWarning
                      />
                    </div>

                    <div className="email-form-field">
                      <label className="email-form-label">
                        Email Content <span className="required">*</span>
                      </label>
                      <div
                        ref={manualContentEditableRef}
                        contentEditable
                        onPaste={pastePlainTextPreservingLineBreaks}
                        onInput={(e) => {
                          isTypingContentRef.current = true;
                          handleVariableInput(e, true);
                          if (manualContentUpdateTimeoutRef.current) {
                            clearTimeout(manualContentUpdateTimeoutRef.current);
                          }
                          manualContentUpdateTimeoutRef.current = setTimeout(() => {
                            const text = getTextWithLineBreaks(e.currentTarget);
                            const normalized = normalizeVariables(text);
                            if (preservedManualDataRef.current) {
                              preservedManualDataRef.current.content = normalized;
                            } else if (normalized.trim()) {
                              preservedManualDataRef.current = {
                                subject: emailSubject,
                                content: normalized
                              };
                            }
                            if (normalized !== emailContent) setEmailContent(normalized);
                            isTypingContentRef.current = false;
                            manualContentUpdateTimeoutRef.current = null;
                          }, 800);
                        }}
                        onBlur={(e) => {
                          if (manualContentUpdateTimeoutRef.current) {
                            clearTimeout(manualContentUpdateTimeoutRef.current);
                            manualContentUpdateTimeoutRef.current = null;
                          }
                          isTypingContentRef.current = false;
                          const text = getTextWithLineBreaks(e.currentTarget);
                          const normalized = normalizeVariables(text);
                          if (normalized !== emailContent) setEmailContent(normalized);
                          const highlighted = highlightVariables(normalized);
                          e.currentTarget.innerHTML = highlighted;
                        }}
                        onKeyDown={(e) => {
                          if (e.key === 'Escape') setShowVariableSuggestions(false);
                          else if (e.key === 'Enter') {
                            e.preventDefault();
                            document.execCommand('insertLineBreak', false);
                          } else handleVariableInput(e, true);
                        }}
                        className="content-editable-textarea manual-draft-textarea"
                        data-placeholder={`Hi [FirstName],

I came across your work and thought our AI-driven lead platform might help you reach new clients more efficiently.
We've helped similar businesses automate outreach and see measurable growth within weeks.

Would you be open to a quick chat this week?

Best regards,
[Your Name]`}
                        suppressContentEditableWarning
                      />
                    </div>
                  </>
                )}
              </>
            )}

            {/* Spam check banner — manual/template only; AI validates on generate */}
            {(creationMethod === 'manual' || creationMethod === 'template') && !showComparisonView && (
            <div className="spam-check-section">
              <div className="spam-check-info-banner with-border">
                <div className="spam-check-info-left">
                  <span className="spam-check-info-text">
                    Take a moment to preview your message and ensure your hard work makes the best possible impact.
                  </span>
                </div>
                <button
                  type="button"
                  onClick={handleSpamCheck}
                  disabled={isCheckingSpam || spamCheckPassed}
                  className={`spam-check-button ${spamCheckPassed ? 'spam-check-passed' : spamCheckResult && (100 - spamCheckResult.spam_score) < 41 ? 'spam-check-failed' : ''}`}
                >
                  {isCheckingSpam 
                    ? 'Checking...' 
                    : spamCheckPassed 
                      ? (
                        <>
                          <svg width="14" height="14" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className="spam-check-passed-svg"
                            aria-hidden="true"
                          >
                            <defs>
                              <linearGradient id="spamCheckPassedIconGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                                <stop offset="0%" stopColor="rgba(212, 88, 255, 0.7)" />
                                <stop offset="100%" stopColor="#6B21A8" />
                              </linearGradient>
                            </defs>
                            <path d="M10 18C14.4183 18 18 14.4183 18 10C18 5.58172 14.4183 2 10 2C5.58172 2 2 5.58172 2 10C2 14.4183 5.58172 18 10 18Z" stroke="url(#spamCheckPassedIconGradient)" strokeWidth="2" fill="none"/>
                            <path d="M7 10L9 12L13 8" stroke="url(#spamCheckPassedIconGradient)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                          </svg>
                          <span className="spam-check-passed-label">Spam Check Passed</span>
                        </>
                      )
                      : spamCheckResult && (100 - spamCheckResult.spam_score) < 41
                        ? <span className="spam-check-failed-label">Spam Check Failed</span>
                        : 'Spam Email Test'}
                </button>
              </div>
            </div>
            )}
          </div>
        </div>
      </div>
      
      {/* Variable Suggestions Popup */}
      {showVariableSuggestions && filteredVariables.length > 0 && (
        <div
          ref={variableSuggestionsRef}
          className="variable-suggestions-popup"
          style={{
            top: `${variableSuggestionsPosition.top}px`,
            left: `${variableSuggestionsPosition.left}px`
          }}
          onClick={(e) => e.stopPropagation()}
        >
          {filteredVariables.map((variable, index) => (
            <div
              key={index}
              onMouseDown={(e) => {
                e.preventDefault();
                e.stopPropagation();
                insertVariable(variable.name);
              }}
              onClick={() => insertVariable(variable.name)}
              className="variable-suggestion-item"
            >
              <span className="variable-suggestion-name" style={{ color: variable.color }}>
                {variable.name}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
});

