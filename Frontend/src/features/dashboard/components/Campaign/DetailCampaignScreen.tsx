import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { Star, Filter, Search, X, Check, Pencil, SlidersHorizontal, ChevronDown, Plus } from 'lucide-react';
import { LeadDetailPanel } from '../ui/LeadDetailPanel';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../ui/table';
import { apiService, LeadResponse } from '../../../../shared/services/api';
import { sortLeadsWithUserAddedFirst } from '../../../../shared/utils/leadSort';
import { readCampaignLeadSelection } from '../../../../shared/utils/campaignLeadSelection';
import { toast } from 'sonner';
import { EmptyState } from '../ui/EmptyState';
import './DetailCampaignScreen.css';

interface Lead {
  id: string;
  companyName: string;
  email: string;
  phone: string;
  location: string;
  tags: string[];
  website?: string;
  score: number;
  starred: boolean;
  created_at?: string;
  isManual?: boolean; // Flag to identify manually added leads
  isUserAdded?: boolean;
}

interface ManualLead {
  id: string; // Can be temporary (manual-*) or real database ID
  business_name: string;
  email: string;
  address?: string;
  industry?: string;
  contact_number?: string;
  website?: string;
  lead_score?: number;
}

interface DetailCampaignScreenProps {
  campaignId: string;
  preselectedLeadIds?: string[];
  searchQuery?: string;
  currentPage?: number;
  itemsPerPage?: number;
  onPageChange?: (page: number) => void;
  onItemsPerPageChange?: (itemsPerPage: number) => void;
  onTotalLeadsChange?: (total: number) => void;
  onToggleSidebar?: () => void;
  onBack?: () => void;
  onNext?: (selectedLeadIds: string[]) => void;
  onSelectedLeadsChange?: (count: number) => void;
  onSelectedLeadIdsChange?: (leadIds: string[]) => void; // Callback to pass selected lead IDs
  showFilters?: boolean;
  onToggleFilters?: (show: boolean) => void;
  onAddManualLeadRef?: (openModal: () => void) => void; // Callback to expose the open modal function
  onGenerateNewLeads?: () => void; // Step-2 CTA when lead list is empty
}

function leadFromResponse(data: LeadResponse): Lead {
  return {
    id: data.id,
    companyName: data.business_name || 'N/A',
    email: data.email || 'N/A',
    phone: (data.contact_number && String(data.contact_number).trim()) || 'N/A',
    location: data.address || 'N/A',
    tags: data.industry ? [data.industry] : [],
    website: data.website,
    score: data.lead_score || 0,
    starred: data.starred || false,
    created_at: data.created_at,
    isUserAdded: data.is_user_added ?? false,
  };
}

