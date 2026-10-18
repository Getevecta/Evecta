import { useState, useEffect, useLayoutEffect, useRef } from 'react';
import { HelmetProvider } from 'react-helmet-async';
import { BrowserRouter as Router, Routes, Route, useLocation, Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { AuthProvider, useAuth } from './shared/contexts/AuthContext';
import { PopupProvider } from './shared/contexts/PopupProvider';
import ProtectedRoute from './shared/components/ProtectedRoute/ProtectedRoute';
import PublicRoute from './shared/components/PublicRoute/PublicRoute';
import Sidebar from './shared/components/Sidebar/Sidebar';
import PageWrapper from './shared/components/PageWrapper/PageWrapper';
import { Toaster } from 'sonner';
import HomePage from './features/homepage/HomePage';
import AboutUsPage from './features/about/AboutUsPage';
import BlogPage from './features/blog/BlogPage';
import BlogPost from './features/blog/BlogPost';
import AuthPage from './features/auth/AuthPage';
import ForgotPassword from './features/auth/ForgotPassword';
import VerifyResetOTP from './features/auth/VerifyResetOTP';
import ResetPassword from './features/auth/ResetPassword';
import OTPVerification from './features/auth/OTPVerification';
import AdminLogin2FA from './features/auth/AdminLogin2FA';
import GoogleCallback from './features/auth/GoogleCallback';
import PrivacyPolicy from './features/privacy/PrivacyPolicy';
import TermsOfService from './features/privacy/TermsOfService';
import Dashboard from './features/dashboard/Dashboard';
import DashboardLayout from './features/dashboard/DashboardLayout';
import NotFoundPage from './features/404/NotFoundPage';
import NoInternetConnection from './features/noInternet/NoInternetConnection';
import WaitlistPage from './features/waitlist/WaitlistPage';
import ContactPage from './features/contact/ContactPage';
import { Menu } from 'lucide-react';
import DashboardMobileRestrictor from './shared/components/DashboardMobileRestrictor/DashboardMobileRestrictor';
import { apiService } from './shared/services/api';
import './App.css';

/** Reset window scroll when the route path changes (e.g. footer links). */
function ScrollToTop() {
  const { pathname } = useLocation();
  useLayoutEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: 'auto' });
    document.documentElement.scrollTop = 0;
    document.body.scrollTop = 0;
    const root = document.getElementById('root');
    if (root) root.scrollTop = 0;
  }, [pathname]);
  return null;
}

// Component to redirect authenticated users to dashboard
// But allow waitlisted users to stay on public pages like homepage
function RedirectIfAuthenticated({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, loading, user } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [checkingWaitlist, setCheckingWaitlist] = useState(false); // Start as false, only check when authenticated
  const [isOnWaitlist, setIsOnWaitlist] = useState(false);
  const hasCheckedWaitlist = useRef(false);
  const hasRedirected = useRef(false);

  useEffect(() => {
    // Reset redirect flag when user logs out
    if (!isAuthenticated || !user) {
      setCheckingWaitlist(false);
      hasCheckedWaitlist.current = false;
      hasRedirected.current = false;
      setIsOnWaitlist(false);
      return;
    }

    // Prevent multiple checks
    if (hasCheckedWaitlist.current) {
      return;
    }

    hasCheckedWaitlist.current = true;
    setCheckingWaitlist(true); // Set to true only when we're actually checking
    
    const checkWaitlist = async () => {
      try {
        const response = await apiService.checkWaitlistStatus();
        if (response.data && (response.data.is_on_waitlist || response.data.user_limit_reached)) {
          setIsOnWaitlist(true);
        }
      } catch (error) {
        console.error('Error checking waitlist status:', error);
        // If error, assume not on waitlist (fail open)
      } finally {
        setCheckingWaitlist(false);
      }
    };

    checkWaitlist();
  }, [isAuthenticated, user]);

  // Redirect to dashboard if authenticated and not on waitlist (must be before any conditional return to satisfy Rules of Hooks)
  useEffect(() => {
    if (isAuthenticated && !isOnWaitlist && !hasRedirected.current) {
      const currentPath = location.pathname;
      if (currentPath.startsWith('/auth') || currentPath === '/') {
        hasRedirected.current = true;
        const isAdmin = Boolean(
          user && (user.is_admin || user.is_superuser || user.role === 'admin')
        );
        navigate(isAdmin ? '/dashboard/admin/ai-usage' : '/dashboard', { replace: true });
      }
    }
  }, [isAuthenticated, isOnWaitlist, location.pathname, navigate, user]);

  // For unauthenticated users, always render content immediately - don't block on loading
  if (!isAuthenticated) {
    return <>{children}</>;
  }

  // User is authenticated - show loading only when checking waitlist
  if (checkingWaitlist) {
    return (
      <div className="loading-container">
        <div className="loading-spinner" />
        <p>Loading...</p>
      </div>
    );
  }

  return <>{children}</>;
}

