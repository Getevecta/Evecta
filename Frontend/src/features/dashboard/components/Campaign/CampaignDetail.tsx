import { useState, useEffect, useRef } from 'react';
import { ArrowLeft, Search, Filter, Plus, Calendar, Send, Users, TrendingUp, Reply, AlertCircle, ChevronDown, Eye, Check, Clock, Mail, XCircle } from 'lucide-react';
import { DashboardPagination } from '../ui/DashboardPagination';
import '../ui/DashboardPagination.css';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../ui/tabs';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../ui/table';
import { apiService, CampaignResponse, CampaignInsightResponse } from '../../../../shared/services/api';
import { toast } from 'sonner';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { PreviewContentModal } from './PreviewContentModal';
import { EmptyState } from '../ui/EmptyState';
import '../LeadDatabase/LeadDatabase.css';
import '../LeadLog/LeadLog.css';
import '../Inbox/Inbox.css';
import './CampaignDetail.css';

interface CampaignDetailProps {
  campaignId?: string;
  onToggleSidebar?: () => void;
  onBack?: () => void;
}

interface Lead {
  id: string;
  name: string;
  company: string;
  title: string;
  email: string;
  phone: string;
  location: string;
  tags: string[];
  website?: string;
  score: number;
  starred: boolean;
  status?: string;
}

type MetricTheme = 'purple' | 'green' | 'orange' | 'red' | 'yellow';

