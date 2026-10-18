import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Target, Lightbulb, Users, Shield, ArrowRight, Briefcase } from 'lucide-react';
import { HomePageHeader, HomePageFooter } from '../homepage/HomePage';
import { PageSeo } from '../../shared/components/PageSeo/PageSeo';
import '../homepage/HomePage.css';
import './AboutUsPage.css';

const VALUES_CARD_COUNT = 4;

const AboutUsPage: React.FC = () => {
  const navigate = useNavigate();
  const valuesCarouselRef = useRef<HTMLDivElement>(null);
  const [valuesSlideIndex, setValuesSlideIndex] = useState(0);

  const updateValuesSlideFromScroll = useCallback(() => {
    const el = valuesCarouselRef.current;
    if (!el) return;
    const cards = Array.from(el.querySelectorAll<HTMLElement>('.value-card'));
    if (!cards.length) return;
    const center = el.scrollLeft + el.clientWidth / 2;
    let best = 0;
    let bestDist = Infinity;
    cards.forEach((c, i) => {
      const mid = c.offsetLeft + c.offsetWidth / 2;
      const d = Math.abs(mid - center);
      if (d < bestDist) {
        bestDist = d;
        best = i;
      }
    });
    setValuesSlideIndex(best);
  }, []);

  useEffect(() => {
    const el = valuesCarouselRef.current;
    if (!el || typeof window === 'undefined') return;
    const onScroll = () => updateValuesSlideFromScroll();
    el.addEventListener('scroll', onScroll, { passive: true });
    updateValuesSlideFromScroll();
    return () => el.removeEventListener('scroll', onScroll);
  }, [updateValuesSlideFromScroll]);

  const scrollValuesToSlide = useCallback((index: number) => {
    const el = valuesCarouselRef.current;
    const card = el?.querySelectorAll('.value-card')[index] as HTMLElement | undefined;
    if (!el || !card) return;
    el.scrollTo({ left: card.offsetLeft, behavior: 'smooth' });
  }, []);

  const handleGetStarted = () => {
    navigate('/auth');
  };

  return (
    <div className="about-us-page">
      <PageSeo
        title="About Evecta"
        description="Evecta is an AI-driven lead and outreach platform built for B2B teams who want qualified pipeline without the complexity."
        path="/about_us"
      />
      <div className="homepage theme-dark">
        <HomePageHeader isDark />
      </div>
      <div className="about-page-content">
      {/* Hero: same structure and style as Contact page header */}
      <header className="about-header about-hero-contact-style">
        <div className="about-header-content">
          <p className="homepage-why-choose-badge text-sm font-medium">Built by Sales Leaders, For Sales Leaders</p>
          <h1 className="homepage-why-choose-heading text-white">Leads to Loyalty</h1>
          <p className="homepage-why-choose-para">
            <span className="about-hero-para-desktop">
              <span className="about-hero-para-desk-row1">
                Growing your business shouldn&apos;t require expensive tools or technical expertise. Our AI-driven&nbsp;lead
              </span>
              <span className="about-hero-para-desk-row2">
                and outreach platform delivers powerful results with zero complexity.
              </span>
            </span>
            <span className="about-hero-para-mobile">
              Growing your business shouldn&apos;t require expensive
              <br />
              tools or technical expertise. Our AI-driven lead and
              <br />
              outreach platform delivers powerful results with
              <br />
              zero complexity.
            </span>
          </p>
        </div>
      </header>

      {/* Story + Image + Our Values intro – dark section (match reference image) */}
      <div className="about-story-values-dark">
        <div className="about-story-values-inner">
          {/* Our Story – label + heading + paragraphs */}
          <p className="about-story-label">Our Story</p>
          <h2 className="about-story-title">
            Built from
            <br />
            Real Struggle
          </h2>
          <p className="about-story-para">
            Evecta was not born from a perfect plan. It came from the same struggle many businesses face every day.
          </p>
          <p className="about-story-para">
            We had a good product, but reaching the right people was harder than expected. Leads were difficult to find, emails took hours to write, and most outreach either landed in spam or received no reply. It felt like the whole process was working against us.
          </p>
          <p className="about-story-para">
            That frustration became our starting point.
          </p>
          <p className="about-story-mission">
            We built Evecta to make outreach feel less painful and more practical. It helps businesses find better prospects, run spam tests before sending, reach real inboxes, and start conversations that actually matter.
          </p>
          <p className="about-story-mission">
            Our Mission: Free you from the struggles we faced so you can focus on what really matters when it comes to growing your business.
          </p>

          {/* Image block */}
          <div className="about-story-image-wrap">
            <img
              src="/Frame%202121457613.png?v=2"
              alt="Team"
              className="about-story-image"
            />
          </div>

        </div>
      </div>

      {/* Our Values Section – dark theme, label + What Drives Us + cards */}
      <div className="values-section values-section-dark spacing-about-values-section-top">
        <div className="values-container">
          <p className="values-section-label">Our Values</p>
          <h2 className="values-title heading-l spacing-about-values-heading-to-subtitle about-values-drives-heading">
            What
            <br />
            Drives Us
          </h2>
          <p className="values-subtitle spacing-about-values-subtitle-to-cards about-values-principles-subtitle">
            <span className="about-values-principles-subtitle-desktop">
              These core principles guide every decision we make and every feature we build.
            </span>
            <span className="about-values-principles-subtitle-mobile">
              These core principles guide
              <br />
              every decision we make and every feature we build.
            </span>
          </p>
          
          <div
            ref={valuesCarouselRef}
            className="values-cards spacing-about-value-card-to-card about-values-cards-carousel"
          >
            <div className="value-card spacing-about-value-card-padding">
              <Target className="value-icon spacing-about-value-icon-to-title" />
              <h3 className="value-card-title heading-m spacing-about-value-title-to-description">Mission-Driven</h3>
              <p className="value-card-description">
                Empowering businesses to scale their outreach with intelligent automation and human-centric design.
              </p>
            </div>
            
            <div className="value-card spacing-about-value-card-padding">
              <Lightbulb className="value-icon spacing-about-value-icon-to-title" />
              <h3 className="value-card-title heading-m spacing-about-value-title-to-description">Innovation First</h3>
              <p className="value-card-description">
                Constantly pushing boundaries with AI technology to deliver cutting-edge lead generation solutions.
              </p>
            </div>
            
            <div className="value-card spacing-about-value-card-padding">
              <Users className="value-icon spacing-about-value-icon-to-title" />
              <h3 className="value-card-title heading-m spacing-about-value-title-to-description">Customer-Centric</h3>
              <p className="value-card-description">
                Built with feedback from thousands of sales teams to create the most intuitive experience possible.
              </p>
            </div>
            
            <div className="value-card spacing-about-value-card-padding">
              <Shield className="value-icon spacing-about-value-icon-to-title" />
              <h3 className="value-card-title heading-m spacing-about-value-title-to-description">Trust & Security</h3>
              <p className="value-card-description">
                Your data is protected with enterprise-grade security and compliance standards.
              </p>
            </div>
          </div>
          <div
            className="about-values-cards-dots"
            role="tablist"
            aria-label="Our values cards"
          >
            {Array.from({ length: VALUES_CARD_COUNT }, (_, i) => (
              <button
                key={i}
                type="button"
                role="tab"
                aria-selected={valuesSlideIndex === i}
                aria-label={`Show value ${i + 1} of ${VALUES_CARD_COUNT}`}
                className={`about-values-cards-dot${valuesSlideIndex === i ? ' is-active' : ''}`}
                onClick={() => scrollValuesToSlide(i)}
              />
            ))}
          </div>
        </div>
      </div>

      {/* Our Services Section – exact same structure and classes as Our Values */}
      <section className="discover-our-services spacing-about-services-section-top values-section values-section-dark">
        <div className="values-container">
          <p className="values-section-label">Our Services</p>
          <h2 className="values-title heading-l about-services-title">
            A more effective
            <br />
            way to Track Progress
          </h2>
          <p className="values-subtitle spacing-about-values-subtitle-to-cards about-services-subtitle">
            <span className="about-services-subtitle-desktop">
              Our services combine smart systems, user-centered design, and data-driven strategy to help you generate more leads with less effort.
            </span>
            <span className="about-services-subtitle-mobile">
              Our services combine smart systems, user-centered
              <br />
              design, and data-driven strategy to help you generate more leads with less effort.
            </span>
          </p>
        </div>
      </section>

      {/* AI-Powered Lead Generation – image left, copy right */}
      <section className="discover-lead-generation discover-lead-generation-dark discover-lead-generation-services-wrap spacing-about-service-block-to-block">
        <div className="discover-services-frame">
          <div className="discover-lead-generation-container discover-lead-generation-layout">
          {/* Left: image */}
          <div className="discover-service-frame-wrap">
            <div className="discover-service-frame">
              <img
                src="/Image%20%5Battachment-full%5D.jpeg"
                alt="AI-Powered Lead Generation"
                className="discover-service-frame-img"
              />
            </div>
          </div>
          {/* Right: service copy on dark background */}
          <div className="discover-lead-generation-content">
            <p className="discover-lead-generation-badge-text">Lead Generation</p>
            <h2 className="discover-lead-generation-headline discover-lead-generation-headline-dark">
              AI-Powered Lead Generation
            </h2>
            <p className="discover-lead-generation-description discover-lead-generation-description-dark">
              AI finds your ideal prospects instantly. Search history keeps them organized and accessible forever.
            </p>
            <div className="discover-lead-generation-tags spacing-about-hashtag-to-hashtag">
              <span className="discover-lead-generation-tag discover-lead-generation-tag-dark">#LeadGeneration</span>
              <span className="discover-lead-generation-tag discover-lead-generation-tag-dark">#OrganizedLeads</span>
              <span className="discover-lead-generation-tag discover-lead-generation-tag-dark">#AIProspecting</span>
            </div>
          </div>
        </div>
        </div>
      </section>

      {/* AI Outreach Section – same outer frame, image right, copy left */}
      <section className="discover-ai-outreach discover-ai-outreach-dark discover-service-same-layout discover-service-image-right spacing-about-service-block-to-block">
        <div className="discover-services-frame">
          <div className="discover-lead-generation-container discover-lead-generation-layout">
          <div className="discover-lead-generation-content">
            <p className="discover-lead-generation-badge-text">AI Assistant</p>
            <h2 className="discover-lead-generation-headline discover-lead-generation-headline-dark">
              AI Outreach That Feels Human
            </h2>
            <p className="discover-lead-generation-description discover-lead-generation-description-dark">
              Create, automate, and personalize campaigns at scale. Every email checked for spam triggers before sending.
            </p>
            <div className="discover-lead-generation-tags spacing-about-hashtag-to-hashtag">
              <span className="discover-lead-generation-tag discover-lead-generation-tag-dark">#OutreachAutomation</span>
              <span className="discover-lead-generation-tag discover-lead-generation-tag-dark">#SpamFreeEmail</span>
              <span className="discover-lead-generation-tag discover-lead-generation-tag-dark">#CustomerEngagement</span>
            </div>
          </div>
          <div className="discover-service-frame-wrap">
            <div className="discover-service-frame">
              <img
                src="/AI Outreach That Feels Human.jpeg"
                alt="AI Outreach That Feels Human"
                className="discover-service-frame-img"
              />
            </div>
          </div>
          </div>
        </div>
      </section>

      {/* Data Analytics Section – same outer frame, image left, copy right */}
      <section className="discover-lead-generation-2 discover-lead-generation-2-dark discover-service-same-layout spacing-about-service-block-to-block">
        <div className="discover-services-frame">
          <div className="discover-lead-generation-container discover-lead-generation-layout">
          <div className="discover-service-frame-wrap">
            <div className="discover-service-frame">
              <img
                src="/Real-Time Lead Analytics & Performance Tracking.jpeg?v=2"
                alt="Real-Time Lead Analytics & Performance Tracking"
                className="discover-service-frame-img"
              />
            </div>
          </div>
          <div className="discover-lead-generation-content">
            <p className="discover-lead-generation-badge-text">Data Analytics</p>
            <h2 className="discover-lead-generation-headline discover-lead-generation-headline-dark">
              Real-Time Lead Analytics & Performance Tracking
            </h2>
            <p className="discover-lead-generation-description discover-lead-generation-description-dark">
              Monitor performance, engagement, and conversions instantly. Make data-backed decisions that turn leads into loyal customers.
            </p>
            <div className="discover-lead-generation-tags spacing-about-hashtag-to-hashtag">
              <span className="discover-lead-generation-tag discover-lead-generation-tag-dark">#TrackPerformance</span>
              <span className="discover-lead-generation-tag discover-lead-generation-tag-dark">#RealTimeData</span>
              <span className="discover-lead-generation-tag discover-lead-generation-tag-dark">#DataDrivenGrowth</span>
            </div>
          </div>
          </div>
        </div>
      </section>

      </div>
      
      <div className="homepage theme-dark">
        <HomePageFooter />
      </div>
    </div>
  );
};

export default AboutUsPage;

