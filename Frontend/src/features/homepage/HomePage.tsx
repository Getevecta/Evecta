import React, { useState, useEffect, useLayoutEffect, useRef, useCallback } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { PrimaryButton } from './components/Button';
import { Card, CardContent } from '../../features/dashboard/components/ui/card';
import { Badge } from '../../features/dashboard/components/ui/badge';
import { cn } from '../../features/dashboard/components/ui/utils';
import { 
  Sparkles, 
  Target, 
  TrendingUp, 
  Mail, 
  BarChart3,
  Users,
  Globe,
  Shield,
  Clock,
  Star,
  Send,
  Brain,
  MessageSquare,
  Database,
  LineChart,
  ArrowUpRight,
  Rocket,
  TrendingDown,
  Filter,
  Search,
  Workflow,
  Eye,
  MousePointerClick,
  Inbox,
  Calendar,
  DollarSign,
  UserPlus,
  Activity,
  Smile,
  Circle,
  MoveRight,
  ArrowRight,
  LayoutGrid,
  Check,
  GitBranch,
} from 'lucide-react';
// @ts-ignore - framer-motion types may not be fully compatible
import { motion } from 'framer-motion';
import { XAxis, YAxis, ResponsiveContainer, LineChart as RechartsLineChart, Line } from 'recharts';
import apiService from '../../shared/services/api';
import { useAuth } from '../../shared/contexts/AuthContext';
import { PageSeo } from '../../shared/components/PageSeo/PageSeo';
import { PLANS, type Plan } from '../dashboard/components/Billing/BillingPage';
import './HomePage.css';

/** Desktop frame (::before) + mobile <img> — keep order aligned with `features` items in HomePage. */
const FEATURE_DESKTOP_IMAGES = [
  '/Frame 2121457639.svg',
  '/Group 1171275152.svg',
  '/Frame 2121457911.svg',
] as const;

const FEATURE_MOBILE_IMAGES = [
  '/Frame%202121457614%202.png',
  '/Frame%202121457614%203.png',
  '/Group%201171275153.png',
] as const;

function preloadFeatureCarouselImages() {
  for (const url of [...FEATURE_DESKTOP_IMAGES, ...FEATURE_MOBILE_IMAGES]) {
    const img = new Image();
    img.src = url;
  }
}

// Header and footer exported so Privacy/Terms can use same layout without new files
export interface HomePageHeaderProps {
  isDark?: boolean;
}

export function HomePageHeader({ isDark = true }: HomePageHeaderProps) {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [headerVisible, setHeaderVisible] = useState(true);
  const lastScrollY = useRef(0);
  const scrollRafId = useRef(0);

  const closeMobileMenu = () => setIsMobileMenuOpen(false);

  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeMobileMenu();
    };
    if (isMobileMenuOpen) {
      document.addEventListener('keydown', handleEscape);
      document.body.style.overflow = 'hidden';
    }
    return () => {
      document.removeEventListener('keydown', handleEscape);
      document.body.style.overflow = '';
    };
  }, [isMobileMenuOpen]);

  /* Hide on scroll down, show on scroll up or near top.
   * Global dashboard.css sets html/body/#root to height:100% — scroll often happens on #root
   * while window.pageYOffset stays 0, so we must read scrollTop from scrollingElement + #root. */
  useEffect(() => {
    const getScrollY = () => {
      const root = document.getElementById('root');
      const se = document.scrollingElement;
      const w = window.pageYOffset;
      const seTop = se?.scrollTop ?? 0;
      const rootTop = root?.scrollTop ?? 0;
      const docTop = document.documentElement?.scrollTop ?? 0;
      const bodyTop = document.body?.scrollTop ?? 0;
      return Math.max(w, seTop, rootTop, docTop, bodyTop);
    };

    const applyScrollDirection = () => {
      const y = getScrollY();
      const prev = lastScrollY.current;
      lastScrollY.current = y;
      if (y <= 24) {
        setHeaderVisible(true);
      } else if (y > prev) {
        setHeaderVisible(false);
      } else {
        setHeaderVisible(true);
      }
    };

    const onScroll = () => {
      if (scrollRafId.current) return;
      scrollRafId.current = requestAnimationFrame(() => {
        scrollRafId.current = 0;
        applyScrollDirection();
      });
    };

    lastScrollY.current = getScrollY();
    applyScrollDirection();

    const root = document.getElementById('root');
    window.addEventListener('scroll', onScroll, { passive: true });
    root?.addEventListener('scroll', onScroll, { passive: true });
    document.documentElement.addEventListener('scroll', onScroll, { passive: true });
    window.visualViewport?.addEventListener('scroll', onScroll, { passive: true });

    return () => {
      window.removeEventListener('scroll', onScroll);
      root?.removeEventListener('scroll', onScroll);
      document.documentElement.removeEventListener('scroll', onScroll);
      window.visualViewport?.removeEventListener('scroll', onScroll);
      if (scrollRafId.current) cancelAnimationFrame(scrollRafId.current);
    };
  }, []);

  const headerRouteLink = (to: string, label: string) => (
    <Link
      to={to}
      onClick={closeMobileMenu}
      className="text-s font-medium hover:text-primary transition-colors whitespace-nowrap cursor-pointer homepage-nav-link no-underline"
    >
      {label}
    </Link>
  );

  return (
    <>
      <div className={cn('homepage-header-wrapper', !headerVisible && 'homepage-header-wrapper--hidden')}>
        <header className="homepage-header z-50 w-full">
          <div className="homepage-header-inner w-full flex items-center">
            <Link to="/" className={cn('homepage-header-logo evecta-logo no-underline shrink-0', isDark && 'evecta-logo-light')}>
              <span className="evecta-logo-text">Evecta</span>
              <span className="evecta-logo-tagline">AI-Powered Platform</span>
            </Link>
            <nav className="homepage-header-nav hidden md:flex items-center gap-8 whitespace-nowrap flex-1 justify-center">
              {headerRouteLink('/', 'Home')}
              {headerRouteLink('/about_us', 'About us')}
              {headerRouteLink('/contact', 'Contact us')}
              {headerRouteLink('/blog', 'Blog')}
            </nav>
            <div className="homepage-header-mobile-right md:hidden flex items-center shrink-0">
              <button type="button" className="homepage-mobile-menu-btn" aria-label="Menu" onClick={() => setIsMobileMenuOpen(true)}>
                <LayoutGrid className="homepage-mobile-menu-icon" size={20} strokeWidth={2} aria-hidden />
              </button>
              <span className="homepage-mobile-separator" aria-hidden="true" />
              <Link to="/auth" className="homepage-header-cta-link homepage-mobile-cta text-s font-medium whitespace-nowrap cursor-pointer no-underline inline-flex items-center gap-[10px]">
                Get Started Free <ArrowRight className="h-4 w-4 flex-shrink-0" aria-hidden />
              </Link>
            </div>
            <div className="homepage-header-cta-wrap hidden md:inline-flex shrink-0 items-center pl-4">
              <Link to="/auth" className="homepage-header-cta-link text-s font-medium whitespace-nowrap cursor-pointer no-underline inline-flex items-center gap-[10px]">
                Get Started Free <ArrowRight className="h-4 w-4 flex-shrink-0" aria-hidden />
              </Link>
            </div>
          </div>
        </header>
        <div className="homepage-header-line" aria-hidden="true" />
      </div>

      {/* Mobile menu slide-in from right - nav links only, no Get Started */}
      <div className={cn('homepage-mobile-menu-overlay md:hidden', isMobileMenuOpen && 'homepage-mobile-menu-overlay--open')} onClick={closeMobileMenu} aria-hidden={!isMobileMenuOpen} />
      <aside className={cn('homepage-mobile-menu md:hidden', isMobileMenuOpen && 'homepage-mobile-menu--open')} aria-label="Navigation menu">
        <div className="homepage-mobile-menu-inner">
          <button type="button" className="homepage-mobile-menu-close" onClick={closeMobileMenu} aria-label="Close menu">
            <span aria-hidden>×</span>
          </button>
          <nav className="homepage-mobile-menu-nav">
            {headerRouteLink('/', 'Home')}
            {headerRouteLink('/about_us', 'About us')}
            {headerRouteLink('/contact', 'Contact us')}
            {headerRouteLink('/blog', 'Blog')}
          </nav>
        </div>
      </aside>

      <div className="homepage-header-spacer" aria-hidden="true" />
    </>
  );
}

