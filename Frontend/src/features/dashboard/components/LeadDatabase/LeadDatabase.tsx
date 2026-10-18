import { useState, useEffect, forwardRef, useImperativeHandle, useRef, useMemo } from 'react';
import { Star, Filter, ChevronLeft, ChevronRight, SlidersHorizontal, ChevronDown, Check, MapPin, Building2, Trash2, Bookmark, Search, X, Upload } from 'lucide-react';
import { DashboardPagination } from '../ui/DashboardPagination';
import { EmptyState } from '../ui/EmptyState';
import { LeadDetailPanel } from '../ui/LeadDetailPanel';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../ui/tabs';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../ui/table';
import { apiService, LeadResponse } from '../../../../shared/services/api';
import { sortLeadsWithUserAddedFirst } from '../../../../shared/utils/leadSort';
import { persistCampaignLeadSelection, clearCampaignLeadSelection } from '../../../../shared/utils/campaignLeadSelection';
import { toast } from 'sonner';
import { useMobileGap } from '../ui/use-mobile-gap';
import '../LeadLog/LeadLog.css';
import './LeadDatabase.css';

const EXCEL_REQUIRED_COPY = 'Company Name and Email is required to upload the file.';

/** Normalizes legacy API errors to the same short copy. */
function formatExcelUploadErrorMessage(detail: string): string {
  const t = detail.trim();
  if (t.includes(EXCEL_REQUIRED_COPY)) {
    return t.length > 220 ? `${t.slice(0, 217)}…` : t;
  }
  if (
    t.includes('Upload was not applied') ||
    t.includes('did not meet this requirement') ||
    t.includes('every row must include both') ||
    t.includes('Each row needs company + email') ||
    t.includes('Missing company column') ||
    t.includes('Missing email column')
  ) {
    const m = t.match(/(\d+)\s*row/i);
    return m ? `${EXCEL_REQUIRED_COPY} ${m[1]} row(s) skipped.` : EXCEL_REQUIRED_COPY;
  }
  if (t.length > 220) {
    return `${t.slice(0, 217)}…`;
  }
  return t;
}

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
  last_contacted?: string;
  campaign_status?: string;
  outreach_status?: string;
  isUserAdded?: boolean;
}

function getSelectedLeadIds(filteredLeads: Lead[], selectedRowIndices: Set<number>): Set<string> {
  const ids = new Set<string>();
  selectedRowIndices.forEach((index) => {
    const lead = filteredLeads[index];
    if (lead?.id) ids.add(lead.id);
  });
  return ids;
}

interface LeadDatabaseProps {
  onToggleSidebar?: () => void;
  onNavigateToGenerate?: () => void;
  onNavigateToCreateCampaign?: (leadIds?: string[]) => void;
}

export interface LeadDatabaseRef {
  refreshLeads: () => Promise<void>;
  getLeadCount: () => number;
}

