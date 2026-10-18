import { useState, useEffect, useMemo, useRef } from 'react';
import { createPortal } from 'react-dom';
import {
  apiService,
  CampaignResponse,
  CampaignGoal,
  CampaignEmailGenerationStatus,
  CampaignEmailReviewSummary,
  CampaignLaunchReadiness,
  CampaignLeadEmailRow,
  CampaignLeadResponse,
  PlanCapabilitiesResponse,
} from '../../../../shared/services/api';
import { toast } from 'sonner';
import { Save } from 'lucide-react';
import './PreviewCampaignDetail.css';
import './CampaignEmailReview.css';
import { CampaignEmailReview, isApprovedLeadEmailRow } from './CampaignEmailReview';
import { CampaignLeadEmailPreviewModal } from './CampaignLeadEmailPreviewModal';
import {
  type LeadPlaceholderData,
  replacePlaceholdersWithLead,
} from './emailPersonalizationHighlight';

interface PreviewLead extends LeadPlaceholderData {
  id: string;
}

function mapCampaignLeadToPreviewLead(campaignLead: CampaignLeadResponse): PreviewLead | null {
  const leadInfo = campaignLead.lead;
  const id = leadInfo?.id || campaignLead.lead_id;
  if (!id) return null;

  return {
    id,
    business_name: leadInfo?.business_name,
    email: leadInfo?.email,
    address: leadInfo?.address,
    industry: leadInfo?.industry,
    website: leadInfo?.website,
    contact_number: leadInfo?.contact_number,
    first_name: null,
    last_name: null,
    job_title: null,
  };
}

function leadDataForPreview(
  lead: PreviewLead,
  campaignLeads: CampaignLeadResponse[],
): LeadPlaceholderData {
  const matched = campaignLeads.find(
    (cl) => cl.lead_id === lead.id || cl.lead?.id === lead.id,
  );
  const nested = matched?.lead;
  return {
    ...lead,
    business_name: lead.business_name ?? nested?.business_name,
    email: lead.email ?? nested?.email,
    address: lead.address ?? nested?.address,
    industry: lead.industry ?? nested?.industry,
    website: lead.website ?? nested?.website,
    contact_number: lead.contact_number ?? nested?.contact_number,
    first_name: lead.first_name,
    last_name: lead.last_name,
    job_title: lead.job_title,
  };
}

interface PreviewCampaignDetailProps {
  campaignId: string;
  onBack?: () => void;
  onNext?: () => void;
  onSaveAsDraft?: () => void;
  selectedLeadsCount?: number;
  selectedLeadIds?: string[];
  emailSubject?: string;
  emailContent?: string;
}

const DAILY_SEND_RATE = 50;

