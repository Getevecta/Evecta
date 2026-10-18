import type { LucideIcon } from 'lucide-react';
import {
  CreditCard,
  History,
  Home,
  User,
  Wallet,
} from 'lucide-react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import '../Inbox/Inbox.css';
import '../Sidebar/Sidebar.css';
import { SidebarCreditsWidget } from '../Sidebar/SidebarCreditsWidget';
import { cn } from '../ui/utils';
import './SettingsSidebar.css';

export type SettingsSidebarSection = 'profile' | 'billing' | 'usage' | 'search-history';

interface SettingsSidebarProps {
  activeSection: SettingsSidebarSection;
  /** Narrow screens: stack at top of main instead of fixed column */
  variant?: 'fixed' | 'embedded';
}

type NavItem = {
  id: SettingsSidebarSection;
  label: string;
  description: string;
  icon: LucideIcon;
  path: string;
  searchText?: string;
};

const PROFILE_NAV: NavItem[] = [
  {
    id: 'profile',
    label: 'General',
    description: 'Profile and account',
    icon: User,
    path: '/dashboard/settings/profile',
    searchText: 'general settings overview',
  },
  {
    id: 'search-history',
    label: 'Search History',
    description: 'Past lead searches',
    icon: History,
    path: '/dashboard/settings/search-history',
    searchText: 'history searches logs past',
  },
];

const CREDITS_NAV: NavItem[] = [
  {
    id: 'billing',
    label: 'Billing',
    description: 'Plans and pricing',
    icon: CreditCard,
    path: '/dashboard/settings/billing',
    searchText: 'billing plans pricing subscription stripe upgrade invoice payment proration',
  },
  {
    id: 'usage',
    label: 'Usage',
    description: 'Credits and top-ups',
    icon: Wallet,
    path: '/dashboard/settings/usage',
    searchText: 'usage credits balance top up spending limits refill buy credits',
  },
];

function renderSidebarNavButton(
  isActive: boolean,
  label: string,
  description: string,
  Icon: LucideIcon,
  onClick: () => void,
) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'w-full flex items-center rounded-lg text-left min-w-0 sidebar-nav-button',
        'gap-[0.531rem] p-1.5',
        isActive
          ? 'sidebar-nav-active-gradient'
          : 'sidebar-nav-button-inactive',
      )}
    >
      <div className="flex shrink-0 items-center justify-center p-2">
        <Icon
          className={cn(
            'sidebar-nav-image-fixed h-5 w-5',
            isActive ? 'text-white' : 'text-gray-600',
          )}
        />
      </div>
      <div className="flex-1 min-w-0 transition-opacity duration-300 ease-out delay-75 sidebar-nav-content-visible sidebar-nav-content-no-count">
        <div className="sidebar-nav-label-secondary sidebar-nav-label-secondary-base">{label}</div>
        <div
          className={cn(
            'sidebar-nav-description-secondary',
            isActive ? 'text-white/80' : 'text-gray-500',
          )}
        >
          {description}
        </div>
      </div>
    </button>
  );
}

export function SettingsSidebar({ activeSection, variant = 'fixed' }: SettingsSidebarProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();

  const urlTab = searchParams.get('tab');
  const searching = false;

  const isProfilePath = location.pathname.startsWith('/dashboard/settings/profile');

  const isNavRowActive = (item: NavItem) => {
    if (item.id === 'profile') {
      return (
        activeSection === 'profile' &&
        isProfilePath &&
        (urlTab === null || urlTab === '' || urlTab === 'profile')
      );
    }
    return activeSection === item.id;
  };

  const renderNavRow = (item: NavItem) => {
    const isActive = isNavRowActive(item);
    return (
      <div key={item.id}>
        {renderSidebarNavButton(isActive, item.label, item.description, item.icon, () =>
          navigate(item.path),
        )}
      </div>
    );
  };

  const showProfileSection = true;
  const profileBlock = <div className="space-y-0.5">{PROFILE_NAV.map((item) => renderNavRow(item))}</div>;

  return (
    <aside
      data-sidebar-item
      className={cn(
        'settings-sidebar-shell bg-white shadow-sm transition-[width,min-width] duration-300 ease-out flex flex-col overflow-hidden relative',
        variant === 'embedded' && 'settings-sidebar-shell--embedded',
      )}
      aria-label="Settings"
    >
      <div className="py-2 flex-shrink-0 sidebar-header-container">
        <div className="flex items-center justify-between w-full transition-[padding] duration-300 ease-out px-6">
          <Link to="/dashboard/generate" className="evecta-logo shrink-0">
            <span className="evecta-logo-text">Evecta</span>
            <span className="evecta-logo-tagline">AI-Powered Platform</span>
          </Link>
        </div>
      </div>

      <div className="sidebar-navigation settings-sidebar-nav-scroll flex-1 pb-0 min-h-0 overflow-y-auto px-6">
        <div className="space-y-0.5">
          <div className="settings-sidebar-back-dashboard-wrap">
            <button
              type="button"
              className="settings-sidebar-back-dashboard-btn"
              onClick={() => navigate('/dashboard/generate')}
              aria-label="Back to dashboard"
            >
              <Home className="settings-sidebar-back-dashboard-icon" size={18} strokeWidth={2} aria-hidden />
              <span className="settings-sidebar-back-dashboard-label">Dashboard</span>
            </button>
          </div>

          {showProfileSection && (
            <div className="sidebar-nav-section">
              {!searching ? (
                <h3
                  className="sidebar-section-title heading-s font-semibold text-gray-500 uppercase tracking-wider mt-1 transition-opacity duration-300 ease-out sidebar-section-title-base"
                  style={{ marginBottom: '4px' }}
                >
                  Profile
                </h3>
              ) : null}
              {profileBlock}
            </div>
          )}

          <div className="sidebar-nav-section">
            {!searching ? (
              <h3
                className="sidebar-section-title heading-s font-semibold text-gray-500 uppercase tracking-wider mt-1 transition-opacity duration-300 ease-out sidebar-section-title-base"
                style={{
                  marginBottom: '4px',
                }}
              >
                Billing &amp; usage
              </h3>
            ) : null}
            <div className="space-y-0.5">
              {CREDITS_NAV.map((item) => renderNavRow(item))}
            </div>
          </div>
        </div>
      </div>

      <div className="flex-shrink-0 transition-[padding] duration-300 ease-out px-6">
        <SidebarCreditsWidget
          collapsed={false}
          onBuyMore={() => navigate('/dashboard/settings/usage')}
        />
      </div>
    </aside>
  );
}
