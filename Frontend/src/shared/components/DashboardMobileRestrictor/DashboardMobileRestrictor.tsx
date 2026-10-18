import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import './DashboardMobileRestrictor.css';

interface DashboardMobileRestrictorProps {
  children: React.ReactNode;
}

const DashboardMobileRestrictor: React.FC<DashboardMobileRestrictorProps> = ({ children }) => {
  const [isMobileOrTablet, setIsMobileOrTablet] = useState(false);
  const { logout } = useAuth();

  // Check if device is mobile or tablet (screens <= 1024px)
  useEffect(() => {
    const checkDevice = () => {
      const width = window.innerWidth;
      // Block dashboard on screens <= 1024px (includes mobile and iPad)
      setIsMobileOrTablet(width <= 1024);
    };

    // Check immediately
    checkDevice();

    // Listen for resize events
    window.addEventListener('resize', checkDevice);
    
    return () => window.removeEventListener('resize', checkDevice);
  }, []);

  const handleLogout = async () => {
    try {
      await logout();
      window.location.href = '/';
    } catch (error) {
      console.error('Logout error:', error);
      window.location.href = '/';
    }
  };

  // Show blocker on mobile/tablet - same layout as no-internet page
  if (isMobileOrTablet) {
    return (
      <div className="dashboard-mobile-blocker">
        <Link to="/" className="dashboard-blocker-logo evecta-logo">
          <span className="evecta-logo-text">Evecta</span>
          <span className="evecta-logo-tagline">AI-Powered Platform</span>
        </Link>

        <div className="dashboard-blocker-content">
          <div className="dashboard-blocker-slack-icon" aria-hidden>
            <svg width="44" height="44" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <defs>
                <linearGradient id="dashboardBlockerSlackGrad" x1="0" y1="0" x2="24" y2="0" gradientUnits="userSpaceOnUse">
                  <stop offset="0%" stopColor="#D458FF" stopOpacity="0.7" />
                  <stop offset="100%" stopColor="#6B21A8" stopOpacity="1" />
                </linearGradient>
              </defs>
              <rect width="3" height="8" x="13" y="2" rx="1.5" stroke="url(#dashboardBlockerSlackGrad)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M19 8.5V10h1.5A1.5 1.5 0 1 0 19 8.5" stroke="url(#dashboardBlockerSlackGrad)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              <rect width="3" height="8" x="8" y="14" rx="1.5" stroke="url(#dashboardBlockerSlackGrad)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M5 15.5V14H3.5A1.5 1.5 0 1 0 5 15.5" stroke="url(#dashboardBlockerSlackGrad)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              <rect width="8" height="3" x="14" y="13" rx="1.5" stroke="url(#dashboardBlockerSlackGrad)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M15.5 19H14v1.5a1.5 1.5 0 1 0 1.5-1.5" stroke="url(#dashboardBlockerSlackGrad)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              <rect width="8" height="3" x="2" y="8" rx="1.5" stroke="url(#dashboardBlockerSlackGrad)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M8.5 5H10V3.5A1.5 1.5 0 1 0 8.5 5" stroke="url(#dashboardBlockerSlackGrad)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <h1 className="dashboard-blocker-title">Desktop Required</h1>
          <p className="dashboard-blocker-description">
            The dashboard is currently only available on desktop and laptop devices.
            Please visit us on a larger screen to access your dashboard.
          </p>
          <p className="dashboard-blocker-secondary">
            You can still access login and signup on mobile devices.
          </p>
          <button
            type="button"
            className="dashboard-blocker-logout-button"
            onClick={handleLogout}
          >
            Logout
          </button>
          <div className="dashboard-blocker-footer">evecta.io</div>
        </div>
      </div>
    );
  }

  return <>{children}</>;
};

export default DashboardMobileRestrictor;