function resolveToneLabel(toneId: string | undefined, capabilities: PlanCapabilitiesResponse | null): string {
  if (!toneId) return 'Professional';
  const tiers = capabilities?.tone_tiers ?? [];
  for (const tier of tiers) {
    const match = tier.tones.find((t) => t.id === toneId);
    if (match) return match.label;
  }
  const fromOptions = capabilities?.tone_options?.find((t) => t.id === toneId);
  if (fromOptions) return fromOptions.label;
  return toneId.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export function PreviewCampaignDetail({
  campaignId,
  onBack,
  onNext,
  onSaveAsDraft,
  selectedLeadsCount,
  selectedLeadIds,
  emailSubject: propEmailSubject,
  emailContent: propEmailContent,
}: PreviewCampaignDetailProps) {
  const [campaign, setCampaign] = useState<CampaignResponse | null>(null);
  const [leads, setLeads] = useState<PreviewLead[]>([]);
  const [leadCount, setLeadCount] = useState<number>(selectedLeadsCount || 0);
  const [goal, setGoal] = useState<CampaignGoal | null>(null);
  // Initialize with props if they have content, otherwise empty string
  const [emailSubject, setEmailSubject] = useState<string>(propEmailSubject && propEmailSubject.trim() ? propEmailSubject : '');
  const [emailContent, setEmailContent] = useState<string>(propEmailContent && propEmailContent.trim() ? propEmailContent : '');
  const [isLoading, setIsLoading] = useState(true);
  const [retryCount, setRetryCount] = useState(0);
  const [isSaving, setIsSaving] = useState(false);
  const [isLaunching, setIsLaunching] = useState(false);
  const [syncedLeadsCount, setSyncedLeadsCount] = useState<number | null>(null); // Track actual synced leads from API
  const [genStatus, setGenStatus] = useState<CampaignEmailGenerationStatus | null>(null);
  const [leadEmails, setLeadEmails] = useState<CampaignLeadEmailRow[]>([]);
  const [reviewSummary, setReviewSummary] = useState<CampaignEmailReviewSummary | null>(null);
  const [launchReadiness, setLaunchReadiness] = useState<CampaignLaunchReadiness | null>(null);
  const [readinessLoading, setReadinessLoading] = useState(false);
  const [showLaunchConfirm, setShowLaunchConfirm] = useState(false);
  const [campaignLeadsRaw, setCampaignLeadsRaw] = useState<CampaignLeadResponse[]>([]);
  const [planCapabilities, setPlanCapabilities] = useState<PlanCapabilitiesResponse | null>(null);
  const [campaignTone, setCampaignTone] = useState<string | undefined>(undefined);
  const [campaignDraftType, setCampaignDraftType] = useState<string | undefined>(undefined);
  const [isEditingCampaignName, setIsEditingCampaignName] = useState(false);
  const [editCampaignName, setEditCampaignName] = useState('');
  const [committedCampaignName, setCommittedCampaignName] = useState('');
  const [isSavingCampaignName, setIsSavingCampaignName] = useState(false);
  const [fallbackPreviewLeadId, setFallbackPreviewLeadId] = useState<string | null>(null);
  const nameAtEditStartRef = useRef('');

  console.log('📧 PreviewCampaignDetail received props:', {
    propEmailSubject: propEmailSubject || 'EMPTY',
    propEmailContent: propEmailContent ? propEmailContent.substring(0, 50) + '...' : 'EMPTY',
    propSubjectLength: propEmailSubject?.length || 0,
    propContentLength: propEmailContent?.length || 0,
    hasPropSubject: !!propEmailSubject,
    hasPropContent: !!propEmailContent,
    propSubjectTruthy: !!propEmailSubject,
    propContentTruthy: !!propEmailContent,
    propSubjectType: typeof propEmailSubject,
    propContentType: typeof propEmailContent
  });

  // Separate function to fetch only campaign details (not email data)
  const fetchCampaignDetailsOnly = async () => {
    setIsLoading(true);
    try {
      const campaignResponse = await apiService.getCampaignLaunchView(campaignId);
      if (campaignResponse.data) {
        setCampaign(campaignResponse.data.campaign);
        if (campaignResponse.data.readiness) {
          setLaunchReadiness(campaignResponse.data.readiness);
        }
        
        // Fetch goal if goal_id exists
        if (campaignResponse.data.campaign.goal_id) {
          try {
            const goalsResponse = await apiService.getCampaignGoals();
            if (goalsResponse.data) {
              const foundGoal = goalsResponse.data.find((g: CampaignGoal) => g.id === campaignResponse.data!.campaign.goal_id);
              if (foundGoal) {
                setGoal(foundGoal);
              }
            }
          } catch (error) {
            console.error('Failed to fetch goal:', error);
          }
        }

      }
      
      // Set email data from props immediately (highest priority) - props always win
      if (propEmailSubject && propEmailSubject.trim()) {
        setEmailSubject(propEmailSubject);
        console.log('✅ fetchCampaignDetailsOnly: Using email_subject from props:', propEmailSubject);
      }
      if (propEmailContent && propEmailContent.trim()) {
        setEmailContent(propEmailContent);
        console.log('✅ fetchCampaignDetailsOnly: Using email_content from props (length):', propEmailContent.length);
      }
      
      // Only use campaign data if props are NOT provided (props take absolute priority)
      if ((!propEmailSubject || !propEmailSubject.trim()) && campaignResponse.data?.campaign.email_subject) {
        setEmailSubject(campaignResponse.data.campaign.email_subject);
        console.log('✅ fetchCampaignDetailsOnly: Using email_subject from campaign data (no props):', campaignResponse.data.campaign.email_subject);
      }
      if ((!propEmailContent || !propEmailContent.trim()) && campaignResponse.data?.campaign.email_content) {
        setEmailContent(campaignResponse.data.campaign.email_content);
        console.log('✅ fetchCampaignDetailsOnly: Using email_content from campaign data (no props, length):', campaignResponse.data.campaign.email_content.length);
      }
      
      setIsLoading(false);
    } catch (error: any) {
      console.error('Failed to fetch campaign details:', error);
      setIsLoading(false);
    }
  };

  useEffect(() => {
    console.log('🔄 Main useEffect triggered:', {
      hasPropSubject: !!propEmailSubject,
      hasPropContent: !!propEmailContent,
      propSubjectValue: propEmailSubject || 'EMPTY',
      propContentValue: propEmailContent ? propEmailContent.substring(0, 30) + '...' : 'EMPTY',
      propSubjectLength: propEmailSubject?.length || 0,
      propContentLength: propEmailContent?.length || 0,
      propSubjectTrimmed: propEmailSubject?.trim() || 'EMPTY',
      propContentTrimmed: propEmailContent?.trim() ? propEmailContent.trim().substring(0, 30) + '...' : 'EMPTY',
      campaignId,
      retryCount
    });
    
    // If we have props with content, use them directly and only fetch campaign details
    // Otherwise, fetch everything including email data from API
    const hasValidProps = propEmailSubject && propEmailContent && 
                          propEmailSubject.trim().length > 0 && 
                          propEmailContent.trim().length > 0;
    
    if (hasValidProps) {
      console.log('✅ Have valid props, using them directly - setting state immediately');
      // Set props immediately in state - DO NOT override with API data
      setEmailSubject(propEmailSubject);
      setEmailContent(propEmailContent);
      console.log('✅ PreviewCampaignDetail: Set email content from props:', {
        subject: propEmailSubject,
        contentLength: propEmailContent.length,
        contentPreview: propEmailContent.substring(0, 100)
      });
      // Fetch campaign details only (async) - but DON'T fetch email content
      const fetchDetails = async () => {
        setIsLoading(true);
        try {
          const campaignResponse = await apiService.getCampaignLaunchView(campaignId);
          if (campaignResponse.data) {
            setCampaign(campaignResponse.data.campaign);
            if (campaignResponse.data.readiness) {
              setLaunchReadiness(campaignResponse.data.readiness);
            }
            
            // DO NOT override email content from props - props take priority
            // Only set email content if props are empty (which shouldn't happen if hasValidProps is true)
            
            // Fetch goal if goal_id exists
            if (campaignResponse.data.campaign.goal_id) {
              try {
                const goalsResponse = await apiService.getCampaignGoals();
                if (goalsResponse.data) {
                  const foundGoal = goalsResponse.data.find((g: CampaignGoal) => g.id === campaignResponse.data!.campaign.goal_id);
                  if (foundGoal) {
                    setGoal(foundGoal);
                  }
                }
              } catch (error) {
                console.error('Failed to fetch goal:', error);
              }
            }

          }
          setIsLoading(false);
        } catch (error: any) {
          console.error('Failed to fetch campaign details:', error);
          setIsLoading(false);
        }
      };
      fetchDetails();
    } else {
      console.log('⚠️ No valid props, fetching from API');
      console.log('⚠️ Prop check failed:', {
        propEmailSubject: propEmailSubject || 'undefined/null',
        propEmailContent: propEmailContent ? propEmailContent.substring(0, 30) + '...' : 'undefined/null',
        hasPropSubject: !!propEmailSubject,
        hasPropContent: !!propEmailContent,
        subjectTrimmedLength: propEmailSubject?.trim().length || 0,
        contentTrimmedLength: propEmailContent?.trim().length || 0
      });
      fetchCampaignData();
    }
  }, [campaignId, retryCount, propEmailSubject, propEmailContent]);

  // Update leadCount when selectedLeadsCount prop changes (if current count is 0 or prop is higher)
  useEffect(() => {
    if (selectedLeadsCount !== undefined && selectedLeadsCount > 0) {
      // Only update if prop has a value and it's greater than current count
      // This ensures we don't override API data, but we do use prop if API hasn't loaded yet
      if (leadCount === 0 || selectedLeadsCount > leadCount) {
        console.log(`[DEBUG] PreviewCampaignDetail: Updating leadCount from prop: ${leadCount} -> ${selectedLeadsCount}`);
        setLeadCount(selectedLeadsCount);
      }
    }
  }, [selectedLeadsCount, leadCount]);

  // Update email data when props change (from step 3) - props take highest priority
  // This ensures props are immediately reflected in state
  useEffect(() => {
    console.log('🔄 useEffect: Props changed:', {
      propEmailSubject: propEmailSubject || 'EMPTY',
      propEmailContent: propEmailContent ? propEmailContent.substring(0, 50) + '...' : 'EMPTY',
      currentEmailSubject: emailSubject || 'EMPTY',
      currentEmailContent: emailContent ? emailContent.substring(0, 50) + '...' : 'EMPTY'
    });
    
    if (propEmailSubject && propEmailSubject.trim() && propEmailSubject !== emailSubject) {
      console.log('✅ useEffect: Setting emailSubject from props:', propEmailSubject);
      setEmailSubject(propEmailSubject);
    }
    if (propEmailContent && propEmailContent.trim() && propEmailContent !== emailContent) {
      console.log('✅ useEffect: Setting emailContent from props (length):', propEmailContent.length);
      setEmailContent(propEmailContent);
    }
  }, [propEmailSubject, propEmailContent, emailSubject, emailContent]);

  // Always load campaign leads so preview can personalize with the first selected lead
  useEffect(() => {
    if (!campaignId) return;

    let cancelled = false;

    const loadCampaignLeads = async () => {
      try {
        const leadsResponse = await apiService.getCampaignLeads(campaignId);
        if (cancelled) return;

        if (leadsResponse.error) {
          console.error('Error fetching campaign leads:', leadsResponse.error);
          return;
        }

        if (!leadsResponse.data || !Array.isArray(leadsResponse.data)) {
          setLeads([]);
          setSyncedLeadsCount(0);
          return;
        }

        const campaignLeads = leadsResponse.data;
        setCampaignLeadsRaw(campaignLeads);
        const fetchedLeads = campaignLeads
          .map(mapCampaignLeadToPreviewLead)
          .filter((lead): lead is PreviewLead => lead !== null);

        setSyncedLeadsCount(fetchedLeads.length);

        if (fetchedLeads.length > 0) {
          setLeadCount((prev) => (prev > 0 ? prev : fetchedLeads.length));
        }

        if (selectedLeadIds?.length) {
          const ordered = selectedLeadIds
            .map((id) => fetchedLeads.find((lead) => lead.id === id))
            .filter((lead): lead is PreviewLead => !!lead);
          const remaining = fetchedLeads.filter((lead) => !selectedLeadIds.includes(lead.id));
          setLeads([...ordered, ...remaining]);
        } else {
          setLeads(fetchedLeads);
        }
      } catch (error) {
        console.error('Failed to fetch campaign leads:', error);
        if (!cancelled) {
          setLeads([]);
          setSyncedLeadsCount(0);
        }
      }
    };

    loadCampaignLeads();

    return () => {
      cancelled = true;
    };
  }, [campaignId, selectedLeadIds]);

  useEffect(() => {
    if (!campaignId) return;

    let cancelled = false;
    let intervalId: ReturnType<typeof setInterval> | undefined;

    const pollGeneration = async () => {
      try {
        const statusRes = await apiService.getCampaignLeadEmailsStatus(campaignId);
        if (cancelled) return;
        if (statusRes.data) {
          setGenStatus(statusRes.data);
        }

        const emailsRes = await apiService.getCampaignLeadEmails(campaignId);
        if (cancelled) return;
        if (emailsRes.data?.length) {
          setLeadEmails(emailsRes.data);
        }

        if (statusRes.data?.is_complete && intervalId) {
          clearInterval(intervalId);
          intervalId = undefined;
        }
      } catch (error) {
        console.warn('Failed to poll per-lead email generation:', error);
      }
    };

    pollGeneration();
    intervalId = setInterval(pollGeneration, 3000);

    return () => {
      cancelled = true;
      if (intervalId) clearInterval(intervalId);
    };
  }, [campaignId]);

  // Sync Step 3 outreach-ready emails to approved review status for launch
  useEffect(() => {
    if (!campaignId || leadEmails.length === 0) return;

    const needsApproval = leadEmails.some(
      (row) =>
        row.generation_status === 'ready' &&
        row.compliance_status === 'passed' &&
        row.review_status !== 'approved',
    );
    if (!needsApproval) return;

    let cancelled = false;
    (async () => {
      try {
        const res = await apiService.approveCampaignEmails(campaignId, { approve_all: true });
        if (cancelled || res.error) return;
        const emailsRes = await apiService.getCampaignLeadEmails(campaignId);
        if (!cancelled && emailsRes.data) {
          setLeadEmails(emailsRes.data);
        }
        if (res.data) {
          setReviewSummary(res.data);
        }
      } catch {
        // non-blocking — table still shows Approved via compliance_status
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [campaignId, leadEmails.length]);

  useEffect(() => {
    if (!campaignId) return;
    let cancelled = false;

    const loadReadiness = async () => {
      try {
        const res = await apiService.getCampaignLaunchReadiness(campaignId);
        if (!cancelled && res.data) {
          setLaunchReadiness(res.data);
        }
      } catch (error) {
        console.warn('Failed to load launch readiness:', error);
      }
    };

    const initialLoad = async () => {
      setReadinessLoading(true);
      try {
        await loadReadiness();
      } finally {
        if (!cancelled) setReadinessLoading(false);
      }
    };

    initialLoad();
    const intervalId = setInterval(loadReadiness, 5000);

    return () => {
      cancelled = true;
      clearInterval(intervalId);
    };
  }, [campaignId, genStatus?.is_complete, reviewSummary?.approved, reviewSummary?.pending_review]);

  useEffect(() => {
    if (!campaignId) return;
    let cancelled = false;

    const loadMeta = async () => {
      try {
        const [capRes, draftRes] = await Promise.all([
          apiService.getPersonalizationCapabilities(),
          apiService.getCampaignDraft(campaignId),
        ]);
        if (cancelled) return;
        if (capRes.data) setPlanCapabilities(capRes.data);
        if (draftRes.data?.tone) setCampaignTone(draftRes.data.tone);
        if (draftRes.data?.draft_type) setCampaignDraftType(draftRes.data.draft_type);
      } catch {
        // non-blocking
      }
    };

    loadMeta();
    return () => {
      cancelled = true;
    };
  }, [campaignId]);

  const toneLabel = useMemo(
    () => resolveToneLabel(campaignTone, planCapabilities),
    [campaignTone, planCapabilities],
  );

  const planBadgeLabel = (planCapabilities?.label || planCapabilities?.plan || 'free').toUpperCase();
  const isTemplateDraft = campaignDraftType === 'TEMPLATE';

  const previewEmailCount = useMemo(
    () => leadEmails.filter(isApprovedLeadEmailRow).length,
    [leadEmails],
  );

  const displaySubject = propEmailSubject || emailSubject || '';
  const displayContent =
    propEmailContent || emailContent || campaign?.email_content || '';
  const fallbackPreviewLeads =
    leads.length > 0
      ? leads
      : [{ id: 'template-fallback', business_name: 'Campaign template' } as PreviewLead];

  const fallbackTemplateEmailRows = useMemo((): CampaignLeadEmailRow[] => {
    if (!displaySubject.trim() && !displayContent.trim()) return [];

    const now = new Date().toISOString();
    return fallbackPreviewLeads.map((lead, index) => {
      const leadData = leadDataForPreview(lead, campaignLeadsRaw);
      const matched = campaignLeadsRaw.find(
        (cl) => cl.lead_id === lead.id || cl.lead?.id === lead.id,
      );
      const rowId = `template-preview-${lead.id}`;

      return {
        id: rowId,
        campaign_id: campaignId,
        campaign_lead_id: matched?.id ?? null,
        lead_id: lead.id,
        lead_index: index,
        business_name: leadData.business_name ?? null,
        email: leadData.email ?? null,
        location: leadData.address ?? null,
        subject: replacePlaceholdersWithLead(displaySubject, leadData),
        body: replacePlaceholdersWithLead(displayContent, leadData),
        generation_status: 'ready',
        compliance_status: 'passed',
        review_status: 'approved',
        regeneration_count: 0,
        created_at: now,
        updated_at: now,
      };
    });
  }, [
    campaignId,
    displaySubject,
    displayContent,
    fallbackPreviewLeads,
    campaignLeadsRaw,
  ]);

  const recipientCount =
    previewEmailCount > 0
      ? previewEmailCount
      : leadEmails.length > 0
        ? 0
        : leads.length > 0
          ? leads.length
          : 1;

  useEffect(() => {
    if (campaign?.name !== undefined && !isEditingCampaignName) {
      setCommittedCampaignName(campaign.name || '');
    }
  }, [campaign?.name, campaign?.id, isEditingCampaignName]);

  const startEditingCampaignName = () => {
    const current = committedCampaignName || campaign?.name || '';
    nameAtEditStartRef.current = current;
    setEditCampaignName(current);
    setIsEditingCampaignName(true);
  };

  const cancelEditingCampaignName = () => {
    setEditCampaignName(nameAtEditStartRef.current);
    setIsEditingCampaignName(false);
  };

  const saveCampaignName = async () => {
    const trimmed = editCampaignName.trim();
    if (!trimmed) {
      toast.error('Campaign name is required');
      setEditCampaignName(nameAtEditStartRef.current);
      return;
    }
    if (trimmed === (committedCampaignName || campaign?.name || '')) {
      setIsEditingCampaignName(false);
      return;
    }
    setIsSavingCampaignName(true);
    try {
      const res = await apiService.updateCampaign(campaignId, { name: trimmed });
      if (res.error) {
        toast.error(res.error);
        return;
      }
      setCommittedCampaignName(trimmed);
      if (res.data) {
        setCampaign(res.data);
      } else if (campaign) {
        setCampaign({ ...campaign, name: trimmed });
      }
      nameAtEditStartRef.current = trimmed;
      setIsEditingCampaignName(false);
      toast.success('Campaign name updated');
    } catch {
      toast.error('Failed to update campaign name');
    } finally {
      setIsSavingCampaignName(false);
    }
  };

  const fetchCampaignData = async () => {
    setIsLoading(true);
    try {
      // Fetch campaign details
      const campaignResponse = await apiService.getCampaignLaunchView(campaignId);
      
      if (campaignResponse.error) {
        console.error('❌ Failed to fetch campaign:', campaignResponse.error);
        toast.error(`Failed to load campaign: ${campaignResponse.error}. Please check your connection.`);
        setIsLoading(false);
        return;
      }
      
      if (campaignResponse.data) {
        setCampaign(campaignResponse.data.campaign);
        if (campaignResponse.data.readiness) {
          setLaunchReadiness(campaignResponse.data.readiness);
        }
      }

      // Priority order: 1. Props (from step 3 - highest priority), 2. API data, 3. Campaign response
      // Props always take priority - they come directly from step 3
      // Start with current state (which might already have props from useEffect)
      let foundSubject = emailSubject || '';
      let foundContent = emailContent || '';
      
      // First priority: Use props if they have content (props override everything)
      if (propEmailSubject && propEmailSubject.trim()) {
        foundSubject = propEmailSubject;
        console.log('✅ fetchCampaignData: Using propEmailSubject:', propEmailSubject);
      }
      if (propEmailContent && propEmailContent.trim()) {
        foundContent = propEmailContent;
        console.log('✅ fetchCampaignData: Using propEmailContent (length):', propEmailContent.length);
      }

      // Second priority: Use campaign data (email_subject and email_content are stored in campaign)
      // Campaign data includes email content from all methods (template, AI, manual)
      if (campaignResponse.data) {
        const campaignData = campaignResponse.data.campaign;
        if ((!foundSubject || !foundSubject.trim()) && campaignData.email_subject && campaignData.email_subject.trim()) {
          foundSubject = campaignData.email_subject;
          console.log('✅ Using email_subject from campaign data:', foundSubject);
        }
        if ((!foundContent || !foundContent.trim()) && campaignData.email_content && campaignData.email_content.trim()) {
          foundContent = campaignData.email_content;
          console.log('✅ Using email_content from campaign data (length):', foundContent.length);
          console.log('✅ Email content preview:', foundContent.substring(0, 100) + '...');
        }
      }
      
      // Third priority: Try getCampaignPreview as fallback if still empty
      if ((!foundSubject || !foundContent)) {
        try {
          const previewResponse = await apiService.getCampaignPreview(campaignId);
          console.log('📧 Preview response:', previewResponse);
          
          // Handle different response structures
          let previewData: any = null;
          if (previewResponse.data) {
            previewData = previewResponse.data;
          } else if ((previewResponse as any).email_subject || (previewResponse as any).email_content) {
            previewData = previewResponse as any;
          }
          
          if (previewData) {
            // Use API data only if we don't have it from props or campaign
            if ((!foundSubject || !foundSubject.trim()) && previewData.email_subject && previewData.email_subject.trim()) {
              foundSubject = previewData.email_subject;
              console.log('✅ Using email_subject from getCampaignPreview:', foundSubject);
            }
            if ((!foundContent || !foundContent.trim()) && previewData.email_content && previewData.email_content.trim()) {
              foundContent = previewData.email_content;
              console.log('✅ Using email_content from getCampaignPreview (length):', foundContent.length);
            }
          }
        } catch (previewError: any) {
          console.error('❌ getCampaignPreview failed:', previewError);
          // Continue without preview data
        }
      }
      
      // Final check: if still empty, try campaign response directly
      if ((!foundSubject || !foundContent) && campaignResponse.data) {
        const campaignData = campaignResponse.data as any;
        if (!foundSubject && campaignData.email_subject && campaignData.email_subject.trim()) {
          foundSubject = campaignData.email_subject;
        }
        if (!foundContent && campaignData.email_content && campaignData.email_content.trim()) {
          foundContent = campaignData.email_content;
        }
      }
      
      // Set the state with what we found (props always win)
      // Always set if we found something, even if it's empty (to clear previous state)
      console.log('📝 Final email data to set:', {
        foundSubject: foundSubject || 'EMPTY',
        foundContent: foundContent ? foundContent.substring(0, 50) + '...' : 'EMPTY',
        foundSubjectLength: foundSubject?.length || 0,
        foundContentLength: foundContent?.length || 0,
        hasFoundSubject: !!foundSubject,
        hasFoundContent: !!foundContent
      });
      
      // Always set email data if we found it, prioritizing found data over props
      // But props should have been set already via useEffect, so this is mainly for API fallback
      if (foundSubject && foundSubject.trim()) {
        console.log('✅ Setting emailSubject from fetchCampaignData:', foundSubject);
        setEmailSubject(foundSubject);
      } else if (propEmailSubject && propEmailSubject.trim()) {
        console.log('✅ Setting emailSubject from props (fallback):', propEmailSubject);
        setEmailSubject(propEmailSubject);
      } else {
        // Only warn if we've checked all sources and still found nothing
        if (retryCount >= 1) {
          console.warn('⚠️ No email subject found from any source after retries');
        } else {
          console.log('ℹ️ Email subject not found yet, will retry...');
        }
      }
      
      if (foundContent && foundContent.trim()) {
        console.log('✅ Setting emailContent from fetchCampaignData (length):', foundContent.length);
        console.log('✅ Email content preview:', foundContent.substring(0, 100) + '...');
        setEmailContent(foundContent);
      } else if (propEmailContent && propEmailContent.trim()) {
        console.log('✅ Setting emailContent from props (fallback, length):', propEmailContent.length);
        setEmailContent(propEmailContent);
      } else {
        // Only warn if we've checked all sources and still found nothing
        if (retryCount >= 1) {
          console.warn('⚠️ No email content found from any source after retries');
        } else {
          console.log('ℹ️ Email content not found yet, will retry...');
        }
      }
      
      // If we didn't find email data and haven't retried too many times, retry after a delay
      // Only retry if props are also empty (props take priority, so no need to retry if we have props)
      if ((!foundSubject || !foundContent) && retryCount < 2 && (!propEmailSubject || !propEmailContent)) {
        setTimeout(() => {
          setRetryCount(prev => prev + 1);
        }, 1000);
      }

      // Fetch goal if goal_id exists
      if (campaignResponse.data?.campaign.goal_id) {
        try {
          const goalsResponse = await apiService.getCampaignGoals();
          if (goalsResponse.data) {
            const foundGoal = goalsResponse.data.find((g: CampaignGoal) => g.id === campaignResponse.data!.campaign.goal_id);
            if (foundGoal) {
              setGoal(foundGoal);
            }
          }
        } catch (error) {
          console.error('Failed to fetch goal:', error);
        }
      }

      // Lead count fallback when leads API hasn't loaded yet
      if (selectedLeadsCount !== undefined && selectedLeadsCount > 0) {
        setLeadCount((prev) => (prev > 0 ? prev : selectedLeadsCount));
      } else if (campaignResponse.data?.lead_count && campaignResponse.data.lead_count > 0) {
        setLeadCount((prev) => (prev > 0 ? prev : campaignResponse.data.lead_count));
      }
    } catch (error: any) {
      console.error('Failed to fetch campaign data:', error);
      toast.error('Failed to load campaign details');
    } finally {
      setIsLoading(false);
    }
  };

  if (isLoading) {
    return (
      <div className="preview-campaign-container">
        <div className="preview-campaign-card">
          <div className="preview-loading">Loading campaign details...</div>
        </div>
      </div>
    );
  }

  if (!campaign) {
    return (
      <div className="preview-campaign-container">
        <div className="preview-campaign-card">
          <div className="preview-error">Campaign not found</div>
        </div>
      </div>
    );
  }

  // Handle Save as Draft
  const handleSaveAsDraft = async () => {
    if (!campaignId) {
      toast.error('Campaign ID is missing');
      return;
    }

    setIsSaving(true);
    try {
      // Ensure leads are synced to backend before save (handles edge cases where sync was missed)
      const leadIdsToSync = selectedLeadIds?.filter(id => !id.startsWith('manual-')) || [];
      if (leadIdsToSync.length > 0) {
        const syncResponse = await apiService.syncCampaignLeads(campaignId, leadIdsToSync);
        if (syncResponse.error) {
          console.warn('Lead sync before save failed (may already be synced):', syncResponse.error);
        }
      }

      // Ensure email content is persisted (handles edge cases where draft update was missed)
      const subjectToSave = propEmailSubject?.trim();
      const contentToSave = propEmailContent?.trim();
      if (subjectToSave && contentToSave) {
        try {
          await apiService.updateCampaignDraftManual(campaignId, {
            email_subject: subjectToSave,
            email_content: contentToSave,
            draft_type: 'MANUAL',
          });
        } catch (draftErr) {
          console.warn('Email persist before save failed (may already be saved):', draftErr);
        }
      }

      const response = await apiService.saveCampaignDraft(campaignId);
      
      if (response.error) {
        toast.error(response.error || 'Failed to save campaign as draft');
        setIsSaving(false);
        return;
      }

      toast.success('Campaign saved as draft successfully');

      // Cleanup: prevent stale email-account step state from leaking into other draft resumes
      // (This global key has historically caused "latest campaign" to override when reopening a different draft.)
      sessionStorage.removeItem('campaignEmailAccountStep');
      sessionStorage.removeItem(`campaignEmailAccountStep_${campaignId}`);
      sessionStorage.removeItem(`campaignEmailAccountChoice_${campaignId}`);
      sessionStorage.removeItem(`campaignEmailType_${campaignId}`);
      
      // Navigate back to campaigns page immediately
      // Use onSaveAsDraft if provided (navigates to campaign list), otherwise fall back to onBack
      if (onSaveAsDraft) {
        onSaveAsDraft();
      } else if (onBack) {
        onBack();
      }
    } catch (error: any) {
      console.error('Failed to save campaign as draft:', error);
      toast.error(error?.message || 'Failed to save campaign as draft');
    } finally {
      setIsSaving(false);
    }
  };


  // Handle Launch Campaign
  const handleLaunchCampaign = async () => {
    if (!campaignId) {
      toast.error('Campaign ID is missing');
      return;
    }

    // Validate that email content exists
    if (!emailSubject || !emailSubject.trim()) {
      toast.error('Email subject is required. Please go back and add a subject.');
      return;
    }

    if (!emailContent || !emailContent.trim()) {
      toast.error('Email content is required. Please go back and add email content.');
      return;
    }

    // Validate that leads are selected
    if (leadCount === 0) {
      toast.error('No leads selected. Please go back and select at least one lead.');
      return;
    }

    if (launchReadiness && !launchReadiness.can_launch) {
      toast.error(launchReadiness.launch_blockers[0] || 'Complete all launch checks before sending.');
      return;
    }
    if (reviewSummary?.has_per_lead_emails && !reviewSummary.can_launch) {
      toast.error(reviewSummary.launch_blockers[0] || 'Complete email review before launching.');
      return;
    }

    setIsLaunching(true);
    try {
      // First, verify that leads are actually synced to the campaign
      console.log('🔍 Verifying leads are synced before launch...');
      const leadsResponse = await apiService.getCampaignLeads(campaignId);
      
      if (leadsResponse.error) {
        console.error('❌ Failed to fetch campaign leads:', leadsResponse.error);
        toast.error('Failed to verify leads. Please go back and ensure leads are selected.');
        setIsLaunching(false);
        return;
      }

      const syncedLeads = leadsResponse.data || [];
      const leadsWithEmail = syncedLeads.filter((campaignLead) => {
        const email = campaignLead.lead?.email;
        return email && email.trim();
      });
      
      console.log('📊 Lead verification:', {
        totalSynced: syncedLeads.length,
        withEmail: leadsWithEmail.length,
        leadCount,
        syncedLeadsData: syncedLeads,
        sampleLead: syncedLeads[0] // Log first lead to see structure
      });

      if (syncedLeads.length === 0) {
        toast.error(
          'No leads are synced to this campaign. If you manually added leads in step 2, please go back to step 2 and click "Next" to properly sync them before launching.',
          { duration: 6000 }
        );
        setIsLaunching(false);
        return;
      }

      if (leadsWithEmail.length === 0) {
        toast.error(
          `Found ${syncedLeads.length} lead(s) but none have valid email addresses. Please go back to step 2 and ensure your selected leads have email addresses.`,
          { duration: 6000 }
        );
        setIsLaunching(false);
        return;
      }

      console.log('🚀 Launching campaign:', {
        campaignId,
        emailSubject: emailSubject.substring(0, 50),
        emailContentLength: emailContent.length,
        syncedLeadsCount: leadsWithEmail.length
      });

      const response = await apiService.launchCampaign(campaignId);
      
      if (response.error) {
        console.error('❌ Launch failed:', response.error);
        toast.error(response.error || 'Failed to launch campaign');
        return;
      }

      console.log('✅ Launch response:', response);

      const queuedCount = response.data?.queued ?? response.data?.approved ?? leadsWithEmail.length;
      
      let successMessage = response.data?.message;
      if (!successMessage) {
        successMessage =
          queuedCount === 1
            ? '1 email queued for sending.'
            : `${queuedCount} emails queued for sending.`;
      }
      
      toast.success(successMessage);
      setShowLaunchConfirm(false);
      
      // Navigate away after a short delay
      setTimeout(() => {
        // Prefer onNext (used by CreateCampaign to go to Campaigns list),
        // fall back to onBack when viewing from standalone preview
        if (onNext) {
          onNext();
        } else if (onBack) {
          onBack();
        }
      }, 2000);
    } catch (error: any) {
      console.error('❌ Failed to launch campaign:', error);
      const errorMessage = error?.response?.data?.detail || 
                           error?.message || 
                           'Failed to launch campaign. Please check the console for details.';
      toast.error(errorMessage);
    } finally {
      setIsLaunching(false);
    }
  };

  const hasPerLeadRows = leadEmails.length > 0;

  const launchBlocker =
    (launchReadiness && !launchReadiness.can_launch
      ? launchReadiness.launch_blockers[0]
      : undefined) ??
    (hasPerLeadRows && previewEmailCount === 0
      ? 'At least one approved email is required to launch.'
      : undefined);

  const launchDisabled =
    isSaving ||
    isLaunching ||
    readinessLoading ||
    (hasPerLeadRows && previewEmailCount === 0) ||
    !launchReadiness?.can_launch;

  const handleLaunchClick = () => {
    if (launchReadiness?.can_launch) {
      setShowLaunchConfirm(true);
      return;
    }
    handleLaunchCampaign();
  };

  const handleConfirmLaunch = () => {
    handleLaunchCampaign();
  };

  return (
    <div className="preview-campaign-container">
      <div className="preview-campaign-card preview-step5-card">
        {syncedLeadsCount !== null && syncedLeadsCount === 0 && (
          <div className="preview-campaign-warning-banner">
            <div className="preview-campaign-warning-icon">⚠️</div>
            <div className="preview-campaign-warning-text">
              No leads are synced to this campaign. Go back to step 2 and click Next to sync leads before launching.
            </div>
          </div>
        )}

        <div className="preview-step5-layout">
          <div className="preview-step5-main">
            {leadEmails.length > 0 ? (
              <CampaignEmailReview
                campaignId={campaignId}
                emails={leadEmails}
                toneLabel={toneLabel}
                campaignLeads={campaignLeadsRaw}
                onEmailsChange={setLeadEmails}
                onReviewSummaryChange={setReviewSummary}
                senderEmail={
                  campaign?.email_sending_mode === 'USER' ? campaign.sender_email || null : null
                }
              />
            ) : (
              <div className="preview-step5-fallback-table preview-step5-fallback-table--scrollable">
                <div
                  className={`preview-step5-fallback-header ${
                    isTemplateDraft
                      ? 'preview-step5-fallback-header--template'
                      : 'preview-step5-fallback-header--full'
                  }`}
                >
                  <span>Lead / Subject preview</span>
                  {!isTemplateDraft && <span>Tone</span>}
                  <span>Status</span>
                  <span className="preview-step5-fallback-actions-head" aria-hidden />
                </div>
                <div className="preview-step5-fallback-body">
                  {fallbackPreviewLeads.map((lead) => {
                    const leadData = leadDataForPreview(lead, campaignLeadsRaw);
                    const rowId = `template-preview-${lead.id}`;
                    const personalizedSubject = replacePlaceholdersWithLead(
                      displaySubject || 'No subject',
                      leadData,
                    );
                    return (
                      <div
                        key={lead.id}
                        className={`preview-step5-fallback-row ${
                          isTemplateDraft
                            ? 'preview-step5-fallback-row--template'
                            : 'preview-step5-fallback-row--full'
                        }`}
                      >
                        <div className="preview-step5-fallback-lead">
                          <span className="preview-step5-fallback-company">
                            {lead.business_name || 'Campaign template'}
                          </span>
                          <span className="preview-step5-fallback-subject">
                            Subject: {personalizedSubject}
                          </span>
                        </div>
                        {!isTemplateDraft && (
                          <span className="campaign-email-review-tone-pill">{toneLabel}</span>
                        )}
                        <span className="preview-step5-fallback-status">
                          <span className="campaign-email-review-status campaign-email-review-status--approved">
                            <span className="campaign-email-review-status-dot" aria-hidden />
                            Approved
                          </span>
                        </span>
                        <span className="preview-step5-fallback-action">
                          <button
                            type="button"
                            className="preview-step5-fallback-preview"
                            onClick={() => setFallbackPreviewLeadId(rowId)}
                            disabled={!displaySubject.trim() && !displayContent.trim()}
                          >
                            Preview
                          </button>
                        </span>
                      </div>
                    );
                  })}
                </div>
                <p className="preview-step5-fallback-note">
                  {fallbackPreviewLeads.length}{' '}
                  {fallbackPreviewLeads.length === 1 ? 'lead' : 'leads'}
                </p>
              </div>
            )}
          </div>

          <aside className="preview-step5-sidebar">
            <div className="preview-step5-summary">
              <div className="preview-step5-summary-header">
                <h3 className="preview-step5-summary-title heading-m">Campaign summary</h3>
                {isEditingCampaignName ? (
                  <div className="preview-step5-summary-edit-actions">
                    <button
                      type="button"
                      className="preview-step5-summary-edit preview-step5-summary-edit--muted"
                      onClick={cancelEditingCampaignName}
                      disabled={isSavingCampaignName}
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      className="preview-step5-summary-edit"
                      onClick={saveCampaignName}
                      disabled={isSavingCampaignName}
                    >
                      {isSavingCampaignName ? 'Saving…' : 'Save'}
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    className="preview-step5-summary-edit"
                    onClick={startEditingCampaignName}
                  >
                    Edit
                  </button>
                )}
              </div>
              <dl className="preview-step5-summary-list">
                <div className="preview-step5-summary-row">
                  <dt>Campaign</dt>
                  <dd>
                    {isEditingCampaignName ? (
                      <input
                        type="text"
                        className="preview-step5-summary-name-input"
                        value={editCampaignName}
                        onChange={(e) => setEditCampaignName(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') saveCampaignName();
                          if (e.key === 'Escape') cancelEditingCampaignName();
                        }}
                        disabled={isSavingCampaignName}
                        autoFocus
                        aria-label="Campaign name"
                      />
                    ) : (
                      committedCampaignName || campaign.name || '—'
                    )}
                  </dd>
                </div>
                <div className="preview-step5-summary-row">
                  <dt>Recipients</dt>
                  <dd>
                    {recipientCount} email{recipientCount !== 1 ? 's' : ''}
                  </dd>
                </div>
                {!isTemplateDraft && (
                  <div className="preview-step5-summary-row preview-step5-summary-row--tone">
                    <dt>Tone</dt>
                    <dd>
                      {toneLabel}
                      <span className="preview-step5-plan-badge">{planBadgeLabel}</span>
                    </dd>
                  </div>
                )}
                <div className="preview-step5-summary-row">
                  <dt>Send rate</dt>
                  <dd>{DAILY_SEND_RATE} / day</dd>
                </div>
              </dl>
            </div>
          </aside>
        </div>

        <div className="create-campaign-actions preview-step5-footer">
          {launchDisabled && launchBlocker && (
            <p className="preview-step5-launch-blocker" role="status">
              {launchBlocker}
            </p>
          )}
          <button
            onClick={onBack}
            className="evecta-secondary-btn preview-step5-back-btn"
            title="Go back"
            type="button"
          >
            Back
          </button>
          <div className="preview-step5-footer-actions">
            <button
              className="evecta-secondary-btn"
              type="button"
              onClick={handleSaveAsDraft}
              disabled={isSaving || isLaunching}
              title="Save as draft"
            >
              <Save size={18} className="dashboard-header-btn-icon" />
              Save as draft
            </button>
            <button
              className="evecta-primary-btn"
              type="button"
              onClick={handleLaunchClick}
              disabled={launchDisabled}
              title={launchBlocker}
            >
              Launch campaign
            </button>
          </div>
        </div>

        {fallbackPreviewLeadId && fallbackTemplateEmailRows.length > 0 && (
          <CampaignLeadEmailPreviewModal
            campaignId={campaignId}
            toneLabel={isTemplateDraft ? 'Template' : toneLabel}
            rows={fallbackTemplateEmailRows}
            initialRowId={fallbackPreviewLeadId}
            campaignLeads={campaignLeadsRaw}
            readOnly
            onClose={() => setFallbackPreviewLeadId(null)}
          />
        )}

        {showLaunchConfirm &&
          launchReadiness?.can_launch &&
          createPortal(
            <div
              className="preview-launch-confirm-overlay"
              onClick={() => !isLaunching && setShowLaunchConfirm(false)}
            >
              <div
                className="preview-launch-confirm-card"
                role="dialog"
                aria-modal="true"
                aria-labelledby="preview-launch-confirm-title"
                onClick={(e) => e.stopPropagation()}
              >
                <h3 id="preview-launch-confirm-title" className="heading-m">
                  Confirm launch
                </h3>
                <p>
                  Queue <strong>{launchReadiness.approved_to_send}</strong> approved email(s) for sending?
                  {launchReadiness.skipped_rejected > 0 && (
                    <> {launchReadiness.skipped_rejected} rejected lead(s) will be skipped.</>
                  )}
                </p>
                <div className="preview-launch-confirm-actions">
                  <button
                    type="button"
                    className="evecta-secondary-btn"
                    onClick={() => setShowLaunchConfirm(false)}
                    disabled={isLaunching}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="evecta-primary-btn"
                    onClick={handleConfirmLaunch}
                    disabled={isLaunching}
                  >
                    {isLaunching ? 'Launching…' : 'Confirm launch'}
                  </button>
                </div>
              </div>
            </div>,
            document.body,
          )}
      </div>
    </div>
  );
}