function scrollDocumentToTop() {
  window.scrollTo({ top: 0, left: 0, behavior: 'auto' });
  document.documentElement.scrollTop = 0;
  document.body.scrollTop = 0;
  const root = document.getElementById('root');
  if (root) root.scrollTop = 0;
}

export function HomePageFooter({ className }: { className?: string }) {
  return (
    <section className={cn('homepage-cta-footer-section', className)}>
      <div className="w-full mx-auto homepage-content-inner">
        <motion.div initial={{ opacity: 0, y: 20 }} whileInView={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }} viewport={{ once: true }} className="homepage-cta-block">
          <h2 className="homepage-cta-heading">
            Ready to 10x your
            <br aria-hidden="true" />
            <span className="homepage-cta-heading-accent">pipeline?</span>
          </h2>
          <p className="homepage-cta-description">
            Join over 10,000 teams saving their effort with verified and spam-free outreach to
            connect with their ideal customers.
          </p>
          <div className="homepage-cta-button-wrap">
            <Link
              to="/auth"
              onClick={scrollDocumentToTop}
              className="homepage-cta-button homepage-hero-primary-btn evecta-primary-btn"
            >
              Get Started <ArrowRight className="h-4 w-4 flex-shrink-0" aria-hidden />
            </Link>
          </div>
        </motion.div>
        <footer className="homepage-footer-card w-full">
          <div className="homepage-footer-inner">
            <div className="homepage-footer-top">
              <div className="homepage-footer-brand">
                <Link to="/" onClick={scrollDocumentToTop} className="homepage-footer-logo-link evecta-logo evecta-logo-light no-underline">
                  <span className="evecta-logo-text">Evecta</span>
                  <span className="evecta-logo-tagline">AI-Powered Platform</span>
                </Link>
              </div>
              <p className="homepage-footer-desc">
                Supercharge your sales pipeline with AI-driven
                <br className="homepage-br-laptop-only" aria-hidden="true" />{' '}
                leads, tailored outreach, spam protection, and
                <br className="homepage-br-laptop-only" aria-hidden="true" />{' '}
                real-time analytics for scalable growth.
              </p>
              <div className="homepage-footer-brand-divider" role="presentation" aria-hidden="true" />
            </div>
            <div className="homepage-footer-mid">
              <div className="homepage-footer-links">
                <div className="homepage-footer-col">
                  <div className="homepage-footer-col-stack">
                    <h4 className="homepage-footer-col-title">Company</h4>
                    <ul className="homepage-footer-list">
                      <li>
                        <Link to="/about_us" onClick={scrollDocumentToTop} className="homepage-footer-link">
                          About
                        </Link>
                      </li>
                      <li>
                        <Link to="/blog" onClick={scrollDocumentToTop} className="homepage-footer-link">
                          Blog
                        </Link>
                      </li>
                      <li>
                        <Link to="/contact" onClick={scrollDocumentToTop} className="homepage-footer-link">
                          Contact
                        </Link>
                      </li>
                    </ul>
                  </div>
                </div>
                <div className="homepage-footer-col">
                  <div className="homepage-footer-col-stack">
                    <h4 className="homepage-footer-col-title">Product</h4>
                    <ul className="homepage-footer-list">
                      <li>
                        <Link to="/" onClick={scrollDocumentToTop} className="homepage-footer-link">
                          Features
                        </Link>
                      </li>
                    </ul>
                  </div>
                </div>
                <div className="homepage-footer-col">
                  <div className="homepage-footer-col-stack">
                    <h4 className="homepage-footer-col-title">Legal</h4>
                    <ul className="homepage-footer-list homepage-footer-list--inline">
                      <li>
                        <Link to="/privacy-policy" onClick={scrollDocumentToTop} className="homepage-footer-link">
                          Privacy Policy
                        </Link>
                      </li>
                      <li>
                        <Link to="/terms-of-service" onClick={scrollDocumentToTop} className="homepage-footer-link">
                          Terms Of Service
                        </Link>
                      </li>
                    </ul>
                  </div>
                </div>
              </div>
              <div className="homepage-footer-social">
                <a href="https://www.facebook.com" target="_blank" rel="noopener noreferrer" className="homepage-footer-social-btn" aria-label="Facebook"><svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"/></svg></a>
                <a href="https://www.instagram.com/evecta_contact?utm_source=ig_web_button_share_sheet&igsh=ZDNlZDc0MzIxNw==" target="_blank" rel="noopener noreferrer" className="homepage-footer-social-btn" aria-label="Instagram"><svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zm0-2.163c-3.259 0-3.667.014-4.947.072-4.358.2-6.78 2.618-6.98 6.98-.059 1.281-.073 1.689-.073 4.948 0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98 1.281.058 1.689.072 4.948.072 3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98-1.281-.059-1.69-.073-4.949-.073zm0 5.838c-3.403 0-6.162 2.759-6.162 6.162s2.759 6.163 6.162 6.163 6.162-2.759 6.162-6.163c0-3.403-2.759-6.162-6.162-6.162zm0 10.162c-2.209 0-4-1.79-4-4 0-2.209 1.791-4 4-4s4 1.791 4 4c0 2.21-1.791 4-4 4zm6.406-11.845c-.796 0-1.441.645-1.441 1.44s.645 1.44 1.441 1.44c.795 0 1.439-.645 1.439-1.44s-.644-1.44-1.439-1.44z"/></svg></a>
                <a href="https://x.com/Evecta_contact?s=20" target="_blank" rel="noopener noreferrer" className="homepage-footer-social-btn" aria-label="Twitter"><svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg></a>
              </div>
            </div>
          </div>
          <p className="homepage-footer-copyright">© 2026 Evecta AI-Powered Platform. All rights reserved.</p>
        </footer>
      </div>
    </section>
  );
}

/** Check inside rounded-square outline only (stroke), same stroke and color - design match */
function HeroReassuranceCheckIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden
    >
      <rect
        x="2"
        y="2"
        width="20"
        height="20"
        rx="6"
        ry="6"
        stroke="currentColor"
        strokeWidth="2"
        fill="none"
      />
      <path
        d="M7 12.5l3.5 3.5 6.5-7"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  );
}

