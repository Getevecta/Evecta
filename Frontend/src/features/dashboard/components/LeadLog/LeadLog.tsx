import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { Eye, ArrowLeft, ChevronDown, Star, Bookmark, Search, X, Calendar, MessageSquare, Mail, MapPin, Building2, Check, Filter } from 'lucide-react';
import { DashboardPagination } from '../ui/DashboardPagination';
import { EmptyState } from '../ui/EmptyState';
import { LeadDetailPanel } from '../ui/LeadDetailPanel';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../ui/table';
import { apiService, LeadLogListResponse, LeadLogResponse, LeadLogLeadResponse } from '../../../../shared/services/api';
import { persistCampaignLeadSelection } from '../../../../shared/utils/campaignLeadSelection';
import { useMobileGap } from '../ui/use-mobile-gap';
import '../Inbox/Inbox.css';
import './LeadLog.css';

interface LeadLogProps {
  searchQuery?: string;
  onSearchQueryChange?: (query: string) => void;
  onToggleSidebar?: () => void;
  onViewModeChange?: (isDetailView: boolean) => void;
  onLeadsSaved?: () => void | Promise<void>;
  onNavigateToLeads?: () => void;
  onNavigateToCampaigns?: () => void;
  onNavigateToCreateCampaign?: (leadIds?: string[]) => void;
}

type ViewMode = 'list' | 'detail';