/** Preserves ?session_id= from Stripe success_url into dashboard location state for server sync. */
function BillingSuccessNavigate() {
  const [searchParams] = useSearchParams();
  const sessionId = searchParams.get('session_id') ?? undefined;
  return (
    <Navigate
      to="/dashboard/settings/billing"
      replace
      state={{
        billingCheckout: 'success' as const,
        ...(sessionId ? { stripeSessionId: sessionId } : {}),
      }}
    />
  );
}

function AppContent() {
  const location = useLocation();
  const isHomePage = location.pathname === '/';
  const isBlogPage = location.pathname === '/blog' || location.pathname.startsWith('/blog/');
  const isPrivacyPolicy = location.pathname === '/privacy-policy';
  const isTermsOfService = location.pathname === '/terms-of-service';
  const isWaitlist = location.pathname === '/waitlist';
  const isContact = location.pathname === '/contact';
  const isAboutUs = location.pathname === '/about_us';
  const isDashboard = location.pathname.startsWith('/dashboard');
  const isBillingStripeReturn =
    location.pathname === '/billing/success' || location.pathname === '/billing/cancel';
  const isAuth = location.pathname === '/auth' || 
                 location.pathname === '/otp-verification' || 
                 location.pathname === '/admin-login-2fa' ||
                 location.pathname === '/forgot-password' || 
                 location.pathname === '/verify-reset-otp' || 
                 location.pathname === '/reset-password' || 
                 location.pathname.startsWith('/auth/google');
  const isStandaloneNotFound = location.pathname === '/404';
  const isNoInternetPreview = location.pathname === '/no-internet';
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);

  // Close mobile menu when route changes
  useEffect(() => {
    setIsMobileMenuOpen(false);
  }, [location.pathname]);

  // Track route changes for analytics - Only track on production (evecta.io)
  useEffect(() => {
    // Only track on production domain
    if (window.location.hostname !== 'evecta.io') {
      return;
    }

    // Track page view in PostHog
    if (window.posthog) {
      window.posthog.capture('$pageview', {
        $current_url: window.location.href,
        path: location.pathname,
      });
    }

    // Track page view in Google Analytics
    if (window.gtag) {
      window.gtag('config', 'G-3NQW5YY961', {
        page_path: location.pathname,
        page_title: document.title,
      });
    }
  }, [location.pathname]);

  // Close mobile menu when clicking outside (backup handler)
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as Element;
      // Only close if clicking on overlay or outside sidebar, not on sidebar itself
      if (isMobileMenuOpen) {
        const isOverlay = target.closest('.sidebar-overlay');
        const isSidebar = target.closest('.sidebar');
        const isToggle = target.closest('.mobile-menu-toggle');
        
        if ((isOverlay || (!isSidebar && !isToggle))) {
        setIsMobileMenuOpen(false);
      }
      }
    };

    if (isMobileMenuOpen) {
      document.addEventListener('click', handleClickOutside, true); // Use capture phase
      return () => document.removeEventListener('click', handleClickOutside, true);
    }
  }, [isMobileMenuOpen]);

  const toggleMobileMenu = (): void => {
    setIsMobileMenuOpen(!isMobileMenuOpen);
  };

  // If it's the homepage, render it standalone without any UI elements
  if (isHomePage) {
    return (
      <Routes>
        <Route path="/" element={
          <RedirectIfAuthenticated>
            <HomePage />
          </RedirectIfAuthenticated>
        } />
      </Routes>
    );
  }

  // If it's the blog page, render it standalone without any UI elements
  if (isBlogPage) {
    return (
      <Routes>
        <Route path="/blog" element={<BlogPage />} />
        <Route path="/blog/:id" element={<BlogPost />} />
      </Routes>
    );
  }

  // If it's the privacy policy page, render it standalone without any UI elements
  if (isPrivacyPolicy) {
    return <PrivacyPolicy />;
  }

  // If it's the terms of service page, render it standalone without any UI elements
  if (isTermsOfService) {
    return <TermsOfService />;
  }

  // If it's the waitlist page, render it standalone
  if (isWaitlist) {
    return (
      <Routes>
        <Route path="/waitlist" element={<WaitlistPage />} />
      </Routes>
    );
  }

  // If it's the contact page, render it standalone
  if (isContact) {
    return (
      <Routes>
        <Route path="/contact" element={<ContactPage />} />
      </Routes>
    );
  }

  // Legacy /about (Discover) route → About Us
  if (location.pathname === '/about') {
    return (
      <Routes>
        <Route path="/about" element={<Navigate to="/about_us" replace />} />
      </Routes>
    );
  }

  // If it's the about us page, render it standalone
  if (isAboutUs) {
    return (
      <Routes>
        <Route path="/about_us" element={<AboutUsPage />} />
      </Routes>
    );
  }

  // If it's the dedicated 404 route, render it standalone without sidebar
  if (isStandaloneNotFound) {
    return (
      <Routes>
        <Route path="/404" element={<NotFoundPage />} />
      </Routes>
    );
  }

  // Preview No Internet page - visit /no-internet to see the design
  if (isNoInternetPreview) {
    return (
      <Routes>
        <Route path="/no-internet" element={<NoInternetConnection />} />
      </Routes>
    );
  }

  // If it's an auth route, render it standalone without sidebar
  if (isAuth) {
    return (
      <Routes>
        <Route path="/auth" element={
          <PublicRoute>
            <AuthPage />
          </PublicRoute>
        } />
        <Route path="/forgot-password" element={
          <PublicRoute>
            <ForgotPassword />
          </PublicRoute>
        } />
        <Route path="/verify-reset-otp" element={
          <PublicRoute>
            <VerifyResetOTP />
          </PublicRoute>
        } />
        <Route path="/reset-password" element={
          <PublicRoute>
            <ResetPassword />
          </PublicRoute>
        } />
        <Route path="/otp-verification" element={
          <PublicRoute>
            <OTPVerification />
          </PublicRoute>
        } />
        <Route path="/admin-login-2fa" element={
          <PublicRoute>
            <AdminLogin2FA />
          </PublicRoute>
        } />
        <Route path="/auth/google/success" element={
          <PublicRoute>
            <GoogleCallback />
          </PublicRoute>
        } />
        <Route path="/auth/google/callback" element={
          <PublicRoute>
            <GoogleCallback />
          </PublicRoute>
        } />
      </Routes>
    );
  }

  // Stripe Checkout return URLs (must match backend FRONTEND_URL + /billing/...)
  if (isBillingStripeReturn) {
    return (
      <Routes>
        <Route
          path="/billing/success"
          element={
            <ProtectedRoute>
              <BillingSuccessNavigate />
            </ProtectedRoute>
          }
        />
        <Route
          path="/billing/cancel"
          element={
            <ProtectedRoute>
              <Navigate
                to="/dashboard/settings/billing"
                replace
                state={{ billingCheckout: 'cancel' as const }}
              />
            </ProtectedRoute>
          }
        />
      </Routes>
    );
  }

  // If it's a dashboard route, use the dashboard layout with protection and mobile restriction
  if (isDashboard) {
    return (
      <Routes>
        <Route path="/dashboard/*" element={
          <ProtectedRoute>
            <DashboardMobileRestrictor>
              <DashboardLayout />
            </DashboardMobileRestrictor>
          </ProtectedRoute>
        }>
          <Route index element={<Navigate to="/dashboard/generate" replace />} />
          <Route path="campaigns/:campaignId/edit" element={<Dashboard />} />
          <Route path="*" element={<Dashboard />} />
        </Route>
      </Routes>
    );
  }

  // Main app layout for all other routes
  return (
    <div className="app">
      {/* Mobile menu toggle */}
      <button 
        className={`mobile-menu-toggle ${isMobileMenuOpen ? 'sidebar-open' : ''}`}
        onClick={toggleMobileMenu}
        aria-label="Toggle menu"
      >
        <Menu />
      </button>

      {/* Sidebar overlay for mobile */}
      <>
        {/* Overlay - Render first so sidebar is on top via z-index */}
        {isMobileMenuOpen && (
          <div 
            className="sidebar-overlay active"
            onClick={() => {
              setIsMobileMenuOpen(false);
            }}
          />
        )}

        {/* Sidebar - Render after overlay, but z-index puts it on top */}
        <Sidebar 
          key={`sidebar-${isMobileMenuOpen}`}
          isMobileOpen={isMobileMenuOpen}
          onMobileClose={() => {
            setIsMobileMenuOpen(false);
          }}
        />
      </>

      <main className="main-content">
        <PageWrapper>
          <Routes>
            <Route path="/chat" element={<Navigate to="/" replace />} />

            {/* Fallback route -> redirect to standalone 404 page */}
            <Route path="*" element={<Navigate to="/404" replace />} />
          </Routes>
        </PageWrapper>
      </main>
    </div>
  );
}

function App() {
  const [isOnline, setIsOnline] = useState(() => navigator.onLine);

  useEffect(() => {
    const handleOnline = () => setIsOnline(true);
    const handleOffline = () => setIsOnline(false);
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);

  return (
    <HelmetProvider>
      <AuthProvider>
        <PopupProvider>
          <Router>
            <ScrollToTop />
            <AppContent />
            {!isOnline && <NoInternetConnection onRetry={() => window.location.reload()} />}
            <Toaster position="top-right" offset={12} richColors duration={4000} visibleToasts={3} />
          </Router>
        </PopupProvider>
      </AuthProvider>
    </HelmetProvider>
  );
}

export default App;