// Animated counter component
function AnimatedCounter({ end, duration = 2, suffix = '', prefix = '' }: { end: number; duration?: number; suffix?: string; prefix?: string }) {
  const [count, setCount] = useState(0);
  const ref = useRef<HTMLSpanElement>(null);
  const [hasAnimated, setHasAnimated] = useState(false);

  useEffect(() => {
    if (hasAnimated) return;
    
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting && !hasAnimated) {
            setHasAnimated(true);
            let startTime: number;
            let animationFrame: number;
            const animate = (timestamp: number) => {
              if (!startTime) startTime = timestamp;
              const progress = (timestamp - startTime) / (duration * 1000);
              if (progress < 1) {
                setCount(Math.floor(end * progress));
                animationFrame = requestAnimationFrame(animate);
              } else {
                setCount(end);
              }
            };
            animationFrame = requestAnimationFrame(animate);
          }
        });
      },
      { threshold: 0.1 }
    );

    if (ref.current) {
      observer.observe(ref.current);
    }

    return () => {
      if (ref.current) {
        observer.unobserve(ref.current);
      }
    };
  }, [end, duration, hasAnimated]);

  return <span ref={ref}>{prefix}{count.toLocaleString()}{suffix}</span>;
}


const HOMEPAGE_THEME_KEY = 'homepage-theme';
type HomepageTheme = 'light' | 'dark';

function homepagePricingPrice(plan: Plan): { main: string; line1: string; line2: string | null } {
  if (plan.id === 'free') {
    return { main: '$0', line1: 'Free for everyone', line2: null };
  }
  return {
    main: `$${plan.monthlyPrice}`,
    line1: 'per month',
    line2: `$${plan.annualEffectiveMonthly}/mo when billed annually · Save $${plan.annualSavings}/yr`,
  };
}

/** Paid tiers only — Free is available in-app / billing, not on the marketing pricing strip. */
const HOMEPAGE_PRICING_PLANS = PLANS.filter((p) => p.id !== 'free');

