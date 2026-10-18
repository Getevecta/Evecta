import React, { useState, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import './MobileRestrictor.css';
import { Laptop } from 'lucide-react';

interface MobileRestrictorProps {
  children: React.ReactNode;
}

const MobileRestrictor: React.FC<MobileRestrictorProps> = ({ children }) => {
  const location = useLocation();
  const [isMobileOrTablet, setIsMobileOrTablet] = useState(false);

  // Check if current route is a dashboard route
  const isDashboardRoute = location.pathname.startsWith('/dashboard');

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

  // Only show blocker for dashboard routes on mobile/tablet
  const shouldBlock = isDashboardRoute && isMobileOrTablet;

  return (
    <>
      {shouldBlock && (
        <div className="mobile-only-blocker">
          <div className="blocker-content">
            <div className="blocker-icon">
              <Laptop size={48} />
            </div>
            <h1>Desktop Required</h1>
            <p>
              The dashboard is currently only available on desktop and laptop devices. 
              Please visit us on a larger screen to access your dashboard.
            </p>
            <p className="blocker-secondary-text">
              You can still access login and signup on mobile devices.
            </p>
            <div className="blocker-footer">
              evecta.io
            </div>
          </div>
        </div>
      )}
      <div className={shouldBlock ? 'desktop-content blocked' : 'desktop-content'}>
        {children}
      </div>
    </>
  );
};

export default MobileRestrictor;