export const LeadDatabase = forwardRef<LeadDatabaseRef, LeadDatabaseProps>(({ onToggleSidebar, onNavigateToGenerate, onNavigateToCreateCampaign }, ref) => {
  // Mobile gap helpers
  const gap0 = useMobileGap(0);
  const gap2 = useMobileGap(2);
  const gap4 = useMobileGap(4);
  const gap6 = useMobileGap(6);
  const gap8 = useMobileGap(8);
  const gap10 = useMobileGap(10);
  const gap12 = useMobileGap(12);
  
  // Load state from localStorage on mount
  const loadStateFromStorage = () => {
    try {
      const saved = localStorage.getItem('leadDatabaseState');
      if (saved) {
        const parsed = JSON.parse(saved);
        return {
          activeTab: parsed.activeTab || 'all',
          searchQuery: parsed.searchQuery || '',
          currentPage: parsed.currentPage || 1,
          itemsPerPage: parsed.itemsPerPage || 10,
          selectedLeadId: parsed.selectedLeadId || null,
          selectedIndustries: parsed.selectedIndustries ? new Set<string>(parsed.selectedIndustries as string[]) : new Set<string>(),
          selectedLocations: parsed.selectedLocations ? new Set<string>(parsed.selectedLocations as string[]) : new Set<string>(),
          scoreRange: parsed.scoreRange || [0, 100],
          emailFilter: parsed.emailFilter || 'all',
          websiteFilter: parsed.websiteFilter || 'all',
          scrollPosition: parsed.scrollPosition || 0,
        };
      }
    } catch (e) {
      console.error('Failed to load state from localStorage:', e);
    }
    return {
      activeTab: 'all',
      searchQuery: '',
      currentPage: 1,
      itemsPerPage: 10,
      selectedLeadId: null,
      selectedIndustries: new Set<string>(),
      selectedLocations: new Set<string>(),
      scoreRange: [0, 100],
      emailFilter: 'all',
      websiteFilter: 'all',
      scrollPosition: 0,
    };
  };

  const savedState = loadStateFromStorage();
  
  const [selectedRowIndices, setSelectedRowIndices] = useState<Set<number>>(new Set());
  const [activeTab, setActiveTab] = useState(savedState.activeTab);
  const [searchQuery, setSearchQuery] = useState(savedState.searchQuery);
  const [allLeads, setAllLeads] = useState<Lead[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [currentPage, setCurrentPage] = useState(savedState.currentPage);
  const [itemsPerPage, setItemsPerPage] = useState(savedState.itemsPerPage);
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);
  const [showFilters, setShowFilters] = useState(false);
  const [showRemoveConfirm, setShowRemoveConfirm] = useState(false);
  const [selectedIndustries, setSelectedIndustries] = useState<Set<string>>(savedState.selectedIndustries);
  const [selectedLocations, setSelectedLocations] = useState<Set<string>>(savedState.selectedLocations);
  const [scoreRange, setScoreRange] = useState<[number, number]>(savedState.scoreRange);
  const [emailFilter, setEmailFilter] = useState<'all' | 'has_email' | 'no_email'>(savedState.emailFilter);
  const [websiteFilter, setWebsiteFilter] = useState<'all' | 'has_website' | 'no_website'>(savedState.websiteFilter);
  const [locationInput, setLocationInput] = useState('');
  const [industryInput, setIndustryInput] = useState('');
  const [showLocationSuggestions, setShowLocationSuggestions] = useState(false);
  const [showIndustrySuggestions, setShowIndustrySuggestions] = useState(false);
  const [showEmailFilterDropdown, setShowEmailFilterDropdown] = useState(false);
  const [showWebsiteFilterDropdown, setShowWebsiteFilterDropdown] = useState(false);
  const [selectedIndustry, setSelectedIndustry] = useState<string>('');
  const [industrySearchQuery, setIndustrySearchQuery] = useState<string>('');
  const [isIndustryDropdownOpen, setIsIndustryDropdownOpen] = useState(false);
  const industryFilterRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const emailFilterButtonRef = useRef<HTMLButtonElement>(null);
  const emailFilterDropdownRef = useRef<HTMLDivElement>(null);
  const websiteFilterButtonRef = useRef<HTMLButtonElement>(null);
  const websiteFilterDropdownRef = useRef<HTMLDivElement>(null);
  const excelFileInputRef = useRef<HTMLInputElement>(null);
  const [showSampleImage, setShowSampleImage] = useState(false);

  const [isUploadingExcel, setIsUploadingExcel] = useState(false);
  const [showUploadExcelModal, setShowUploadExcelModal] = useState(false);
  const [selectedExcelFile, setSelectedExcelFile] = useState<File | null>(null);
  const [isExcelDropActive, setIsExcelDropActive] = useState(false);

  // Save state to localStorage whenever it changes
  useEffect(() => {
    const stateToSave = {
      activeTab,
      searchQuery,
      currentPage,
      itemsPerPage,
      selectedLeadId: selectedLead?.id || null,
      selectedIndustries: Array.from(selectedIndustries),
      selectedLocations: Array.from(selectedLocations),
      scoreRange,
      emailFilter,
      websiteFilter,
      scrollPosition: scrollContainerRef.current?.scrollTop || 0,
    };
    localStorage.setItem('leadDatabaseState', JSON.stringify(stateToSave));
  }, [activeTab, searchQuery, currentPage, itemsPerPage, selectedLead?.id, selectedIndustries, selectedLocations, scoreRange, emailFilter, websiteFilter]);

  // Save scroll position on scroll and before unload
  useEffect(() => {
    const handleScroll = () => {
      if (scrollContainerRef.current) {
        const stateToSave = {
          activeTab,
          searchQuery,
          currentPage,
          itemsPerPage,
          selectedLeadId: selectedLead?.id || null,
          selectedIndustries: Array.from(selectedIndustries),
          selectedLocations: Array.from(selectedLocations),
          scoreRange,
          emailFilter,
          websiteFilter,
          scrollPosition: scrollContainerRef.current.scrollTop,
        };
        localStorage.setItem('leadDatabaseState', JSON.stringify(stateToSave));
      }
    };

    const handleBeforeUnload = () => {
      if (scrollContainerRef.current) {
        const stateToSave = {
          activeTab,
          searchQuery,
          currentPage,
          itemsPerPage,
          selectedLeadId: selectedLead?.id || null,
          selectedIndustries: Array.from(selectedIndustries),
          selectedLocations: Array.from(selectedLocations),
          scoreRange,
          emailFilter,
          websiteFilter,
          scrollPosition: scrollContainerRef.current.scrollTop,
        };
        localStorage.setItem('leadDatabaseState', JSON.stringify(stateToSave));
      }
    };

    const scrollContainer = scrollContainerRef.current;
    if (scrollContainer) {
      scrollContainer.addEventListener('scroll', handleScroll);
    }
    window.addEventListener('beforeunload', handleBeforeUnload);
    
    return () => {
      if (scrollContainer) {
        scrollContainer.removeEventListener('scroll', handleScroll);
      }
      window.removeEventListener('beforeunload', handleBeforeUnload);
    };
  }, [activeTab, searchQuery, currentPage, itemsPerPage, selectedLead?.id, selectedIndustries, selectedLocations, scoreRange, emailFilter, websiteFilter]);

  // Fetch leads from API
  useEffect(() => {
    fetchLeads();
  }, []);

  const hasRestoredStateRef = useRef(false);

  // Restore selected lead and scroll position after leads are loaded (only once)
  useEffect(() => {
    if (allLeads.length > 0 && !hasRestoredStateRef.current) {
      hasRestoredStateRef.current = true;
      const saved = localStorage.getItem('leadDatabaseState');
      if (saved) {
        try {
          const parsed = JSON.parse(saved);
          if (parsed.selectedLeadId) {
            const leadToSelect = allLeads.find(l => l.id === parsed.selectedLeadId);
            if (leadToSelect) {
              setSelectedLead(leadToSelect);
            }
          }
          // Restore scroll position after a short delay to ensure DOM is rendered
          setTimeout(() => {
            if (scrollContainerRef.current && parsed.scrollPosition) {
              scrollContainerRef.current.scrollTop = parsed.scrollPosition;
            }
          }, 150);
        } catch (e) {
          console.error('Failed to parse saved state:', e);
        }
      }
    }
  }, [allLeads]);

  // Position email/website filter dropdowns and close when clicking outside
  useEffect(() => {
    if (showEmailFilterDropdown && emailFilterButtonRef.current && emailFilterDropdownRef.current) {
      const buttonRect = emailFilterButtonRef.current.getBoundingClientRect();
      emailFilterDropdownRef.current.style.top = `${buttonRect.bottom + 4}px`;
      emailFilterDropdownRef.current.style.left = `${buttonRect.left}px`;
    }
  }, [showEmailFilterDropdown]);

  useEffect(() => {
    if (showWebsiteFilterDropdown && websiteFilterButtonRef.current && websiteFilterDropdownRef.current) {
      const buttonRect = websiteFilterButtonRef.current.getBoundingClientRect();
      websiteFilterDropdownRef.current.style.top = `${buttonRect.bottom + 4}px`;
      websiteFilterDropdownRef.current.style.left = `${buttonRect.left}px`;
    }
  }, [showWebsiteFilterDropdown]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as HTMLElement;
      if (showEmailFilterDropdown && !target.closest('[data-email-filter-dropdown]')) {
        setShowEmailFilterDropdown(false);
      }
      if (showWebsiteFilterDropdown && !target.closest('[data-website-filter-dropdown]')) {
        setShowWebsiteFilterDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [showEmailFilterDropdown, showWebsiteFilterDropdown]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (industryFilterRef.current && !industryFilterRef.current.contains(event.target as Node)) {
        setIsIndustryDropdownOpen(false);
        setIndustrySearchQuery('');
      }
    };
    if (isIndustryDropdownOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [isIndustryDropdownOpen]);

  const validateExcelFile = (file: File) => {
    const name = file.name.toLowerCase();
    return (
      name.endsWith('.xlsx') ||
      name.endsWith('.xls') ||
      file.type === 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' ||
      file.type === 'application/vnd.ms-excel'
    );
  };

  const uploadExcelFile = async (file: File) => {
    if (!validateExcelFile(file)) {
      toast.error('Please choose an Excel file only (.xlsx or .xls).');
      return false;
    }

    setIsUploadingExcel(true);
    try {
      const response = await apiService.uploadLeadsFromExcel(file);
      if (response.error) {
        const detail = formatExcelUploadErrorMessage(response.message || response.error);
        toast.error('Upload failed', { description: detail });
        return false;
      }

      const summary = response.data;
      const msg = response.message || 'Import completed.';
      toast.success(msg);

      if (summary) {
        const detailParts: string[] = [];
        if ((summary.skipped_duplicates_existing ?? 0) > 0) {
          detailParts.push(
            `${summary.skipped_duplicates_existing} already in Lead Database`,
          );
        }
        if ((summary.skipped_duplicates_in_file ?? 0) > 0) {
          detailParts.push(
            `${summary.skipped_duplicates_in_file} duplicate email(s) in file`,
          );
        }
        if (summary.failed_rows > 0) {
          detailParts.push(
            `${summary.failed_rows} missing company or email`,
          );
        }
        if ((summary.blank_rows ?? 0) > 0) {
          detailParts.push(`${summary.blank_rows} blank row(s) ignored`);
        }
        if (summary.truncated_rows > 0) {
          detailParts.push(
            `${summary.truncated_rows} past 1000-row limit`,
          );
        }
        if (detailParts.length > 0) {
          toast.message('Import details', { description: detailParts.join(' · ') });
        }
      }

      await fetchLeads();
      return true;
    } catch (e) {
      console.error(e);
      toast.error('Could not import the file. Try again.');
      return false;
    } finally {
      setIsUploadingExcel(false);
    }
  };

  const handleExcelFileSelected = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (!validateExcelFile(file)) {
      toast.error('Please choose an Excel file only (.xlsx or .xls).');
      return;
    }
    setSelectedExcelFile(file);
  };

  const handleOpenUploadExcelModal = () => {
    setSelectedExcelFile(null);
    setShowUploadExcelModal(true);
  };

  const handleCloseUploadExcelModal = () => {
    if (isUploadingExcel) return;
    setShowUploadExcelModal(false);
    setSelectedExcelFile(null);
    setIsExcelDropActive(false);
  };

  const handleUploadExcelFromModal = async () => {
    if (!selectedExcelFile || isUploadingExcel) return;
    const uploaded = await uploadExcelFile(selectedExcelFile);
    if (uploaded) {
      setShowUploadExcelModal(false);
      setSelectedExcelFile(null);
      setIsExcelDropActive(false);
    }
  };

  const fetchLeads = async () => {
    setIsLoading(true);
    try {
      const response = await apiService.getLeads();
      if (response.data) {
        // Map API response to component format
        const mappedLeads: Lead[] = response.data.map((lead: LeadResponse) => ({
          id: lead.id,
          companyName: lead.business_name || 'N/A',
          email: lead.email || 'N/A',
          phone: (lead.contact_number && String(lead.contact_number).trim()) || 'N/A',
          location: lead.address || 'N/A',
          tags: lead.industry ? [lead.industry] : [],
          website: lead.website,
          score: lead.lead_score || 0,
          starred: lead.starred || false,
          created_at: lead.created_at,
          last_contacted: lead.last_contacted,
          campaign_status: lead.campaign_status,
          outreach_status: lead.outreach_status || 'not_started',
          isUserAdded: lead.is_user_added ?? false,
        }));
        const sortedLeads = sortLeadsWithUserAddedFirst(mappedLeads);
        const uniqueLeads: Lead[] = [];
        const seenIds = new Set<string>();
        for (const lead of sortedLeads) {
          if (!lead.id || seenIds.has(lead.id)) continue;
          seenIds.add(lead.id);
          uniqueLeads.push(lead);
        }
        setAllLeads(uniqueLeads);
      }
    } catch (error) {
      console.error('Failed to fetch leads:', error);
      setAllLeads([]);
    } finally {
      setIsLoading(false);
    }
  };

  // Expose refresh method and lead count to parent component
  useImperativeHandle(ref, () => ({
    refreshLeads: fetchLeads,
    getLeadCount: () => allLeads.length,
  }));

  const starredLeads = allLeads.filter(lead => lead.starred);

  // Industries with lead counts (for inline filter dropdown - same design as Lead Log)
  const industriesWithCounts = useMemo(() => {
    const byKey = new Map<string, { display: string; leadCount: number }>();
    allLeads.forEach(lead => {
      const industries = (lead.tags || []).filter((t): t is string => !!t && String(t).trim() !== '');
      if (industries.length === 0) return;
      industries.forEach(industry => {
        const key = industry.toLowerCase().trim();
        const existing = byKey.get(key);
        if (existing) {
          existing.leadCount += 1;
          if (industry.length > existing.display.length) existing.display = industry;
        } else {
          byKey.set(key, { display: industry, leadCount: 1 });
        }
      });
    });
    return Array.from(byKey.values())
      .map(({ display, leadCount }) => ({ industry: display, leadCount }))
      .sort((a, b) => a.industry.localeCompare(b.industry));
  }, [allLeads]);

  const filteredIndustriesWithCounts = useMemo(() => {
    if (!industrySearchQuery.trim()) return industriesWithCounts;
    const q = industrySearchQuery.toLowerCase();
    return industriesWithCounts.filter(({ industry }) => industry.toLowerCase().includes(q));
  }, [industriesWithCounts, industrySearchQuery]);
  
  // Filter leads based on filter sidebar and inline industry
  const filterLeadsBySidebar = (leads: Lead[]) => {
    let filtered = leads;
    
    // Apply industry filter (inline bar takes precedence over sidebar)
    if (selectedIndustry && selectedIndustry.trim() !== '') {
      filtered = filtered.filter(lead => 
        (lead.tags || []).some(tag => tag && tag.toLowerCase().includes(selectedIndustry.toLowerCase()))
      );
    } else if (selectedIndustries.size > 0) {
      filtered = filtered.filter(lead => 
        (lead.tags || []).some(tag => selectedIndustries.has(tag))
      );
    }
    
    // Apply location filter
    if (selectedLocations.size > 0) {
      filtered = filtered.filter(lead => {
        if (!lead.location || lead.location === 'N/A') return false;
        const leadLocation = lead.location.trim();
        // Check if any selected location matches (case-insensitive and trimmed)
        return Array.from(selectedLocations).some(selectedLoc => 
          selectedLoc.trim().toLowerCase() === leadLocation.toLowerCase()
        );
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

    // Apply website filter
    if (websiteFilter === 'has_website') {
      filtered = filtered.filter(lead => lead.website && lead.website !== 'N/A' && lead.website.trim() !== '');
    } else if (websiteFilter === 'no_website') {
      filtered = filtered.filter(lead => !lead.website || lead.website === 'N/A' || lead.website.trim() === '');
    }
    
    return filtered;
  };
  
  // Filter leads based on search query (name, score, location, etc.)
  const filterLeadsBySearch = (leads: Lead[]) => {
    if (!searchQuery.trim()) {
      return leads;
    }
    const query = searchQuery.toLowerCase().trim();
    return leads.filter(lead => 
      lead.companyName.toLowerCase().includes(query) ||
      lead.email.toLowerCase().includes(query) ||
      lead.phone.toLowerCase().includes(query) ||
      lead.location.toLowerCase().includes(query) ||
      String(lead.score || 0).includes(query) ||
      (lead.tags || []).some(tag => tag.toLowerCase().includes(query)) ||
      (lead.website && lead.website.toLowerCase().includes(query))
    );
  };

  const tabLeads = activeTab === 'all' ? allLeads : starredLeads;
  const sidebarFilteredLeads = filterLeadsBySidebar(tabLeads);
  const filteredLeads = filterLeadsBySearch(sidebarFilteredLeads);
  const totalLeads = allLeads.length;
  const totalStarred = starredLeads.length;

  // Pagination logic
  const totalPages = Math.ceil(filteredLeads.length / itemsPerPage);
  const startIndex = (currentPage - 1) * itemsPerPage;
  const endIndex = startIndex + itemsPerPage;
  const displayedLeads = filteredLeads.slice(startIndex, endIndex);

  const allPageSelected = useMemo(
    () =>
      displayedLeads.length > 0 &&
      displayedLeads.every((_, index) => selectedRowIndices.has(startIndex + index)),
    [displayedLeads, selectedRowIndices, startIndex],
  );

  const selectedLeadRowCount = selectedRowIndices.size;

  const selectedLeadIds = useMemo(
    () => getSelectedLeadIds(filteredLeads, selectedRowIndices),
    [filteredLeads, selectedRowIndices],
  );

  // Reset to page 1 and clear row selection when search query, tab, or filters change
  useEffect(() => {
    setCurrentPage(1);
    setSelectedRowIndices(new Set());
  }, [searchQuery, activeTab, itemsPerPage, selectedIndustries, selectedLocations, selectedIndustry, scoreRange, emailFilter, websiteFilter]);

  // Update selected lead when allLeads changes (to keep it in sync)
  useEffect(() => {
    if (selectedLead) {
      const updatedLead = allLeads.find(lead => lead.id === selectedLead.id);
      if (updatedLead) {
        // Only update if something actually changed to avoid infinite loops
        if (JSON.stringify(updatedLead) !== JSON.stringify(selectedLead)) {
          setSelectedLead(updatedLead);
        }
      } else {
        // If selected lead is no longer in the list, clear selection
        setSelectedLead(null);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allLeads]);

  const toggleSelect = (rowIndex: number) => {
    setSelectedRowIndices((prev) => {
      const next = new Set(prev);
      if (next.has(rowIndex)) {
        next.delete(rowIndex);
      } else {
        next.add(rowIndex);
      }
      return next;
    });
  };

  const toggleSelectAll = () => {
    setSelectedRowIndices((prev) => {
      const next = new Set(prev);
      const pageIndices = displayedLeads.map((_, index) => startIndex + index);
      const everyOnPage = pageIndices.length > 0 && pageIndices.every((index) => next.has(index));
      if (everyOnPage) {
        pageIndices.forEach((index) => next.delete(index));
      } else {
        pageIndices.forEach((index) => next.add(index));
      }
      return next;
    });
  };

  const toggleStar = async (leadId: string, e?: React.MouseEvent) => {
    if (e) {
      e.stopPropagation();
    }
    const lead = allLeads.find(l => l.id === leadId);
    if (!lead) return;

    // Optimistically update UI
    const newStarred = !lead.starred;
    setAllLeads(prevLeads => 
      prevLeads.map(l => 
        l.id === leadId ? { ...l, starred: newStarred } : l
      )
    );
    // Update selected lead if it's the one being toggled
    if (selectedLead && selectedLead.id === leadId) {
      setSelectedLead(prev => prev ? { ...prev, starred: newStarred } : null);
    }

    // Call API to persist the change
    try {
      await apiService.toggleLeadStar(leadId);
      // The optimistic update is sufficient - API call succeeded
    } catch (error) {
      console.error('Failed to toggle star:', error);
      // Revert on error
      setAllLeads(prevLeads => 
        prevLeads.map(l => 
          l.id === leadId ? { ...l, starred: !newStarred } : l
        )
      );
      if (selectedLead && selectedLead.id === leadId) {
        setSelectedLead(prev => prev ? { ...prev, starred: !newStarred } : null);
      }
    }
  };

  const toggleStarAll = async (e: React.MouseEvent) => {
    e.stopPropagation(); // Prevent tab switching when clicking star
    e.preventDefault(); // Prevent default behavior
    
    // Don't toggle if we're on the starred tab - it would unstar all leads
    if (activeTab === 'starred') {
      return;
    }
    
    const allStarred = displayedLeads.every(lead => lead.starred);
    const newStarred = !allStarred;
    
    // Only toggle leads that need to change (if we want to star all, only toggle unstarred ones)
    const leadsToToggle = displayedLeads.filter(lead => lead.starred !== newStarred);
    
    // Optimistically update UI
    setAllLeads(prevLeads => 
      prevLeads.map(lead => 
        displayedLeads.some(dLead => dLead.id === lead.id) 
          ? { ...lead, starred: newStarred } 
          : lead
      )
    );

    // Call API only for leads that need to be toggled
    try {
      await Promise.all(
        leadsToToggle.map(lead => apiService.toggleLeadStar(lead.id))
      );
    } catch (error) {
      console.error('Failed to toggle stars:', error);
      // Revert on error - fetch fresh data
      fetchLeads();
    }
  };

  const handleRemoveLeads = () => {
    if (selectedLeadRowCount === 0) return;
    setShowRemoveConfirm(true);
  };

  const confirmRemoveLeads = async () => {
    if (selectedLeadRowCount === 0) return;
    
    try {
      // Bulk delete in a single request per chunk. The backend caps each call at
      // 1000 ids, so chunk here (cross-page selection can exceed one page/1000).
      const ids = Array.from(selectedLeadIds);
      const BULK_DELETE_CHUNK = 1000;
      for (let i = 0; i < ids.length; i += BULK_DELETE_CHUNK) {
        await apiService.deleteLeads(ids.slice(i, i + BULK_DELETE_CHUNK));
      }

      // Clear selected leads before refreshing
      const deletedIds = selectedLeadIds;
      setSelectedRowIndices(new Set());
      
      // Clear selected lead if it was deleted
      if (selectedLead && deletedIds.has(selectedLead.id)) {
        setSelectedLead(null);
      }
      
      setShowRemoveConfirm(false);
      
      // Refetch leads from server to ensure consistency
      await fetchLeads();
    } catch (error) {
      console.error('Error removing leads:', error);
      // Refetch leads even on error to ensure UI is in sync
      await fetchLeads();
      // You might want to show an error toast here
    }
  };

  // Handle create campaign from Lead Database - pass selected leads to campaign flow
  const handleCreateCampaign = () => {
    if (!onNavigateToCreateCampaign) return;

    // Clear all previous campaign state to ensure a fresh start
    sessionStorage.removeItem('editCampaignId');
    sessionStorage.removeItem('resumeCampaignId');
    sessionStorage.removeItem('campaignEmailAccountStep');
    sessionStorage.removeItem('campaignEmailAccountChoice');
    sessionStorage.removeItem('openExistingEmailsTab');
    sessionStorage.removeItem('cameFromCampaign');
    sessionStorage.removeItem('showImapForm');
    sessionStorage.removeItem('emailSetupGoToStep5');
    sessionStorage.removeItem('emailSetupCampaignId');
    sessionStorage.removeItem('campaignLogId');

    // Clear any campaign-specific sessionStorage keys
    Object.keys(sessionStorage).forEach(key => {
      if (
        key.startsWith('campaignEmailAccountStep_') ||
        key.startsWith('campaignEmailAccountChoice_') ||
        key.startsWith('spamCheckContentHash_') ||
        key.startsWith('spamCheckPassed_') ||
        key.startsWith('spamCheckScore_')
      ) {
        sessionStorage.removeItem(key);
      }
    });

    // If leads are selected, pass their Lead Database UUIDs into Create Campaign step 2
    if (selectedLeadRowCount > 0) {
      const uniqueSelectedIds = Array.from(selectedLeadIds);
      if (uniqueSelectedIds.length === 0) {
        console.error(
          '[DEBUG] LeadDatabase: rows selected but no lead IDs resolved — aborting Create Campaign',
        );
        return;
      }
      persistCampaignLeadSelection(uniqueSelectedIds);
      onNavigateToCreateCampaign(uniqueSelectedIds);
      return;
    }

    // No explicit selection – show full Lead Database at step 2
    clearCampaignLeadSelection();
    onNavigateToCreateCampaign();
  };

  return (
    <div className="lead-database-root-container">
      {/* Main Content Area */}
      <div className="lead-database-main-content-wrapper">
        {/* Header - Save to database (only when on starred tab) */}
        {activeTab === 'starred' && totalStarred > 0 && selectedLeadRowCount === 0 ? (
          <div className="lead-database-header-container-mobile lead-database-header-mobile lead-database-header-container-mobile-styles">
            <div className="lead-database-button-group lead-database-button-group-styles">
              <Button onClick={() => console.log('Save starred leads')} className="lead-database-button-save-database">
                <img src="/Save to database button.svg" alt="Save to database" className="lead-database-image-button" />
              </Button>
            </div>
          </div>
        ) : null}

        {/* Toolbar — Inbox-aligned search + compact utility filters */}
        <div className="lead-database-toolbar">
          <div className="lead-database-toolbar-search-wrap">
            <div className="lead-database-toolbar-search-input-container">
              <Search className="lead-database-toolbar-search-icon" size={14} strokeWidth={2} aria-hidden />
              <input
                type="text"
                placeholder="Search leads"
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setCurrentPage(1);
                }}
                className="lead-database-toolbar-search-input"
              />
            </div>
          </div>
          <div className="lead-database-toolbar-trailing">
            {selectedLeadRowCount > 0 && (
              <Button
                variant="outline"
                onClick={handleRemoveLeads}
                className="evecta-destructive-btn"
              >
                <Trash2 size={16} />
                Remove Leads
              </Button>
            )}
            <div
              ref={industryFilterRef}
              className="lead-database-toolbar-industry lead-log-industry-filter"
            >
              <div className="lead-log-industry-filter-wrapper">
                <div
                  className="lead-log-industry-filter-container lead-database-toolbar-industry-trigger"
                  onClick={() => setIsIndustryDropdownOpen(true)}
                >
                  <Filter className="lead-log-industry-filter-icon" size={14} strokeWidth={2} aria-hidden />
                  <Input
                    type="text"
                    placeholder="Industry"
                    value={isIndustryDropdownOpen ? industrySearchQuery : (selectedIndustry || '')}
                    onChange={(e) => {
                      setIndustrySearchQuery(e.target.value);
                      setIsIndustryDropdownOpen(true);
                    }}
                    onFocus={() => {
                      setIsIndustryDropdownOpen(true);
                      setIndustrySearchQuery('');
                    }}
                    className="lead-log-industry-filter-input lead-database-toolbar-industry-field !size-auto !h-full min-h-0 !min-h-0 !rounded-none !border-0 !border-none bg-transparent !px-0 !py-0 shadow-none !shadow-none outline-none ring-0 focus-visible:!ring-0 focus-visible:!ring-offset-0 focus-visible:!border-0"
                  />
                  <ChevronDown
                    className="lead-log-industry-filter-icon lead-database-toolbar-industry-chevron"
                    style={{
                      flexShrink: 0,
                      transform: isIndustryDropdownOpen ? 'rotate(180deg)' : 'rotate(0deg)',
                      transition: 'transform 0.2s',
                    }}
                  />
                </div>
              </div>
              {isIndustryDropdownOpen && (
                <div
                  className="lead-log-industry-filter-dropdown"
                  style={{
                    position: 'absolute',
                    top: '100%',
                    left: 0,
                    right: 0,
                    marginTop: '4px',
                    backgroundColor: 'white',
                    border: '0.8px solid #6B7280',
                    borderRadius: '6.75px',
                    boxShadow: '0 4px 6px rgba(0, 0, 0, 0.1)',
                    overflowY: 'auto',
                    zIndex: 1000
                  }}
                >
                  <div
                    className="lead-log-industry-filter-dropdown-item"
                    style={{
                      fontWeight: 600,
                      color: selectedIndustry === '' ? '#6B21A8' : '#111827',
                      backgroundColor: selectedIndustry === '' ? 'rgba(107, 33, 168, 0.1)' : 'transparent',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      borderRadius: '4px'
                    }}
                    onClick={() => {
                      setSelectedIndustry('');
                      setIndustrySearchQuery('');
                      setIsIndustryDropdownOpen(false);
                      setCurrentPage(1);
                    }}
                    onMouseEnter={(e) => {
                      if (selectedIndustry !== '') {
                        e.currentTarget.style.backgroundColor = 'rgba(107, 33, 168, 0.1)';
                      }
                    }}
                    onMouseLeave={(e) => {
                      if (selectedIndustry !== '') {
                        e.currentTarget.style.backgroundColor = 'transparent';
                      }
                    }}
                  >
                    <span>All Industries</span>
                    {selectedIndustry === '' && <Check className="lead-log-industry-filter-icon" style={{ color: '#6B21A8' }} />}
                  </div>
                  {filteredIndustriesWithCounts.length > 0 ? (
                    filteredIndustriesWithCounts.map(({ industry, leadCount }) => (
                      <div
                        key={industry}
                        className="lead-log-industry-filter-dropdown-item"
                        style={{
                          fontWeight: 600,
                          color: selectedIndustry === industry ? '#6B21A8' : '#111827',
                          backgroundColor: selectedIndustry === industry ? 'rgba(107, 33, 168, 0.1)' : 'transparent',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          borderRadius: '4px',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap'
                        }}
                        onClick={() => {
                          setSelectedIndustry(industry);
                          setIndustrySearchQuery('');
                          setIsIndustryDropdownOpen(false);
                          setCurrentPage(1);
                        }}
                        onMouseEnter={(e) => {
                          if (selectedIndustry !== industry) {
                            e.currentTarget.style.backgroundColor = 'rgba(107, 33, 168, 0.1)';
                          }
                        }}
                        onMouseLeave={(e) => {
                          if (selectedIndustry !== industry) {
                            e.currentTarget.style.backgroundColor = 'transparent';
                          }
                        }}
                      >
                        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
                          {industry} ({leadCount} {leadCount === 1 ? 'lead' : 'leads'})
                        </span>
                        {selectedIndustry === industry && <Check className="lead-log-industry-filter-icon" style={{ color: '#6B21A8', flexShrink: 0 }} />}
                      </div>
                    ))
                  ) : (
                    <div
                      className="lead-log-industry-filter-dropdown-item"
                      style={{
                        fontWeight: 500,
                        color: '#6B7280',
                        textAlign: 'center'
                      }}
                    >
                      No industries found
                    </div>
                  )}
                </div>
              )}
            </div>
            {/* Filter Button - opens filter panel from right */}
            <button
              type="button"
              onClick={() => setShowFilters(true)}
              className="lead-database-toolbar-filter-btn"
            >
              <SlidersHorizontal size={14} aria-hidden />
              Filter
            </button>
            <div className="lead-database-excel-upload-group">
              <input
                ref={excelFileInputRef}
                type="file"
                accept=".xlsx,.xls,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
                className="sr-only"
                tabIndex={-1}
                aria-hidden
                onChange={handleExcelFileSelected}
              />
              <Button
                type="button"
                variant="secondary"
                disabled={isUploadingExcel}
                onClick={handleOpenUploadExcelModal}
                className="lead-database-upload-excel-btn"
                title="Company Name and Email is required to upload the file."
              >
                <Upload size={16} aria-hidden />
                {isUploadingExcel ? 'Uploading…' : 'Upload Excel'}
              </Button>
            </div>
            {/* Create Campaign - uses selected leads when present */}
            {onNavigateToCreateCampaign && (
              <Button
                variant="default"
                onClick={handleCreateCampaign}
                className="lead-database-create-campaign-btn"
              >
                Create Campaign
              </Button>
            )}
          </div>
        </div>

        {/* Main Content - content scrolls, pagination fixed at bottom */}
        <div className="lead-database-main-content-area dashboard-content-with-pagination">

         {/* Table - Scrollable */}
         <div ref={scrollContainerRef} className="lead-database-table-wrapper lead-database-table-wrapper-styles dashboard-data-table dashboard-pagination-scroll-area">
           {isLoading ? (
             <div className="lead-database-loading-state">Loading leads...</div>
           ) : allLeads.length === 0 ? (
             <div className="lead-database-empty-state-container">
               <EmptyState
                 iconPath="/lead-database-header.svg"
                 title="No leads found."
                 description="Save leads from Search History to see them here."
               >
                 
               </EmptyState>
             </div>
           ) : (
            <Table className="lead-database-table lead-database-table-styles">
               <TableHeader className="lead-database-table-header-styles">
                <TableRow>
                  <TableHead className="lead-database-table-head-checkbox-styles">
                     <button
                       type="button"
                       onClick={(e) => {
                         e.stopPropagation();
                         toggleSelectAll();
                       }}
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
                            setShowWebsiteFilterDropdown(false);
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
                              onClick={() => {
                                setEmailFilter('all');
                                setShowEmailFilterDropdown(false);
                              }}
                            >
                              <span className="email-filter-dropdown-check-slot">
                                {emailFilter === 'all' ? <Check size={12} /> : null}
                              </span>
                              All Emails
                            </button>
                            <button
                              type="button"
                              className={emailFilter === 'has_email' ? 'email-filter-dropdown-option-active' : undefined}
                              onClick={() => {
                                setEmailFilter('has_email');
                                setShowEmailFilterDropdown(false);
                              }}
                            >
                              <span className="email-filter-dropdown-check-slot">
                                {emailFilter === 'has_email' ? <Check size={12} /> : null}
                              </span>
                              Has Email
                            </button>
                            <button
                              type="button"
                              className={emailFilter === 'no_email' ? 'email-filter-dropdown-option-active' : undefined}
                              onClick={() => {
                                setEmailFilter('no_email');
                                setShowEmailFilterDropdown(false);
                              }}
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
                  <TableHead className="lead-database-table-head-base-styles lead-database-table-head-website">
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', position: 'relative' }}>
                      <span>Website</span>
                      <div style={{ position: 'relative' }} data-website-filter-dropdown>
                        <button
                          ref={websiteFilterButtonRef}
                          onClick={(e) => {
                            e.stopPropagation();
                            setShowWebsiteFilterDropdown(!showWebsiteFilterDropdown);
                            setShowEmailFilterDropdown(false);
                          }}
                          style={{
                            background: 'none',
                            border: 'none',
                            cursor: 'pointer',
                            padding: '2px',
                            display: 'flex',
                            alignItems: 'center',
                            color: websiteFilter !== 'all' ? '#6B21A8' : '#6B7280'
                          }}
                          title="Filter by website"
                        >
                          <Filter size={14} />
                        </button>
                        {showWebsiteFilterDropdown && (
                          <div
                            ref={websiteFilterDropdownRef}
                            style={{
                              position: 'fixed',
                              backgroundColor: '#FFFFFF',
                              border: '1px solid #E5E7EB',
                              borderRadius: '4px',
                              boxShadow: '0 2px 4px rgba(0, 0, 0, 0.08)',
                              zIndex: 10000
                            }}
                            onMouseLeave={() => setShowWebsiteFilterDropdown(false)}
                            data-website-filter-dropdown
                          >
                            <button
                              type="button"
                              className={websiteFilter === 'all' ? 'email-filter-dropdown-option-active' : undefined}
                              onClick={() => {
                                setWebsiteFilter('all');
                                setShowWebsiteFilterDropdown(false);
                              }}
                            >
                              <span className="email-filter-dropdown-check-slot">
                                {websiteFilter === 'all' ? <Check size={12} /> : null}
                              </span>
                              All Websites
                            </button>
                            <button
                              type="button"
                              className={websiteFilter === 'has_website' ? 'email-filter-dropdown-option-active' : undefined}
                              onClick={() => {
                                setWebsiteFilter('has_website');
                                setShowWebsiteFilterDropdown(false);
                              }}
                            >
                              <span className="email-filter-dropdown-check-slot">
                                {websiteFilter === 'has_website' ? <Check size={12} /> : null}
                              </span>
                              Has Website
                            </button>
                            <button
                              type="button"
                              className={websiteFilter === 'no_website' ? 'email-filter-dropdown-option-active' : undefined}
                              onClick={() => {
                                setWebsiteFilter('no_website');
                                setShowWebsiteFilterDropdown(false);
                              }}
                            >
                              <span className="email-filter-dropdown-check-slot">
                                {websiteFilter === 'no_website' ? <Check size={12} /> : null}
                              </span>
                              No Website
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  </TableHead>
                 </TableRow>
               </TableHeader>
               <TableBody>
                 {displayedLeads.length === 0 ? (
                   <TableRow>
                     <TableCell colSpan={5} className="lead-database-table-filter-empty-cell">
                       <EmptyState
                         compact
                         iconPath="/lead-database-header.svg"
                         title="No leads match your current filters."
                         description="Try adjusting your search or filters."
                       />
                     </TableCell>
                   </TableRow>
                 ) : (
                   displayedLeads.map((lead, index) => {
                     const rowIndex = startIndex + index;
                     return (
                   <TableRow 
                     key={`${lead.id}-${rowIndex}`}
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
                         onClick={(e) => {
                           e.stopPropagation();
                           e.preventDefault();
                           toggleSelect(rowIndex);
                           // Explicitly prevent row selection
                           setSelectedLead(null);
                         }}
                         onMouseDown={(e) => {
                           e.stopPropagation();
                         }}
                         className="lead-database-table-checkbox-button"
                       >
                        <div className={`lead-database-table-checkbox-box ${selectedRowIndices.has(rowIndex) ? 'checked' : ''}`}>
                          {selectedRowIndices.has(rowIndex) && (
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
                     );
                   })
                 )}
               </TableBody>
             </Table>
           )}
         </div>

          {/* Pagination fixed at bottom - shared design */}
          <div className="dashboard-pagination-fixed">
            <DashboardPagination
              totalItems={filteredLeads.length}
              currentPage={currentPage}
              itemsPerPage={itemsPerPage}
              onPageChange={setCurrentPage}
              onItemsPerPageChange={(v) => { setItemsPerPage(v); setCurrentPage(1); }}
              itemLabel="leads"
              leftExtra={selectedLeadRowCount > 0 ? (
                <span className="lead-database-selected-leads-badge">
                  <Check className="lead-database-selected-leads-badge-icon" size={12} />
                  {selectedLeadRowCount} {selectedLeadRowCount === 1 ? 'lead' : 'leads'} selected
                </span>
              ) : undefined}
            />
          </div>
        </div>
      </div>

      {/* Right Side Detail Panel */}
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
            outreach_status: selectedLead.outreach_status,
            last_contacted: selectedLead.last_contacted,
            campaign_status: selectedLead.campaign_status,
          }}
          onClose={() => setSelectedLead(null)}
        />
      )}

      {/* Filter Sidebar - design matching reference */}
      {showFilters && (
        <>
          <div
            onClick={() => setShowFilters(false)}
            className="lead-database-filter-overlay"
          />
          <div className="lead-database-filter-sidebar lead-database-filter-sidebar-slide-in lead-database-filter-panel-styles">
            {/* X close - outside inner frame only */}
            <button
              type="button"
              aria-label="Close"
              onClick={() => setShowFilters(false)}
              className="lead-database-filter-close lead-database-filter-close-outside"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 4L4 12M4 4l8 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </button>
            {/* Inner frame - Filters header + content */}
            <div className="lead-database-filter-inner-frame">
            {/* Header: Filters + icon (inside inner frame) */}
            <div className="lead-database-filter-header">
              <div className="lead-database-filter-header-left">
                <SlidersHorizontal size={16} style={{ color: '#374151', flexShrink: 0 }} />
                <span className="lead-database-filter-title">Filters</span>
              </div>
            </div>
            {/* Filter Content - Industry, Location, Lead Score Range */}
            <div className="lead-database-filter-content">
              {/* Industry Section */}
              {(() => {
                const allIndustries = new Set<string>();
                allLeads.forEach(lead => {
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
                            document.getElementById('industry-filter-input')?.focus();
                          }}
                        >
                          <input
                            id="industry-filter-input"
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

              {/* Location Section */}
              {(() => {
                const allLocations = new Set<string>();
                allLeads.forEach(lead => {
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
                            document.getElementById('location-filter-input')?.focus();
                          }}
                        >
                          <input
                            id="location-filter-input"
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

              {/* Lead Score Range Section */}
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
                      z-index: 10;
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
                      z-index: 10;
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

      {/* Remove Confirmation Dialog - same design as Save All Leads */}
      {showRemoveConfirm && (
        <>
          <div
            onClick={() => setShowRemoveConfirm(false)}
            className="evecta-dialog-overlay lead-database-remove-confirm-overlay"
          />
          <div
            onClick={(e) => e.stopPropagation()}
            className="evecta-dialog lead-database-remove-confirm-dialog"
          >
            <div className="evecta-dialog-header lead-database-remove-confirm-header">
              <h2 id="confirm-removal-dialog-title" className="evecta-dialog-title lead-database-remove-confirm-title">
                Confirm Removal?
              </h2>
              <button
                type="button"
                aria-label="Close"
                onClick={() => setShowRemoveConfirm(false)}
                className="evecta-dialog-close lead-database-remove-confirm-close"
              >
                <X className="evecta-dialog-close-x" aria-hidden strokeWidth={2} size={18} />
              </button>
            </div>
            <p className="evecta-dialog-description lead-database-remove-confirm-text">
              You are about to permanently remove selected leads. This action cannot be undone.
            </p>
            <div className="evecta-dialog-actions lead-database-remove-confirm-actions">
              <button
                type="button"
                onClick={() => setShowRemoveConfirm(false)}
                className="evecta-dialog-btn evecta-dialog-btn--secondary lead-database-remove-confirm-keep-btn"
              >
                Keep Leads
              </button>
              <button
                type="button"
                onClick={confirmRemoveLeads}
                className="evecta-dialog-btn evecta-dialog-btn--destructive lead-database-remove-confirm-remove-btn"
              >
                Remove Leads
              </button>
            </div>
          </div>
        </>
      )}

      {showUploadExcelModal && (
        <>
          <div
            onClick={handleCloseUploadExcelModal}
            className="lead-database-upload-modal-overlay"
          />
          <div
            onClick={(e) => e.stopPropagation()}
            className="lead-database-upload-modal"
          >
            <div className="lead-database-upload-modal-header">
              <h2 className="lead-database-upload-modal-title">Upload File</h2>
              <button
                type="button"
                aria-label="Close"
                onClick={handleCloseUploadExcelModal}
                className="lead-database-upload-modal-close"
                disabled={isUploadingExcel}
              >
                <X size={16} />
              </button>
            </div>
           
            <div
              className={`lead-database-upload-dropzone ${isExcelDropActive ? 'is-active' : ''}`}
              onDragOver={(e) => {
                e.preventDefault();
                setIsExcelDropActive(true);
              }}
              onDragEnter={(e) => {
                e.preventDefault();
                setIsExcelDropActive(true);
              }}
              onDragLeave={(e) => {
                e.preventDefault();
                const nextTarget = e.relatedTarget as Node | null;
                if (!nextTarget || !e.currentTarget.contains(nextTarget)) {
                  setIsExcelDropActive(false);
                }
              }}
              onDrop={(e) => {
                e.preventDefault();
                setIsExcelDropActive(false);
                const droppedFile = e.dataTransfer.files?.[0];
                if (!droppedFile) return;
                if (!validateExcelFile(droppedFile)) {
                  toast.error('Please choose an Excel file only (.xlsx or .xls).');
                  return;
                }
                setSelectedExcelFile(droppedFile);
              }}
              onClick={() => !isUploadingExcel && excelFileInputRef.current?.click()}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if ((e.key === 'Enter' || e.key === ' ') && !isUploadingExcel) {
                  e.preventDefault();
                  excelFileInputRef.current?.click();
                }
              }}
            >
              <Upload size={36} strokeWidth={1.5} />
              <p className="lead-database-upload-dropzone-text">Drag and drop file here</p>
              {selectedExcelFile && (
                <p className="lead-database-upload-dropzone-filename">{selectedExcelFile.name}</p>
              )}
            </div>
            <div className="lead-database-upload-requirements-box">
              <p className="lead-database-upload-requirements-title">Upload requirements:</p>
              <p className="lead-database-upload-requirements-text">
                Please ensure each entry occupies its own row.{` `}
                <button
                  type="button"
                  onClick={() => setShowSampleImage(true)}
                  className="lead-database-upload-view-sample-btn"
                >
                  View Sample
                </button>
              </p>
              <p className="lead-database-upload-requirements-text">
                The uploaded file must include the following columns: business_name, industry, and email.{` `}
                Every row needs Company Name and Email. Blank rows are ignored. Duplicate emails (in the file or already in Lead Database) are skipped.{` `}
                <a
                  href="/ExampleLeadTable.xlsx"
                  download="ExampleLeadTable.xlsx"
                  className="lead-database-upload-download-table-btn"
                >
                  Download File
                </a>
              </p>
              {showSampleImage && (
                <>
                  <div
                    className="lead-database-sample-overlay"
                    onClick={() => setShowSampleImage(false)}
                  />

                  <div className="lead-database-sample-preview">
                    <button
                      type="button"
                      className="lead-database-sample-close"
                      onClick={() => setShowSampleImage(false)}
                    >
                      <X size={18} />
                    </button>

                    <img
                      src="/Sample excel file.png"
                      alt="Sample Excel file"
                      className="lead-database-sample-image"
                    />
                  </div>
                </>
              )}
              <p className="lead-database-upload-requirements-note">Support format: XLS</p>
              <p className="lead-database-upload-requirements-note-strong">Max file size: 2mb</p>
            </div>
            <div className="lead-database-upload-modal-actions">
              <button
                type="button"
                onClick={handleUploadExcelFromModal}
                disabled={!selectedExcelFile || isUploadingExcel}
                className="lead-database-upload-modal-submit"
              >
                {isUploadingExcel ? 'Uploading…' : 'Upload File'}
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
});

