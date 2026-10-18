import { useState, useEffect } from 'react';
import { Search, Eye, Calendar, Pencil, Trash2, X, Check } from 'lucide-react';
import { DashboardPagination } from '../ui/DashboardPagination';
import { EmptyState } from '../ui/EmptyState';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../ui/tabs';
import { apiService, CampaignInsightResponse } from '../../../../shared/services/api';
import { toast } from 'sonner';
import '../LeadLog/LeadLog.css';
import './Campaign.css';

interface Campaign {
  id: string;
  title: string;
  status: 'draft' | 'ongoing' | 'completed' | 'paused' | 'sent';
  description: string;
  created_at: string;
  leads_count: number;
  avg_score: number;
  email_sending_mode?: 'SYSTEM' | 'USER';
  /** When USER mode, the actual email used (e.g. from selected mailbox). From API if provided. */
  sender_email?: string;
}

interface CampaignProps {
  onToggleSidebar?: () => void;
  onViewChange?: (view: 'campaign-detail' | 'campaign-preview' | 'campaign-creation', campaignId?: string) => void;
  onNavigateToCreateCampaign?: (campaignId?: string) => void;
}

export function Campaign({ onToggleSidebar, onViewChange, onNavigateToCreateCampaign }: CampaignProps) {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeTab, setActiveTab] = useState<'all' | 'draft' | 'ongoing'>('all');
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(10);
  const [selectedCampaigns, setSelectedCampaigns] = useState<Set<string>>(new Set());
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [campaignsToDelete, setCampaignsToDelete] = useState<string[]>([]);
  const [selectedStatus, setSelectedStatus] = useState<string>('all');
  const [campaignInsights, setCampaignInsights] = useState<Record<string, CampaignInsightResponse>>({});
  const [cardMenuOpen, setCardMenuOpen] = useState<string | null>(null);

  // Close card menu when clicking outside
  useEffect(() => {
    if (!cardMenuOpen) return;
    const close = () => setCardMenuOpen(null);
    document.addEventListener('click', close);
    return () => document.removeEventListener('click', close);
  }, [cardMenuOpen]);

  // Fetch campaigns from API
  useEffect(() => {
    fetchCampaigns();
  }, [currentPage, itemsPerPage, searchQuery]);

  const fetchCampaigns = async () => {
    setIsLoading(true);
    try {
      // Fetch campaigns from API
      const response = await apiService.getCampaigns({
        page: currentPage,
        per_page: itemsPerPage,
        search: searchQuery || undefined
      });

      if (response.error) {
        console.error('Failed to fetch campaigns:', response.error);
        toast.error(response.error || 'Failed to load campaigns');
        setCampaigns([]);
        return;
      }

      if (response.data) {
        // Transform API response to match Campaign interface
        const transformedCampaigns: Campaign[] = response.data.data.map((campaign: any) => {
          // Map backend status to frontend status
          // Backend uses lowercase: "draft", "ongoing", "completed"
          // When a campaign is launched, backend sets status to "ongoing"
          // Show "ongoing" campaigns as "sent" to indicate emails have been sent
          let displayStatus: Campaign['status'] = 'ongoing';
          if (campaign.status === 'draft' || campaign.status === 'DRAFT') {
            displayStatus = 'draft';
          } else if (campaign.status === 'ongoing' || campaign.status === 'ONGOING') {
            // Launched campaigns show as "sent"
            displayStatus = 'sent';
          } else if (campaign.status === 'completed' || campaign.status === 'COMPLETED') {
            displayStatus = 'completed';
          } else if (campaign.status === 'paused' || campaign.status === 'PAUSED') {
            displayStatus = 'paused';
          }
          
          return {
            id: campaign.id,
            title: campaign.name,
            status: displayStatus,
            description: campaign.description || '',
            created_at: campaign.created_at,
            leads_count: campaign.lead_count || 0,
            avg_score: Math.round(campaign.avg_lead_score || 0),
            email_sending_mode: campaign.email_sending_mode,
            sender_email: campaign.sender_email ?? campaign.connected_email ?? campaign.email_address
          };
        });

        setCampaigns(transformedCampaigns);
        
        // Fetch insights for ongoing campaigns
        const ongoingCampaigns = transformedCampaigns.filter(c => c.status === 'ongoing' || c.status === 'sent');
        if (ongoingCampaigns.length > 0) {
          fetchCampaignInsights(ongoingCampaigns.map(c => c.id));
        }
      } else {
        setCampaigns([]);
      }
    } catch (error: any) {
      console.error('Failed to fetch campaigns:', error);
      toast.error(error?.message || 'Failed to load campaigns');
      setCampaigns([]);
    } finally {
      setIsLoading(false);
    }
  };

  // Fetch campaign insights for ongoing campaigns
  const fetchCampaignInsights = async (campaignIds: string[]) => {
    const insightsPromises = campaignIds.map(async (campaignId) => {
      try {
        const response = await apiService.getCampaignInsight(campaignId);
        if (response.data) {
          return { campaignId, insight: response.data };
        }
        return null;
      } catch (error) {
        // Silently fail for insights - campaigns might not have insights yet
        return null;
      }
    });

    const results = await Promise.all(insightsPromises);
    const insightsMap: Record<string, CampaignInsightResponse> = {};
    results.forEach(result => {
      if (result) {
        insightsMap[result.campaignId] = result.insight;
      }
    });
    setCampaignInsights(prev => ({ ...prev, ...insightsMap }));
  };

  // Calculate campaign counts
  const formatCount = (count: number) => {
    return count > 99 ? '99+' : count.toString();
  };

  const totalCount = campaigns.length;
  const draftCount = campaigns.filter(c => c.status === 'draft').length;
  const ongoingCount = campaigns.filter(c => c.status === 'ongoing' || c.status === 'sent').length;
  const completedCount = campaigns.filter(c => c.status === 'completed').length;

  const filteredCampaigns = campaigns.filter(campaign => {
    const matchesSearch = (campaign.title || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
                         (campaign.description || '').toLowerCase().includes(searchQuery.toLowerCase());
    
    // If status filter is set, use it instead of tab filter
    if (selectedStatus !== 'all') {
      let matchesStatus = false;
      if (selectedStatus === 'ongoing') {
        matchesStatus = campaign.status === 'ongoing' || campaign.status === 'sent';
      } else if (selectedStatus === 'draft') {
        matchesStatus = campaign.status === 'draft';
      }
      return matchesSearch && matchesStatus;
    }
    
    // Otherwise, use tab filter
    let matchesTab = false;
    if (activeTab === 'all') {
      matchesTab = true;
    } else if (activeTab === 'draft') {
      matchesTab = campaign.status === 'draft';
    } else if (activeTab === 'ongoing') {
      matchesTab = campaign.status === 'ongoing' || campaign.status === 'sent';
    } else if (activeTab === 'completed') {
      matchesTab = campaign.status === 'completed';
    }
    
    return matchesSearch && matchesTab;
  });

  const paginatedCampaigns = filteredCampaigns.slice(
    (currentPage - 1) * itemsPerPage,
    currentPage * itemsPerPage
  );

  const totalPages = Math.ceil(filteredCampaigns.length / itemsPerPage);

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'draft':
        return { bg: '#F97316', text: '#FFFFFF', border: '#F97316' }; // Orange background with white text
      case 'ongoing':
        return { bg: '#3B82F6', text: '#FFFFFF', border: '#3B82F6' }; // Blue background with white text (shown as "Ongoing")
      case 'sent':
        return { bg: '#3B82F6', text: '#FFFFFF', border: '#3B82F6' }; // Blue background with white text (shown as "Ongoing")
      case 'completed':
        return { bg: '#3B82F6', text: '#FFFFFF', border: '#3B82F6' }; // Blue background with white text
      case 'paused':
        return { bg: '#F3F4F6', text: '#374151', border: '#D1D5DB' };
      default:
        return { bg: '#F3F4F6', text: '#374151', border: '#D1D5DB' };
    }
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  };

  return (
    <div className="campaign-main-container">
      {/* Header */}
      <div className="campaign-header-container-mobile">
        {/* Second Line - Title, Description, and Buttons */}
        <div className="campaign-header-mobile">
          {/* Filter Tabs - Left Side */}
          <Tabs className="campaign-tabs-mobile" value={activeTab} onValueChange={(value) => {
            setActiveTab(value as 'all' | 'draft' | 'ongoing');
            setCurrentPage(1);
          }}>
            <TabsList className="campaign-tabs-list-mobile">
              <TabsTrigger 
                value="all"
                className={`campaign-tab-trigger ${activeTab === 'all' ? 'active' : 'inactive'}`}
              >
                All Campaigns ({formatCount(totalCount)})
              </TabsTrigger>
              <TabsTrigger 
                value="draft"
                className={`campaign-tab-trigger ${activeTab === 'draft' ? 'active' : 'inactive'}`}
              >
                Draft ({formatCount(draftCount)})
              </TabsTrigger>
              <TabsTrigger 
                value="ongoing"
                className={`campaign-tab-trigger ${activeTab === 'ongoing' ? 'active' : 'inactive'}`}
              >
                Ongoing ({formatCount(ongoingCount)})
              </TabsTrigger>
            </TabsList>
          </Tabs>
          <div className="campaign-header-buttons-container">
            {selectedCampaigns.size > 0 && (
              <>
                {(() => {
                  // Check if all campaigns in filtered list are selected
                  const allFilteredSelected = filteredCampaigns.length > 0 && 
                    filteredCampaigns.every(campaign => selectedCampaigns.has(campaign.id));
                  
                  // Check if all draft campaigns are selected (from filtered list)
                  const draftCampaignIds = filteredCampaigns
                    .filter(campaign => campaign.status === 'draft')
                    .map(campaign => campaign.id);
                  
                  const allDraftSelected = draftCampaignIds.length > 0 && 
                    draftCampaignIds.every(id => selectedCampaigns.has(id));
                  
                  // If all filtered campaigns are selected, header only shows draft bulk-delete (unselect is on each card)
                  if (allFilteredSelected) {
                    if (!allDraftSelected) {
                      return null;
                    }
                    return (
                      <button
                        type="button"
                        onClick={() => {
                          const draftIdsToDelete = Array.from(selectedCampaigns).filter((campaignId) => {
                            const campaign = campaigns.find((c) => c.id === campaignId);
                            return campaign && campaign.status === 'draft';
                          });
                          if (draftIdsToDelete.length === 0) {
                            toast.error('No draft campaigns selected');
                            return;
                          }
                          setCampaignsToDelete(draftIdsToDelete);
                          setShowDeleteDialog(true);
                        }}
                        className="evecta-destructive-btn"
                      >
                        <Trash2 size={16} />
                        Remove All Draft Campaign
                      </button>
                    );
                  }
                  
                  // If some campaigns are selected (but not all), show select all + remove buttons
                  return (
                    <>
                      {/* Show "Select All Campaign" button when some campaigns are selected */}
                      <button
                        type="button"
                        onClick={() => {
                          const newSelected = new Set(selectedCampaigns);
                          filteredCampaigns.forEach(campaign => newSelected.add(campaign.id));
                          setSelectedCampaigns(newSelected);
                        }}
                        className="campaign-unselect-button"
                      >
                        <img
                          src="/Select All Campaign Button.svg"
                          alt="Select All Campaign"
                          className="campaign-unselect-button-img"
                        />
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          const draftCampaignIds = Array.from(selectedCampaigns).filter(campaignId => {
                            const campaign = campaigns.find(c => c.id === campaignId);
                            return campaign && campaign.status === 'draft';
                          });

                          if (draftCampaignIds.length === 0) {
                            toast.error('Only draft campaigns can be deleted');
                            return;
                          }

                          setCampaignsToDelete(draftCampaignIds);
                          setShowDeleteDialog(true);
                        }}
                        className="evecta-destructive-btn"
                      >
                        <Trash2 size={16} />
                        Remove Draft Campaign
                      </button>
                    </>
                  );
                })()}
              </>
            )}
            <Button
              variant="default"
              onClick={() => {
                // Clear all previous campaign state to ensure fresh start
                sessionStorage.removeItem('editCampaignId');
                sessionStorage.removeItem('campaignEmailAccountStep');
                sessionStorage.removeItem('campaignEmailAccountChoice');
                sessionStorage.removeItem('openExistingEmailsTab');
                sessionStorage.removeItem('cameFromCampaign');
                sessionStorage.removeItem('preselectedLeadIds');
                sessionStorage.removeItem('showImapForm');
                sessionStorage.removeItem('emailSetupGoToStep5');
                sessionStorage.removeItem('emailSetupCampaignId');
                sessionStorage.removeItem('campaignLeadIds');
                sessionStorage.removeItem('campaignLogId');
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
                if (onNavigateToCreateCampaign) {
                  onNavigateToCreateCampaign();
                }
              }}
              className="create-campaign-button lead-log-create-campaign-btn"
            >
              Create Campaign
            </Button>
          </div>
        </div>
      </div>

      {/* Campaigns List - scrolls, pagination fixed at bottom */}
      <div className="campaign-list-container dashboard-pagination-scroll-area">
        {isLoading ? (
          <div className="campaign-loading-state">
            Loading campaigns...
          </div>
        ) : paginatedCampaigns.length === 0 ? (
          <EmptyState
            iconPath="/finger-cricle.svg"
            title="No campaigns found."
            description="Create your first campaign to get started."
          />
        ) : (
          <div className="campaign-grid-container">
            {(() => {
              const allPaginatedSelected =
                paginatedCampaigns.length > 0 &&
                paginatedCampaigns.every((c) => selectedCampaigns.has(c.id));
              return paginatedCampaigns.map((campaign) => {
              const isOngoing = campaign.status === 'ongoing' || campaign.status === 'sent';
              
              // For ongoing campaigns, use the new design
              if (isOngoing) {
                // Get real statistics from insights
                const insight = campaignInsights[campaign.id];
                const totalLeads = campaign.leads_count || 0;
                const sentCount = insight?.tracking?.total_outreached ?? insight?.total_sent ?? 0;
                const queuedCount = Math.max(0, totalLeads - sentCount);
                const repliedCount = insight?.total_replied || 0;
                const openedCount = insight?.total_opened || 0;
                let emailDisplay = '';
                if (campaign.email_sending_mode === 'SYSTEM') {
                  emailDisplay = 'System Email';
                } else if (campaign.email_sending_mode === 'USER') {
                  emailDisplay = campaign.sender_email && campaign.sender_email.trim() ? campaign.sender_email : 'Custom Email';
                } else {
                  emailDisplay = campaign.sender_email && campaign.sender_email.trim() ? campaign.sender_email : 'Custom Email';
                }
                const systemSenderEmail =
                  campaign.email_sending_mode === 'SYSTEM' && campaign.sender_email?.trim()
                    ? campaign.sender_email.trim()
                    : '';
                return (
                  <div
                    key={campaign.id}
                    onClick={() => onViewChange && onViewChange('campaign-detail', campaign.id)}
                    className="campaign-card-base campaign-card-ongoing"
                  >
                    <div className="campaign-card-checkbox-wrapper">
                    <div
                      onClick={(e) => { e.stopPropagation(); setCardMenuOpen(prev => prev === campaign.id ? null : campaign.id); }}
                      onMouseDown={(e) => e.stopPropagation()}
                      className="campaign-card-checkbox"
                    >
                      <img src={selectedCampaigns.has(campaign.id) ? "/tick checkbox.svg" : "/checkbox.svg"} alt="" className="campaign-card-checkbox-img" />
                    </div>
                    {cardMenuOpen === campaign.id && (
                      <div className="campaign-card-checkbox-menu" onClick={(e) => e.stopPropagation()}>
                        <button
                          type="button"
                          className="campaign-card-menu-item"
                          onClick={() => {
                            if (allPaginatedSelected) {
                              setSelectedCampaigns((prev) => {
                                const next = new Set(prev);
                                paginatedCampaigns.forEach((c) => next.delete(c.id));
                                return next;
                              });
                            } else {
                              setSelectedCampaigns(new Set(paginatedCampaigns.map((c) => c.id)));
                            }
                            setCardMenuOpen(null);
                          }}
                        >
                          {allPaginatedSelected ? (
                            <>
                              <X size={16} className="campaign-card-menu-icon" />
                              <span>Unselect Campaign</span>
                            </>
                          ) : (
                            <>
                              <Pencil size={16} className="campaign-card-menu-icon" />
                              <span>Select All Campaign</span>
                            </>
                          )}
                        </button>
                        <div className="campaign-card-menu-divider" />
                        <button type="button" className="campaign-card-menu-item campaign-card-menu-item-delete evecta-destructive-menu-item" onClick={() => { setCampaignsToDelete([campaign.id]); setShowDeleteDialog(true); setCardMenuOpen(null); }}>
                          <Trash2 size={16} className="campaign-card-menu-icon" />
                          <span>Delete Campaign</span>
                        </button>
                      </div>
                    )}
                    </div>
                    <div className="campaign-card-header-banner campaign-card-header-ongoing">
                      <div className="campaign-card-header-banner-inner">
                        <div className="campaign-card-status-pill ongoing">
                          <span className="campaign-card-status-dot" /><span className="campaign-card-status-text">Ongoing</span>
                        </div>
                        <h3 className="campaign-card-banner-title">{campaign.title}</h3>
                        <p className="campaign-card-banner-description">{campaign.description || 'No description provided'}</p>
                      </div>
                    </div>
                    <div className="campaign-card-body">
                      <div className="campaign-card-stats-row">
                        <div className="campaign-card-stat campaign-card-stat-sent"><span className="campaign-card-stat-value">{sentCount}</span><span className="campaign-card-stat-label">Sent</span></div>
                        <div className="campaign-card-stat campaign-card-stat-opened"><span className="campaign-card-stat-value">{openedCount}</span><span className="campaign-card-stat-label">Opened</span></div>
                        <div className="campaign-card-stat campaign-card-stat-queued"><span className="campaign-card-stat-value">{queuedCount}</span><span className="campaign-card-stat-label">Queued</span></div>
                        <div className="campaign-card-stat campaign-card-stat-replied"><span className="campaign-card-stat-value">{repliedCount}</span><span className="campaign-card-stat-label">Replied</span></div>
                      </div>
                      <div className="campaign-card-email-field">
                        {campaign.email_sending_mode === 'SYSTEM' ? (
                          <div className="campaign-card-email-stack">
                            <span className="campaign-card-email-mode">System Email</span>
                            {systemSenderEmail ? (
                              <span className="campaign-card-email-address">{systemSenderEmail}</span>
                            ) : null}
                          </div>
                        ) : (
                          <span className="campaign-card-email-value campaign-card-email-address">{emailDisplay}</span>
                        )}
                      </div>
                      <div className="campaign-card-footer-row">
                        <div className="campaign-card-created">
                          <Calendar className="campaign-card-created-icon" size={14} />
                          <span className="campaign-card-created-label">Created On: </span>
                          <span className="campaign-card-created-date">{formatDate(campaign.created_at)}</span>
                        </div>
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); onViewChange && onViewChange('campaign-detail', campaign.id); }}
                          className="campaign-view-button campaign-view-button-solid"
                        >
                          View Campaign
                        </button>
                      </div>
                    </div>
                  </div>
                );
              } else {
                // Draft campaigns: same layout as image, with Draft _Container.svg header and not-launched block
                const totalLeads = campaign.leads_count || 0;
                let emailDisplay = '';
                if (campaign.email_sending_mode === 'SYSTEM') {
                  emailDisplay = 'System Email';
                } else if (campaign.email_sending_mode === 'USER') {
                  emailDisplay = campaign.sender_email && campaign.sender_email.trim() ? campaign.sender_email : 'Custom Email';
                } else {
                  emailDisplay = campaign.sender_email && campaign.sender_email.trim() ? campaign.sender_email : 'Custom Email';
                }
                const draftSystemSenderEmail =
                  campaign.email_sending_mode === 'SYSTEM' && campaign.sender_email?.trim()
                    ? campaign.sender_email.trim()
                    : '';
                return (
                  <div
                  key={campaign.id}
                    onClick={() => campaign.status === 'draft' && onNavigateToCreateCampaign ? onNavigateToCreateCampaign(campaign.id) : onViewChange && onViewChange('campaign-detail', campaign.id)}
                    className="campaign-card-base campaign-card-draft"
                  >
                    <div className="campaign-card-checkbox-wrapper">
                    <div
                      onClick={(e) => { e.stopPropagation(); setCardMenuOpen(prev => prev === campaign.id ? null : campaign.id); }}
                      onMouseDown={(e) => e.stopPropagation()}
                    className="campaign-card-checkbox"
                  >
                      <img src={selectedCampaigns.has(campaign.id) ? "/tick checkbox.svg" : "/checkbox.svg"} alt="" className="campaign-card-checkbox-img" />
                  </div>
                    {cardMenuOpen === campaign.id && (
                      <div className="campaign-card-checkbox-menu" onClick={(e) => e.stopPropagation()}>
                        <button
                          type="button"
                          className="campaign-card-menu-item"
                          onClick={() => {
                            if (allPaginatedSelected) {
                              setSelectedCampaigns((prev) => {
                                const next = new Set(prev);
                                paginatedCampaigns.forEach((c) => next.delete(c.id));
                                return next;
                              });
                            } else {
                              setSelectedCampaigns(new Set(paginatedCampaigns.map((c) => c.id)));
                            }
                            setCardMenuOpen(null);
                          }}
                        >
                          {allPaginatedSelected ? (
                            <>
                              <X size={16} className="campaign-card-menu-icon" />
                              <span>Unselect Campaign</span>
                            </>
                          ) : (
                            <>
                              <Pencil size={16} className="campaign-card-menu-icon" />
                              <span>Select All Campaign</span>
                            </>
                          )}
                        </button>
                        <div className="campaign-card-menu-divider" />
                        <button type="button" className="campaign-card-menu-item campaign-card-menu-item-delete evecta-destructive-menu-item" onClick={() => { setCampaignsToDelete([campaign.id]); setShowDeleteDialog(true); setCardMenuOpen(null); }}>
                          <Trash2 size={16} className="campaign-card-menu-icon" />
                          <span>Delete Campaign</span>
                        </button>
                            </div>
                          )}
                        </div>
                    <div className="campaign-card-header-banner campaign-card-header-draft">
                      <div className="campaign-card-header-banner-inner">
                        <div className="campaign-card-status-pill draft">
                          <span className="campaign-card-status-dot" /><span className="campaign-card-status-text">Draft</span>
                        </div>
                        <h3 className="campaign-card-banner-title">{campaign.title}</h3>
                        <p className="campaign-card-banner-description">{campaign.description || 'No description provided'}</p>
                      </div>
                    </div>
                    <div className="campaign-card-body">
                      <div className="campaign-card-stats-row">
                        <div className="campaign-card-stat campaign-card-stat-sent"><span className="campaign-card-stat-value">0</span><span className="campaign-card-stat-label">Sent</span></div>
                        <div className="campaign-card-stat campaign-card-stat-opened"><span className="campaign-card-stat-value">0</span><span className="campaign-card-stat-label">Opened</span></div>
                        <div className="campaign-card-stat campaign-card-stat-queued"><span className="campaign-card-stat-value">{totalLeads}</span><span className="campaign-card-stat-label">Queued</span></div>
                        <div className="campaign-card-stat campaign-card-stat-replied"><span className="campaign-card-stat-value">0</span><span className="campaign-card-stat-label">Replied</span></div>
                      </div>
                      <div className="campaign-card-not-launched">
                        <div>
                          <div className="campaign-card-not-launched-title">Campaign not launched yet</div>
                          <div className="campaign-card-not-launched-sub">Progress will show after launch</div>
                    </div>
                      </div>
                      <div className="campaign-card-email-field">
                        {campaign.email_sending_mode === 'SYSTEM' ? (
                          <div className="campaign-card-email-stack">
                            <span className="campaign-card-email-mode">System Email</span>
                            {draftSystemSenderEmail ? (
                              <span className="campaign-card-email-address">{draftSystemSenderEmail}</span>
                            ) : null}
                          </div>
                        ) : (
                          <span className="campaign-card-email-value campaign-card-email-address">{emailDisplay}</span>
                        )}
                      </div>
                      <div className="campaign-card-footer-row">
                        <div className="campaign-card-created">
                          <Calendar className="campaign-card-created-icon" size={14} />
                          <span className="campaign-card-created-label">Created On: </span>
                          <span className="campaign-card-created-date">{formatDate(campaign.created_at)}</span>
                        </div>
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); onNavigateToCreateCampaign && onNavigateToCreateCampaign(campaign.id); }}
                          className="campaign-view-button campaign-view-button-solid"
                        >
                          View Campaign
                        </button>
                      </div>
                    </div>
                </div>
              );
              }
            });
            })()}
          </div>
        )}
      </div>

      {/* Pagination fixed at bottom - shared design */}
      <div className="dashboard-pagination-fixed">
        <DashboardPagination
          totalItems={filteredCampaigns.length}
          currentPage={currentPage}
          itemsPerPage={itemsPerPage}
          onPageChange={setCurrentPage}
          onItemsPerPageChange={(v) => { setItemsPerPage(v); setCurrentPage(1); }}
          itemLabel="campaigns"
        />
      </div>

      {/* Delete Confirmation Dialog */}
      {showDeleteDialog && (
        <div
          className="evecta-dialog-overlay campaign-delete-dialog-overlay"
          onClick={() => setShowDeleteDialog(false)}
        >
          <div
            className="evecta-dialog campaign-delete-dialog-content"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="evecta-dialog-header campaign-delete-dialog-header">
              <h2 className="evecta-dialog-title campaign-delete-dialog-title">
                Delete draft campaign?
              </h2>
            </div>
            <p className="evecta-dialog-description campaign-delete-dialog-text">
              Are you sure you want to delete {campaignsToDelete.length > 1 ? `${campaignsToDelete.length} draft campaigns` : 'this draft campaign'}?
            </p>

            <div className="evecta-dialog-actions campaign-delete-dialog-buttons">
              <button
                type="button"
                onClick={() => {
                  setShowDeleteDialog(false);
                  setCampaignsToDelete([]);
                }}
                className="evecta-dialog-btn evecta-dialog-btn--secondary campaign-delete-dialog-btn campaign-delete-dialog-btn-no"
              >
                No
              </button>
              <button
                type="button"
                onClick={async () => {
                  setShowDeleteDialog(false);
                  // Delete each draft campaign
                  let successCount = 0;
                  let errorCount = 0;

                  for (const campaignId of campaignsToDelete) {
                    try {
                      const response = await apiService.deleteCampaign(campaignId);
                      console.log('Delete campaign response:', response);
                      if (response.error) {
                        console.error('Failed to delete campaign:', response.error);
                        errorCount++;
                      } else {
                        successCount++;
                      }
                    } catch (error: any) {
                      console.error('Failed to delete campaign:', error);
                      errorCount++;
                    }
                  }

                  if (successCount > 0) {
                    toast.success(`Successfully deleted ${successCount} campaign(s)`);
                    setSelectedCampaigns(new Set());
                    await fetchCampaigns();
                  }

                  if (errorCount > 0) {
                    toast.error(`Failed to delete ${errorCount} campaign(s)`);
                  }

                  setCampaignsToDelete([]);
                }}
                className="evecta-dialog-btn evecta-dialog-btn--destructive campaign-delete-dialog-btn campaign-delete-dialog-btn-yes"
              >
                Yes
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