const HomePage: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated } = useAuth();
  const [activeStep, setActiveStep] = useState(0);
  const [howItWorksPauseAuto, setHowItWorksPauseAuto] = useState(false);
  const [activeFeatureIndex, setActiveFeatureIndex] = useState(0);
  const pricingGridRef = useRef<HTMLDivElement>(null);
  const [isFeaturesMobileLayout, setIsFeaturesMobileLayout] = useState(() =>
    typeof window !== 'undefined' ? window.matchMedia('(max-width: 1023px)').matches : false
  );

  useEffect(() => {
    const mq = window.matchMedia('(max-width: 1023px)');
    const sync = () => setIsFeaturesMobileLayout(mq.matches);
    sync();
    mq.addEventListener('change', sync);
    return () => mq.removeEventListener('change', sync);
  }, []);

  useEffect(() => {
    preloadFeatureCarouselImages();
  }, []);

  /** Same total height for the features block on every card so flex spacer aligns CTAs + “What’s included” across plans. */
  const syncPricingCardBottomHeights = useCallback(() => {
    const root = pricingGridRef.current;
    if (!root) return;
    const els = Array.from(root.querySelectorAll<HTMLElement>('[data-pricing-card-bottom]'));
    if (els.length === 0) return;
    els.forEach((el) => {
      el.style.minHeight = '';
    });
    void root.offsetHeight;
    const heights = els.map((el) => el.getBoundingClientRect().height);
    const maxH = Math.ceil(Math.max(...heights, 0));
    if (maxH <= 0) return;
    els.forEach((el) => {
      el.style.minHeight = `${maxH}px`;
    });
  }, []);

  useLayoutEffect(() => {
    const root = pricingGridRef.current;
    if (!root) return;

    const run = () => {
      requestAnimationFrame(() => syncPricingCardBottomHeights());
    };

    run();

    const onResize = () => run();
    window.addEventListener('resize', onResize);

    let mq: MediaQueryList | null = null;
    if (typeof window.matchMedia === 'function') {
      mq = window.matchMedia('(min-width: 1024px)');
      mq.addEventListener('change', onResize);
    }

    const fonts = document.fonts;
    if (fonts?.ready) {
      void fonts.ready.then(() => run());
    }

    return () => {
      window.removeEventListener('resize', onResize);
      mq?.removeEventListener?.('change', onResize);
    };
  }, [syncPricingCardBottomHeights]);

  useEffect(() => {
    const id = requestAnimationFrame(() => syncPricingCardBottomHeights());
    return () => cancelAnimationFrame(id);
  }, [syncPricingCardBottomHeights]);

  const [theme, setTheme] = useState<HomepageTheme>(() => {
    try {
      const stored = localStorage.getItem(HOMEPAGE_THEME_KEY);
      if (stored === 'light' || stored === 'dark') return stored;
    } catch (_) {}
    return 'dark';
  });

  const toggleTheme = () => {
    setTheme((prev) => {
      const next = prev === 'dark' ? 'light' : 'dark';
      try {
        localStorage.setItem(HOMEPAGE_THEME_KEY, next);
      } catch (_) {}
      return next;
    });
  };

  // Scroll to section when URL hash is set (direct links or in-app navigation)
  useEffect(() => {
    const raw = location.hash.replace(/^#/, '');
    if (!raw) return;
    const id = decodeURIComponent(raw);
    const t = window.setTimeout(() => {
      const element = document.getElementById(id);
      if (element) {
        element.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }, 80);
    return () => clearTimeout(t);
  }, [location.hash]);

  const handleGetStarted = () => {
    navigate('/auth');
  };

  const handleContactClick = () => {
    // Navigate to contact or open contact modal
    window.location.href = '#contact';
  };

  const howItWorksSteps = [
    {
      number: 1,
      title: 'AI-Powered Requirement Chat',
      description:
        'Specify your target audience to our AI include details like industry, role, company size and location.',
      icon: MessageSquare,
      visual: 'chat'
    },
    {
      number: 2,
      title: 'Discover High Quality Leads',
      description:
        'Let AI scan global datasets to identify and surface prospects that perfectly align with your business goals.',
      icon: Search,
      visual: 'search'
    },
    {
      number: 3,
      title: 'Build Your Lead Database',
      description:
        'Review the matches and save your best prospects into an organized lead database for structured outreach.',
      icon: Filter,
      visual: 'organize'
    },
    {
      number: 4,
      title: 'Spam Safe AI Outreach',
      description:
        'Launch personalized AI messages with built-in spam protection to ensure you always land in the inbox.',
      icon: Send,
      visual: 'outreach'
    },
    {
      number: 5,
      title: 'Real Time Growth Analytics',
      description:
        'Track your performance through a clear dashboard and refine your strategy to scale what works.',
      icon: BarChart3,
      visual: 'analytics'
    }
  ];

  /** How it works — preview panel (same order as `howItWorksSteps`) */
  const HOW_IT_WORKS_PREVIEW_IMAGES = [
    '/AI-Powered%20Requirement%20Chat%20image.png',
    '/Discover%20High%20Quality%20Leads%20image.png',
    '/Build%20Your%20Lead%20Database%20image.png',
    '/Spam%20Safe%20AI%20Outreach%20image.png',
    '/Real%20Time%20Growth%20Analytics%20image.png',
  ] as const;

  const comparisonData = {
    before: [
      { label: 'Time spent researching leads', value: '20+ hours/week', icon: Clock, bad: true },
      { label: 'Lead quality & accuracy', value: '45-60%', icon: Target, bad: true },
      { label: 'Email response rates', value: '2-4%', icon: Mail, bad: true },
      { label: 'Manual data entry errors', value: '15-20%', icon: TrendingDown, bad: true }
    ],
    after: [
      { label: 'Time spent researching leads', value: '< 2 hours/week', icon: Clock, good: true },
      { label: 'Lead quality & accuracy', value: '95-98%', icon: Target, good: true },
      { label: 'Email response rates', value: '12-18%', icon: Mail, good: true },
      { label: 'Manual data entry errors', value: '0%', icon: TrendingUp, good: true }
    ]
  };

  const impactMetrics = [
    {
      icon: Users,
      number: 523000,
      label: 'Leads Generated',
      sublabel: 'across all customers',
      gradient: 'from-blue-500 to-cyan-500'
    },
    {
      icon: Rocket,
      number: 10,
      suffix: 'x',
      label: 'Faster Prospecting',
      sublabel: 'vs manual research',
      gradient: 'from-purple-500 to-pink-500'
    },
    {
      icon: TrendingUp,
      number: 215,
      suffix: '%',
      label: 'Revenue Increase',
      sublabel: 'average customer growth',
      gradient: 'from-green-500 to-emerald-500'
    },
    {
      icon: DollarSign,
      number: 2.4,
      suffix: 'M',
      prefix: '$',
      label: 'Pipeline Created',
      sublabel: 'for our customers',
      gradient: 'from-orange-500 to-red-500'
    }
  ];

  const features: Array<{
    title: string;
    description: string;
    image: string;
  }> = [
    {
      title: 'AI-Powered Lead Discovery',
      description:
        'Define your ideal customer profile, find qualified leads, save them to your database, and automatically maintain a complete search history.',
      image: FEATURE_DESKTOP_IMAGES[0],
    },
    {
      title: 'Outreach with Spam Protection',
      description:
        'Craft high-impact outreach with AI, write manually or custom templates, backed by a built-in spam-risk check before every email hits the inbox.',
      image: FEATURE_DESKTOP_IMAGES[1],
    },
    {
      title: 'Analytics Dashboard',
      description:
        'Track open rates, reply rates, conversions, and ROI across every campaign and make smarter decisions with real-time data.',
      image: FEATURE_DESKTOP_IMAGES[2],
    }
  ];

  const featuresSwipeStartRef = useRef<{ x: number; y: number } | null>(null);
  const onFeaturesSwipeTouchStart = useCallback((e: React.TouchEvent) => {
    if (!isFeaturesMobileLayout) return;
    const touch = e.touches[0];
    featuresSwipeStartRef.current = { x: touch.clientX, y: touch.clientY };
  }, [isFeaturesMobileLayout]);

  const onFeaturesSwipeTouchEnd = useCallback(
    (e: React.TouchEvent) => {
      if (!isFeaturesMobileLayout || !featuresSwipeStartRef.current) return;
      const touch = e.changedTouches[0];
      const dx = touch.clientX - featuresSwipeStartRef.current.x;
      const dy = touch.clientY - featuresSwipeStartRef.current.y;
      featuresSwipeStartRef.current = null;
      const minSwipe = 48;
      if (Math.abs(dx) < minSwipe) return;
      if (Math.abs(dy) > Math.abs(dx) * 0.85) return;
      const len = features.length;
      if (dx < 0) {
        setActiveFeatureIndex((prev) => (prev + 1) % len);
      } else {
        setActiveFeatureIndex((prev) => (prev - 1 + len) % len);
      }
    },
    [isFeaturesMobileLayout]
  );

  const onFeaturesSwipeTouchCancel = useCallback(() => {
    featuresSwipeStartRef.current = null;
  }, []);

  const testimonials = [
    {
      name: 'Sarah Johnson',
      role: 'VP of Sales',
      company: 'TechFlow Inc.',
      image: 'SJ',
      text: "We went from spending 15 hours a week on prospecting to less than 2 hours. The AI finds leads we would have never discovered manually. Our pipeline has grown 3x in just 3 months.",
      rating: 5,
      results: { metric: '3x', label: 'Pipeline Growth' }
    },
    {
      name: 'Michael Chen',
      role: 'Founder & CEO',
      company: 'StartupX',
      image: 'MC',
      text: "The personalization features are incredible. We're seeing 14% reply rates compared to 3% with our old approach. LeadGen Pro pays for itself 10x over.",
      rating: 5,
      results: { metric: '14%', label: 'Reply Rate' }
    },
    {
      name: 'Emily Rodriguez',
      role: 'Growth Marketing Lead',
      company: 'SaaS Corp',
      image: 'ER',
      text: "Best investment we've made this year. The automation saved our team 80+ hours per month, and the lead quality is outstanding. We've closed $500k in new deals.",
      rating: 5,
      results: { metric: '$500k', label: 'New Revenue' }
    }
  ];

  useEffect(() => {
    if (howItWorksPauseAuto) return undefined;
    const interval = setInterval(() => {
      setActiveStep((prev) => (prev + 1) % howItWorksSteps.length);
    }, 4000);
    return () => clearInterval(interval);
  }, [howItWorksPauseAuto]);

  // Line chart data - 12 months, two series (purple and lighter purple)
  const chartData = [
    { month: 'Jan', line1: 30, line2: 24 },
    { month: 'Feb', line1: 28, line2: 26 },
    { month: 'Mar', line1: 22, line2: 25 },
    { month: 'Apr', line1: 10, line2: 28 },
    { month: 'May', line1: 80, line2: 45 },
    { month: 'Jun', line1: 55, line2: 20 },
    { month: 'Jul', line1: 40, line2: 48 },
    { month: 'Aug', line1: 95, line2: 60 },
    { month: 'Sep', line1: 60, line2: 55 },
    { month: 'Oct', line1: 85, line2: 75 },
    { month: 'Nov', line1: 100, line2: 90 },
    { month: 'Dec', line1: 102, line2: 92 },
  ];


  const isDark = theme === 'dark';

  return (
    <div className={cn('homepage min-h-screen homepage-gradient-bg', isDark ? 'theme-dark' : 'theme-light')}>
      <PageSeo
        title="Evecta — AI-Powered Lead Management"
        description="Discover leads, run AI outreach, and track revenue in one platform. Evecta helps B2B teams generate qualified pipeline without the grunt work."
        path="/"
      />
      <HomePageHeader isDark={isDark} />

      {/* Hero + Graph area: Hero Section.svg background from top till graph card */}
      <div className="homepage-hero-to-graph-wrap">
      {/* Hero Section - Hero Section.svg background */}
      <section className="relative overflow-hidden min-h-0 flex items-center justify-center spacing-hero-section-top hero-section-no-grid py-10 sm:py-12">
        <div className="w-full mx-auto homepage-content-inner relative w-full pt-0 pb-0">
          <div className="w-full">
            <div className="text-center">
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5 }}
                className="flex flex-col items-center"
              >
                {/* Full-width SVG pattern; content centered inside */}
                <div className="hero-patterned-block w-full px-4 py-8 sm:py-10">
                  <div className="w-full">
                    <p className="hero-trust-line">
                      Trusted by Sales Team Globally
                    </p>
                    <h1 className="hero-heading spacing-hero-badge-to-heading px-4" style={{ lineHeight: '1.1' }}>
                      <span className="hero-heading-line hero-heading-line--first">Lead Generation and</span>
                      <span className="hero-heading-line hero-heading-line--second">
                        Outreach,{' '}
                        <span className="hero-gradient-text">Fully Automated.</span>
                      </span>
                    </h1>
                    <p className="hero-subtitle w-full spacing-hero-heading-to-subtitle px-4 text-center">
                      Boost sales with AI-driven lead discovery and automated spam-proof outreach that{' '}
                      <br className="homepage-br-laptop-only" aria-hidden="true" />
                      drives meaningful connections and real conversions.
                    </p>
                    <div className="flex flex-col sm:flex-row gap-3 sm:gap-6 justify-center items-center spacing-hero-subtitle-to-cta">
                      <PrimaryButton onClick={handleGetStarted}>
                        Get Started
                      </PrimaryButton>
                    </div>
                  </div>
                </div>
                <div className="hero-reassurance flex flex-col sm:flex-row items-center justify-center spacing-hero-cta-to-reassurance px-4 w-full">
                  <div className="hero-reassurance-item flex items-center gap-2">
                    <HeroReassuranceCheckIcon className="hero-reassurance-check-icon" />
                    <span className="hero-reassurance-text">Setup in 2 minutes</span>
                  </div>
                  <div className="hero-reassurance-item flex items-center gap-2">
                    <HeroReassuranceCheckIcon className="hero-reassurance-check-icon" />
                    <span className="hero-reassurance-text">No hidden fees</span>
                  </div>
                  <div className="hero-reassurance-item flex items-center gap-2">
                    <HeroReassuranceCheckIcon className="hero-reassurance-check-icon" />
                    <span className="hero-reassurance-text">Encrypted end-to-end</span>
                  </div>
                </div>
              </motion.div>
            </div>
          </div>
        </div>
      </section>

      {/* Dashboard Preview Section - Hero Section.svg ends exactly at graph card bottom */}
      <section className="pt-0 pb-0 homepage-gradient-bg spacing-hero-text-to-dashboard">
        <div className="w-full mx-auto homepage-content-inner">
          <div className="w-full">
            <motion.div
              initial={{ opacity: 0, y: 40 }}
              whileInView={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7 }}
              viewport={{ once: true }}
              className="relative"
            >
              <div className="homepage-graph-only-bg">
              <div className="homepage-graph-card relative rounded-xl sm:rounded-2xl overflow-hidden w-full bg-white dark:bg-white border-0 shadow-sm">
                {/* Grey border on top, left, right only; no border at bottom */}
                <div className="bg-white p-3 sm:p-4 rounded-2xl homepage-graph-inner">
                  {/* Stats Row */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 sm:gap-4 w-full mb-4">
                    {[
                      { label: 'Total Leads', value: '2,847', change: '+12%' },
                      { label: 'Campaigns', value: '24', change: '+3' },
                      { label: 'Response Rate', value: '14.2%', change: '+2.1%' },
                      { label: 'Conversions', value: '89', change: '+8' }
                    ].map((stat, i) => (
                      <motion.div
                        key={i}
                        initial={{ opacity: 0, y: 20 }}
                        whileInView={{ opacity: 1, y: 0 }}
                        transition={{ delay: i * 0.1 }}
                        viewport={{ once: true }}
                        className="bg-white rounded-xl border border-gray-100 p-3"
                      >
                        <div className="text-[11px] sm:text-xs text-gray-900 dark:text-gray-900 mb-0.5">{stat.label}</div>
                        <div className="flex items-baseline justify-between gap-1">
                          <span className="text-lg sm:text-xl font-bold text-gray-900 dark:text-gray-900">{stat.value}</span>
                          <span className="text-[10px] font-medium text-[#6D28D9] bg-[#EDE9FE] dark:bg-[#EDE9FE] dark:text-[#6D28D9] border border-[#C4B5FD] dark:border-[#C4B5FD] px-1.5 py-0.5 rounded-md shrink-0">{stat.change}</span>
                        </div>
                      </motion.div>
                    ))}
                  </div>
                  {/* Graph: on mobile extends to section edges for more horizontal space */}
                  <div className="homepage-graph-wider">
                  <Card className="bg-white border-0 rounded-xl w-full shadow-none homepage-graph-card-inner">
                    <CardContent className="p-0 pt-0 sm:py-2 sm:px-4">
                      <div className="hidden sm:flex items-center justify-between gap-2 mb-3">
                        <h3 className="text-sm sm:text-base font-bold text-gray-900 dark:text-gray-900">Campaign Progress Over Time</h3>
                        <span className="text-[10px] sm:text-xs text-gray-500 dark:text-gray-500 whitespace-nowrap">Jan 5 - Jan 10, 2026</span>
                      </div>
                      <motion.div
                        className="h-[160px] sm:h-[180px] md:h-[200px] w-full"
                        initial={{ opacity: 0, y: 24 }}
                        whileInView={{ opacity: 1, y: 0 }}
                        viewport={{ once: true, amount: 0 }}
                        transition={{ duration: 0.6, ease: 'easeOut' }}
                      >
                        <ResponsiveContainer width="100%" height="100%" minHeight={160}>
                          <RechartsLineChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                            <XAxis
                              dataKey="month"
                              axisLine={{ stroke: '#E5E7EB' }}
                              tickLine={{ stroke: '#E5E7EB' }}
                              tick={{ fontSize: 10, fill: '#6B7280' }}
                              height={28}
                            />
                            <YAxis
                              domain={[0, 110]}
                              ticks={[10, 20, 30, 40, 50, 60, 70, 80, 90, 100]}
                              axisLine={{ stroke: '#E5E7EB' }}
                              tickLine={{ stroke: '#E5E7EB' }}
                              tick={{ fontSize: 10, fill: '#6B7280' }}
                              width={28}
                            />
                            <Line type="monotone" dataKey="line1" stroke="#8B5CF6" strokeWidth={2.5} dot={false} activeDot={false} isAnimationActive animationDuration={1200} animationEasing="ease-out" />
                            <Line type="monotone" dataKey="line2" stroke="#C4B5FD" strokeWidth={2} dot={false} activeDot={false} isAnimationActive animationDuration={1400} animationEasing="ease-out" />
                          </RechartsLineChart>
                        </ResponsiveContainer>
                      </motion.div>
                    </CardContent>
                  </Card>
                  </div>
                </div>
              </div>
              </div>
            </motion.div>
          </div>
        </div>
      </section>
      </div>

      {/* Stats below graph - solid dark background (Hero Section.svg ends above) */}
      <section className="pt-0 pb-8 sm:pb-10 md:pb-12 homepage-gradient-bg">
        <div className="w-full mx-auto homepage-content-inner">
          <div className="w-full">
            <motion.div
              initial={{ opacity: 0, y: 40 }}
              whileInView={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7 }}
              viewport={{ once: true }}
              className="relative"
            >
              <svg width="0" height="0" className="absolute" aria-hidden>
                <defs>
                  <linearGradient id="stats-card-icon-gradient" x1="0" y1="0" x2="24" y2="24" gradientUnits="userSpaceOnUse">
                    <stop offset="0%" stopColor="#D458FF" stopOpacity={0.7} />
                    <stop offset="100%" stopColor="#6B21A8" stopOpacity={1} />
                  </linearGradient>
                </defs>
              </svg>
              <div className="homepage-stats-below-graph">
                {[
                  { icon: Globe, metric: 'No', label: 'Data Selling' },
                  { icon: Clock, metric: '99.9%', label: 'Uptime' },
                  { icon: Users, metric: '10k+', label: 'Active Users' },
                  { icon: Shield, metric: 'GDPR', label: 'Compliant' },
                ].map((item, i) => {
                  const IconComponent = item.icon;
                  return (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, y: 16 }}
                    whileInView={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.4, delay: i * 0.08 }}
                    viewport={{ once: true }}
                    className="homepage-stats-below-graph-item"
                  >
                    <div className="homepage-stats-below-graph-top-row">
                      <div className="homepage-stats-below-graph-icon-wrap">
                        <IconComponent className="homepage-stats-below-graph-icon" size={24} strokeWidth={2} stroke="url(#stats-card-icon-gradient)" aria-hidden />
                      </div>
                      <span className="homepage-stats-below-graph-metric">{item.metric}</span>
                    </div>
                    <span className="homepage-stats-below-graph-label">{item.label}</span>
                  </motion.div>
                  );
                })}
              </div>
            </motion.div>
          </div>
        </div>
      </section>

      {/* Impact Metrics */}
      <section className="py-20 bg-gradient-to-br from-primary/5 via-purple-500/5 to-transparent hidden">
        <div className="w-full mx-auto homepage-content-inner">
          <div className="text-center mb-12">
            <Badge className="mb-4 bg-primary/10 text-primary border-primary/20">Real Impact</Badge>
            <h2 className="heading-l mb-4">
              The numbers speak for themselves
            </h2>
            <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
              Join thousands of companies transforming their sales process with AI
            </p>
          </div>
          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6">
            {impactMetrics.map((metric, index) => (
              <motion.div
                key={index}
                initial={{ opacity: 0, scale: 0.9 }}
                whileInView={{ opacity: 1, scale: 1 }}
                transition={{ duration: 0.5, delay: index * 0.1 }}
                viewport={{ once: true }}
              >
                <Card className="relative overflow-hidden group hover:shadow-xl transition-all duration-300 border-2 hover:border-primary/50">
                  <div className={cn(
                    "absolute inset-0 bg-gradient-to-br opacity-5 group-hover:opacity-10 transition-opacity",
                    metric.gradient
                  )} />
                  <CardContent className="p-6 relative">
                    <div className={cn(
                      "h-14 w-14 rounded-xl flex items-center justify-center bg-gradient-to-br shadow-lg mb-4",
                      metric.gradient
                    )}>
                      <metric.icon className="h-7 w-7 text-white" />
                    </div>
                    <div className="text-4xl font-bold mb-2 bg-gradient-to-r from-foreground to-foreground/70 bg-clip-text text-transparent">
                      <AnimatedCounter 
                        end={metric.number} 
                        duration={2.5}
                        suffix={metric.suffix || ''}
                        prefix={metric.prefix || ''}
                      />
                    </div>
                    <div className="font-semibold mb-1">{metric.label}</div>
                    <div className="text-sm text-muted-foreground">{metric.sublabel}</div>
                  </CardContent>
                </Card>
              </motion.div>
            ))}
              </div>
            </div>
      </section>

      {/* Why Evecta — lead gen & outreach (About Us.svg background) */}
      <section id="why-evecta" className="homepage-the-difference-section">
        <div className="w-full mx-auto homepage-content-inner">
          <div className="w-full">
            <div className="text-left homepage-why-choose-text-block">
              <p className="homepage-why-choose-badge">Why Evecta?</p>
              <h2 className="homepage-why-choose-heading text-white">
                Smarter Way to Find Leads and Close Deals
              </h2>
              <p className="homepage-why-choose-para">
                Discover ideal leads, draft emails with AI, check for spam, run targeted outreach and track every
                campaign. All in one place.
              </p>
            </div>
            <motion.div
              initial={{ opacity: 0, y: 24 }}
              whileInView={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6 }}
              viewport={{ once: true }}
              className="homepage-why-choose-card w-full grid md:grid-cols-2 gap-0 min-h-[320px]"
            >
            {/* Left: Design image from public */}
            <div className="homepage-why-choose-chat-wrap relative flex items-center justify-center min-h-[280px]">
              <img
                src="/Image%20%5Battachment-full%5D.jpeg"
                alt="Evecta — leads, email, outreach, and campaign tracking in one place"
                className="homepage-why-choose-left-image w-full h-auto max-h-[360px] object-contain object-left rounded-2xl"
              />
            </div>
            {/* Right: Copy + Watch Demo - line breaks and colors per design */}
            <div className="homepage-why-choose-right flex flex-col items-start text-left">
              <h3 className="homepage-why-choose-card-heading text-white">
                Your ideal customers are already out there.
              </h3>
              <p className="homepage-why-choose-card-para mb-6">
                Find the right leads, reach them with personalized outreach, and close deals faster than you ever
                thought possible.
              </p>
            </div>
          </motion.div>
          </div>
        </div>
      </section>

      {/* Before/After Comparison */}
      <section className="homepage-beforeafter-section pt-0">
        <div className="w-full mx-auto homepage-content-inner">
          <div className="homepage-beforeafter-inner w-full">
            <div className="homepage-beforeafter-header text-center">
              <h2 className="homepage-beforeafter-main-title">
                Before VS After
              </h2>
              <p className="homepage-beforeafter-subtitle">
                <span className="homepage-beforeafter-subtitle-gradient">LeadGen Pro</span>
              </p>
              <p className="homepage-beforeafter-desc">
                <span className="homepage-beforeafter-desc-line">See how top-performing teams are </span>
                <span className="homepage-beforeafter-desc-line">transforming their sales process.</span>
              </p>
            </div>
            <div className="homepage-beforeafter-cards">
              {/* Before */}
              <motion.div
                initial={{ opacity: 0, x: -20 }}
                whileInView={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.5 }}
                viewport={{ once: true }}
                className="h-full"
              >
                <div className="homepage-beforeafter-card homepage-beforeafter-card-before">
                  <h3 className="homepage-beforeafter-card-title">Before</h3>
                  <p className="homepage-beforeafter-card-subtitle">Manual prospecting</p>
                  <div className="homepage-beforeafter-metrics">
                    {comparisonData.before.map((item, index) => (
                      <div key={index} className="homepage-beforeafter-metric-row">
                        <span className="homepage-beforeafter-metric-label">{item.label}</span>
                        <span className="homepage-beforeafter-metric-value">{item.value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </motion.div>
              {/* After */}
              <motion.div
                initial={{ opacity: 0, x: 20 }}
                whileInView={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.5 }}
                viewport={{ once: true }}
                className="h-full"
              >
                <div className="homepage-beforeafter-card homepage-beforeafter-card-after">
                  <h3 className="homepage-beforeafter-card-title">After</h3>
                  <p className="homepage-beforeafter-card-subtitle">Manual prospecting</p>
                  <div className="homepage-beforeafter-metrics">
                    {comparisonData.after.map((item, index) => (
                      <div key={index} className="homepage-beforeafter-metric-row">
                        <span className="homepage-beforeafter-metric-label">{item.label}</span>
                        <span className="homepage-beforeafter-metric-value">{item.value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </motion.div>
            </div>
          </div>
        </div>
      </section>

      {/* How It Works - left: vertical steps, right: design preview (updates per step); same side gap as graph section */}
      <section id="how-it-works" className="homepage-gradient-bg how-it-works-homepage">
        <div className="w-full mx-auto homepage-content-inner">
          <div className="w-full how-it-works-homepage-layout">
            <svg width="0" height="0" className="absolute overflow-hidden pointer-events-none" aria-hidden>
              <defs>
                <linearGradient id="how-it-works-step-icon-gradient" x1="0" y1="0" x2="20" y2="20" gradientUnits="userSpaceOnUse">
                  <stop offset="0%" stopColor="#D458FF" stopOpacity={0.7} />
                  <stop offset="100%" stopColor="#6B21A8" stopOpacity={1} />
                </linearGradient>
              </defs>
            </svg>
            {/* Row 1 left: heading only */}
            <div className="how-it-works-homepage-left how-it-works-homepage-heading">
              <p className="homepage-why-choose-badge">How It Works</p>
              <h2 className="homepage-why-choose-heading text-white">
                From zero to{' '}
                <span className="how-it-works-homepage-heading-line2">booked meetings in 5 simple steps</span>
              </h2>
            </div>
            {/* Full-width row on laptop so subtitle can stay one line; stacks under heading on mobile */}
            <div className="how-it-works-homepage-subtitle-row">
              <p className="homepage-why-choose-para how-it-works-homepage-subtitle">
                Our proven process helps you generate and convert leads faster than ever
              </p>
            </div>
            {/* Row 1 right: spacer so row 2 aligns steps with preview */}
            <div className="how-it-works-homepage-right-spacer" aria-hidden="true" />
            {/* Preview + steps + progress: mobile SVG frame wraps both; laptop two-column grid */}
            <div className="how-it-works-homepage-preview-steps-bundle">
              <div className="how-it-works-homepage-right">
                <motion.div
                  key={activeStep}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.35 }}
                  className="how-it-works-homepage-preview"
                >
                  <div className="how-it-works-homepage-preview-inner">
                    <div className="how-it-works-homepage-preview-scroll">
                      <div className="how-it-works-homepage-preview-img-wrap">
                        <img
                          src={HOW_IT_WORKS_PREVIEW_IMAGES[activeStep]}
                          alt={howItWorksSteps[activeStep]?.title ?? ''}
                          className="how-it-works-homepage-preview-img"
                          decoding="async"
                          draggable={false}
                        />
                      </div>
                    </div>
                  </div>
                </motion.div>
              </div>
              <div className="how-it-works-homepage-left how-it-works-homepage-steps-wrap">
                <div className="how-it-works-homepage-steps">
                  {howItWorksSteps.map((step, index) => {
                    const isActive = activeStep === index;
                    return (
                      <motion.div
                        key={index}
                        initial={{ opacity: 0, x: -12 }}
                        whileInView={{ opacity: 1, x: 0 }}
                        transition={{ duration: 0.3, delay: index * 0.06 }}
                        viewport={{ once: true }}
                        className={cn(
                          'how-it-works-homepage-step',
                          isActive && 'how-it-works-homepage-step-active'
                        )}
                        onClick={() => {
                          setHowItWorksPauseAuto(true);
                          setActiveStep(index);
                        }}
                      >
                        {isActive ? (
                          <div className="how-it-works-homepage-step-inner how-it-works-homepage-step-inner-expanded">
                            <div className="how-it-works-homepage-step-icon-wrap how-it-works-homepage-step-icon-wrap-active">
                              <step.icon
                                className="how-it-works-homepage-step-icon"
                                size={20}
                                strokeWidth={2}
                                stroke="url(#how-it-works-step-icon-gradient)"
                                aria-hidden
                              />
                            </div>
                            <div className="how-it-works-homepage-step-label">
                              Step-{step.number}
                            </div>
                            <div className="how-it-works-homepage-step-title-row">
                              <div className="how-it-works-homepage-step-title">{step.title}</div>
                              <button
                                type="button"
                                className="how-it-works-homepage-step-next-btn"
                                aria-label="Next step"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setHowItWorksPauseAuto(true);
                                  setActiveStep((prev) => (prev + 1) % howItWorksSteps.length);
                                }}
                              >
                                <ArrowRight className="how-it-works-homepage-step-title-arrow h-4 w-4 flex-shrink-0" aria-hidden />
                              </button>
                            </div>
                            <p className="how-it-works-homepage-step-desc">{step.description}</p>
                          </div>
                        ) : (
                          <div className="how-it-works-homepage-step-inner how-it-works-homepage-step-inner-collapsed">
                            <span className="how-it-works-homepage-step-title-only">{step.title}</span>
                          </div>
                        )}
                      </motion.div>
                    );
                  })}
                </div>
              </div>
              {/* Same framed area as preview + step copy (direct child of bundle so frame/::before includes dots) */}
              <div
                className="how-it-works-homepage-mobile-progress"
                role="tablist"
                aria-label="How it works steps"
              >
                {howItWorksSteps.map((_, i) => (
                  <button
                    key={i}
                    type="button"
                    role="tab"
                    aria-selected={i === activeStep}
                    aria-label={`Step ${i + 1}`}
                    className={cn(
                      'how-it-works-homepage-progress-segment',
                      i === activeStep && 'how-it-works-homepage-progress-segment-active'
                    )}
                    onClick={() => {
                      setHowItWorksPauseAuto(true);
                      setActiveStep(i);
                    }}
                  />
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Features Section – frame image container; left: content inside frame, right: 3-panel sliding carousel */}
      <section id="features" className="homepage-gradient-bg features-homepage-section">
        <div className="w-full mx-auto homepage-content-inner">
          <div className="w-full">
            {/* Heading above frame (same typography as How It Works) */}
            <div className="text-left features-homepage-heading mb-6">
              <p className="homepage-why-choose-badge">Features</p>
              <h2 className="homepage-why-choose-heading text-white">
                Complete Operating
                <br className="homepage-br-laptop-only" aria-hidden="true" />{' '}
                System for Lead Generation & Outreach
              </h2>
              <p className="homepage-why-choose-para features-homepage-subtitle">
                Enterprise-grade tools designed to help you find, engage, and convert your ideal customers
              </p>
            </div>
            {/* Features: frame image cycles with arrow – AI Lead Discovery → Outreach → Analytics → back to AI Lead Discovery */}
            <div
              className={cn(
                'features-homepage-frame features-homepage-frame--swipeable',
                !isFeaturesMobileLayout && 'features-homepage-frame--desktop-art'
              )}
              data-feature-index={activeFeatureIndex}
              onTouchStart={onFeaturesSwipeTouchStart}
              onTouchEnd={onFeaturesSwipeTouchEnd}
              onTouchCancel={onFeaturesSwipeTouchCancel}
            >
              {isFeaturesMobileLayout ? (
                <img
                  className="features-homepage-frame-mobile-img"
                  src={FEATURE_MOBILE_IMAGES[activeFeatureIndex]}
                  alt={features[activeFeatureIndex].title}
                  loading="eager"
                  decoding="async"
                  fetchPriority={activeFeatureIndex === 0 ? 'high' : 'auto'}
                  draggable={false}
                />
              ) : (
                <div className="features-homepage-frame-desktop-art" aria-hidden>
                  {FEATURE_DESKTOP_IMAGES.map((src, i) => (
                    <img
                      key={src}
                      src={src}
                      alt=""
                      className={cn(
                        'features-homepage-frame-desktop-img',
                        i === activeFeatureIndex && 'features-homepage-frame-desktop-img--active'
                      )}
                      loading="eager"
                      fetchPriority={i === 0 ? 'high' : 'auto'}
                      decoding="async"
                      draggable={false}
                    />
                  ))}
                </div>
              )}
              <motion.div
                key={activeFeatureIndex}
                className="features-homepage-content features-homepage-content-with-arrow"
                initial={
                  isFeaturesMobileLayout
                    ? { opacity: 0, y: 12 }
                    : { opacity: 0, x: -8 }
                }
                animate={
                  isFeaturesMobileLayout
                    ? { opacity: 1, y: 0 }
                    : { opacity: 1, x: 0 }
                }
                transition={{
                  duration: isFeaturesMobileLayout ? 0.42 : 0.3,
                  delay: isFeaturesMobileLayout ? 0.58 : 0,
                  ease: [0.22, 1, 0.36, 1],
                }}
              >
                <div className="features-homepage-frame-copy">
                  <div className="features-homepage-title-row">
                    <h3 className="features-homepage-card-title">
                      {features[activeFeatureIndex].title}
                    </h3>
                    {!isFeaturesMobileLayout ? (
                      <button
                        type="button"
                        onClick={() => setActiveFeatureIndex((prev) => (prev + 1) % features.length)}
                        className="features-homepage-arrow-btn features-homepage-arrow-btn-desktop"
                        aria-label="Next feature"
                      >
                        <MoveRight className="h-6 w-6" />
                      </button>
                    ) : null}
                  </div>
                  <p className="features-homepage-card-desc">
                    {features[activeFeatureIndex].description}
                  </p>
                </div>
                <div
                  className="features-homepage-mobile-dots"
                  role="tablist"
                  aria-label="Features"
                >
                  {features.map((_, i) => (
                    <button
                      key={i}
                      type="button"
                      role="tab"
                      aria-selected={i === activeFeatureIndex}
                      aria-label={`${features[i].title}`}
                      className={cn(
                        'features-homepage-mobile-dot',
                        i === activeFeatureIndex && 'features-homepage-mobile-dot-active'
                      )}
                      onClick={() => setActiveFeatureIndex(i)}
                    />
                  ))}
                </div>
              </motion.div>
            </div>
          </div>
        </div>
      </section>

      {/* Pricing — Claude-style cards; paid plans from Billing PLANS (no Free on homepage) */}
      <section id="pricing" className="homepage-gradient-bg homepage-pricing-section homepage-pricing-section--claude">
        <div className="w-full mx-auto homepage-content-inner">
          <svg width="0" height="0" className="absolute overflow-hidden pointer-events-none" aria-hidden>
            <defs>
              <linearGradient
                id="pricing-card-icon-gradient"
                x1="0"
                y1="0"
                x2="22"
                y2="0"
                gradientUnits="userSpaceOnUse"
              >
                <stop offset="0%" stopColor="#d458ff" stopOpacity={0.7} />
                <stop offset="70%" stopColor="#d458ff" stopOpacity={0.7} />
                <stop offset="100%" stopColor="#6b21a8" stopOpacity={1} />
              </linearGradient>
            </defs>
          </svg>
          <div className="w-full">
            <div className="text-left homepage-pricing-heading mb-6">
              <p className="homepage-why-choose-badge">Pricing</p>
              <h2 className="homepage-why-choose-heading text-white">
                Plans that scale with your pipeline
              </h2>
              <p className="homepage-why-choose-para features-homepage-subtitle">
                Simple, transparent pricing. Upgrade or change plans anytime.
              </p>
            </div>
            <div className="homepage-pricing-grid-wrap">
              <div
                ref={pricingGridRef}
                className="homepage-pricing-grid"
                aria-label="Pricing plans"
              >
              {HOMEPAGE_PRICING_PLANS.map((plan) => {
                const price = homepagePricingPrice(plan);
                return (
                  <motion.article
                    key={plan.id}
                    initial={{ opacity: 0, y: 16 }}
                    whileInView={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.45 }}
                    viewport={{ once: true }}
                    className="homepage-pricing-card-claude"
                  >
                    <div className="homepage-pricing-card-head">
                      <GitBranch
                        className="homepage-pricing-plan-icon"
                        size={22}
                        strokeWidth={1.5}
                        stroke="url(#pricing-card-icon-gradient)"
                        aria-hidden
                      />
                      <h3 className="homepage-pricing-plan-title-serif">{plan.name}</h3>
                      <p className="homepage-pricing-tagline">{plan.description}</p>
                      <div className="homepage-pricing-price-block-claude">
                        <div className="homepage-pricing-price-main-row-claude">
                          <span className="homepage-pricing-price-sans">{price.main}</span>
                          <span className="homepage-pricing-price-suffix">{price.line1}</span>
                        </div>
                        <div className="homepage-pricing-billing-note-slot">
                          {price.line2 ? (
                            <p className="homepage-pricing-billing-note">{price.line2}</p>
                          ) : null}
                        </div>
                      </div>
                    </div>
                    {/* Grows when this card has less content above the CTA — keeps buttons on one row across cards */}
                    <div className="homepage-pricing-card-claude-spacer" aria-hidden="true" />
                    <div className="homepage-pricing-card-claude-cta">
                      <Link
                        to="/auth"
                        className="homepage-pricing-cta-claude no-underline inline-flex items-center justify-center"
                      >
                        Get started
                      </Link>
                    </div>
                    <div className="homepage-pricing-divider-claude" role="presentation" aria-hidden="true" />
                    <div className="homepage-pricing-card-claude-bottom" data-pricing-card-bottom>
                      <p className="homepage-pricing-features-intro-claude">What&apos;s included</p>
                      <ul className="homepage-pricing-features-claude" aria-label={`${plan.name} includes`}>
                        {plan.features.map((line) => (
                          <li key={line} className="homepage-pricing-feature-claude">
                            <Check className="homepage-pricing-check-claude" size={16} strokeWidth={2} aria-hidden />
                            <span>{line}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  </motion.article>
                );
              })}
              </div>
            </div>
            <p className="homepage-pricing-footnote-claude">
              Prices exclude applicable taxes. Usage limits apply per plan.
            </p>
          </div>
        </div>
      </section>

      {/* Testimonials */}
      <section id="testimonials" className="py-20 bg-muted/30 hidden">
        <div className="w-full mx-auto homepage-content-inner">
          <div className="text-center mb-16">
            <Badge className="mb-4 bg-primary/10 text-primary border-primary/20">Success Stories</Badge>
            <h2 className="heading-l mb-4">
              Trusted by high-performing sales teams
            </h2>
            <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
              See how our customers are crushing their sales goals with LeadGen Pro
            </p>
          </div>
          <div className="grid md:grid-cols-3 gap-8">
            {testimonials.map((testimonial, index) => (
              <motion.div
                key={index}
                initial={{ opacity: 0, scale: 0.9 }}
                whileInView={{ opacity: 1, scale: 1 }}
                transition={{ duration: 0.4, delay: index * 0.1 }}
                viewport={{ once: true }}
              >
                <Card className="h-full hover:shadow-xl transition-all duration-300 border-2 hover:border-primary/30">
                  <CardContent className="p-6 space-y-4">
                    {/* Rating */}
                    <div className="flex gap-1">
                      {Array.from({ length: testimonial.rating }).map((_, i) => (
                        <Star key={i} className="h-5 w-5 fill-yellow-400 text-yellow-400" />
                      ))}
                    </div>
                    {/* Quote */}
                    <p className="text-muted-foreground leading-relaxed italic">
                      "{testimonial.text}"
                    </p>
                    {/* Results Badge */}
                    <div className="inline-flex items-center gap-2 bg-green-50 border border-green-200 rounded-lg px-3 py-2">
                      <ArrowUpRight className="h-4 w-4 text-green-600" />
                      <div>
                        <div className="text-sm font-bold text-green-700">{testimonial.results.metric}</div>
                        <div className="text-xs text-green-600">{testimonial.results.label}</div>
                      </div>
                    </div>
                    {/* Author */}
                    <div className="flex items-center gap-3 pt-4 border-t">
                      <div className="h-12 w-12 rounded-full bg-gradient-to-br from-primary to-primary/80 text-primary-foreground flex items-center justify-center font-bold">
                        {testimonial.image}
                      </div>
                      <div>
                        <div className="font-semibold">{testimonial.name}</div>
                        <div className="text-sm text-muted-foreground">{testimonial.role}</div>
                        <div className="text-xs text-muted-foreground">{testimonial.company}</div>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      <HomePageFooter className="homepage-cta-footer-section--home-after-features" />
    </div>
  );
};

export default HomePage;