export function LeadLog({ searchQuery: searchQueryProp, onSearchQueryChange, onToggleSidebar, onViewModeChange, onLeadsSaved, onNavigateToLeads, onNavigateToCampaigns, onNavigateToCreateCampaign }: LeadLogProps) {
  // Mobile gap helpers
  const gap4 = useMobileGap(4);
  const gap6 = useMobileGap(6);
  const gap8 = useMobileGap(8);
  const gap10 = useMobileGap(10);
  const gap12 = useMobileGap(12);
  const gap16 = useMobileGap(16);
  
  const [viewMode, setViewMode] = useState<ViewMode>('list');
  const [leadLogs, setLeadLogs] = useState<LeadLogListResponse[]>([]);
  const [currentLog, setCurrentLog] = useState<LeadLogResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [internalSearchQuery, setInternalSearchQuery] = useState('');
  // Use controlled search from parent (Dashboard header) when provided, else internal
  const searchQuery = searchQueryProp ?? internalSearchQuery;
  const setSearchQuery = onSearchQueryChange ?? setInternalSearchQuery;
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(10);
  const [selectedLeads, setSelectedLeads] = useState<Set<string>>(new Set());
  const [starredLeads, setStarredLeads] = useState<Set<string>>(new Set());
  const [selectedLead, setSelectedLead] = useState<LeadLogLeadResponse | null>(null);
  const [isCreatingCampaign, setIsCreatingCampaign] = useState(false);
  const [selectedIndustry, setSelectedIndustry] = useState<string>('');
  const [logIndustriesCache, setLogIndustriesCache] = useState<Map<string, string[]>>(new Map());
  const [industrySearchQuery, setIndustrySearchQuery] = useState<string>('');
  const [isIndustryDropdownOpen, setIsIndustryDropdownOpen] = useState<boolean>(false);
  const industryFilterRef = useRef<HTMLDivElement>(null);
  const [emailFilter, setEmailFilter] = useState<'all' | 'has_email' | 'no_email'>('all');
  const [showEmailFilterDropdown, setShowEmailFilterDropdown] = useState(false);
  const emailFilterButtonRef = useRef<HTMLButtonElement>(null);
  const emailFilterDropdownRef = useRef<HTMLDivElement>(null);

  // Notify parent component (Dashboard) when view mode changes
  useEffect(() => {
    if (onViewModeChange) {
      onViewModeChange(viewMode === 'detail');
    }
  }, [viewMode, onViewModeChange]);

  // Reset to page 1 when search query changes (e.g. from header)
  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery]);

  // Fetch lead logs list
  useEffect(() => {
    if (viewMode === 'list') {
      fetchLeadLogs();
    }
  }, [viewMode]);

  const fetchLeadLogs = async () => {
    setIsLoading(true);
    try {
      const response = await apiService.getLeadLogs();
      if (response.data) {
        console.log('Fetched lead logs:', response.data.length);
        setLeadLogs(response.data);
      } else {
        console.log('No lead logs data in response');
      }
    } catch (error) {
      console.error('Failed to fetch lead logs:', error);
    } finally {
      setIsLoading(false);
    }
  };

  // Fetch specific log details
  const fetchLogDetails = async (logId: string) => {
    setIsLoading(true);
    try {
      const response = await apiService.getLeadLogById(logId);
      console.log('📋 Lead Log API Response:', response);
      if (response.data) {
        console.log('📋 Lead Log Data:', response.data);
        console.log('📋 Leads Array:', response.data.leads);
        console.log('📋 Leads Count:', response.data.leads?.length || 0);
        setCurrentLog(response.data);
        setViewMode('detail');
        setCurrentPage(1);
        // Clear search so all leads are shown when opening a session (search filters leads in detail view)
        setSearchQuery('');
        
        // Cache industries from leads
        if (response.data.leads && response.data.leads.length > 0) {
          const industries = Array.from(new Set(
            response.data.leads
              .map(lead => lead.industry)
              .filter(industry => industry && industry.trim())
          ));
          setLogIndustriesCache(prev => {
            const newCache = new Map(prev);
            newCache.set(logId, industries);
            return newCache;
          });
        }
      } else {
        console.error('❌ No data in response:', response);
      }
    } catch (error) {
      console.error('Failed to fetch log details:', error);
    } finally {
      setIsLoading(false);
    }
  };

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
    setCurrentPage(1);
  }, [emailFilter]);

  // Handle back to list
  const handleBackToList = () => {
    setViewMode('list');
    setCurrentLog(null);
    setSelectedLeads(new Set());
    setStarredLeads(new Set());
    if (onSearchQueryChange) {
      onSearchQueryChange('');
    } else {
      setInternalSearchQuery('');
    }
    setSelectedIndustry('');
    setEmailFilter('all');
    setCurrentPage(1);
  };

  // Handle create campaign - save leads and navigate to campaign
  const handleCreateCampaign = async () => {
    if (!currentLog) return;
    
    setIsCreatingCampaign(true);
    try {
      // If no leads are selected, use all leads from the log
      let leadIdsToUse: string[];
      if (selectedLeads.size > 0) {
        leadIdsToUse = Array.from(selectedLeads);
      } else {
        // Use all leads from the current log
        leadIdsToUse = (currentLog.leads || []).map(lead => lead.id);
      }
      
      if (leadIdsToUse.length === 0) return;
      
      const response = await apiService.promoteLeadsFromLog(currentLog.id, leadIdsToUse);

      if (response.error) {
        alert(response.error || response.message || 'Failed to save leads');
        return;
      }

      // API message carries duplicate-skip info (e.g. "45 saved, 2 duplicates skipped")
      const saveMessage = response.message;
      if (saveMessage) {
        alert(saveMessage);
      }

      const databaseLeadIds = (response.data?.lead_ids || []).map(String).filter(Boolean);
      if (databaseLeadIds.length === 0) {
        alert(
          'Leads were saved but could not be loaded for the campaign. Open Lead Database and try again.',
        );
        return;
      }

      // Refresh the log to reflect updated state
      await fetchLogDetails(currentLog.id);
      setSelectedLeads(new Set());

      // Notify parent component to refresh LeadDatabase
      if (onLeadsSaved) {
        await onLeadsSaved();
      }

      // Clear all previous campaign state to ensure fresh start
      sessionStorage.removeItem('editCampaignId');
      sessionStorage.removeItem('campaignEmailAccountStep');
      sessionStorage.removeItem('campaignEmailAccountChoice');
      sessionStorage.removeItem('openExistingEmailsTab');
      sessionStorage.removeItem('cameFromCampaign');
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

      // Use Lead Database UUIDs from promote — not lead-log row IDs
      const uniqueSelectedIds = persistCampaignLeadSelection(databaseLeadIds);
      sessionStorage.setItem('campaignLogId', currentLog.id);

      // Navigate to create campaign view with database lead IDs
      if (onNavigateToCreateCampaign) {
        onNavigateToCreateCampaign(uniqueSelectedIds);
      } else if (onNavigateToCampaigns) {
        onNavigateToCampaigns();
      }
      
      // Show success message only once
      // Note: toast will be shown in Dashboard when navigating
    } catch (error) {
      console.error('Failed to create campaign:', error);
    } finally {
      setIsCreatingCampaign(false);
    }
  };

  // Handle save selected leads
  const handleSaveSelectedLeads = async () => {
    if (!currentLog || selectedLeads.size === 0) return;

    try {
      const selectedIds = Array.from(selectedLeads);
      const response = await apiService.promoteLeadsFromLog(currentLog.id, selectedIds);

      if (response.data?.message) {
        console.log('Success:', response.data.message);
      }

      await fetchLogDetails(currentLog.id);
      setSelectedLeads(new Set());

      if (onLeadsSaved) {
        await onLeadsSaved();
      }

      setTimeout(() => {
        if (onNavigateToLeads) {
          onNavigateToLeads();
        }
      }, 100);
    } catch (error: any) {
      console.error('Failed to save leads:', error);
      const errorMessage = error?.response?.data?.detail || error?.message || 'Failed to save leads';
      alert(errorMessage);
    }
  };

  // Format date (full string with "Created on:" prefix)
  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    const options: Intl.DateTimeFormatOptions = {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: true
    };
    const formattedDate = date.toLocaleDateString('en-US', options);
    return `Created on: ${formattedDate}`;
  };

  // Format date only (without "Created on:" prefix)
  const formatDateOnly = (dateString: string) => {
    const date = new Date(dateString);
    const options: Intl.DateTimeFormatOptions = {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: true
    };
    return date.toLocaleDateString('en-US', options);
  };

  /** Session list cards — same pattern as Inbox thread cards ("Mar 1, 2026 at 8:15 PM") */
  const formatSessionCardTimestamp = (dateString: string | undefined | null): string => {
    if (!dateString) return '—';
    const date = new Date(dateString);
    if (Number.isNaN(date.getTime())) return '—';
    const months = [
      'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
    ];
    const month = months[date.getMonth()];
    const day = date.getDate();
    const year = date.getFullYear();
    const hours = date.getHours();
    const minutes = date.getMinutes();
    const ampm = hours >= 12 ? 'PM' : 'AM';
    const displayHours = hours % 12 || 12;
    const displayMinutes = minutes.toString().padStart(2, '0');
    return `${month} ${day}, ${year} at ${displayHours}:${displayMinutes} ${ampm}`;
  };

  // Truncate text to 30 characters with ellipsis
  const truncateText = (text: string | null | undefined, maxLength: number = 30): string => {
    if (!text || text === 'N/A') return text || 'N/A';
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + '...';
  };

  // Extract industries from logs (from cached data or query/chat_title text)
  const extractIndustriesFromLog = useCallback((log: LeadLogListResponse): string[] => {
    // First try cached industries (from leads when user has opened the log)
    const cachedIndustries = logIndustriesCache.get(log.id);
    if (cachedIndustries && cachedIndustries.length > 0) {
      return cachedIndustries;
    }
    
    const industries: string[] = [];
    
    // Extract from query/chat_title: "X in Y" pattern (e.g., "Service Businesses in Toronto" -> "Service Businesses")
    const text = (log.query || log.chat_title || '').trim();
    const inMatch = text.match(/^(.+?)\s+in\s+/i);
    if (inMatch) {
      const industryPart = inMatch[1].trim();
      if (industryPart && !industries.includes(industryPart)) {
        industries.push(industryPart);
      }
    }
    
    // If no "in" pattern, use the full text as industry (e.g., "Service Businesses" alone)
    if (industries.length === 0 && text) {
      if (!industries.includes(text)) {
        industries.push(text);
      }
    }
    
    // Additional keywords - only add if not already covered by a more specific industry
    const query = text.toLowerCase();
    const industryKeywords = [
      'service businesses', 'e-commerce businesses', 'e-commerce', 'service',
      'chocolate factory', 'chocolate', 'factory',
      'nutritionist', 'nutritionists', 'nutrition',
      'mental health', 'mental health coach', 'mental health coaches',
      'wellness center', 'wellness centers', 'wellness',
      'physiotherapy', 'physiotherapist', 'physio',
      'chiropractic', 'chiropractor',
      'podiatry', 'podiatrist',
      'general practitioner', 'general practitioners', 'gp', 'gps',
      'dental clinic', 'dental clinics', 'dentist', 'dentistry',
      'coach', 'coaches',
      'clinic', 'clinics',
      'center', 'centers', 'centre', 'centres'
    ];
    
    industryKeywords.forEach(keyword => {
      if (query.includes(keyword)) {
        const capitalized = keyword.split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
        // Skip if already have a more specific industry that contains this (avoids "E-commerce" + "E-Commerce Businesses" duplicates)
        const isRedundant = industries.some(existing =>
          existing.toLowerCase().includes(keyword) || keyword.includes(existing.toLowerCase())
        );
        if (!isRedundant && !industries.includes(capitalized)) {
          industries.push(capitalized);
        }
      }
    });
    
    return industries;
  }, [logIndustriesCache]);

  // Get unique industries with lead counts (deduplicated, merged when one name contains another)
  const industriesWithCounts = useMemo(() => {
    const byLowerKey = new Map<string, { display: string; leadCount: number }>();
    leadLogs.forEach(log => {
      const industries = extractIndustriesFromLog(log);
      const leadCount = log.lead_count || 0;
      industries.forEach(industry => {
        const key = industry.toLowerCase().trim();
        const existing = byLowerKey.get(key);
        if (existing) {
          existing.leadCount += leadCount;
          if (industry.length > existing.display.length) {
            existing.display = industry;
          }
        } else {
          byLowerKey.set(key, { display: industry, leadCount });
        }
      });
    });
    // Merge entries where one name contains another (e.g. "E-commerce" into "E-Commerce Businesses")
    const merged = new Map<string, { display: string; leadCount: number }>();
    const entries = Array.from(byLowerKey.entries()).sort((a, b) => b[0].length - a[0].length);
    for (const [key, { display, leadCount }] of entries) {
      let targetKey: string | null = null;
      for (const [mk] of merged) {
        if (mk.includes(key) || key.includes(mk)) {
          targetKey = mk.length >= key.length ? mk : key;
          break;
        }
      }
      if (targetKey && merged.has(targetKey)) {
        const m = merged.get(targetKey)!;
        m.leadCount += leadCount;
        if (display.length > m.display.length) m.display = display;
      } else {
        merged.set(key, { display, leadCount });
      }
    }
    return Array.from(merged.values())
      .map(({ display, leadCount }) => ({ industry: display, leadCount }))
      .sort((a, b) => a.industry.localeCompare(b.industry));
  }, [leadLogs, extractIndustriesFromLog]);

  // For backwards compatibility - industry names only (used by filteredIndustries search)
  const allIndustries = useMemo(() => industriesWithCounts.map(i => i.industry), [industriesWithCounts]);

  // Filter industries based on search query (for dropdown search)
  const filteredIndustriesWithCounts = useMemo(() => {
    if (!industrySearchQuery.trim()) {
      return industriesWithCounts;
    }
    const query = industrySearchQuery.toLowerCase();
    return industriesWithCounts.filter(({ industry }) => 
      industry.toLowerCase().includes(query)
    );
  }, [industriesWithCounts, industrySearchQuery]);

  // Handle click outside to close dropdown
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (industryFilterRef.current && !industryFilterRef.current.contains(event.target as Node)) {
        setIsIndustryDropdownOpen(false);
        setIndustrySearchQuery('');
      }
    };

    if (isIndustryDropdownOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => {
        document.removeEventListener('mousedown', handleClickOutside);
      };
    }
  }, [isIndustryDropdownOpen]);

  // Filter logs by search query and industry
  const filteredLogs = useMemo(() => {
    return leadLogs.filter(log => {
      // Search query filter
      const matchesSearch = !searchQuery || searchQuery.trim() === '' ||
    log.query?.toLowerCase().includes(searchQuery.toLowerCase()) ||
        log.chat_title?.toLowerCase().includes(searchQuery.toLowerCase());
      
      // Industry filter - only apply if an industry is selected (not "all")
      if (!selectedIndustry || selectedIndustry.trim() === '' || selectedIndustry === 'all') {
        return matchesSearch;
      }
      
      try {
        const logIndustries = extractIndustriesFromLog(log);
        const matchesIndustry = logIndustries.some(industry => 
          industry.toLowerCase().includes(selectedIndustry.toLowerCase())
        );
        return matchesSearch && matchesIndustry;
      } catch (error) {
        console.error('Error extracting industries:', error);
        return matchesSearch; // If there's an error, only filter by search
      }
    });
  }, [leadLogs, searchQuery, selectedIndustry, extractIndustriesFromLog]);

  // Pagination for list view
  const totalPages = Math.ceil(filteredLogs.length / itemsPerPage);
  const startIndex = (currentPage - 1) * itemsPerPage;
  const endIndex = startIndex + itemsPerPage;
  const displayedLogs = filteredLogs.slice(startIndex, endIndex);

  // Filter leads in detail view by search query and email filter
  const filteredLeads = (currentLog?.leads || []).filter(lead => {
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      if (!(
        lead.business_name?.toLowerCase().includes(q) ||
        lead.email?.toLowerCase().includes(q) ||
        lead.contact_number != null &&
          String(lead.contact_number).toLowerCase().includes(q) ||
        lead.address?.toLowerCase().includes(q) ||
        lead.industry?.toLowerCase().includes(q)
      )) return false;
    }
    if (emailFilter === 'has_email') {
      return !!(lead.email && lead.email !== 'N/A' && String(lead.email).trim() !== '');
    }
    if (emailFilter === 'no_email') {
      return !lead.email || lead.email === 'N/A' || String(lead.email).trim() === '';
    }
    return true;
  });

  // Pagination for detail view
  const detailTotalPages = Math.ceil(filteredLeads.length / itemsPerPage);
  const detailStartIndex = (currentPage - 1) * itemsPerPage;
  const detailEndIndex = detailStartIndex + itemsPerPage;
  const displayedLeads = filteredLeads.slice(detailStartIndex, detailEndIndex);

  if (viewMode === 'detail' && currentLog) {
    return (
      <div className="lead-log-root-container">
        {/* Main Content - Detail View */}
        <div className="lead-log-detail-container lead-log-detail-container-styles">
          {/* Session Title and Info with Action Buttons */}
          <div className="lead-log-header-section">
            <div className="lead-log-title-container">
              <div className="lead-log-title-row" style={{ gap: gap8, display: 'flex', alignItems: 'flex-start' }}>
                <ArrowLeft 
                  className="lead-log-title-back-icon"
                  onClick={handleBackToList}
                />
                <div className="lead-log-title-stack">
                  <span className="lead-log-title-text">
                    {currentLog.chat_title}
                  </span>
                  <p className="lead-log-subtitle">
                    <span className="lead-log-subtitle-prefix">
                      {(currentLog.leads || []).length} leads - Created on:{' '}
                    </span>
                    <span className="lead-log-subtitle-date">
                      {formatSessionCardTimestamp(currentLog.created_at)}
                    </span>
                  </p>
                </div>
              </div>
            </div>
            
            {/* Search Bar and Action Buttons */}
            <div style={{ display: 'flex', alignItems: 'center', gap: gap12, flex: 1, justifyContent: 'flex-end' }}>
              {/* Search Bar - matches Create Campaign button shape & size */}
              <div className="lead-log-detail-search-wrapper">
                <div className="lead-log-detail-search-container">
                  <Search className="lead-log-detail-search-icon" size={14} strokeWidth={2} aria-hidden />
                  <Input
                    placeholder="Search here"
                    value={searchQuery}
                    onChange={(e) => {
                      setSearchQuery(e.target.value);
                      setCurrentPage(1);
                    }}
                    className="lead-log-detail-search-input focus-visible:ring-0 focus-visible:ring-transparent focus-visible:border-none lead-log-search-input"
                  />
                </div>
              </div>
              
              {/* Action Buttons */}
              <div className="lead-log-action-buttons" style={{ display: 'flex', alignItems: 'center', gap: gap8 }}>
                {selectedLeads.size > 0 && (
                  <button
                    type="button"
                    onClick={handleSaveSelectedLeads}
                    className="lead-log-save-selected-watch-demo-btn dashboard-header-btn-style"
                  >
                    <Check size={18} className="dashboard-header-btn-icon" />
                    Save Selected Leads
                  </button>
                )}
                {currentLog && (currentLog.leads || []).length > 0 && (
                  <Button
                    variant="default"
                    onClick={handleCreateCampaign}
                    disabled={isCreatingCampaign}
                    className="lead-log-create-campaign-btn"
                  >
                    Create Campaign
                  </Button>
                )}
              </div>
            </div>
          </div>

          {/* Leads Table - scrolls, pagination fixed at bottom */}
          <div className="dashboard-content-with-pagination" style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
          <div className="lead-log-table-wrapper lead-log-table-wrapper-styles dashboard-data-table dashboard-pagination-scroll-area">
            <Table className="lead-database-table lead-log-table-styles">
              <TableHeader className="lead-log-table-header-styles">
                <TableRow className="lead-log-table-row-styles">
                  <TableHead className="lead-log-table-head-checkbox">
                    <button
                      onClick={() => {
                        if (selectedLeads.size === displayedLeads.length) {
                          setSelectedLeads(new Set());
                        } else {
                          setSelectedLeads(new Set(displayedLeads.map(l => l.id)));
                        }
                      }}
                      className="lead-log-table-checkbox-button"
                    >
                      <div className={`lead-log-table-checkbox-box ${selectedLeads.size === displayedLeads.length && displayedLeads.length > 0 ? 'checked' : ''}`}>
                        {selectedLeads.size === displayedLeads.length && displayedLeads.length > 0 && (
                          <Check className="lead-log-table-checkbox-check" />
                        )}
                      </div>
                    </button>
                  </TableHead>
                  <TableHead className="lead-log-table-head-base lead-log-table-head-company">Company Name</TableHead>
                  <TableHead className="lead-log-table-head-base lead-log-table-head-email">
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
                  <TableHead className="lead-log-table-head-base lead-log-table-head-location">Location</TableHead>
                  <TableHead className="lead-log-table-head-base lead-log-table-head-website">Website</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {displayedLeads.length === 0 ? (
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
                displayedLeads.map((lead) => (
                  <TableRow 
                    key={lead.id} 
                    onClick={() => setSelectedLead(lead)}
                    className={selectedLead?.id === lead.id ? 'lead-log-table-row-selected' : ''}
                    style={{ 
                      borderBottom: '0.5px solid #E5E7EB', 
                      backgroundColor: selectedLead?.id === lead.id ? '#F3E8FF' : 'white',
                      cursor: 'pointer'
                    }}
                  >
                    <TableCell className="lead-log-table-cell-checkbox">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          const newSelected = new Set(selectedLeads);
                          if (newSelected.has(lead.id)) {
                            newSelected.delete(lead.id);
                          } else {
                            newSelected.add(lead.id);
                          }
                          setSelectedLeads(newSelected);
                        }}
                        className="lead-log-table-checkbox-button"
                      >
                        <div className={`lead-log-table-checkbox-box ${selectedLeads.has(lead.id) ? 'checked' : ''}`}>
                          {selectedLeads.has(lead.id) && (
                            <Check className="lead-log-table-checkbox-check" />
                          )}
                        </div>
                      </button>
                    </TableCell>
                    <TableCell className="lead-log-table-cell-base lead-log-table-cell-company" title={lead.business_name || 'N/A'} style={{ fontWeight: 500, color: '#111827' }}>
                      <span className="dashboard-table-cell-text-clip">{truncateText(lead.business_name)}</span>
                    </TableCell>
                    <TableCell className="lead-log-table-cell-base lead-log-table-cell-email" title={lead.email || 'N/A'}>
                      <span className="dashboard-table-cell-text-clip">{truncateText(lead.email)}</span>
                    </TableCell>
                    <TableCell className="lead-log-table-cell-base lead-log-table-cell-location" title={lead.address || 'N/A'}>
                      <span className="dashboard-table-cell-text-clip">{truncateText(lead.address)}</span>
                    </TableCell>
                    <TableCell className="lead-log-table-cell-base lead-log-table-cell-website" title={lead.website || 'N/A'}>
                      {lead.website && lead.website !== 'N/A' ? (
                        <a 
                          href={lead.website.startsWith('http') ? lead.website : `https://${lead.website}`} 
                          target="_blank" 
                          rel="noopener noreferrer"
                          className="lead-log-table-cell-website-link dashboard-table-cell-text-clip"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {truncateText(lead.website)}
                        </a>
                      ) : <span className="dashboard-table-cell-text-clip">N/A</span>}
                    </TableCell>
                  </TableRow>
                ))
                )}
              </TableBody>
            </Table>
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
              leftExtra={selectedLeads.size > 0 ? (
                <span className="lead-log-selected-leads-badge">
                  <Check className="lead-log-selected-leads-badge-icon" size={12} />
                  {selectedLeads.size} {selectedLeads.size === 1 ? 'lead' : 'leads'} selected
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
  }

  // List View
  return (
    <div className="lead-log-list-container lead-log-list-container-styles">
      {/* Main Content - List View */}
      <div className="lead-log-list-content lead-log-list-content-styles">

        {/* Search and filter — same shell as Inbox (.inbox-search-filters + inner fields) */}
        <div className="lead-log-search-filter-outer">
          <div className="lead-log-search-filter-container">
            <div className="lead-log-search-bar-search-wrap">
              <div className="lead-log-search-input-container">
                <Search className="lead-log-search-icon" size={14} strokeWidth={2} aria-hidden />
                <Input
                  type="text"
                  placeholder="Search chat sessions"
                  value={searchQuery}
                  onChange={(e) => {
                    setSearchQuery(e.target.value);
                    setCurrentPage(1);
                  }}
                  className="lead-log-search-input focus-visible:ring-0 focus-visible:ring-transparent focus-visible:border-none focus-visible:ring-offset-0"
                />
              </div>
            </div>
            <div className="lead-log-search-filter-spacer" aria-hidden />
            <div ref={industryFilterRef} className="lead-log-industry-filter">
              <div className="lead-log-industry-filter-wrapper">
                <div
                  className="lead-log-industry-filter-container lead-log-industry-filter-bar-trigger"
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
                    className="lead-log-industry-filter-input focus-visible:ring-0 focus-visible:ring-transparent focus-visible:border-none focus-visible:ring-offset-0"
                  />
                  <ChevronDown
                    className="lead-log-industry-filter-icon lead-log-industry-filter-chevron"
                    size={14}
                    strokeWidth={2}
                    aria-hidden
                    style={{
                      flexShrink: 0,
                      transform: isIndustryDropdownOpen ? 'rotate(180deg)' : 'rotate(0deg)',
                      transition: 'transform 0.2s',
                    }}
                  />
                </div>
              
              {/* Dropdown List */}
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
          </div>
        </div>
        </div>

        {/* Scrollable Card Area */}
        <div className="lead-log-scrollable-cards" style={{ flex: '1 1 0%', minHeight: 0, overflowY: 'auto', paddingBottom: '8px' }}>
          <div className="inbox-thread-grid">
            {isLoading ? (
              <div style={{ gridColumn: '1 / -1', textAlign: 'center', padding: '40px', color: '#6B7280' }}>Loading...</div>
            ) : displayedLogs.length === 0 ? (
              <div className="lead-log-scrollable-empty">
                <EmptyState
                  iconPath="/lead-log-header.svg"
                  title="No search sessions found."
                  description="Your lead generation history will appear here."
                />
              </div>
            ) : (
              displayedLogs.map((log) => {
                const n = log.lead_count ?? 0;
                return (
                  <div
                    key={log.id}
                    className="inbox-campaign-card"
                    role="button"
                    tabIndex={0}
                    onClick={() => fetchLogDetails(log.id)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        fetchLogDetails(log.id);
                      }
                    }}
                  >
                    <div className="inbox-campaign-card-row">
                      <div className="inbox-campaign-card-text">
                        <h3 className="inbox-campaign-card-title">
                          {log.chat_title || log.query}
                        </h3>
                        <p className="inbox-campaign-card-meta">
                          <span className="inbox-campaign-card-sent-label">Created on: </span>
                          <span className="inbox-campaign-card-sent-value">
                            {formatSessionCardTimestamp(log.created_at)}
                          </span>
                        </p>
                      </div>
                      <span className="inbox-campaign-card-leads-badge" title="Leads in this session">
                        {n} Lead{n === 1 ? '' : 's'}
                      </span>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Fixed Pagination at Bottom - Shared design */}
        <div className="dashboard-pagination-fixed">
          <DashboardPagination
            totalItems={filteredLogs.length}
            currentPage={currentPage}
            itemsPerPage={itemsPerPage}
            onPageChange={setCurrentPage}
            onItemsPerPageChange={(v) => { setItemsPerPage(v); setCurrentPage(1); }}
            itemLabel="sessions"
          />
        </div>
      </div>
    </div>
  );
}
