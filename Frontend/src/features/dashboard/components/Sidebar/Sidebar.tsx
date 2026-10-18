import { Link } from 'react-router-dom';
import { ArrowLeftRight, LayoutDashboard, Shield, X } from 'lucide-react';
import { cn } from '../ui/utils';
import { useIsMobile } from '../ui/use-mobile';
import './Sidebar.css';
import { SidebarCreditsWidget } from './SidebarCreditsWidget';
import { DASHBOARD_FEATURES } from '../../dashboardFeatures';

export type DashboardWorkspaceMode = 'admin' | 'user';

interface SidebarProps {
  isOpen: boolean;
  collapsed?: boolean;
  currentView: 'generate' | 'leads' | 'lead-log' | 'campaigns' | 'campaign-creation' | 'outreach' | 'sequence-creation' | 'sequence-builder' | 'lead-outreach' | 'templates' | 'users' | 'admin' | 'settings' | 'campaign-detail' | 'campaign-preview' | 'profile' | 'inbox' | 'email-accounts' | 'admin-ai-usage' | 'admin-credits' | 'admin-gemini-purchases' | 'admin-users' | 'admin-mailboxes';
  onViewChange: (view: 'generate' | 'leads' | 'lead-log' | 'campaigns' | 'campaign-creation' | 'outreach' | 'sequence-creation' | 'sequence-builder' | 'lead-outreach' | 'templates' | 'users' | 'admin' | 'settings' | 'campaign-detail' | 'campaign-preview' | 'profile' | 'inbox' | 'email-accounts' | 'admin-ai-usage' | 'admin-credits' | 'admin-gemini-purchases' | 'admin-users' | 'admin-mailboxes') => void;
  onClose?: () => void;
  currentUserRole?: 'admin' | 'manager' | 'user';
  currentUserName?: string;
  currentUserEmail?: string;
  onToggleCollapse?: () => void;
  // When true, a lead generation run is currently in progress.
  // Used to prevent starting a new AI Lead Gen chat while processing.
  isLeadGenInProgress?: boolean;
  /** Opens dashboard billing (pricing / checkout). */
  onOpenBilling?: () => void;
  /** Admin-only: which sidebar workspace is active. */
  workspaceMode?: DashboardWorkspaceMode;
  /** Admin-only: switch between admin panel and user dashboard. */
  onSwitchWorkspace?: (mode: DashboardWorkspaceMode) => void;
}

/** Dashboard views that belong under the sidebar "Campaigns" item (list + wizard + detail). */
const VIEWS_UNDER_CAMPAIGNS_NAV: ReadonlySet<SidebarProps['currentView']> = new Set([
  'campaigns',
  'campaign-creation',
  'campaign-detail',
  'campaign-preview',
]);

function isLeadManagementNavActive(
  itemId: 'leads' | 'campaigns' | 'templates' | 'inbox',
  currentView: SidebarProps['currentView'],
): boolean {
  if (itemId === 'campaigns') {
    return VIEWS_UNDER_CAMPAIGNS_NAV.has(currentView);
  }
  if (itemId === 'leads') {
    return currentView === 'leads' || currentView === 'lead-log';
  }
  return currentView === itemId;
}