export function DetailCampaignScreen({
  campaignId, 
  preselectedLeadIds,
  searchQuery: externalSearchQuery = '',
  currentPage: externalCurrentPage,
  itemsPerPage: externalItemsPerPage,
  onPageChange,
  onItemsPerPageChange,
  onTotalLeadsChange,
  onToggleSidebar, 
  onBack, 
  onNext,
  onSelectedLeadsChange,
  onSelectedLeadIdsChange,
  showFilters: externalShowFilters = false,
  onToggleFilters,
  onAddManualLeadRef,
  onGenerateNewLeads
}: DetailCampaignScreenProps) {
  const [selectedLeads, setSelectedLeads] = useState<Set<string>>(new Set());
  const [allLeads, setAllLeads] = useState<Lead[]>([]);
  const [filteredLeads, setFilteredLeads] = useState<Lead[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState(externalSearchQuery);
  const [currentPage, setCurrentPage] = useState(externalCurrentPage || 1);
  const [itemsPerPage, setItemsPerPage] = useState(externalItemsPerPage || 10);
  const showFilters = externalShowFilters;
  const [selectedIndustries, setSelectedIndustries] = useState<Set<string>>(new Set());
  const [selectedLocations, setSelectedLocations] = useState<Set<string>>(new Set());
  const [scoreRange, setScoreRange] = useState<[number, number]>([0, 100]);
  const [locationInput, setLocationInput] = useState('');
  const [industryInput, setIndustryInput] = useState('');
  const [showLocationSuggestions, setShowLocationSuggestions] = useState(false);
  const [showIndustrySuggestions, setShowIndustrySuggestions] = useState(false);
  const [emailFilter, setEmailFilter] = useState<'all' | 'has_email' | 'no_email'>('all');
  const [showEmailFilterDropdown, setShowEmailFilterDropdown] = useState(false);
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);
  const emailFilterButtonRef = useRef<HTMLButtonElement>(null);
  const emailFilterDropdownRef = useRef<HTMLDivElement>(null);
  const previousPreselectedRef = useRef<string[] | undefined>(undefined);
  const autoSaveTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  
  // Manual lead management
  const [manualLeads, setManualLeads] = useState<ManualLead[]>([]);
  const [showAddManualLeadModal, setShowAddManualLeadModal] = useState(false);
  const [editingManualLead, setEditingManualLead] = useState<ManualLead | null>(null);
  const [manualLeadForm, setManualLeadForm] = useState<ManualLead>({
    id: '',
    business_name: '',
    email: '',
    address: '',
    industry: '',
    contact_number: '',
    website: '',
    lead_score: undefined
  });
  const [leadScoreInput, setLeadScoreInput] = useState('');

  // Convert manual leads to Lead format for display (must be defined before useEffects)
  const manualLeadsAsLeads: Lead[] = useMemo(() => {
    if (!manualLeads || !Array.isArray(manualLeads)) return [];
    return manualLeads.map(ml => ({
      id: ml.id,
      companyName: ml.business_name || 'N/A',
      email: ml.email || 'N/A',
      phone: (ml.contact_number && String(ml.contact_number).trim()) || 'N/A',
      location: ml.address || 'N/A',
      tags: ml.industry ? [ml.industry] : [],
      website: ml.website,
      score: ml.lead_score || 0,
      starred: false,
      isManual: true,
    }));
  }, [manualLeads]);

  // Combine regular leads and manual leads (must be defined before useEffects)
  // Manual leads should appear first in the table
  const allLeadsWithManual = useMemo(() => {
    if (!allLeads || !Array.isArray(allLeads)) return manualLeadsAsLeads;
    const sortedCatalogLeads = sortLeadsWithUserAddedFirst(allLeads);
    return [...manualLeadsAsLeads, ...sortedCatalogLeads];
  }, [allLeads, manualLeadsAsLeads]);

  // Filter leads function (must be defined before useEffects that use it)
  const filterLeads = useCallback(() => {
    let filtered = allLeadsWithManual;

    // Apply search query filter
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(lead => 
        lead.companyName.toLowerCase().includes(query) ||
        lead.email.toLowerCase().includes(query) ||
        lead.phone.toLowerCase().includes(query) ||
        lead.location.toLowerCase().includes(query) ||
        (lead.tags || []).some(tag => tag.toLowerCase().includes(query)) ||
        (lead.website && lead.website.toLowerCase().includes(query)) ||
        lead.score.toString().includes(query)
      );
    }

    // Apply industry filter
    if (selectedIndustries.size > 0) {
      filtered = filtered.filter(lead => 
        (lead.tags || []).some(tag => selectedIndustries.has(tag))
      );
    }

    // Apply location filter
    if (selectedLocations.size > 0) {
      filtered = filtered.filter(lead => {
        if (!lead.location || lead.location === 'N/A') return false;
        return selectedLocations.has(lead.location.trim());
      });
    }

    // Apply score range filter
    if (scoreRange[1] < 100) {
      filtered = filtered.filter(lead => lead.score <= scoreRange[1]);
    }

    // Apply email filter
    if (emailFilter === 'has_email') {
      filtered = filtered.filter(lead => lead.email && lead.email !== 'N/A' && lead.email.trim() !== '');
    } else if (emailFilter === 'no_email') {
      filtered = filtered.filter(lead => !lead.email || lead.email === 'N/A' || lead.email.trim() === '');
    }

    setFilteredLeads(filtered);
    setCurrentPage(1); // Reset to first page when filtering
  }, [allLeadsWithManual, searchQuery, selectedIndustries, selectedLocations, scoreRange, emailFilter]);

  // Fetch leads when campaignId or preselectedLeadIds change
  useEffect(() => {
    console.log('[DEBUG] DetailCampaignScreen: fetchLeads triggered', {
      campaignId,
      preselectedLeadIds,
      preselectedCount: preselectedLeadIds?.length || 0
    });
    fetchLeads();
  }, [campaignId, preselectedLeadIds]);

  // Update internal search query when external prop changes
  useEffect(() => {
    setSearchQuery(externalSearchQuery);
  }, [externalSearchQuery]);

  // Update pagination when external props change
  useEffect(() => {
    if (externalCurrentPage !== undefined && externalCurrentPage !== currentPage) {
      setCurrentPage(externalCurrentPage);
    }
  }, [externalCurrentPage, currentPage]);

  useEffect(() => {
    if (externalItemsPerPage !== undefined && externalItemsPerPage !== itemsPerPage) {
      setItemsPerPage(externalItemsPerPage);
    }
  }, [externalItemsPerPage]);

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

  // Apply filters when they change
  useEffect(() => {
    filterLeads();
  }, [filterLeads]);

  // Update total leads count in parent
  useEffect(() => {
    const displayedLeads = filteredLeads;
    if (onTotalLeadsChange) {
      onTotalLeadsChange(displayedLeads.length);
    }
  }, [filteredLeads, allLeadsWithManual, onTotalLeadsChange]);

  // Close detail panel when search/filter hides the selected row or leaves no rows
  useEffect(() => {
    if (filteredLeads.length === 0) {
      setSelectedLead(null);
      return;
    }
    setSelectedLead((prev) =>
      prev && !filteredLeads.some((l) => l.id === prev.id) ? null : prev
    );
  }, [filteredLeads]);

  // Initialize selected leads from preselectedLeadIds
  useEffect(() => {
    // Check if preselectedLeadIds actually changed to prevent infinite loops
    const preselectedIdsString = preselectedLeadIds ? JSON.stringify(preselectedLeadIds.sort()) : 'undefined';
    const previousIdsString = previousPreselectedRef.current ? JSON.stringify(previousPreselectedRef.current.sort()) : 'undefined';
    
    if (preselectedIdsString === previousIdsString) {
      // No change, skip update
      return;
    }
    
    previousPreselectedRef.current = preselectedLeadIds;
    
    if (preselectedLeadIds && preselectedLeadIds.length > 0) {
      // Deduplicate preselected lead IDs to prevent duplicates
      const uniqueLeadIds = Array.from(new Set(preselectedLeadIds));
      console.log('[DEBUG] DetailCampaignScreen: Initializing selected leads from preselectedLeadIds:', uniqueLeadIds);
      setSelectedLeads(new Set(uniqueLeadIds));
      
      // Auto-sync preselected leads to campaign when initialized (if campaignId exists)
      if (campaignId && uniqueLeadIds.length > 0) {
        // Filter out manual lead IDs (they haven't been created in DB yet)
        const realLeadIds = uniqueLeadIds.filter(id => !id.startsWith('manual-'));
        if (realLeadIds.length > 0) {
          console.log('[DEBUG] DetailCampaignScreen: Auto-syncing preselected leads to campaign:', realLeadIds);
          // Sync leads directly to avoid dependency issues with useCallback
          apiService.syncCampaignLeads(campaignId, realLeadIds).then(syncResponse => {
            if (syncResponse.error) {
              console.error('[DEBUG] Auto-sync failed:', syncResponse.error);
            } else {
              console.log('[DEBUG] DetailCampaignScreen: Preselected leads auto-synced successfully');
            }
          }).catch(error => {
            console.error('[DEBUG] Failed to auto-sync preselected leads:', error);
          });
        }
      }
      
      // Call callbacks to update parent state so Next button is enabled
      // Use setTimeout to defer callbacks until after render to avoid React warning
      setTimeout(() => {
        if (onSelectedLeadsChange) {
          console.log('[DEBUG] DetailCampaignScreen: Calling onSelectedLeadsChange with count:', uniqueLeadIds.length);
          onSelectedLeadsChange(uniqueLeadIds.length);
        }
        if (onSelectedLeadIdsChange) {
          console.log('[DEBUG] DetailCampaignScreen: Calling onSelectedLeadIdsChange with IDs:', uniqueLeadIds);
          onSelectedLeadIdsChange(uniqueLeadIds);
        }
      }, 0);
    } else if (preselectedLeadIds !== undefined && preselectedLeadIds.length === 0) {
      // Only reset if preselectedLeadIds is explicitly an empty array (not undefined)
      console.log('[DEBUG] DetailCampaignScreen: preselectedLeadIds is empty array, resetting selection');
      setSelectedLeads(new Set());
      // Use setTimeout to avoid calling callbacks during render
      setTimeout(() => {
        if (onSelectedLeadsChange) {
          onSelectedLeadsChange(0);
        }
      }, 0);
    }
    // Note: Don't reset if preselectedLeadIds is undefined - that means it hasn't been set yet
  }, [preselectedLeadIds, campaignId]); // Added campaignId to sync when campaign is created

  const fetchLeads = async () => {
    setIsLoading(true);
    try {
      // Resolve preselection from props OR shared session storage (Lead Gen / DB / Log).
      // Props can briefly be undefined during Dashboard navigation; storage is the safety net.
      const uniqueLeadIds =
        (preselectedLeadIds && preselectedLeadIds.length > 0
          ? Array.from(new Set(preselectedLeadIds))
          : undefined) ?? readCampaignLeadSelection();

      console.log('[DEBUG] DetailCampaignScreen: fetchLeads called', {
        propCount: preselectedLeadIds?.length || 0,
        resolvedCount: uniqueLeadIds?.length || 0,
        campaignId,
      });

      const hasPreselectedLeads = !!(uniqueLeadIds && uniqueLeadIds.length > 0);

      if (hasPreselectedLeads && uniqueLeadIds) {
        console.log('[DEBUG] DetailCampaignScreen: Using preselected leads path (bulk ID fetch)');
        console.log('[DEBUG] DetailCampaignScreen: Resolving preselected leads:', uniqueLeadIds.length, 'ids');

        const mapFromLeadResponse = leadFromResponse;
        const leadMap = new Map<string, Lead>();
        const CHUNK = 200;
        let bulkGetFailed = false;

        for (let i = 0; i < uniqueLeadIds.length; i += CHUNK) {
          const chunk = uniqueLeadIds.slice(i, i + CHUNK);
          const bulkRes = await apiService.getLeadsByIds(chunk);
          if (bulkRes.error || bulkRes.data === undefined) {
            console.error('[DEBUG] DetailCampaignScreen: bulk get leads failed:', bulkRes.error);
            bulkGetFailed = true;
            break;
          }
          const rows = Array.isArray(bulkRes.data) ? bulkRes.data : [];
          for (const row of rows) {
            leadMap.set(row.id, mapFromLeadResponse(row));
          }
        }

        // Fallback when bulk-get fails or returns nothing — common if staging
        // is behind, rate-limited, or IDs were briefly out of sync.
        if (bulkGetFailed || leadMap.size === 0) {
          console.warn('[DEBUG] DetailCampaignScreen: falling back to getLeads() + filter');
          const allRes = await apiService.getLeads();
          if (allRes.error || !Array.isArray(allRes.data)) {
            toast.error('Failed to load selected leads');
            setAllLeads([]);
            setSelectedLeads(new Set());
            setTimeout(() => {
              onSelectedLeadsChange?.(0);
              onSelectedLeadIdsChange?.([]);
            }, 0);
            setIsLoading(false);
            return;
          }
          const wanted = new Set(uniqueLeadIds);
          for (const row of allRes.data) {
            if (wanted.has(row.id)) {
              leadMap.set(row.id, mapFromLeadResponse(row));
            }
          }
        }

        let uniqueLeads = uniqueLeadIds
          .map(id => leadMap.get(id))
          .filter((l): l is Lead => !!l);
        
        // If some leads failed to fetch, log a warning but DO NOT fetch all leads
        // When coming from AI Lead Gen, we should ONLY show the preselected leads that were successfully fetched
        // Never fall back to showing all leads from the database
        if (uniqueLeads.length < uniqueLeadIds.length && uniqueLeadIds.length > 0) {
          const fetchedIds = new Set(uniqueLeads.map(l => l.id));
          const missingIds = uniqueLeadIds.filter(id => !fetchedIds.has(id));
          console.warn(`[DEBUG] DetailCampaignScreen: ${missingIds.length} preselected leads failed to fetch. Only showing ${uniqueLeads.length} successfully fetched leads. Missing IDs:`, missingIds);
          
          // Note: We intentionally do NOT fetch all leads here to avoid showing leads from Lead Database
          // Leads should be saved to database before navigation from AI Lead Gen
        }
        
        console.log(`[DEBUG] DetailCampaignScreen: Setting ${uniqueLeads.length} leads to display`);
        setAllLeads(uniqueLeads);

        const resolvedIds = uniqueLeads.map(l => l.id);
        setSelectedLeads(new Set(resolvedIds));
        setTimeout(() => {
          onSelectedLeadsChange?.(resolvedIds.length);
          onSelectedLeadIdsChange?.(resolvedIds);
        }, 0);

        if (uniqueLeads.length === 0 && uniqueLeadIds.length > 0) {
          console.error(
            `[DEBUG] DetailCampaignScreen: Failed to resolve ${uniqueLeadIds.length} preselected leads against the database. Lead IDs:`,
            uniqueLeadIds
          );
          
          // Try to check if these are lead log IDs and promote them
          // First, check which lead logs contain these lead IDs
          try {
            const leadLogsResponse = await apiService.getLeadLogs();
            if (leadLogsResponse.data && Array.isArray(leadLogsResponse.data)) {
              // Try to find which log contains these leads and promote them
              for (const log of leadLogsResponse.data.slice(0, 10)) { // Check up to 10 recent logs
                try {
                  const logDetailsResponse = await apiService.getLeadLogById(log.id);
                  if (logDetailsResponse.data?.leads) {
                    const logLeadIds = logDetailsResponse.data.leads.map((l: any) => l.id);
                    const matchingIds = uniqueLeadIds.filter(id => logLeadIds.includes(id));
                    
                    if (matchingIds.length > 0) {
                      console.log(`[DEBUG] Found ${matchingIds.length} leads in log ${log.id}, promoting...`);
                      // Get the lead details from the log before promoting
                      const leadDetailsMap = new Map<string, any>();
                      logDetailsResponse.data.leads.forEach((lead: any) => {
                        if (matchingIds.includes(lead.id)) {
                          leadDetailsMap.set(lead.id, lead);
                        }
                      });
                      
                      // Promote the leads from this log
                      try {
                        const promoteRes = await apiService.promoteLeadsFromLog(log.id, matchingIds);
                        console.log(`[DEBUG] Successfully promoted ${matchingIds.length} leads from log ${log.id}`);

                        const promotedIds = (promoteRes.data?.lead_ids || []).map(String).filter(Boolean);
                        if (promotedIds.length > 0) {
                          const retryBulk = await apiService.getLeadsByIds(promotedIds);
                          const retryRows = Array.isArray(retryBulk.data) ? retryBulk.data : [];
                          const retryLeads = retryRows.map((lead: LeadResponse) => leadFromResponse(lead));
                          if (retryLeads.length > 0) {
                            uniqueLeads = [...uniqueLeads, ...retryLeads];
                            setAllLeads(uniqueLeads);
                            const newDatabaseIds = retryLeads.map(l => l.id);
                            setSelectedLeads(new Set(newDatabaseIds));
                            if (onSelectedLeadsChange) {
                              onSelectedLeadsChange(retryLeads.length);
                            }
                            if (onSelectedLeadIdsChange) {
                              onSelectedLeadIdsChange(newDatabaseIds);
                            }
                            return;
                          }
                        }

                        // Fallback: match by email/name if promote response had no lead_ids
                        await new Promise(resolve => setTimeout(resolve, 500));

                        // After promotion, leads get new database IDs, so we need to find them by email/business_name
                        // Build maps to match promoted leads
                        const emailToLeadMap = new Map<string, any>();
                        const nameToLeadMap = new Map<string, any>();

                        logDetailsResponse.data.leads.forEach((lead: any) => {
                          if (matchingIds.includes(lead.id)) {
                            if (lead.email && lead.email !== 'N/A') {
                              emailToLeadMap.set(lead.email.toLowerCase().trim(), lead);
                            }
                            if (lead.business_name) {
                              nameToLeadMap.set(lead.business_name.toLowerCase().trim(), lead);
                            }
                          }
                        });

                        // Fetch all leads and match by email/business_name to get the new database IDs
                        const allLeadsResponse = await apiService.getLeads();
                        const retryLeads: Lead[] = [];

                        if (allLeadsResponse.data && Array.isArray(allLeadsResponse.data)) {
                          const matchedLeads = allLeadsResponse.data.filter((dbLead: any) => {
                            // Match by email first (most reliable)
                            if (dbLead.email && emailToLeadMap.has(dbLead.email.toLowerCase().trim())) {
                              return true;
                            }
                            // Match by business_name if email doesn't match or is missing
                            if (dbLead.business_name && nameToLeadMap.has(dbLead.business_name.toLowerCase().trim())) {
                              return true;
                            }
                            return false;
                          });

                          retryLeads.push(...matchedLeads.map((lead: LeadResponse) => leadFromResponse(lead)));
                        }

                        if (retryLeads.length > 0) {
                          uniqueLeads = [...uniqueLeads, ...retryLeads];
                          setAllLeads(uniqueLeads);

                          // Update selected leads state with the new database IDs
                          const newDatabaseIds = retryLeads.map(l => l.id);
                          setSelectedLeads(new Set(newDatabaseIds));

                          // Update parent callbacks
                          if (onSelectedLeadsChange) {
                            onSelectedLeadsChange(retryLeads.length);
                          }
                          if (onSelectedLeadIdsChange) {
                            onSelectedLeadIdsChange(newDatabaseIds);
                          }

                          // Leads loaded successfully, no need to show toast
                          return; // Exit early if we successfully promoted and loaded leads
                        } else {
                          console.warn(`[DEBUG] Promoted ${matchingIds.length} leads but couldn't find them in database after promotion`);
                        }
                      } catch (promoteError) {
                        console.error(`[DEBUG] Failed to promote leads from log ${log.id}:`, promoteError);
                      }
                    }
                  }
                } catch (logError) {
                  // Continue to next log
                  continue;
                }
              }
            }
          } catch (promoteAttemptError) {
            console.error('[DEBUG] Error attempting to promote leads:', promoteAttemptError);
          }
          
          // If we still don't have leads after promotion attempt, show error
          if (uniqueLeads.length === 0) {
            toast.error(`Failed to load ${uniqueLeadIds.length} preselected leads. Please ensure the leads are saved to your database from Search History or AI Lead Gen before creating a campaign.`);
          }
        } else if (uniqueLeads.length < uniqueLeadIds.length) {
          const missingCount = uniqueLeadIds.length - uniqueLeads.length;
          console.warn(`[DEBUG] DetailCampaignScreen: Only fetched ${uniqueLeads.length} out of ${uniqueLeadIds.length} preselected leads. ${missingCount} leads are missing.`);
          toast.warning(`${missingCount} out of ${uniqueLeadIds.length} preselected leads could not be loaded. Showing ${uniqueLeads.length} available leads.`);
        }
        
      } else if (campaignId) {
        // Priority 2: If campaignId exists but no preselected leads, fetch ALL leads
        // (editing a draft campaign or coming directly from Campaign page)
        console.log('[DEBUG] DetailCampaignScreen: No preselected leads, fetching ALL leads (campaignId exists)');
        const response = await apiService.getLeads();
        if (response.data) {
          const mappedLeads: Lead[] = response.data.map((lead: LeadResponse) => leadFromResponse(lead));
          setAllLeads(sortLeadsWithUserAddedFirst(mappedLeads));
        }
      } else {
        // Priority 3: No preselected leads and no campaignId - fetch all leads
        console.log('[DEBUG] DetailCampaignScreen: No preselected leads and no campaignId, fetching ALL leads');
        const response = await apiService.getLeads();
        if (response.data) {
          const mappedLeads: Lead[] = response.data.map((lead: LeadResponse) => leadFromResponse(lead));
          setAllLeads(sortLeadsWithUserAddedFirst(mappedLeads));
        }
      }
    } catch (error) {
      console.error('Failed to fetch leads:', error);
      toast.error('Failed to load leads');
      setAllLeads([]);
    } finally {
      setIsLoading(false);
    }
  };

  // Debounced auto-save function for leads
  const autoSaveLeads = useCallback(async (leadIds: string[]) => {
    if (!campaignId) return;
    
    // Filter out manual lead IDs (they haven't been created in DB yet)
    const realLeadIds = leadIds.filter(id => !id.startsWith('manual-'));
    
    if (realLeadIds.length === 0) {
      console.log('[DEBUG] DetailCampaignScreen: No real lead IDs to auto-save (only manual leads)');
      return;
    }
    
    try {
      console.log('[DEBUG] DetailCampaignScreen: Auto-saving leads to backend:', realLeadIds);
      const syncResponse = await apiService.syncCampaignLeads(campaignId, realLeadIds);
      if (syncResponse.error) {
        console.error('[DEBUG] Auto-save failed:', syncResponse.error);
      } else {
        console.log('[DEBUG] DetailCampaignScreen: Leads auto-saved successfully');
      }
    } catch (error) {
      console.error('[DEBUG] Auto-save error:', error);
    }
  }, [campaignId]);

  const toggleLeadSelection = (leadId: string) => {
    const newSelected = new Set(selectedLeads);
    if (newSelected.has(leadId)) {
      newSelected.delete(leadId);
    } else {
      newSelected.add(leadId);
    }
    const selectedIdsArray = Array.from(newSelected);
    console.log('[DEBUG] DetailCampaignScreen: Toggled lead selection. New selected count:', newSelected.size, 'Selected IDs:', selectedIdsArray);
    setSelectedLeads(newSelected);
    
    // Auto-save: Sync leads to backend with debounce (500ms delay)
    if (campaignId) {
      // Clear previous timeout
      if (autoSaveTimeoutRef.current) {
        clearTimeout(autoSaveTimeoutRef.current);
      }
      // Set new timeout for auto-save
      autoSaveTimeoutRef.current = setTimeout(() => {
        autoSaveLeads(selectedIdsArray);
      }, 500);
    }
    
    if (onSelectedLeadsChange) {
      console.log('[DEBUG] DetailCampaignScreen: Calling onSelectedLeadsChange with count:', newSelected.size);
      onSelectedLeadsChange(newSelected.size);
    }
    if (onSelectedLeadIdsChange) {
      console.log('[DEBUG] DetailCampaignScreen: Calling onSelectedLeadIdsChange with IDs:', selectedIdsArray);
      onSelectedLeadIdsChange(selectedIdsArray);
    }
  };

  const toggleSelectAll = () => {
    const pageIds = paginatedLeads.map((lead) => lead.id);
    setSelectedLeads((prevSelected) => {
      const isAllPageSelected =
        pageIds.length > 0 && pageIds.every((id) => prevSelected.has(id));
      const newSelected = new Set(prevSelected);
      if (isAllPageSelected) {
        pageIds.forEach((id) => newSelected.delete(id));
      } else {
        pageIds.forEach((id) => newSelected.add(id));
      }
      const selectedIdsArray = Array.from(newSelected);
      console.log('[DEBUG] DetailCampaignScreen: Toggled select all. New selected count:', newSelected.size);

      // Auto-save: Sync leads to backend with debounce (500ms delay)
      if (campaignId) {
        if (autoSaveTimeoutRef.current) {
          clearTimeout(autoSaveTimeoutRef.current);
        }
        autoSaveTimeoutRef.current = setTimeout(() => {
          autoSaveLeads(selectedIdsArray);
        }, 500);
      }

      if (onSelectedLeadsChange) {
        console.log('[DEBUG] DetailCampaignScreen: Calling onSelectedLeadsChange with count (select all):', newSelected.size);
        onSelectedLeadsChange(newSelected.size);
      }
      if (onSelectedLeadIdsChange) {
        console.log('[DEBUG] DetailCampaignScreen: Calling onSelectedLeadIdsChange with IDs (select all):', selectedIdsArray);
        onSelectedLeadIdsChange(selectedIdsArray);
      }
      return newSelected;
    });
  };

  const toggleStar = async (leadId: string) => {
    const lead = allLeads.find(l => l.id === leadId);
    if (!lead) return;

    // Optimistically update UI
    const newStarred = !lead.starred;
    setAllLeads(prev => prev.map(l => 
      l.id === leadId ? { ...l, starred: newStarred } : l
    ));
    setFilteredLeads(prev => prev.map(l => 
      l.id === leadId ? { ...l, starred: newStarred } : l
    ));

    // Call API to persist the change
    try {
      await apiService.toggleLeadStar(leadId);
    } catch (error) {
      console.error('Failed to toggle star:', error);
      // Revert on error
      setAllLeads(prev => prev.map(l => 
        l.id === leadId ? { ...l, starred: !newStarred } : l
      ));
      setFilteredLeads(prev => prev.map(l => 
        l.id === leadId ? { ...l, starred: !newStarred } : l
      ));
    }
  };

  // Manual lead management functions
  const openAddManualLeadModal = useCallback(() => {
    setEditingManualLead(null);
    setManualLeadForm({
      id: '',
      business_name: '',
      email: '',
      address: '',
      industry: '',
      contact_number: '',
      website: '',
      lead_score: undefined
    });
    setLeadScoreInput('');
    setShowAddManualLeadModal(true);
  }, []);

  // Expose the open modal function to parent component
  useEffect(() => {
    if (onAddManualLeadRef) {
      onAddManualLeadRef(openAddManualLeadModal);
    }
  }, [onAddManualLeadRef, openAddManualLeadModal]);

  const openEditManualLeadModal = (lead: ManualLead) => {
    setEditingManualLead(lead);
    setManualLeadForm({ ...lead });
    setLeadScoreInput(lead.lead_score != null ? String(lead.lead_score) : '');
    setShowAddManualLeadModal(true);
  };

  const getLeadScoreValidationError = (raw: string): string | null => {
    const trimmed = raw.trim();
    if (trimmed === '') return null;
    if (!/^\d+$/.test(trimmed)) {
      return 'Lead score must be a whole number between 0 and 100';
    }
    const score = parseInt(trimmed, 10);
    if (score < 0 || score > 100) {
      return 'Lead score must be between 0 and 100';
    }
    return null;
  };

  const parseLeadScoreForSave = (raw: string): number => {
    const trimmed = raw.trim();
    return trimmed === '' ? 0 : parseInt(trimmed, 10);
  };

  const leadScoreError = getLeadScoreValidationError(leadScoreInput);

  const handleSaveManualLead = async () => {
    // Validate email is required
    if (!manualLeadForm.email || !manualLeadForm.email.trim()) {
      toast.error('Email is required');
      return;
    }

    // Validate email format
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(manualLeadForm.email.trim())) {
      toast.error('Please enter a valid email address');
      return;
    }

    if (!manualLeadForm.business_name || !manualLeadForm.business_name.trim()) {
      toast.error('Company Name is required');
      return;
    }

    if (!manualLeadForm.address || !manualLeadForm.address.trim()) {
      toast.error('Address is required');
      return;
    }

    if (!manualLeadForm.industry || !manualLeadForm.industry.trim()) {
      toast.error('Industry is required');
      return;
    }

    if (leadScoreError) {
      toast.error(leadScoreError);
      return;
    }
    const leadScore = parseLeadScoreForSave(leadScoreInput);

    try {
      if (editingManualLead) {
        // Check if this is a real database lead (not a temporary manual- ID)
        if (editingManualLead.id.startsWith('manual-')) {
          // This is a temporary lead that hasn't been saved yet - create it
          const createResponse = await apiService.createLead({
            business_name: manualLeadForm.business_name || 'Manual Lead',
            email: manualLeadForm.email,
            address: manualLeadForm.address,
            industry: manualLeadForm.industry,
            contact_number: manualLeadForm.contact_number,
            website: manualLeadForm.website,
            lead_score: leadScore
          });

          if (createResponse.error) {
            toast.error(`Failed to create lead: ${createResponse.error}`);
            return;
          }

          const realLeadId = createResponse.data?.id;
          if (!realLeadId) {
            toast.error('Failed to create lead: No ID returned');
            return;
          }

          // Replace temporary ID with real database ID
          const updatedLead: ManualLead = { ...manualLeadForm, id: realLeadId, lead_score: leadScore };
          setManualLeads(prev => prev.map(ml => 
            ml.id === editingManualLead.id ? updatedLead : ml
          ));

          // Update selectedLeads to use real ID
          setSelectedLeads(prev => {
            const newSelected = new Set(prev);
            newSelected.delete(editingManualLead.id);
            newSelected.add(realLeadId);
            
            // Auto-sync to campaign if campaignId exists
            if (campaignId) {
              const allSelectedIds = Array.from(newSelected);
              apiService.syncCampaignLeads(campaignId, allSelectedIds).then(syncResponse => {
                if (syncResponse.error) {
                  console.error('[DEBUG] Auto-sync failed:', syncResponse.error);
                } else {
                  console.log('[DEBUG] Lead auto-synced to campaign');
                }
              }).catch(error => {
                console.error('[DEBUG] Auto-sync error:', error);
              });
            }
            
            setTimeout(() => {
              if (onSelectedLeadIdsChange) {
                onSelectedLeadIdsChange(Array.from(newSelected));
              }
            }, 0);
            return newSelected;
          });

          toast.success('Lead created and saved');
        } else {
          // This is a real database lead - update it
          const updateResponse = await apiService.updateLead(editingManualLead.id, {
            business_name: manualLeadForm.business_name,
            email: manualLeadForm.email,
            address: manualLeadForm.address,
            industry: manualLeadForm.industry,
            contact_number: manualLeadForm.contact_number,
            website: manualLeadForm.website,
            lead_score: leadScore
          });

          if (updateResponse.error) {
            toast.error(`Failed to update lead: ${updateResponse.error}`);
            return;
          }

          // Update local state
          setManualLeads(prev => prev.map(ml => 
            ml.id === editingManualLead.id ? { ...manualLeadForm, id: editingManualLead.id, lead_score: leadScore } : ml
          ));
          
          // Auto-sync to campaign if lead is selected and campaignId exists
          if (campaignId && selectedLeads.has(editingManualLead.id)) {
            const allSelectedIds = Array.from(selectedLeads);
            apiService.syncCampaignLeads(campaignId, allSelectedIds).then(syncResponse => {
              if (syncResponse.error) {
                console.error('[DEBUG] Auto-sync failed:', syncResponse.error);
              } else {
                console.log('[DEBUG] Lead auto-synced to campaign');
              }
            }).catch(error => {
              console.error('[DEBUG] Auto-sync error:', error);
            });
          }
          
          toast.success('Lead updated');
        }
      } else {
        // Add new manual lead - create it immediately in the database
        const createResponse = await apiService.createLead({
          business_name: manualLeadForm.business_name || 'Manual Lead',
          email: manualLeadForm.email,
          address: manualLeadForm.address,
          industry: manualLeadForm.industry,
          contact_number: manualLeadForm.contact_number,
          website: manualLeadForm.website,
          lead_score: leadScore
        });

        if (createResponse.error) {
          toast.error(`Failed to create lead: ${createResponse.error}`);
          return;
        }

        const realLeadId = createResponse.data?.id;
        if (!realLeadId) {
          toast.error('Failed to create lead: No ID returned');
          return;
        }

        // Use the real database ID
        const newManualLead: ManualLead = { ...manualLeadForm, id: realLeadId, lead_score: leadScore };
        setManualLeads(prev => [...prev, newManualLead]);
        
        // Auto-select the newly added lead
        setSelectedLeads(prev => {
          const newSelected = new Set([...prev, realLeadId]);
          
          // Auto-sync to campaign if campaignId exists
          if (campaignId) {
            const allSelectedIds = Array.from(newSelected);
            apiService.syncCampaignLeads(campaignId, allSelectedIds).then(syncResponse => {
              if (syncResponse.error) {
                console.error('[DEBUG] Auto-sync failed:', syncResponse.error);
              } else {
                console.log('[DEBUG] Lead auto-synced to campaign');
              }
            }).catch(error => {
              console.error('[DEBUG] Auto-sync error:', error);
            });
          }
          
          // Use setTimeout to avoid calling callbacks during render
          setTimeout(() => {
            if (onSelectedLeadsChange) {
              onSelectedLeadsChange(newSelected.size);
            }
            if (onSelectedLeadIdsChange) {
              onSelectedLeadIdsChange(Array.from(newSelected));
            }
          }, 0);
          return newSelected;
        });
        
        toast.success('Lead created and saved');
      }
      
      setShowAddManualLeadModal(false);
      // Reset form
      setManualLeadForm({
        id: '',
        business_name: '',
        email: '',
        address: '',
        industry: '',
        contact_number: '',
        website: '',
        lead_score: undefined
      });
      setLeadScoreInput('');
      setEditingManualLead(null);
    } catch (error: any) {
      console.error('Error saving manual lead:', error);
      toast.error(error?.message || 'Failed to save lead');
    }
  };

  const handleDeleteManualLead = async (leadId: string) => {
    // Check if this is a real database lead (not a temporary manual- ID)
    if (!leadId.startsWith('manual-')) {
      // This is a real database lead - delete it from the database
      try {
        const deleteResponse = await apiService.deleteLead(leadId);
        if (deleteResponse.error) {
          toast.error(`Failed to delete lead: ${deleteResponse.error}`);
          return;
        }
      } catch (error: any) {
        console.error('Error deleting lead:', error);
        toast.error(error?.message || 'Failed to delete lead');
        return;
      }
    }

    // Remove from local state
    setManualLeads(prev => prev.filter(ml => ml.id !== leadId));
    setSelectedLeads(prev => {
      const newSelected = new Set(prev);
      newSelected.delete(leadId);
      const newSize = newSelected.size;
      setTimeout(() => {
        if (onSelectedLeadsChange) {
          onSelectedLeadsChange(newSize);
        }
        if (onSelectedLeadIdsChange) {
          onSelectedLeadIdsChange(Array.from(newSelected));
        }
      }, 0);
      return newSelected;
    });
    toast.success('Lead deleted');
  };

  const handleNext = async () => {
    if (selectedLeads.size === 0) {
      toast.error('Please select at least one lead');
      return;
    }

    try {
      // Manual leads are now saved immediately to the database when added,
      // so we can directly use the selected lead IDs (they're all real database IDs now)
      // Filter out any remaining temporary manual- IDs (shouldn't happen, but safety check)
      const selectedLeadIdsArray = Array.from(selectedLeads);
      const validLeadIds = selectedLeadIdsArray.filter(id => !id.startsWith('manual-'));
      
      if (validLeadIds.length === 0) {
        toast.error('No valid leads selected. Please ensure all leads are properly saved.');
        return;
      }

      console.log('[DEBUG] Syncing leads to campaign:', validLeadIds);

      // Sync selected leads with campaign
      console.log(`[DEBUG] Syncing ${validLeadIds.length} leads to campaign ${campaignId}:`, validLeadIds);
    
      const response = await apiService.syncCampaignLeads(campaignId, validLeadIds);
      console.log('[DEBUG] Sync response:', response);
      
      if (response.error) {
        console.error('Sync failed with error:', response.error);
        toast.error(response.error || 'Failed to sync leads with campaign');
        return;
      }
      
      console.log('[DEBUG] Leads synced successfully:', response.data);
      const finalLeadCount = validLeadIds.length;
      
      // Update parent with the actual synced lead count
      if (onSelectedLeadsChange) {
        onSelectedLeadsChange(finalLeadCount);
      }
      
      // Show completion message here to ensure it displays before step change
      toast.success('Campaign lead selection complete', {
        id: 'campaign-lead-selection-complete',
        duration: 3000,
      });
      
      // Clear sessionStorage after syncing leads (if it exists)
      sessionStorage.removeItem('campaignLeadIds');
      sessionStorage.removeItem('campaignLogId');
      
      // Call onNext after a small delay to ensure toast is visible
      console.log('[DEBUG] DetailCampaignScreen: Calling onNext callback with', validLeadIds.length, 'leads');
      if (onNext) {
        console.log('[DEBUG] DetailCampaignScreen: onNext callback exists, calling it');
        // Use setTimeout to ensure toast renders first
        setTimeout(() => {
          onNext(validLeadIds);
          console.log('[DEBUG] DetailCampaignScreen: onNext callback called');
        }, 100);
      } else {
        console.error('[DEBUG] DetailCampaignScreen: onNext callback is NOT defined!');
      }
    } catch (error: any) {
      console.error('Failed to sync leads:', error);
      toast.error(error?.message || 'Failed to sync leads with campaign');
    }
  };

  // Handle page changes
  const handlePageChange = (newPage: number) => {
    if (onPageChange) {
      onPageChange(newPage);
    } else {
      setCurrentPage(newPage);
    }
  };

  // Handle items per page changes
  const handleItemsPerPageChange = (newItemsPerPage: number) => {
    const numValue = Number(newItemsPerPage);
    if (isNaN(numValue) || numValue <= 0) {
      console.error('Invalid items per page value:', newItemsPerPage);
      return;
    }
    setItemsPerPage(numValue);
    setCurrentPage(1);
    if (onItemsPerPageChange) {
      onItemsPerPageChange(numValue);
    }
    if (onPageChange) {
      onPageChange(1);
    }
  };

  const displayedLeads = filteredLeads;
  const startIndex = (currentPage - 1) * itemsPerPage;
  const endIndex = startIndex + itemsPerPage;
  const paginatedLeads = displayedLeads.slice(startIndex, endIndex);
  const totalPages = Math.ceil(displayedLeads.length / itemsPerPage);
  const allPageSelected =
    paginatedLeads.length > 0 && paginatedLeads.every((lead) => selectedLeads.has(lead.id));

  return (
    <div className="detail-campaign-screen">
      {/* Filter Sidebar */}
      {showFilters && (
        <>
          {/* Overlay */}
          <div
            onClick={() => onToggleFilters && onToggleFilters(false)}
            className="lead-database-filter-overlay"
          />
          {/* Filter Sidebar - reuse Lead Database design */}
          <div className="lead-database-filter-sidebar lead-database-filter-sidebar-slide-in lead-database-filter-panel-styles">
            {/* X close - outside inner frame */}
            <button
              type="button"
              aria-label="Close"
              onClick={() => onToggleFilters && onToggleFilters(false)}
              className="lead-database-filter-close lead-database-filter-close-outside"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 4L4 12M4 4l8 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </button>
            {/* Inner frame with shared header + content styles */}
            <div className="lead-database-filter-inner-frame">
              {/* Header: Filters + slider icon (same as Lead Database) */}
              <div className="lead-database-filter-header">
                <div className="lead-database-filter-header-left">
                  <SlidersHorizontal size={18} style={{ color: '#374151', flexShrink: 0 }} />
                  <span className="lead-database-filter-title">Filters</span>
                </div>
              </div>

              {/* Filter Content - reuse Lead Database layout */}
              <div className="lead-database-filter-content">
                {/* Industry Section (Lead Database style) */}
                {(() => {
                  const allIndustries = new Set<string>();
                  allLeadsWithManual.forEach(lead => {
                    (lead.tags || []).forEach(tag => {
                      if (tag && tag !== 'N/A') {
                        allIndustries.add(tag);
                      }
                    });
                  });
                  const uniqueIndustries = Array.from(allIndustries).sort();
                  const filteredIndustries = industryInput.trim()
                    ? uniqueIndustries.filter(ind => ind.toLowerCase().includes(industryInput.toLowerCase()))
                    : uniqueIndustries;

                  return (
                    <div className="lead-database-filter-section">
                      <h3 className="lead-database-filter-label">Industry</h3>
                      <div className="lead-database-filter-chip-wrap">
                        <div style={{ position: 'relative' }} className="lead-database-filter-input-dropdown-wrap">
                          <div
                            className="lead-database-filter-chip-container"
                            onClick={() => {
                              setShowIndustrySuggestions(true);
                              document.getElementById('campaign-industry-filter-input')?.focus();
                            }}
                          >
                            <input
                              id="campaign-industry-filter-input"
                              type="text"
                              value={industryInput}
                              onChange={(e) => {
                                setIndustryInput(e.target.value);
                                setShowIndustrySuggestions(true);
                              }}
                              onFocus={() => setShowIndustrySuggestions(true)}
                              onBlur={(e) => {
                                const relatedTarget = e.relatedTarget as HTMLElement;
                                if (!relatedTarget || !relatedTarget.closest('[data-industry-suggestions]')) {
                                  setTimeout(() => setShowIndustrySuggestions(false), 200);
                                }
                              }}
                              placeholder="Enter Industry..."
                              className="lead-database-filter-chip-input focus-visible:ring-0 focus-visible:ring-transparent focus-visible:border-none focus:outline-none"
                            />
                            <ChevronDown size={16} className="lead-database-filter-input-chevron" />
                          </div>
                          {showIndustrySuggestions && (
                            <div
                              data-industry-suggestions
                              onMouseDown={(e) => e.preventDefault()}
                              className="lead-database-filter-dropdown"
                            >
                              {filteredIndustries.length > 0 ? filteredIndustries.map((industry) => (
                                <div
                                  key={industry}
                                  onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); }}
                                  onClick={(e) => {
                                    e.preventDefault();
                                    e.stopPropagation();
                                    const newSelected = new Set(selectedIndustries);
                                    const trimmedIndustry = industry.trim();
                                    if (newSelected.has(trimmedIndustry)) {
                                      newSelected.delete(trimmedIndustry);
                                    } else {
                                      newSelected.add(trimmedIndustry);
                                    }
                                    setSelectedIndustries(newSelected);
                                    setIndustryInput('');
                                    setShowIndustrySuggestions(false);
                                  }}
                                  className="lead-database-filter-dropdown-item"
                                >
                                  <div className={`lead-database-table-checkbox-box ${selectedIndustries.has(industry) ? 'checked' : ''}`}>
                                    {selectedIndustries.has(industry) && <Check className="lead-database-table-checkbox-check" />}
                                  </div>
                                  <span>{industry}</span>
                                </div>
                              )) : (
                                <div className="lead-database-filter-dropdown-empty">
                                  No such industry found
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                        {selectedIndustries.size > 0 && (
                          <div className="lead-database-filter-chip-row">
                            {Array.from(selectedIndustries).slice(0, 3).map((industry) => (
                              <span key={industry} className="lead-database-filter-chip">
                                <span className="lead-database-filter-chip-text">{industry}</span>
                                <X
                                  size={12}
                                  className="lead-database-filter-chip-remove"
                                  onMouseDown={(e) => {
                                    e.preventDefault();
                                    e.stopPropagation();
                                    const next = new Set(selectedIndustries);
                                    next.delete(industry);
                                    setSelectedIndustries(next);
                                  }}
                                />
                              </span>
                            ))}
                            {selectedIndustries.size > 3 && (
                              <span className="lead-database-filter-chip-more">
                                +{selectedIndustries.size - 3} more
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })()}

                {/* Location Section (Lead Database style) */}
                {(() => {
                  const allLocations = new Set<string>();
                  allLeadsWithManual.forEach(lead => {
                    if (lead.location && lead.location !== 'N/A') {
                      allLocations.add(lead.location.trim());
                    }
                  });
                  const uniqueLocations = Array.from(allLocations).sort();
                  const filteredLocations = locationInput.trim()
                    ? uniqueLocations.filter(loc => loc.toLowerCase().includes(locationInput.toLowerCase()))
                    : uniqueLocations;

                  return (
                    <div className="lead-database-filter-section">
                      <h3 className="lead-database-filter-label">Location</h3>
                      <div className="lead-database-filter-chip-wrap">
                        <div style={{ position: 'relative' }} className="lead-database-filter-input-dropdown-wrap">
                          <div
                            className="lead-database-filter-chip-container"
                            onClick={() => {
                              setShowLocationSuggestions(true);
                              document.getElementById('campaign-location-filter-input')?.focus();
                            }}
                          >
                            <input
                              id="campaign-location-filter-input"
                              type="text"
                              value={locationInput}
                              onChange={(e) => {
                                setLocationInput(e.target.value);
                                setShowLocationSuggestions(true);
                              }}
                              onFocus={() => setShowLocationSuggestions(true)}
                              onBlur={(e) => {
                                const relatedTarget = e.relatedTarget as HTMLElement;
                                if (!relatedTarget || !relatedTarget.closest('[data-location-suggestions]')) {
                                  setTimeout(() => setShowLocationSuggestions(false), 200);
                                }
                              }}
                              placeholder="Enter Location..."
                              className="lead-database-filter-chip-input focus-visible:ring-0 focus-visible:ring-transparent focus-visible:border-none focus:outline-none"
                            />
                            <ChevronDown size={16} className="lead-database-filter-input-chevron" />
                          </div>
                          {showLocationSuggestions && (
                            <div
                              data-location-suggestions
                              onMouseDown={(e) => e.preventDefault()}
                              className="lead-database-filter-dropdown"
                            >
                              {filteredLocations.length > 0 ? filteredLocations.map((location) => (
                                <div
                                  key={location}
                                  onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); }}
                                  onClick={(e) => {
                                    e.preventDefault();
                                    e.stopPropagation();
                                    const newSelected = new Set(selectedLocations);
                                    const trimmedLocation = location.trim();
                                    if (newSelected.has(trimmedLocation)) {
                                      newSelected.delete(trimmedLocation);
                                    } else {
                                      newSelected.add(trimmedLocation);
                                    }
                                    setSelectedLocations(newSelected);
                                    setLocationInput('');
                                    setShowLocationSuggestions(false);
                                  }}
                                  className="lead-database-filter-dropdown-item"
                                >
                                  <div className={`lead-database-table-checkbox-box ${selectedLocations.has(location) ? 'checked' : ''}`}>
                                    {selectedLocations.has(location) && <Check className="lead-database-table-checkbox-check" />}
                                  </div>
                                  <span>{location}</span>
                                </div>
                              )) : (
                                <div className="lead-database-filter-dropdown-empty">
                                  No such location found
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                        {selectedLocations.size > 0 && (
                          <div className="lead-database-filter-chip-row">
                            {Array.from(selectedLocations).slice(0, 3).map((location) => (
                              <span key={location} className="lead-database-filter-chip">
                                <span className="lead-database-filter-chip-text">{location}</span>
                                <X
                                  size={12}
                                  className="lead-database-filter-chip-remove"
                                  onMouseDown={(e) => {
                                    e.preventDefault();
                                    e.stopPropagation();
                                    const next = new Set(selectedLocations);
                                    next.delete(location);
                                    setSelectedLocations(next);
                                  }}
                                />
                              </span>
                            ))}
                            {selectedLocations.size > 3 && (
                              <span className="lead-database-filter-chip-more">
                                +{selectedLocations.size - 3} more
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })()}

                {/* Lead Score Range Section – Lead Database style */}
                <div className="lead-database-filter-section">
                  <h3 className="lead-database-filter-label">Lead Score Range</h3>
                  <div className="lead-database-filter-slider-wrap">
                    <input
                      type="range"
                      className="lead-database-filter-range"
                      min="0"
                      max="100"
                      value={scoreRange[1]}
                      onChange={(e) => setScoreRange([scoreRange[0], parseInt(e.target.value)])}
                      style={{
                        width: '100%',
                        height: '14px',
                        borderRadius: '999px',
                        background: `linear-gradient(to right, #6B21A8 0%, rgba(212, 88, 255, 0.7) ${scoreRange[1]}%, #D1D1D6 ${scoreRange[1]}%, #D1D1D6 100%)`,
                        outline: 'none',
                        cursor: 'pointer',
                        WebkitAppearance: 'none',
                        appearance: 'none',
                        position: 'relative',
                        zIndex: 0
                      }}
                    />
                    <style>{`
                      input[type="range"]::-webkit-slider-runnable-track {
                        height: 14px;
                        border-radius: 999px;
                        background: linear-gradient(to right, #6B21A8 0%, rgba(212, 88, 255, 0.7) ${scoreRange[1]}%, #D1D1D6 ${scoreRange[1]}%, #D1D1D6 100%);
                      }
                      input[type="range"]::-moz-range-track {
                        height: 14px;
                        border-radius: 999px;
                        background: linear-gradient(to right, #6B21A8 0%, rgba(212, 88, 255, 0.7) ${scoreRange[1]}%, #D1D1D6 ${scoreRange[1]}%, #D1D1D6 100%);
                      }
                      input[type="range"]::-webkit-slider-thumb {
                        -webkit-appearance: none;
                        appearance: none;
                        width: 20px;
                        height: 20px;
                        border-radius: 50%;
                        background: url('/Slider.svg') no-repeat center;
                        background-size: contain;
                        border: none;
                        cursor: pointer;
                        margin-top: -3px;
                        position: relative;
                        zIndex: 10;
                        opacity: 1;
                        visibility: visible;
                      }
                      input[type="range"]::-moz-range-thumb {
                        width: 20px;
                        height: 20px;
                        border-radius: 50%;
                        background: url('/Slider.svg') no-repeat center;
                        background-size: contain;
                        border: none;
                        cursor: pointer;
                        position: relative;
                        zIndex: 10;
                        opacity: 1;
                        visibility: visible;
                      }
                    `}</style>
                  </div>
                  <div className="lead-database-filter-score-labels">
                    <span>0%</span>
                    <span>{scoreRange[1]}%</span>
                  </div>
                </div>

                {/* Clear Filters Button */}
                <button
                  type="button"
                  onClick={() => {
                    setSelectedIndustries(new Set());
                    setSelectedLocations(new Set());
                    setScoreRange([0, 100]);
                    setLocationInput('');
                    setIndustryInput('');
                  }}
                  className="lead-database-filter-clear-btn"
                >
                  Clear Filters
                </button>
              </div>
            </div>
          </div>
        </>
      )}

      {/* Main Content */}
      <div className="detail-campaign-content">
        <div className="detail-campaign-card">
          {/* Table header always when not loading; empty state in body when no rows or search matches nothing. */}
          {isLoading ? (
            <div className="loading-state">Loading leads...</div>
          ) : (
            <div className="lead-database-table-wrapper lead-database-table-wrapper-styles dashboard-data-table dashboard-pagination-scroll-area">
              <Table className="lead-database-table lead-database-table-styles">
                <TableHeader className="lead-database-table-header-styles">
                  <TableRow>
                    <TableHead className="lead-database-table-head-checkbox-styles">
                      <button
                        type="button"
                        onClick={toggleSelectAll}
                        className="lead-database-table-checkbox-button"
                      >
                        <div className={`lead-database-table-checkbox-box ${allPageSelected ? 'checked' : ''}`}>
                          {allPageSelected && (
                            <Check className="lead-database-table-checkbox-check" />
                          )}
                        </div>
                      </button>
                    </TableHead>
                    <TableHead className="lead-database-table-head-base-styles lead-database-table-head-company">Company Name</TableHead>
                    <TableHead className="lead-database-table-head-base-styles lead-database-table-head-email">
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
                              color: emailFilter !== 'all' ? '#6B21A8' : '#6B7280'
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
                    <TableHead className="lead-database-table-head-base-styles lead-database-table-head-location">Location</TableHead>
                    <TableHead className="lead-database-table-head-base-styles lead-database-table-head-website">Website</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {allLeadsWithManual.length === 0 || displayedLeads.length === 0 ? (
                    <TableRow className="detail-campaign-empty-results-row">
                      <TableCell colSpan={5} className="lead-database-table-filter-empty-cell detail-campaign-table-empty-cell">
                        <div className="empty-state empty-state--in-table">
                          <EmptyState
                            iconPath="/finger-cricle.svg"
                            title="No leads found."
                            description="Generate new leads to complete your campaign."
                          >
                            {onGenerateNewLeads ? (
                              <div className="detail-campaign-empty-cta-wrap">
                                <button
                                  type="button"
                                  onClick={onGenerateNewLeads}
                                  className="evecta-secondary-btn dashboard-profile-generate-leads-btn detail-campaign-empty-state-cta"
                                >
                                  <Plus className="dashboard-profile-generate-leads-icon" aria-hidden size={18} />
                                  <span className="detail-campaign-empty-state-cta-label">Generate New Leads</span>
                                </button>
                              </div>
                            ) : null}
                          </EmptyState>
                        </div>
                      </TableCell>
                    </TableRow>
                  ) : (
                    paginatedLeads.map((lead) => (
                    <TableRow 
                      key={lead.id}
                      onClick={(e) => {
                        // Don't select row if clicking on checkbox or checkbox cell
                        if ((e.target as HTMLElement).closest('.lead-database-table-checkbox-button') || 
                            (e.target as HTMLElement).closest('.lead-database-table-cell-checkbox-styles')) {
                          return;
                        }
                        setSelectedLead(lead);
                      }}
                      className={selectedLead?.id === lead.id ? 'lead-database-table-row-selected' : 'lead-database-table-row-unselected'}
                    >
                      <TableCell className="lead-database-table-cell-checkbox-styles">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            e.preventDefault();
                            toggleLeadSelection(lead.id);
                            // Explicitly prevent row selection
                            setSelectedLead(null);
                          }}
                          onMouseDown={(e) => {
                            e.stopPropagation();
                          }}
                          className="lead-database-table-checkbox-button"
                        >
                          <div className={`lead-database-table-checkbox-box ${selectedLeads.has(lead.id) ? 'checked' : ''}`}>
                            {selectedLeads.has(lead.id) && (
                              <Check className="lead-database-table-checkbox-check" />
                            )}
                          </div>
                        </button>
                      </TableCell>
                      <TableCell className="lead-database-table-cell-base lead-database-table-cell-company" title={lead.companyName}>
                        <a 
                          href="#"
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedLead(lead);
                          }}
                          className="lead-database-table-cell-link dashboard-table-cell-text-clip"
                          title={lead.companyName}
                        >
                          {lead.companyName}
                        </a>
                      </TableCell>
                      <TableCell className="lead-database-table-cell-base lead-database-table-cell-email" title={lead.email}>
                        <span className="lead-database-table-cell-span-center dashboard-table-cell-text-clip">
                          {lead.email 
                            ? (lead.email.length > 15 ? lead.email.substring(0, 15) + '...' : lead.email)
                            : 'No email found'}
                        </span>
                      </TableCell>
                      <TableCell className="lead-database-table-cell-base lead-database-table-cell-location" title={lead.location}>
                        <span className="lead-database-table-cell-span-center dashboard-table-cell-text-clip">
                          {lead.location 
                            ? (lead.location.length > 30 ? lead.location.substring(0, 20) + '...' : lead.location)
                            : 'N/A'}
                        </span>
                      </TableCell>
                      <TableCell className="lead-database-table-cell-base lead-database-table-cell-website" title={lead.website || 'N/A'}>
                        {lead.website && lead.website !== 'N/A' ? (
                          <a 
                            href={lead.website.startsWith('http') ? lead.website : `https://${lead.website}`} 
                            target="_blank" 
                            rel="noopener noreferrer"
                            className="lead-database-table-cell-website-link dashboard-table-cell-text-clip"
                            onClick={(e) => e.stopPropagation()}
                          >
                            {lead.website.length > 30 ? lead.website.substring(0, 30) + '...' : lead.website}
                          </a>
                        ) : (
                          <span className="lead-database-table-cell-span-center">N/A</span>
                        )}
                      </TableCell>
                    </TableRow>
                  ))
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </div>
      </div>

      {/* Lead Detail Panel - when a lead row is clicked */}
      {selectedLead && (
        <LeadDetailPanel
          lead={{
            id: selectedLead.id,
            companyName: selectedLead.companyName,
            email: selectedLead.email,
            contact_number: selectedLead.phone,
            location: selectedLead.location,
            tags: selectedLead.tags,
            score: selectedLead.score,
            outreach_status: (selectedLead as any).outreach_status,
            last_contacted: (selectedLead as any).last_contacted,
            campaign_status: (selectedLead as any).campaign_status,
          }}
          onClose={() => setSelectedLead(null)}
        />
      )}

      {/* Add/Edit Manual Lead Modal */}
      {showAddManualLeadModal && (
        <div
          className="evecta-dialog-overlay detail-campaign-modal-overlay"
          onClick={() => setShowAddManualLeadModal(false)}
        >
          <div
            className="detail-campaign-modal-container"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="detail-campaign-modal-header evecta-dialog-header">
              <h2 className="evecta-dialog-title detail-campaign-modal-title">
                {editingManualLead ? 'Edit Lead' : 'Add Lead Manually'}
              </h2>
              <button
                type="button"
                onClick={() => setShowAddManualLeadModal(false)}
                className="evecta-dialog-close detail-campaign-modal-close-button"
                aria-label="Close"
              >
                <X className="evecta-dialog-close-x" aria-hidden strokeWidth={2} size={18} />
              </button>
            </div>

            <div className="detail-campaign-modal-form">
              <div>
                <label className="detail-campaign-modal-label">
                  Email <span className="detail-campaign-modal-label-required">*</span>
                </label>
                <Input
                  type="email"
                  value={manualLeadForm.email}
                  onChange={(e) => setManualLeadForm({ ...manualLeadForm, email: e.target.value })}
                  placeholder="example@email.com"
                  className="detail-campaign-modal-input"
                />
              </div>

              <div>
                <label className="detail-campaign-modal-label">
                  Company Name <span className="detail-campaign-modal-label-required">*</span>
                </label>
                <Input
                  type="text"
                  value={manualLeadForm.business_name}
                  onChange={(e) => setManualLeadForm({ ...manualLeadForm, business_name: e.target.value })}
                  placeholder="Company name"
                  className="detail-campaign-modal-input"
                />
              </div>

              <div>
                <label className="detail-campaign-modal-label">
                  Address <span className="detail-campaign-modal-label-required">*</span>
                </label>
                <Input
                  type="text"
                  value={manualLeadForm.address || ''}
                  onChange={(e) => setManualLeadForm({ ...manualLeadForm, address: e.target.value })}
                  placeholder="Address"
                  className="detail-campaign-modal-input"
                />
              </div>

              <div>
                <label className="detail-campaign-modal-label">
                  Industry <span className="detail-campaign-modal-label-required">*</span>
                </label>
                <Input
                  type="text"
                  value={manualLeadForm.industry || ''}
                  onChange={(e) => setManualLeadForm({ ...manualLeadForm, industry: e.target.value })}
                  placeholder="Industry"
                  className="detail-campaign-modal-input"
                />
              </div>

              <div>
                <label className="detail-campaign-modal-label">
                  Contact Number
                </label>
                <Input
                  type="text"
                  value={manualLeadForm.contact_number || ''}
                  onChange={(e) => setManualLeadForm({ ...manualLeadForm, contact_number: e.target.value })}
                  placeholder="Contact number"
                  className="detail-campaign-modal-input"
                />
              </div>

              <div>
                <label className="detail-campaign-modal-label">
                  Website
                </label>
                <Input
                  type="text"
                  value={manualLeadForm.website || ''}
                  onChange={(e) => setManualLeadForm({ ...manualLeadForm, website: e.target.value })}
                  placeholder="Website URL"
                  className="detail-campaign-modal-input"
                />
              </div>

              <div>
                <label className="detail-campaign-modal-label">
                  Lead Score
                </label>
                <Input
                  type="text"
                  inputMode="numeric"
                  value={leadScoreInput}
                  onChange={(e) => setLeadScoreInput(e.target.value.replace(/[^\d]/g, ''))}
                  placeholder="0-100"
                  className={`detail-campaign-modal-input${leadScoreError ? ' detail-campaign-modal-input--error' : ''}`}
                />
                {leadScoreError && (
                  <p className="detail-campaign-modal-field-error">
                    {leadScoreError}
                  </p>
                )}
              </div>
            </div>

            <div className="detail-campaign-modal-actions evecta-dialog-actions">
              <button
                onClick={() => setShowAddManualLeadModal(false)}
                className="evecta-dialog-btn evecta-dialog-btn--secondary detail-campaign-modal-action-button create-campaign-back-btn"
                type="button"
              >
                Back
              </button>
              <button
                onClick={handleSaveManualLead}
                className="evecta-dialog-btn evecta-dialog-btn--primary detail-campaign-modal-action-button create-campaign-next-btn"
                type="button"
              >
                {editingManualLead ? 'Update Lead' : 'Add Lead'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

