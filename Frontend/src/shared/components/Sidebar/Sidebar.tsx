import { useState, useEffect } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import { useAuth } from "../../contexts/AuthContext";
import MessageBox from "../../components/MessageBox/MessageBox";
import { LogOut, CircleUserRound, AtomIcon, NewspaperIcon, X, User, ArrowRight } from "lucide-react";
import "./Sidebar.css";

interface SidebarProps {
  isMobileOpen?: boolean;
  onMobileClose: () => void;
}

interface MenuItem {
  id: string;
  label: string;
  path: string;
  icon: React.ComponentType<{ className?: string }>;
}

interface MessageBoxState {
  isVisible: boolean;
  type: "success" | "error" | "info";
  message: string;
}

const Sidebar: React.FC<SidebarProps> = ({ isMobileOpen = false, onMobileClose }) => {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout, setUser } = useAuth();

  const [messageBox, setMessageBox] = useState<MessageBoxState>({ 
    isVisible: false, 
    type: "success", 
    message: "" 
  });

  // Listen for logout events to update immediately
  useEffect(() => {
    const handleStorageChange = (e: StorageEvent) => {
      if (e.key === 'user_logged_out') {
        // User logged out, clear user state immediately
        setUser(null);
      }
    };

    const handleLogoutCheck = () => {
      const logoutTime = localStorage.getItem('user_logged_out');
      if (logoutTime && user) {
        // Check if logout happened recently (within last 5 seconds)
        const logoutTimestamp = parseInt(logoutTime, 10);
        const now = Date.now();
        if (now - logoutTimestamp < 5000) {
          // Clear user state immediately
          setUser(null);
        }
      }
    };

    // Listen for storage events (cross-tab communication)
    window.addEventListener('storage', handleStorageChange);
    
    // Check on mount and periodically
    handleLogoutCheck();
    const interval = setInterval(handleLogoutCheck, 500);

    return () => {
      window.removeEventListener('storage', handleStorageChange);
      clearInterval(interval);
    };
  }, [user, setUser]);

  const menuItems: MenuItem[] = [
    { id: "about", label: "Discover", path: "/about_us", icon: AtomIcon },
    { id: "blog", label: "Blog", path: "/blog", icon: NewspaperIcon },
  ];

  const handleNavigation = (path: string) => navigate(path);
  const handleAddClick = () => {
    // If already on chat page, reset it; otherwise navigate to it
    if (location.pathname === "/chat") {
      navigate("/chat", { state: { resetChat: true } });
    } else {
      navigate("/chat", { state: { resetChat: true } });
    }
  };

  // LOGOUT
  const handleLogout = async (): Promise<void> => {
    await logout();
    setMessageBox({ isVisible: true, type: "success", message: "Logged out successfully!" });
    navigate("/");
  };

  // Get user initials
  const getInitials = (name: string) => {
    return name
      .split(' ')
      .map(n => n[0])
      .join('')
      .toUpperCase()
      .slice(0, 2);
  };

  // Handle profile click - navigate to auth if not logged in, or dashboard if logged in
  const handleProfileClick = () => {
    if (user) {
      navigate("/dashboard");
    } else {
      navigate("/auth");
    }
  };

  return (
    <div className={`sidebar ${isMobileOpen ? 'mobile-open' : ''}`}>
      <div className="sidebar-header">
        <Link 
          to="/" 
          className="evecta-logo evecta-logo-centered sidebar-evecta-logo"
          aria-label="Evecta home"
        >
          <span className="evecta-logo-text">Evecta</span>
        </Link>
        <button 
          className="mobile-close-button" 
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            if (onMobileClose) {
              onMobileClose();
            }
          }}
          aria-label="Close sidebar"
          type="button"
        >
          <X />
        </button>
      </div>

      <div className="sidebar-middle">
        <nav className="sidebar-nav">
          {menuItems.map(item => {
            const IconComponent = item.icon;
            return (
              <button 
                key={item.id} 
                className={`nav-item ${location.pathname === item.path ? "active" : ""}`} 
                onClick={() => handleNavigation(item.path)}
              >
                <div className="nav-icon-container">
                  <IconComponent className="nav-icon" />
                </div>
                <span className="nav-label">{item.label}</span>
              </button>
            );
          })}
        </nav>
      </div>

      {/* Profile Section - Conditional based on login status */}
      <div className="sidebar-profile-section">
        {user ? (
          // Logged in: Show vertical avatar and name
          <div className="sidebar-profile-container">
            <button 
              onClick={handleProfileClick}
              className="sidebar-profile-button"
            >
              <div className="sidebar-profile-avatar-container">
                <span className="sidebar-profile-avatar-initials">
                  {getInitials(user.username || user.email || 'User')}
                </span>
              </div>
              <div className="sidebar-profile-name">
                {(user.username || user.email || 'User').split(' ')[0]}
              </div>
            </button>
          </div>
        ) : (
          // Not logged in: Show Sign In button
          <div className="sidebar-signin-container">
            <button 
              onClick={() => navigate("/auth")}
              className="sidebar-signin-button-base"
            >
              <div className="sidebar-signin-icon-container">
                <svg 
                  xmlns="http://www.w3.org/2000/svg" 
                  width="24" 
                  height="24" 
                  viewBox="0 0 24 24" 
                  fill="none" 
                  stroke="#6B7280" 
                  strokeWidth="2" 
                  strokeLinecap="round" 
                  strokeLinejoin="round"
                >
                  <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/>
                  <circle cx="12" cy="7" r="4"/>
                </svg>
              </div>
              <div className="sidebar-signin-text">
                Sign In
              </div>
            </button>
          </div>
        )}
      </div>

      <MessageBox
        type={messageBox.type}
        message={messageBox.message}
        isVisible={messageBox.isVisible}
        onClose={() => setMessageBox({ isVisible: false, type: "success", message: "" })}
      />
    </div>
  );
};

export default Sidebar;