export function CampaignDetail({ campaignId, onToggleSidebar, onBack }: CampaignDetailProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(10);
  const [selectedLeads, setSelectedLeads] = useState<Set<string>>(new Set());
  const [campaign, setCampaign] = useState<CampaignResponse | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [insights, setInsights] = useState<CampaignInsightResponse | null>(null);
  const [isLoadingInsights, setIsLoadingInsights] = useState(false);
  const [selectedTimeRange, setSelectedTimeRange] = useState<'7' | '30' | '90' | 'custom'>('custom');
  const [showCalendar, setShowCalendar] = useState(false);
  const [startDate, setStartDate] = useState(() => {
    const date = new Date();
    date.setDate(date.getDate() - 6); // Default to 7 days (today - 6 days = 7 days total)
    return date.toISOString().split('T')[0];
  });
  const [endDate, setEndDate] = useState(() => {
    return new Date().toISOString().split('T')[0];
  });
  const [dateRangeError, setDateRangeError] = useState<string>('');
  const [showPreviewContentModal, setShowPreviewContentModal] = useState(false);
  const [emailFilter, setEmailFilter] = useState<'all' | 'has_email' | 'no_email'>('all');
  const [showEmailFilterDropdown, setShowEmailFilterDropdown] = useState(false);
  const emailFilterButtonRef = useRef<HTMLButtonElement>(null);
  const emailFilterDropdownRef = useRef<HTMLDivElement>(null);
  const calendarRef = useRef<HTMLDivElement>(null);
  const campaignIdRef = useRef(campaignId);
  campaignIdRef.current = campaignId;
  
  // Calculate max end date (7 days from start date)
  const getMaxEndDate = (start: string) => {
    if (!start) return '';
    const startDateObj = new Date(start);
    const maxDate = new Date(startDateObj);
    maxDate.setDate(maxDate.getDate() + 6); // 7 days total (including start and end)
    return maxDate.toISOString().split('T')[0];
  };
  
  // Validate date range is not more than 7 days
  const validateDateRange = (start: string, end: string): boolean => {
    if (!start || !end) return false;
    const startDateObj = new Date(start);
    const endDateObj = new Date(end);
    const diffTime = Math.abs(endDateObj.getTime() - startDateObj.getTime());
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    return diffDays <= 6; // 0-6 days difference = 7 days total
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

  // Format date for display (e.g., "Dec 1, 2025")
  const formatDateForDisplay = (dateString: string): string => {
    if (!dateString) return '';
    const date = new Date(dateString);
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return `${months[date.getMonth()]} ${date.getDate()}, ${date.getFullYear()}`;
  };

  // Fetch campaign data and leads
  useEffect(() => {
    if (!campaignId) {
      toast.error('Campaign ID is missing');
      setIsLoading(false);
      return;
    }

    // Clear previous campaign data immediately so Failed/Sent metrics never
    // bleed from another campaign while the new one loads.
    setCampaign(null);
    setLeads([]);
    setInsights(null);
    setSelectedLeads(new Set());
    setCurrentPage(1);

    const fetchCampaignData = async () => {
      setIsLoading(true);
      try {
        // Fetch campaign details
        const campaignResponse = await apiService.getCampaignLaunchView(campaignId);
        if (campaignIdRef.current !== campaignId) return;

        if (campaignResponse.data) {
          setCampaign(campaignResponse.data.campaign);
          
          // Fetch insights if campaign is ongoing or sent
          if (campaignResponse.data.campaign.status === 'ongoing' || campaignResponse.data.campaign.status === 'sent') {
            fetchCampaignInsights(campaignId, startDate, endDate);
          }
        }

        // Fetch campaign leads (includes snapshot data for deleted leads)
        const leadsResponse = await apiService.getCampaignLeads(campaignId);
        if (campaignIdRef.current !== campaignId) return;

        if (leadsResponse.data && Array.isArray(leadsResponse.data)) {
          const campaignLeads = leadsResponse.data;

          // Map campaign lead responses to Lead objects, using snapshot if lead is deleted
          const fetchedLeads: Lead[] = campaignLeads
            .map((campaignLead: any) => {
              const leadInfo = campaignLead.lead;
              if (!leadInfo?.id) return null;

              // Normalize email status for display. Backend returns values like "sent", "opened", etc.
              const rawStatus: string | undefined = campaignLead.email_status || undefined;
              const status = rawStatus
                ? rawStatus.charAt(0).toUpperCase() + rawStatus.slice(1)
                : 'Not sent';

              const lead: Lead = {
                id: leadInfo.id,
                name: leadInfo.business_name || 'N/A',
                company: leadInfo.business_name || 'N/A',
                title: '', // Not available in snapshot
                email: leadInfo.email || 'N/A',
                phone: leadInfo.contact_number || '',
                location: leadInfo.address || 'N/A',
                tags: leadInfo.industry ? (Array.isArray(leadInfo.industry) ? leadInfo.industry : [leadInfo.industry]) : [],
                website: leadInfo.website,
                score: leadInfo.lead_score || 0,
                starred: false,
                status,
              };
              return lead;
            })
            .filter((lead): lead is Lead => lead !== null);

          setLeads(fetchedLeads);
        }
      } catch (error: any) {
        if (campaignIdRef.current !== campaignId) return;
        console.error('Failed to fetch campaign data:', error);
        toast.error('Failed to load campaign details');
      } finally {
        if (campaignIdRef.current === campaignId) {
          setIsLoading(false);
        }
      }
    };

    fetchCampaignData();
  }, [campaignId]);

  // Refetch insights when date range changes
  useEffect(() => {
    if (campaignId && campaign && (campaign.status === 'ongoing' || campaign.status === 'sent') && startDate && endDate) {
      fetchCampaignInsights(campaignId, startDate, endDate);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [startDate, endDate]);

  // Fetch campaign insights
  const fetchCampaignInsights = async (id: string, startDate?: string, endDate?: string) => {
    setIsLoadingInsights(true);
    try {
      const response = await apiService.getCampaignInsight(id, startDate, endDate);
      // Ignore stale responses from a previously opened campaign
      if (campaignIdRef.current !== id) return;

      if (response.data) {
        setInsights(response.data);
      } else {
        setInsights(null);
      }
    } catch (error: any) {
      if (campaignIdRef.current !== id) return;
      console.error('Failed to fetch campaign insights:', error);
      setInsights(null);
      // Don't show error toast - insights might not be available for all campaigns
    } finally {
      if (campaignIdRef.current === id) {
        setIsLoadingInsights(false);
      }
    }
  };

  // Close calendar when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (calendarRef.current && !calendarRef.current.contains(event.target as Node)) {
        setShowCalendar(false);
      }
    };

    if (showCalendar) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [showCalendar]);

  // Helper function to generate path data for graph (with padding from axes)
  const generatePathData = (data: number[], maxValue: number) => {
    if (data.length === 0) return '';
    const paddingTop = 20; // Padding from top
    const paddingBottom = 20; // Padding from bottom
    const paddingLeft = 30; // Padding from left (y-axis) - increased for better spacing
    const chartHeight = 200 - paddingTop - paddingBottom; // Adjusted height
    const chartBottom = 240 - paddingBottom; // Bottom position with padding
    const chartLeft = 40 + paddingLeft; // Left position with padding (starts at x=70)
    const chartWidth = 520 - (paddingLeft * 2); // Adjusted width (subtract padding from both sides
    
    const points = data.map((value, index) => {
      // X position with padding from y-axis - distribute points across available width
      const x = chartLeft + (index * (chartWidth / (data.length - 1 || 1)));
      // Calculate y with padding - ensure it doesn't touch bottom or top
      const normalizedValue = value / maxValue;
      const y = chartBottom - (normalizedValue * chartHeight);
      // Ensure minimum padding from bottom and top
      const minY = chartBottom - chartHeight;
      const maxY = chartBottom - paddingTop;
      const finalY = Math.max(minY, Math.min(maxY, y));
      return `${x},${finalY}`;
    });
    return `M ${points.join(' L ')}`;
  };

  // Helper function to generate area path (with padding from axes)
  const generateAreaPath = (data: number[], maxValue: number) => {
    if (data.length === 0) return '';
    const paddingBottom = 20;
    const paddingLeft = 30;
    const chartBottom = 240 - paddingBottom;
    const chartLeft = 40 + paddingLeft;
    const chartWidth = 520 - (paddingLeft * 2);
    const linePath = generatePathData(data, maxValue);
    const lastX = chartLeft + ((data.length - 1) * (chartWidth / (data.length - 1 || 1)));
    return `${linePath} L ${lastX},${chartBottom} Z`;
  };

  // Helper function to generate stacked area path (for stacked area chart)
  const generateStackedAreaPath = (data: number[], baseData: number[], maxValue: number) => {
    if (data.length === 0) return '';
    const paddingTop = 20;
    const paddingBottom = 20;
    const paddingLeft = 30;
    const chartHeight = 200 - paddingTop - paddingBottom;
    const chartBottom = 240 - paddingBottom;
    const chartLeft = 40 + paddingLeft;
    const chartWidth = 520 - (paddingLeft * 2);
    
    // Generate top line points (data + base) - left to right
    const topPoints: string[] = [];
    // Generate bottom line points (base) - left to right
    const bottomPoints: string[] = [];
    
    for (let i = 0; i < data.length; i++) {
      const x = chartLeft + (i * (chartWidth / (data.length - 1 || 1)));
      const baseValue = baseData[i] || 0;
      const topValue = data[i] + baseValue;
      const bottomValue = baseValue;
      
      // Top point
      const normalizedTop = topValue / maxValue;
      let topY = chartBottom - (normalizedTop * chartHeight);
      const minY = chartBottom - chartHeight;
      const maxY = chartBottom - paddingTop;
      topY = Math.max(minY, Math.min(maxY, topY));
      topPoints.push(`${x},${topY}`);
      
      // Bottom point
      const normalizedBottom = bottomValue / maxValue;
      let bottomY = chartBottom - (normalizedBottom * chartHeight);
      bottomY = Math.max(minY, Math.min(maxY, bottomY));
      bottomPoints.push(`${x},${bottomY}`);
    }
    
    // Build path: start at first bottom point, draw bottom line left to right, then top line right to left, close
    const bottomPath = bottomPoints.join(' L ');
    const topPathReversed = [...topPoints].reverse().join(' L ');
    const path = `M ${bottomPoints[0]} L ${bottomPath} L ${topPathReversed} Z`;
    
    return path;
  };

  // Get cumulative data for each metric
  const getCumulativeData = (metric: 'sent' | 'opened' | 'clicked' | 'bounced') => {
    if (!insights || !insights.daily_stats || insights.daily_stats.length === 0) {
      return [];
    }
    let cumulative = 0;
    return insights.daily_stats.map(stat => {
      cumulative += stat[metric];
      return cumulative;
    });
  };

  // Get not opened data (sent - opened)
  const getNotOpenedData = () => {
    if (!insights || !insights.daily_stats || insights.daily_stats.length === 0) {
      return [];
    }
    let cumulativeSent = 0;
    let cumulativeOpened = 0;
    return insights.daily_stats.map(stat => {
      cumulativeSent += stat.sent;
      cumulativeOpened += stat.opened;
      return cumulativeSent - cumulativeOpened;
    });
  };

  // Get replied data (using clicked as proxy)
  const getRepliedData = () => {
    return getCumulativeData('clicked');
  };

  // Calculate max value for scaling (based on all metrics)
  const getMaxValue = () => {
    if (!insights || !insights.daily_stats || insights.daily_stats.length === 0) {
      return 200; // Default max
    }
    const sentData = getCumulativeData('sent');
    const openedData = getCumulativeData('opened');
    const clickedData = getCumulativeData('clicked');
    const bouncedData = getCumulativeData('bounced');
    const notOpenedData = getNotOpenedData();
    const repliedData = getRepliedData();
    
    const allData = [...sentData, ...openedData, ...clickedData, ...bouncedData, ...notOpenedData, ...repliedData];
    const max = Math.max(...allData, 1);
    // Round up to nearest 50 for cleaner graph
    return Math.ceil(max / 50) * 50 || 50;
  };

  // Get Y-axis labels based on max value
  const getYAxisLabels = (max: number) => {
    const steps = 4;
    const labels = [];
    for (let i = 0; i <= steps; i++) {
      labels.push(Math.round((max / steps) * i));
    }
    return labels;
  };

  // Use campaign data or fallback
  const campaignData = campaign || {
    id: campaignId || '1',
    name: 'Loading...',
    status: 'draft' as const,
    description: '',
    created_at: new Date().toISOString(),
    lead_count: 0,
    avg_lead_score: 0
  };

  const filteredLeads = leads.filter(lead => {
    const matchesSearch = 
      lead.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      lead.company.toLowerCase().includes(searchQuery.toLowerCase()) ||
      lead.email.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (lead.tags && lead.tags.some(tag => tag.toLowerCase().includes(searchQuery.toLowerCase())));
    // Apply email filter
    if (emailFilter === 'has_email') {
      if (!lead.email || lead.email === 'N/A' || lead.email.trim() === '') return false;
    } else if (emailFilter === 'no_email') {
      if (lead.email && lead.email !== 'N/A' && lead.email.trim() !== '') return false;
    }
    return matchesSearch;
  });

  const paginatedLeads = filteredLeads.slice(
    (currentPage - 1) * itemsPerPage,
    currentPage * itemsPerPage
  );

  const totalPages = Math.ceil(filteredLeads.length / itemsPerPage);

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'draft':
        return { bg: '#F97316', text: '#FFFFFF', border: '#F97316' };
      case 'ongoing':
        return { bg: '#6B21A8', text: '#FFFFFF', border: '#6B21A8' };
      case 'completed':
        return { bg: '#D1FAE5', text: '#065F46', border: '#6EE7B7' };
      case 'paused':
        return { bg: '#F3F4F6', text: '#374151', border: '#D1D5DB' };
      default:
        return { bg: '#F3F4F6', text: '#374151', border: '#D1D5DB' };
    }
  };

  const statusColors = getStatusColor(campaignData.status);
  const isCampaignOngoing = campaignData.status === 'ongoing' || campaignData.status === 'sent';

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  };

  // Show loading state
  if (isLoading) {
    return (
      <div className="campaign-detail-loading-container">
        <p className="campaign-detail-loading-text">Loading campaign details...</p>
      </div>
    );
  }

  return (
    <div className={`campaign-detail-main-container${isCampaignOngoing ? ' campaign-detail-ongoing' : ''}`}>
      <div className="campaign-detail-scroll-container">
      <div className="campaign-detail-upper-section">
      {/* Header - single frame: arrow, campaign name (same line), calendar, three-dot horizontal + description & info below */}
      <div className="campaign-detail-header">
        <div className="campaign-detail-header-single-frame">
          {/* Top row: ArrowLeft, then column (name + description + created on) aligned, then calendar, three-dot */}
          <div className="campaign-detail-header-top-row">
            <button
              type="button"
              onClick={onBack}
              className="campaign-detail-back-arrow-button"
              aria-label="Back"
            >
              <ArrowLeft className="campaign-detail-back-arrow-icon" size={22} />
            </button>
            <div className="campaign-detail-header-text-column">
              <h1 className="campaign-detail-title heading-xl campaign-detail-title-inline">
                {campaignData.name}
              </h1>
              <p className="campaign-detail-description campaign-detail-description-in-frame">
                {campaignData.description || 'No description'}
              </p>
              <div className="campaign-detail-info-row campaign-detail-info-row-in-frame">
                <div className="campaign-detail-info-item">
                  <Calendar className="campaign-detail-info-icon" />
                  <span>Created On: <span className="campaign-detail-info-value">{formatDate(campaignData.created_at)}</span></span>
                </div>
                <div className="campaign-detail-info-item">
                  <Send className="campaign-detail-info-icon" />
                  <span>
                    Launched On:{' '}
                    <span className="campaign-detail-info-value">
                      {campaignData.launched_at ? formatDate(campaignData.launched_at) : '—'}
                    </span>
                  </span>
                </div>
                <div className="campaign-detail-info-item">
                  <Users className="campaign-detail-info-icon" />
                  <span>Leads: <span className="campaign-detail-info-value">{campaignData.lead_count || 0}</span></span>
                </div>
              </div>
            </div>
            {(campaignData.status === 'ongoing' || campaignData.status === 'sent') && (
              <div className="campaign-detail-date-picker-wrapper campaign-detail-header-date-picker" ref={calendarRef}>
                <button
                  type="button"
                  onClick={() => setShowCalendar(!showCalendar)}
                  className="campaign-detail-date-picker-button"
                >
                  <Calendar className="campaign-detail-date-picker-icon" size={20} strokeWidth={2} />
                  <span>
                    {startDate && endDate
                      ? `${formatDateForDisplay(startDate)} - ${formatDateForDisplay(endDate)}`
                      : 'Select date range'}
                  </span>
                </button>
                {showCalendar && (
                  <div className="campaign-detail-calendar-popup">
                    <div className="campaign-detail-calendar-field">
                      <label className="campaign-detail-calendar-label">Start Date</label>
                      <input
                        type="date"
                        value={startDate}
                        onChange={(e) => {
                          const newStartDate = e.target.value;
                          setStartDate(newStartDate);
                          setDateRangeError('');
                          if (endDate && newStartDate) {
                            const maxEnd = getMaxEndDate(newStartDate);
                            if (endDate > maxEnd) setEndDate(maxEnd);
                          }
                        }}
                        max={endDate || new Date().toISOString().split('T')[0]}
                        className="campaign-detail-calendar-input"
                      />
                    </div>
                    <div className="campaign-detail-calendar-field">
                      <label className="campaign-detail-calendar-label">End Date (Max 7 days from start)</label>
                      <input
                        type="date"
                        value={endDate}
                        onChange={(e) => {
                          const newEndDate = e.target.value;
                          if (startDate) {
                            if (validateDateRange(startDate, newEndDate)) {
                              setEndDate(newEndDate);
                              setDateRangeError('');
                            } else {
                              setDateRangeError('Date range cannot exceed 7 days');
                              setEndDate(getMaxEndDate(startDate));
                            }
                          } else setEndDate(newEndDate);
                        }}
                        min={startDate}
                        max={startDate ? getMaxEndDate(startDate) : new Date().toISOString().split('T')[0]}
                        className="campaign-detail-calendar-input"
                      />
                      {dateRangeError && (
                        <p style={{ color: '#EF4444', fontSize: '11px', marginTop: '4px' }}>{dateRangeError}</p>
                      )}
                    </div>
                    <div className="campaign-detail-calendar-actions">
                      <button type="button" onClick={() => { setStartDate(''); setEndDate(''); setShowCalendar(false); }} className="campaign-detail-calendar-cancel-button">Cancel</button>
                      <button
                        type="button"
                        onClick={() => {
                          if (startDate && endDate) {
                            if (validateDateRange(startDate, endDate)) {
                              setShowCalendar(false);
                              setDateRangeError('');
                              if (campaignId) fetchCampaignInsights(campaignId, startDate, endDate);
                            } else {
                              toast.error('Date range cannot exceed 7 days. Please select a range within 7 days.');
                              setDateRangeError('Date range cannot exceed 7 days');
                            }
                          } else toast.error('Please select both start and end dates');
                        }}
                        className="campaign-detail-calendar-apply-button"
                      >
                        Apply
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
            <div className="campaign-detail-header-dot-menu-wrapper">
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setShowPreviewContentModal(true);
                }}
                className="campaign-detail-header-dot-button campaign-detail-header-preview-eye-button"
                aria-label="Preview content"
              >
                <Eye size={20} strokeWidth={2} className="campaign-detail-header-dot-icon" />
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Campaign Progress Over Time Section - Show for ongoing and sent campaigns */}
      {(campaignData.status === 'ongoing' || campaignData.status === 'sent') && (
        <>
        <div className="campaign-detail-progress-section">
        <div className="campaign-detail-progress-header">
          <div className="campaign-detail-progress-header-content">
            <h2 className="campaign-detail-progress-title heading-l">
              Campaign Progress Over Time
            </h2>
            <p className="campaign-detail-progress-description">
              Track your campaign's performance across key engagement metrics.
            </p>
            <div className="campaign-detail-progress-description-line" aria-hidden="true" />
          </div>
        </div>

        {/* Stats Cards - Top Section */}
        <div className="campaign-detail-stats-cards">
          {(() => {
            const totalLeads = leads.length;
            const totalSent = insights?.total_sent || 0;
            const totalOpened = insights?.total_opened || 0;
            const totalBounced = insights?.total_bounced || 0;
            const openRate = totalSent > 0 ? (totalOpened / totalSent) * 100 : 0;
            const bounceRate = totalSent > 0 ? (totalBounced / totalSent) * 100 : 0;
            const totalReplied = insights?.total_replied || 0;
            const replyRate = totalSent > 0 ? (totalReplied / totalSent) * 100 : 0;
            const stats: Array<{
              label: string;
              value: string;
              subtext: string;
              theme: MetricTheme;
              Icon: typeof Send;
              badge?: string;
              valueAccent?: boolean;
            }> = [
              { label: 'Total Sent', value: totalSent.toString(), subtext: `Of ${totalLeads} leads`, theme: 'purple', Icon: Send },
              { label: 'Open Rate', value: `${openRate.toFixed(0)}%`, subtext: `${totalOpened} opened`, theme: 'green', Icon: Eye },
              { label: 'Reply Rate', value: `${replyRate.toFixed(0)}%`, subtext: `${totalReplied} ${totalReplied === 1 ? 'reply' : 'replies'}`, theme: 'orange', Icon: Reply },
              {
                label: 'Bounce Rate',
                value: `${bounceRate.toFixed(0)}%`,
                subtext: 'Out of 100',
                theme: 'red',
                Icon: TrendingUp,
                badge: bounceRate >= 5 ? 'High Bounce' : undefined,
                valueAccent: bounceRate >= 5,
              },
            ];
            return stats.map((stat) => {
              const IconComponent = stat.Icon;
              return (
                <div key={stat.label} className={`campaign-detail-metric-card campaign-detail-metric-card--${stat.theme}`}>
                  <div className="campaign-detail-metric-card-header">
                    <div className="campaign-detail-metric-card-icon-wrap">
                      <IconComponent size={16} strokeWidth={2} />
                    </div>
                    <span className="campaign-detail-metric-card-title">{stat.label}</span>
                  </div>
                  <div className={`campaign-detail-metric-card-value${stat.valueAccent ? ' campaign-detail-metric-card-value--accent' : ''}`}>
                    {stat.value}
                  </div>
                  <div className="campaign-detail-metric-card-meta">
                    <span className="campaign-detail-metric-card-subtext">{stat.subtext}</span>
                    {stat.badge && <span className="campaign-detail-metric-card-badge">{stat.badge}</span>}
                  </div>
                </div>
              );
            });
          })()}
        </div>

        {/* Campaign Outreach Progress Section */}
        <div className="campaign-detail-outreach-progress-section">
          {/* Background SVG */}
          <div className="campaign-detail-outreach-progress-background" />
          {/* Content */}
          <div className="campaign-detail-outreach-progress-content">
          <div className="campaign-detail-outreach-progress-header">
            <div className="campaign-detail-outreach-progress-header-content">
              <h2 className="campaign-detail-outreach-progress-title heading-l" style={{ fontSize: '14px' }}>
                Daily Campaign Progress
              </h2>
              <p className="campaign-detail-outreach-progress-description">
                Track your daily outreach progress and completion timeline.
              </p>
              <div className="campaign-detail-outreach-progress-description-line" aria-hidden="true" />
            </div>
          </div>

          {/* Outreach Metrics Cards */}
          <div className="campaign-detail-outreach-metrics">
            {(() => {
              // Use backend tracking metrics if available, otherwise fallback to frontend calculation
              const tracking = insights?.tracking;
              const totalLeads = tracking?.total_leads ?? leads.length;
              const outreachedToday = tracking?.outreached_today ?? 0;
              const totalOutreached = tracking?.total_outreached ?? (insights?.total_sent || 0);
              const failed = tracking?.failed ?? insights?.total_failed ?? leads.filter(lead => lead.status.toLowerCase() === 'failed').length;
              const remaining = tracking?.remaining ?? Math.max(0, totalLeads - (insights?.total_sent || 0) - failed);
              const estimatedDays = tracking?.estimated_completion_days ?? null;
              const estimatedDate = tracking?.estimated_completion_date ?? null;

              const dailyRate = tracking?.daily_outreach_rate ?? 0;
              const clampPct = (n: number) => Math.min(100, Math.max(0, Math.round(n)));
              const todayPct = dailyRate > 0
                ? clampPct((outreachedToday / dailyRate) * 100)
                : (outreachedToday > 0 ? 100 : 0);
              const totalPct = totalLeads > 0 ? clampPct((totalOutreached / totalLeads) * 100) : 0;
              const failedPct = totalLeads > 0 ? clampPct((failed / totalLeads) * 100) : 0;
              const remainingPct = totalLeads > 0 ? clampPct((remaining / totalLeads) * 100) : 0;
              const estPct = totalLeads > 0 ? clampPct(((totalLeads - remaining) / totalLeads) * 100) : 0;
              const isCompleted = totalLeads > 0 && remaining === 0;

              let estValue = '—';
              let estSubtext = 'No estimate available';

              if (isCompleted) {
                estValue = 'Done';
                estSubtext = failed > 0 ? `${failed} of ${totalLeads} leads failed` : 'All Leads Contacted';
              } else if (estimatedDays != null && estimatedDays >= 0) {
                estValue = `${estimatedDays} Day${estimatedDays === 1 ? '' : 's'}`;
                estSubtext = 'All Leads Contacted';
              } else if (estimatedDate) {
                estValue = new Date(`${estimatedDate}T00:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
                estSubtext = 'Estimated completion';
              } else if (remaining > 0) {
                estSubtext = 'Sending not active';
              }

              const outreachStats: Array<{
                label: string;
                value: string;
                subtext: string;
                theme: MetricTheme;
                Icon: typeof Send;
                progress: number;
              }> = [
                { label: 'Outreach Today', value: outreachedToday.toString(), subtext: 'Leads Contacted', theme: 'purple', Icon: Send, progress: todayPct },
                { label: 'Total Outreached', value: totalOutreached.toString(), subtext: `Of ${totalLeads} leads`, theme: 'purple', Icon: Users, progress: totalPct },
                { label: 'Failed', value: failed.toString(), subtext: 'Send Failed', theme: 'red', Icon: XCircle, progress: failedPct },
                { label: 'Remaining', value: remaining.toString(), subtext: 'Leads Pending', theme: 'yellow', Icon: Clock, progress: remainingPct },
                {
                  label: isCompleted ? 'Completed' : 'Est. Completion',
                  value: estValue,
                  subtext: estSubtext,
                  theme: 'purple',
                  Icon: Calendar,
                  progress: estPct,
                },
              ];
              return outreachStats.map((stat) => {
                const IconComponent = stat.Icon;
                return (
                  <div key={stat.label} className={`campaign-detail-metric-card campaign-detail-metric-card--outreach campaign-detail-metric-card--${stat.theme}`}>
                    <div className="campaign-detail-metric-card-header">
                      <div className="campaign-detail-metric-card-icon-wrap">
                        <IconComponent size={16} strokeWidth={2} />
                      </div>
                      <span className="campaign-detail-metric-card-title">{stat.label}</span>
                    </div>
                    <div className="campaign-detail-metric-card-value">{stat.value}</div>
                    <div className="campaign-detail-metric-card-subtext">{stat.subtext}</div>
                    <div className="campaign-detail-metric-progress">
                      <div className="campaign-detail-metric-progress-track">
                        <div className="campaign-detail-metric-progress-fill" style={{ width: `${stat.progress}%` }} />
                      </div>
                      <span className="campaign-detail-metric-progress-label">{stat.progress}%</span>
                    </div>
                  </div>
                );
              });
            })()}
          </div>

          {/* Daily Outreach Rate from system mail - design: A198CE 10% bg, 9164FF 20% border */}
          <div className="campaign-detail-daily-outreach-block">
            <div className="campaign-detail-daily-outreach-content">
              <div className="campaign-detail-daily-outreach-text">
                <h2 className="campaign-detail-daily-outreach-title">
                  Daily Outreach Rate from{' '}
                  {campaignData?.email_sending_mode === 'SYSTEM'
                    ? 'system mail'
                    : campaignData?.email_sending_mode === 'USER' && campaignData?.sender_email
                      ? `Gmail (${campaignData.sender_email})`
                      : campaignData?.email_sending_mode === 'USER'
                        ? 'your email'
                        : 'system mail'}
                </h2>
                <p className="campaign-detail-daily-outreach-description">Automated email sending schedule</p>
              </div>
              <div className="campaign-detail-daily-outreach-rate">
                <span className="campaign-detail-daily-outreach-rate-value">{insights?.tracking?.daily_outreach_rate ?? '—'}</span>
                <span className="campaign-detail-daily-outreach-rate-label">emails per day</span>
              </div>
            </div>
          </div>
        </div>

          {/* Chart Area */}
          <div className="campaign-detail-chart-area">
            {(() => {
              const dailyStats = insights?.daily_stats || [];
              const totalSent = insights?.total_sent || 0;
              const totalOpened = insights?.total_opened || 0;
              const totalBounced = insights?.total_bounced || 0;
              const totalClicked = insights?.total_clicked || 0;
              
              // Prepare chart data with Sent (count) and rates (percentages)
              // Calculate cumulative values and rates
              let maxSentValue = 0;
              let maxRateValue = 0;
              
              const chartData = dailyStats.length > 0 ? dailyStats.map((stat, index) => {
                let cumulativeSent = 0;
                let cumulativeOpened = 0;
                let cumulativeBounced = 0;
                let cumulativeReplied = 0;
                
                for (let i = 0; i <= index; i++) {
                  cumulativeSent += dailyStats[i].sent || 0;
                  cumulativeOpened += dailyStats[i].opened || 0;
                  cumulativeBounced += dailyStats[i].bounced || 0;
                  // Real replied count from the backend — never derived from clicks
                  cumulativeReplied += dailyStats[i].replied || 0;
                }
                
                // Calculate rates as percentages
                const openRate = cumulativeSent > 0 ? (cumulativeOpened / cumulativeSent) * 100 : 0;
                const bounceRate = cumulativeSent > 0 ? (cumulativeBounced / cumulativeSent) * 100 : 0;
                const replyRate = cumulativeSent > 0 ? (cumulativeReplied / cumulativeSent) * 100 : 0;
                
                // Update max values for scaling
                maxSentValue = Math.max(maxSentValue, cumulativeSent);
                maxRateValue = Math.max(maxRateValue, openRate, bounceRate, replyRate);
                
                // X-axis: Monday, Tuesday, ..., Sunday (getDay() 0=Sun,1=Mon -> map to Mon=0..Sun=6)
                const dayNames = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
                let dateStr: string;
                if (stat.date) {
                  const d = new Date(stat.date);
                  dateStr = dayNames[(d.getDay() + 6) % 7] ?? dayNames[index % 7];
                } else {
                  dateStr = dayNames[index % 7];
                }
                
                return {
                  date: dateStr,
                  Sent: cumulativeSent,
                  'Open Rate': Math.round(openRate * 10) / 10, // Round to 1 decimal
                  'Bounce Rate': Math.round(bounceRate * 10) / 10,
                  'Reply Rate': Math.round(replyRate * 10) / 10
                };
              }) : [
                { date: 'Monday', Sent: 0, 'Open Rate': 0, 'Bounce Rate': 0, 'Reply Rate': 0 },
                { date: 'Tuesday', Sent: 0, 'Open Rate': 0, 'Bounce Rate': 0, 'Reply Rate': 0 },
                { date: 'Wednesday', Sent: 0, 'Open Rate': 0, 'Bounce Rate': 0, 'Reply Rate': 0 },
                { date: 'Thursday', Sent: 0, 'Open Rate': 0, 'Bounce Rate': 0, 'Reply Rate': 0 },
                { date: 'Friday', Sent: 0, 'Open Rate': 0, 'Bounce Rate': 0, 'Reply Rate': 0 },
                { date: 'Saturday', Sent: 0, 'Open Rate': 0, 'Bounce Rate': 0, 'Reply Rate': 0 },
                { date: 'Sunday', Sent: 0, 'Open Rate': 0, 'Bounce Rate': 0, 'Reply Rate': 0 }
              ];
              
              // Normalize Sent to 0-100 scale to match rates
              // We'll scale Sent proportionally so it fits on the same Y-axis
              // Store original Sent value for tooltip display
              const clampPct = (n: number) => Math.min(100, Math.max(0, n));
              const normalizedChartData = chartData.map(item => {
                const originalSent = item.Sent;
                const normalizedSent = maxSentValue > 0 ? (item.Sent / maxSentValue) * 100 : 0;
                return {
                  ...item,
                  Sent: clampPct(Math.round(normalizedSent * 10) / 10),
                  'Open Rate': clampPct(item['Open Rate']),
                  'Bounce Rate': clampPct(item['Bounce Rate']),
                  'Reply Rate': clampPct(item['Reply Rate']),
                  _originalSent: originalSent
                };
              });
              
              // Y-axis: 10, 20, 30, ..., 100
              const yAxisMax = 100;
              const yAxisTicks = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100];
              
                      return (
                <>
                  {isLoadingInsights && (
                    <div className="campaign-detail-chart-loading">
                      Loading insights...
                    </div>
                  )}
                  
                  <ResponsiveContainer width="100%" height={400}>
                    <LineChart
                      data={normalizedChartData}
                      margin={{ top: 16, right: 10, left: 8, bottom: 28 }}
                    >
                      <XAxis
                        dataKey="date"
                        stroke="#a198ce"
                        tick={{ fontSize: 10, fill: '#a198ce' }}
                        tickFormatter={(v) => String(v).toUpperCase()}
                        axisLine={{ stroke: '#FF0004', strokeWidth: 1, fill: 'none' }}
                        tickLine={{ stroke: '#a198ce', strokeWidth: 1 }}
                        interval={0}
                        angle={0}
                        textAnchor="middle"
                        height={36}
                      />
                      <YAxis
                        domain={[0, 100]}
                        ticks={yAxisTicks}
                        interval={0}
                        stroke="#a198ce"
                        tick={{ fontSize: 11, fill: '#a198ce' }}
                        axisLine={{ stroke: '#a198ce', strokeWidth: 1 }}
                        tickLine={{ stroke: '#a198ce', strokeWidth: 1 }}
                        width={50}
                        tickFormatter={(value) => String(value)}
                        dx={-5}
                        tickMargin={8}
                      />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: '#FFFFFF',
                          borderRadius: '8px',
                          border: '1px solid #E8E4F4',
                          boxShadow: '0 4px 14px rgba(15, 23, 42, 0.12)',
                          padding: '10px 12px',
                        }}
                        formatter={(value: number, name: string, props: any) => {
                          if (name === 'Sent') {
                            const originalSent = props.payload?._originalSent ?? value;
                            return [`${Math.round(Number(originalSent))}`, 'Sent'];
                          }
                          return [`${Number(value).toFixed(1)}%`, name];
                        }}
                        labelStyle={{ color: '#111827', fontWeight: 700, fontSize: 13 }}
                        itemStyle={{ fontWeight: 500, color: '#374151', fontSize: 12 }}
                      />
                      <Line type="monotone" dataKey="Sent" stroke="#9164FF" strokeWidth={2.5} dot={false} connectNulls isAnimationActive={false} activeDot={{ r: 4, fill: '#9164FF' }} />
                      <Line type="monotone" dataKey="Open Rate" stroke="#10B981" strokeWidth={2.5} dot={false} connectNulls isAnimationActive={false} activeDot={{ r: 4, fill: '#10B981' }} />
                      <Line type="monotone" dataKey="Reply Rate" stroke="#F97316" strokeWidth={2.5} dot={false} connectNulls isAnimationActive={false} activeDot={{ r: 4, fill: '#F97316' }} />
                      <Line type="monotone" dataKey="Bounce Rate" stroke="#EF4444" strokeWidth={2.5} dot={false} connectNulls isAnimationActive={false} activeDot={{ r: 4, fill: '#EF4444' }} />
                    </LineChart>
                  </ResponsiveContainer>

                  <div className="campaign-detail-chart-legend-below">
                    <div className="campaign-detail-chart-legend-below-item">
                      <span className="campaign-detail-chart-legend-swatch" style={{ backgroundColor: '#9164FF' }} />
                      <span className="campaign-detail-chart-legend-below-label">Sent</span>
                    </div>
                    <div className="campaign-detail-chart-legend-below-item">
                      <span className="campaign-detail-chart-legend-swatch" style={{ backgroundColor: '#10B981' }} />
                      <span className="campaign-detail-chart-legend-below-label">Open Rate</span>
                    </div>
                    <div className="campaign-detail-chart-legend-below-item">
                      <span className="campaign-detail-chart-legend-swatch" style={{ backgroundColor: '#F97316' }} />
                      <span className="campaign-detail-chart-legend-below-label">Reply Rate</span>
                    </div>
                    <div className="campaign-detail-chart-legend-below-item">
                      <span className="campaign-detail-chart-legend-swatch" style={{ backgroundColor: '#EF4444' }} />
                      <span className="campaign-detail-chart-legend-below-label">Bounce Rate</span>
                    </div>
                  </div>
                </>
              );
            })()}
          </div>
        </div>
        </div>
        </>
      )}
      </div>

      {/* Campaign Leads Section — table scroll + pagination layout matches Lead Database */}
      <div className="campaign-detail-leads-section campaign-detail-leads-section-standalone">
        {/* Title, subtitle, and search on one row — search matches Inbox */}
        <div className="campaign-detail-leads-header-row">
          <div className="campaign-detail-leads-header-text">
            <h2 className="campaign-detail-leads-title heading-l" style={{ fontSize: '14px' }}>
              Campaign Leads
            </h2>
            <p className="campaign-detail-leads-subtitle">
              Manage and track {campaignData.lead_count || 0} leads in this campaign
              {campaignData.email_sending_mode === 'USER' && campaignData.sender_email
                ? ` · From ${campaignData.sender_email}`
                : ''}
            </p>
          </div>
          <div className="inbox-search-filter-container campaign-detail-leads-search-inbox">
            <div className="inbox-search-refresh-wrapper">
              <div className="inbox-search-input-container">
                <Search className="inbox-search-icon" />
                <Input
                  placeholder="Search here..."
                  value={searchQuery}
                  onChange={(e) => {
                    setSearchQuery(e.target.value);
                    setCurrentPage(1);
                  }}
                  className="inbox-search-input"
                />
              </div>
            </div>
          </div>
        </div>

        <div className="campaign-detail-leads-table-pagination dashboard-content-with-pagination">
        {/* Leads Table - same table as Lead Database (shared styles) */}
        <div className="lead-database-table-wrapper lead-database-table-wrapper-styles dashboard-data-table dashboard-pagination-scroll-area">
          {paginatedLeads.length === 0 ? (
            <div className="campaign-detail-leads-empty-state">
              <EmptyState
                iconPath="/finger-cricle.svg"
                title="No leads found."
                description="Try adjusting your search criteria or filters."
              />
            </div>
          ) : (
            <Table className="lead-database-table lead-database-table-styles">
              <TableHeader className="lead-database-table-header-styles">
                <TableRow>
                  <TableHead className="lead-database-table-head-checkbox-styles">
                    <button
                      onClick={() => {
                        if (selectedLeads.size === paginatedLeads.length && paginatedLeads.length > 0) {
                          setSelectedLeads(new Set());
                        } else {
                          setSelectedLeads(new Set(paginatedLeads.map(l => l.id)));
                        }
                      }}
                      className="lead-database-table-checkbox-button"
                    >
                      <div className={`lead-database-table-checkbox-box ${selectedLeads.size === paginatedLeads.length && paginatedLeads.length > 0 ? 'checked' : ''}`}>
                        {selectedLeads.size === paginatedLeads.length && paginatedLeads.length > 0 && (
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
                  <TableHead className="lead-database-table-head-base-styles lead-database-table-head-status">Status</TableHead>
                  <TableHead className="lead-database-table-head-base-styles lead-database-table-head-location">Location</TableHead>
                  <TableHead className="lead-database-table-head-base-styles lead-database-table-head-website">Website</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {paginatedLeads.map((lead) => (
                  <TableRow 
                    key={lead.id} 
                  >
                    <TableCell className="lead-database-table-cell-checkbox-styles">
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
                        className="lead-database-table-checkbox-button"
                      >
                        <div className={`lead-database-table-checkbox-box ${selectedLeads.has(lead.id) ? 'checked' : ''}`}>
                          {selectedLeads.has(lead.id) && (
                            <Check className="lead-database-table-checkbox-check" />
                          )}
                        </div>
                      </button>
                    </TableCell>
                    <TableCell className="lead-database-table-cell-base lead-database-table-cell-company" title={lead.company}>{lead.company}</TableCell>
                    <TableCell className="lead-database-table-cell-base lead-database-table-cell-email" title={lead.email}>{lead.email}</TableCell>
                    <TableCell className="lead-database-table-cell-base lead-database-table-cell-status">
                      {(() => {
                        const s = (lead.status || 'not sent').toLowerCase();
                        const style: React.CSSProperties =
                          s === 'sent'         ? { background: '#D1FAE5', color: '#065F46' } :
                          s === 'opened'       ? { background: '#DBEAFE', color: '#1E40AF' } :
                          s === 'clicked'      ? { background: '#EDE9FE', color: '#5B21B6' } :
                          s === 'bounced'      ? { background: '#FEE2E2', color: '#991B1B' } :
                          s === 'failed'       ? { background: '#FEE2E2', color: '#991B1B' } :
                          s === 'unsubscribed' ? { background: '#FEF3C7', color: '#92400E' } :
                          s === 'queued'       ? { background: '#F3F4F6', color: '#374151' } :
                                                 { background: '#F3F4F6', color: '#374151' };
                        const tooltip =
                          s === 'unsubscribed' ? 'Client has unsubscribed from emails' :
                          s === 'bounced'      ? 'Email bounced — delivery failed' :
                          s === 'failed'       ? 'Email failed to send' :
                          s === 'opened'       ? 'Client opened the email' :
                          s === 'clicked'      ? 'Client clicked a link in the email' :
                          s === 'sent'         ? 'Email sent successfully' :
                          s === 'queued'       ? 'Email is queued to be sent' :
                                                 'No email sent yet';
                        return (
                          <span title={tooltip} style={{
                            ...style,
                            display: 'inline-block',
                            padding: '2px 10px',
                            borderRadius: '999px',
                            fontSize: '12px',
                            fontWeight: 600,
                            cursor: 'default',
                          }}>
                            {lead.status || 'Not sent'}
                          </span>
                        );
                      })()}
                    </TableCell>
                    <TableCell className="lead-database-table-cell-base lead-database-table-cell-location" title={lead.location}>{lead.location}</TableCell>
                    <TableCell className="lead-database-table-cell-base lead-database-table-cell-website" title={lead.website || 'N/A'}>
                      {lead.website && lead.website !== 'N/A' ? (
                        <a 
                          href={lead.website.startsWith('http') ? lead.website : `https://${lead.website}`} 
                          target="_blank" 
                          rel="noopener noreferrer"
                          className="lead-database-table-cell-website-link"
                        >
                          {lead.website}
                        </a>
                      ) : 'N/A'}
                    </TableCell>
                  </TableRow>
                ))}
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
          />
        </div>
        </div>
      </div>
      </div>
      {showPreviewContentModal && campaignId && (
        <PreviewContentModal campaignId={campaignId} onClose={() => setShowPreviewContentModal(false)} />
      )}
    </div>
  );
}