export function Sidebar({
  isOpen,
  collapsed = false,
  currentView,
  onViewChange,
  onClose,
  currentUserRole = 'user',
  currentUserName = 'User',
  currentUserEmail = 'user@example.com',
  onToggleCollapse,
  isLeadGenInProgress = false,
  onOpenBilling,
  workspaceMode = 'user',
  onSwitchWorkspace,
}: SidebarProps) {
  const isMobile = useIsMobile();
  const isAdmin = currentUserRole === 'admin';
  const showAdminWorkspace = isAdmin && workspaceMode === 'admin';
  const showUserWorkspace = !isAdmin || workspaceMode === 'user';
  const homePath = showAdminWorkspace ? '/dashboard/admin/ai-usage' : '/dashboard/generate';

  const leadGenItems = [
    {
      id: 'generate' as const,
      label: 'AI Lead Gen',
      icon: null,
      iconPath: '/slack-header.svg',
      defaultIconPath: '/slack-header.svg',
      description: 'Generate new leads'
    }
  ];

  const leadManagementItems = [
    {
      id: 'leads' as const,
      label: 'Lead Database',
      icon: null,
      iconPath: '/data-header.svg',
      defaultIconPath: '/data-header.svg',
      description: 'Manage your leads'
    },
    {
      id: 'campaigns' as const,
      label: 'Campaigns',
      icon: null,
      iconPath: '/finger-cricle-header.svg',
      defaultIconPath: '/finger-cricle-header.svg',
      description: 'Organize campaigns'
    },
    {
      id: 'templates' as const,
      label: 'Email Templates',
      icon: null,
      iconPath: '/message-header.svg',
      defaultIconPath: '/message-header.svg',
      description: 'Reusable templates'
    },
    {
      id: 'inbox' as const,
      label: 'Inbox',
      icon: null,
      iconPath: '/direct-inbox-header.svg',
      defaultIconPath: '/direct-inbox-header.svg',
      description: 'Lead emails & labeling'
    }
  ].filter(
    (item) => item.id !== 'templates' || DASHBOARD_FEATURES.showEmailTemplatesSection,
  );

  const emailItems = [
    {
      id: 'email-accounts' as const,
      label: 'Email Accounts',
      icon: null,
      iconPath: '/message-search-header.svg',
      defaultIconPath: '/message-search-header.svg',
      description: 'Connect email accounts'
    }
  ];

  const outreachItems: any[] = [];

  const analyticsItems: any[] = [];

  const adminItems =
    currentUserRole === 'admin'
      ? [
          {
            id: 'admin-ai-usage' as const,
            label: 'AI Usage',
            icon: null,
            iconPath: '/finger-cricle-header.svg',
            defaultIconPath: '/finger-cricle-header.svg',
            description: 'Token & cost metering',
          },
          {
            id: 'admin-gemini-purchases' as const,
            label: 'API Costs',
            icon: null,
            iconPath: '/finger-cricle-header.svg',
            defaultIconPath: '/finger-cricle-header.svg',
            description: 'Gemini, Hunter & Places usage',
          },
          {
            id: 'admin-credits' as const,
            label: 'Credits',
            icon: null,
            iconPath: '/finger-cricle-header.svg',
            defaultIconPath: '/finger-cricle-header.svg',
            description: 'Admin top-up credits',
          },
          {
            id: 'admin-users' as const,
            label: 'Users',
            icon: null,
            iconPath: '/finger-cricle-header.svg',
            defaultIconPath: '/finger-cricle-header.svg',
            description: 'User list & plan management',
          },
          {
            id: 'admin-mailboxes' as const,
            label: 'Mailboxes',
            icon: null,
            iconPath: '/finger-cricle-header.svg',
            defaultIconPath: '/finger-cricle-header.svg',
            description: 'System domains & mailboxes',
          },
        ]
      : [];

  return (
    <>
      {/* Mobile Overlay */}
      {isMobile && isOpen && (
        <div 
          className="fixed inset-0 bg-black bg-opacity-50 z-40"
          onClick={onClose}
        />
      )}
      
      <aside 
        data-sidebar-item
        className={cn(
          "bg-white transition-[width,min-width,shadow] duration-300 ease-out flex flex-col shadow-sm overflow-hidden relative",
          // Desktop: full width when open, collapsed when collapsed, hidden when closed
          !isMobile && isOpen && !collapsed && "w-[280px] min-w-[280px]",
          !isMobile && isOpen && collapsed && "w-16 min-w-16",
          !isMobile && !isOpen && "w-0 overflow-hidden hidden",
          // Mobile: expanded (with text) when open, hidden when closed
          isMobile && isOpen && "w-[280px] min-w-[280px]",
          isMobile && !isOpen && "w-0 overflow-hidden hidden"
        )}
        data-collapsed={collapsed}
        style={{
          ...(isMobile && isOpen ? { 
            backgroundColor: 'white', 
            border: '1px solid #E5E7EB',
            zIndex: 50,
            position: 'fixed',
            top: 0,
            left: 0,
            height: '100vh',
            willChange: 'width',
            flexShrink: 0
          } : (!isMobile && isOpen ? {
            position: 'absolute',
            top: 0,
            left: 0,
            height: '100vh',
            /* Keep width off inline styles so w-[280px] / w-16 win — width:auto was
               overriding them and let the aside grow past 280px (e.g. credits line),
               overlapping the main column that is only offset by 280px. */
            willChange: 'width',
            zIndex: 1,
            flexShrink: 0
          } : {
            display: 'none'
          }))
        }}
      >
      {/* Header */}
      <div className="py-2 flex-shrink-0 sidebar-header-container">
        <div className={cn(
          "flex items-center justify-between w-full transition-[padding] duration-300 ease-out",
          collapsed ? "px-3" : "px-6"
        )}>
          <Link 
            to={homePath} 
            className={cn(
              "evecta-logo shrink-0",
              collapsed && "evecta-logo-centered"
            )}
          >
            <span className="evecta-logo-text">Evecta</span>
            {!collapsed && (
              <span className="evecta-logo-tagline">
                {showAdminWorkspace ? 'Admin panel' : 'AI-Powered Platform'}
              </span>
            )}
          </Link>
          {/* Mobile Close Button */}
          {isMobile && (
            <button
              onClick={onClose}
              className="p-2 rounded-lg hover:bg-gray-100 transition-colors lg:hidden"
            >
              <X className="h-5 w-5 text-gray-600" />
            </button>
          )}
        </div>
      </div>

      {/* Navigation */}
      <div className={cn(
        "sidebar-navigation flex-1 pt-1 pb-0 min-h-0 overflow-y-auto transition-[padding] duration-300 ease-out",
          collapsed ? "px-2" : "px-6"
      )}>
        <div className={cn(
          collapsed ? "space-y-0.5" : "space-y-0.5"
        )}>
          {/* AI LEAD PROSPECTING */}
          {showUserWorkspace && (
          <div className="sidebar-nav-section">
            {!collapsed ? (
              <h3
                className={`sidebar-section-title sidebar-section-title-lead-prospecting text-gray-500 uppercase tracking-wider transition-opacity duration-300 ease-out ${!collapsed ? 'sidebar-section-title-base' : 'sidebar-section-title-collapsed'}`}
              >
                AI LEAD PROSPECTING
              </h3>
            ) : null}
            <div className="space-y-0.5">
              {leadGenItems.map((item) => {
                // Disable AI Lead Gen only while a generation run is actually in progress
                // and we're already on the AI Lead Gen view.
                const isDisabledLeadGen =
                  item.id === 'generate' &&
                  currentView === 'generate' &&
                  isLeadGenInProgress;

                const buttonContent = (
                  <button
                    disabled={isDisabledLeadGen}
                    onClick={() => {
                      if (isDisabledLeadGen) {
                        return;
                      }
                      onViewChange(item.id);
                      // Close mobile sidebar after navigation
                      if (isMobile && onClose) {
                        onClose();
                      }
                    }}
                    className={cn(
                      "w-full flex items-center rounded-lg text-left min-w-0",
                      collapsed ? "justify-center p-1" : "gap-[0.531rem] p-1.5",
                      currentView === item.id
                        ? "sidebar-nav-active-gradient"
                        : "sidebar-nav-button-inactive",
                      isDisabledLeadGen && "cursor-not-allowed opacity-70"
                    )}
                  >
                    <div className={cn(
                      "flex shrink-0 items-center justify-center",
                      collapsed ? "p-1" : "p-2"
                    )}>
                      {item.iconPath ? (
                        <img
                          src={item.defaultIconPath || item.iconPath}
                          alt={item.label}
                          className={cn(
                            "sidebar-nav-image sidebar-nav-image-fixed",
                            currentView === item.id && "sidebar-nav-image-active-white"
                          )}
                          width={20}
                          height={20}
                        />
                      ) : item.icon ? (
                        <item.icon className={cn(
                          "sidebar-nav-image-fixed h-5 w-5",
                          currentView === item.id ? "text-white" : "text-gray-600"
                        )} />
                      ) : null}
                    </div>
                    {!collapsed ? (
                      <div className="flex-1 min-w-0 transition-opacity duration-300 ease-out delay-75" style={{ opacity: !collapsed ? 1 : 0, overflow: 'hidden' }}>
                        <div className="sidebar-nav-label-main sidebar-nav-label-main--ai-lead-gen">{item.label}</div>
                        <div className={cn(
                          "sidebar-nav-description-main sidebar-nav-description-main--ai-lead-gen",
                          currentView === item.id ? "text-white/80" : "text-gray-500"
                        )}>
                          {item.description}
                        </div>
                      </div>
                    ) : null}
                  </button>
                );

                return <div key={item.id}>{buttonContent}</div>;
              })}
            </div>
          </div>
          )}

          {/* Lead Campaigns */}
          {showUserWorkspace && (
          <div className="sidebar-nav-section">
            {!collapsed ? (
              <h3
                className={`sidebar-section-title heading-s font-semibold text-gray-500 uppercase tracking-wider mt-1 transition-opacity duration-300 ease-out ${!collapsed ? 'sidebar-section-title-base' : 'sidebar-section-title-collapsed'}`}
                style={{
                  marginBottom: leadManagementItems.some((item) => isLeadManagementNavActive(item.id, currentView))
                    ? '4px'
                    : '4px',
                }}
              >
                Lead Campaigns
              </h3>
            ) : null}
            <div className="space-y-0.5">
              {leadManagementItems.map((item) => {
                const leadMgmtActive = isLeadManagementNavActive(item.id, currentView);
                const buttonContent = (
                  <button
                    onClick={() => {
                      onViewChange(item.id);
                      // Close mobile sidebar after navigation
                      if (isMobile && onClose) {
                        onClose();
                      }
                    }}
                    className={cn(
                      "w-full flex items-center rounded-lg text-left min-w-0 sidebar-nav-button",
                      collapsed ? "justify-center p-1" : "gap-[0.531rem] p-1.5",
                      leadMgmtActive
                        ? "sidebar-nav-active-gradient"
                        : "sidebar-nav-button-inactive"
                    )}
                  >
                    <div className={cn(
                      "flex shrink-0 items-center justify-center",
                      collapsed ? "p-1" : "p-2"
                    )}>
                      {item.iconPath ? (
                        <img 
                          src={item.defaultIconPath || item.iconPath} 
                          alt={item.label}
                          className={cn(
                            "sidebar-nav-image sidebar-nav-image-fixed",
                            leadMgmtActive && "sidebar-nav-image-active-white"
                          )}
                          width={20}
                          height={20}
                        />
                      ) : item.icon ? (
                        <item.icon className={cn(
                          "sidebar-nav-image-fixed h-5 w-5",
                          leadMgmtActive ? "text-white" : "text-gray-600"
                        )} />
                      ) : null}
                    </div>
                    {!collapsed ? (
                      <div className={`flex-1 min-w-0 transition-opacity duration-300 ease-out delay-75 ${!collapsed ? 'sidebar-nav-content-visible' : 'sidebar-nav-content-hidden'} sidebar-nav-content-no-count`}>
                        <div className="sidebar-nav-label-secondary sidebar-nav-label-secondary-base">{item.label}</div>
                        <div className={cn(
                          "sidebar-nav-description-secondary",
                          leadMgmtActive ? "text-white/80" : "text-gray-500"
                        )}>
                          {item.description}
                        </div>
                      </div>
                    ) : null}
                  </button>
                );

                return <div key={item.id}>{buttonContent}</div>;
              })}
            </div>
          </div>
          )}

          {/* EMAIL - Only show if there are items */}
          {showUserWorkspace && emailItems.length > 0 && (
          <div className="sidebar-nav-section">
            {!collapsed ? (
              <h3
                className={`sidebar-section-title heading-s font-semibold text-gray-500 uppercase tracking-wider mt-1 transition-opacity duration-300 ease-out ${!collapsed ? 'sidebar-section-title-base' : 'sidebar-section-title-collapsed'}`}
                style={{
                  marginBottom: emailItems.some(item => item.id === currentView) ? '4px' : '4px',
                }}
              >
                EMAIL
              </h3>
            ) : null}
            <div className="space-y-0.5">
              {emailItems.map((item) => {
                const buttonContent = (
                  <button
                    onClick={() => {
                      onViewChange(item.id);
                      // Close mobile sidebar after navigation
                      if (isMobile && onClose) {
                        onClose();
                      }
                    }}
                    className={cn(
                      "w-full flex items-center rounded-lg text-left min-w-0",
                      collapsed ? "justify-center p-1" : "gap-[0.531rem] p-1.5",
                      currentView === item.id
                        ? "sidebar-nav-active-gradient"
                        : "sidebar-nav-button-inactive"
                    )}
                  >
                    <div className={cn(
                      "flex shrink-0 items-center justify-center",
                      collapsed ? "p-1" : "p-2"
                    )}>
                      {item.iconPath ? (
                        <img
                          src={item.defaultIconPath || item.iconPath}
                          alt={item.label}
                          className={cn(
                            "sidebar-nav-image sidebar-nav-image-fixed",
                            currentView === item.id && "sidebar-nav-image-active-white"
                          )}
                          width={20}
                          height={20}
                        />
                      ) : item.icon ? (
                        <item.icon className={cn(
                          "sidebar-nav-image-fixed h-5 w-5",
                          currentView === item.id ? "text-white" : "text-gray-600"
                        )} />
                      ) : null}
                    </div>
                    {!collapsed ? (
                      <div className="flex-1 min-w-0 transition-opacity duration-300 ease-out delay-75" style={{ opacity: !collapsed ? 1 : 0, overflow: 'hidden' }}>
                        <div className="sidebar-nav-label-main">{item.label}</div>
                        <div className={cn(
                          "sidebar-nav-description-main",
                          currentView === item.id ? "text-white/80" : "text-gray-500"
                        )}>
                          {item.description}
                        </div>
                      </div>
                    ) : null}
                  </button>
                );

                return <div key={item.id}>{buttonContent}</div>;
              })}
            </div>
          </div>
          )}

          {showAdminWorkspace && adminItems.length > 0 && (
          <div className="sidebar-nav-section">
            {!collapsed ? (
              <h3
                className={`sidebar-section-title heading-s font-semibold text-gray-500 uppercase tracking-wider mt-1 transition-opacity duration-300 ease-out ${!collapsed ? 'sidebar-section-title-base' : 'sidebar-section-title-collapsed'}`}
              >
                ADMIN
              </h3>
            ) : null}
            <div className="space-y-0.5">
              {adminItems.map((item) => {
                const buttonContent = (
                  <button
                    onClick={() => {
                      onViewChange(item.id);
                      if (isMobile && onClose) {
                        onClose();
                      }
                    }}
                    className={cn(
                      "w-full flex items-center rounded-lg text-left min-w-0",
                      collapsed ? "justify-center p-1" : "gap-[0.531rem] p-1.5",
                      currentView === item.id
                        ? "sidebar-nav-active-gradient"
                        : "sidebar-nav-button-inactive"
                    )}
                    style={{ overflow: 'hidden' }}
                  >
                    <div className={cn(
                      "flex shrink-0 items-center justify-center",
                      collapsed ? "p-1" : "p-2"
                    )}>
                      {item.iconPath ? (
                        <img
                          src={item.defaultIconPath || item.iconPath}
                          alt={item.label}
                          className={cn(
                            "sidebar-nav-image sidebar-nav-image-fixed",
                            currentView === item.id && "sidebar-nav-image-active-white"
                          )}
                          width={20}
                          height={20}
                        />
                      ) : null}
                    </div>
                    {!collapsed ? (
                      <div className="flex-1 min-w-0 transition-opacity duration-300 ease-out delay-75" style={{ opacity: !collapsed ? 1 : 0, overflow: 'hidden' }}>
                        <div className="sidebar-nav-label-main">{item.label}</div>
                        <div className={cn(
                          "sidebar-nav-description-main",
                          currentView === item.id ? "text-white/80" : "text-gray-500"
                        )}>
                          {item.description}
                        </div>
                      </div>
                    ) : null}
                  </button>
                );
                return <div key={item.id}>{buttonContent}</div>;
              })}
            </div>
          </div>
          )}

          {/* CAMPAIGN & OUTREACH - Only show if there are items */}
          {outreachItems.length > 0 && (
          <div className="sidebar-nav-section">
            {!collapsed ? (
              <h3
                className={`sidebar-section-title heading-s font-semibold text-gray-500 uppercase tracking-wider mt-1 transition-opacity duration-300 ease-out ${!collapsed ? 'sidebar-section-title-base' : 'sidebar-section-title-collapsed'}`}
                style={{
                  marginBottom: outreachItems.some(item => item.id === currentView) ? '14px' : '12px',
                }}
              >
                CAMPAIGN & OUTREACH
              </h3>
            ) : null}
            <div className="space-y-0.5">
              {outreachItems.map((item) => {
                const buttonContent = (
                  <button
                    onClick={() => {
                      onViewChange(item.id);
                      // Close mobile sidebar after navigation
                      if (isMobile && onClose) {
                        onClose();
                      }
                    }}
                    className={cn(
                      "w-full flex items-center rounded-lg text-left min-w-0",
                      collapsed ? "justify-center p-1" : "gap-[0.531rem] p-1.5",
                      currentView === item.id
                        ? "sidebar-nav-active-gradient"
                        : "sidebar-nav-button-inactive"
                    )}
                    style={{ overflow: 'hidden' }}
                  >
                    <div className={cn(
                      "flex shrink-0 items-center justify-center",
                      collapsed ? "p-1" : "p-2"
                    )}>
                      <item.icon className={cn(
                        "sidebar-nav-image-fixed h-5 w-5",
                        currentView === item.id ? "text-white" : "text-gray-600"
                      )} />
                    </div>
                    {!collapsed ? (
                      <div className="flex-1 min-w-0 transition-opacity duration-300 ease-out delay-75" style={{ opacity: !collapsed ? 1 : 0, overflow: 'hidden' }}>
                        <div className="sidebar-nav-label-main" style={{ fontWeight: 500 }}>{item.label}</div>
                        <div className={cn(
                          "sidebar-nav-description-main",
                          currentView === item.id ? "text-white/80" : "text-gray-500"
                        )}>
                          {item.description}
                        </div>
                      </div>
                    ) : null}
                  </button>
                );

                return <div key={item.id}>{buttonContent}</div>;
              })}
            </div>
          </div>
          )}

          {/* ANALYTICS - Only show if there are items */}
          {analyticsItems.length > 0 && (
          <div className="sidebar-nav-section">
            {!collapsed ? (
              <h3
                className="sidebar-section-title heading-s font-semibold text-gray-500 uppercase tracking-wider mt-1 transition-opacity duration-300 ease-out"
                style={{
                  opacity: !collapsed ? 1 : 0,
                  marginBottom: analyticsItems.some(item => item.id === currentView) ? '14px' : '12px',
                }}
              >
                ANALYTICS
              </h3>
            ) : null}
            <div className="space-y-0.5">
              {analyticsItems.map((item) => {
                const buttonContent = (
                  <button
                    onClick={() => {
                      onViewChange(item.id);
                      // Close mobile sidebar after navigation
                      if (isMobile && onClose) {
                        onClose();
                      }
                    }}
                    className={cn(
                      "w-full flex items-center rounded-lg text-left min-w-0",
                      collapsed ? "justify-center p-1" : "gap-[0.531rem] p-1.5",
                      currentView === item.id
                        ? "sidebar-nav-active-gradient"
                        : "sidebar-nav-button-inactive"
                    )}
                  >
                    <div className={cn(
                      "rounded-lg flex items-center justify-center",
                      collapsed ? "p-0" : "p-0",
                      currentView === item.id ? "bg-transparent" : "bg-transparent"
                    )}>
                      {item.iconPath ? (
                        <img 
                          src={item.defaultIconPath || item.iconPath} 
                          alt={item.label}
                          className="sidebar-nav-image sidebar-nav-image-fixed"
                          width={20}
                          height={20}
                          style={{
                            display: 'block'
                          }}
                        />
                      ) : item.icon ? (
                        <item.icon className={cn(
                          "sidebar-nav-image-fixed h-5 w-5",
                          currentView === item.id ? "text-white" : "text-gray-600"
                        )} />
                      ) : null}
                    </div>
                    {!collapsed ? (
                      <div className="flex-1 min-w-0 transition-opacity duration-300 ease-out delay-75" style={{ opacity: !collapsed ? 1 : 0, overflow: 'hidden' }}>
                        <div className="sidebar-nav-label-main" style={{ fontWeight: 500 }}>{item.label}</div>
                        <div className={cn(
                          "sidebar-nav-description-main",
                          currentView === item.id ? "text-white/80" : "text-gray-500"
                        )}>
                          {item.description}
                        </div>
                      </div>
                    ) : null}
                  </button>
                );

                return <div key={item.id}>{buttonContent}</div>;
              })}
            </div>
          </div>
          )}

        </div>
      </div>

      {isAdmin && onSwitchWorkspace ? (
        <div
          className={cn(
            'flex-shrink-0 transition-[padding] duration-300 ease-out pb-2',
            collapsed ? 'px-2' : 'px-6',
          )}
        >
          <button
            type="button"
            className={cn(
              'sidebar-workspace-switch',
              collapsed && 'sidebar-workspace-switch--collapsed',
            )}
            onClick={() => {
              onSwitchWorkspace(showAdminWorkspace ? 'user' : 'admin');
              if (isMobile && onClose) onClose();
            }}
            title={
              showAdminWorkspace
                ? 'Open user dashboard'
                : 'Back to admin panel'
            }
          >
            {showAdminWorkspace ? (
              <LayoutDashboard size={16} aria-hidden />
            ) : (
              <Shield size={16} aria-hidden />
            )}
            {!collapsed && (
              <span className="sidebar-workspace-switch__label">
                {showAdminWorkspace ? 'Use user dashboard' : 'Back to admin panel'}
              </span>
            )}
            {!collapsed && <ArrowLeftRight size={14} className="sidebar-workspace-switch__icon" aria-hidden />}
          </button>
        </div>
      ) : null}

      {showUserWorkspace && onOpenBilling ? (
        <div
          className={cn(
            'flex-shrink-0 transition-[padding] duration-300 ease-out',
            collapsed ? 'px-2' : 'px-6',
          )}
        >
          <SidebarCreditsWidget
            collapsed={collapsed}
            onBuyMore={() => {
              onOpenBilling();
              if (isMobile && onClose) {
                onClose();
              }
            }}
          />
        </div>
      ) : null}

    </aside>
    </>
  );
}
