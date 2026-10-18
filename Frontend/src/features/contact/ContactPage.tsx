import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';
import { Clock, ChevronDown, ChevronUp, ArrowRight, Mail } from 'lucide-react';
import { HomePageHeader, HomePageFooter } from '../homepage/HomePage';
import { PageSeo } from '../../shared/components/PageSeo/PageSeo';
import { apiService } from '../../shared/services/api';
import '../homepage/HomePage.css';
import './ContactPage.css';

const ContactPage: React.FC = () => {
  const [openFaqIndex, setOpenFaqIndex] = useState<number | null>(0);
  const [formData, setFormData] = useState({
    fullName: '',
    email: '',
    companyName: '',
    subject: '',
    message: '',
  });
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: value,
    }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);

    const res = await apiService.submitContactForm({
      full_name: formData.fullName.trim(),
      email: formData.email.trim(),
      company_name: formData.companyName.trim() || null,
      subject: formData.subject.trim(),
      message: formData.message.trim(),
    });

    setIsSubmitting(false);

    if (res.error || !res.data) {
      toast.error(
        res.error ||
          res.message ||
          'Something went wrong. You can email us directly at mail@evecta.io.',
      );
      return;
    }

    toast.success(res.data.message);
    setFormData({
      fullName: '',
      email: '',
      companyName: '',
      subject: '',
      message: '',
    });
  };

  const handleLinkClick = (e: React.MouseEvent<HTMLAnchorElement>) => {
    // Remove focus immediately after click
    setTimeout(() => {
      if (document.activeElement instanceof HTMLElement) {
        document.activeElement.blur();
      }
    }, 0);
  };

  const contactFaqChevron = (isOpen: boolean) =>
    isOpen ? (
      <ChevronDown className="discover-faq-chevron contact-faq-chevron" aria-hidden />
    ) : (
      <ChevronUp className="discover-faq-chevron contact-faq-chevron" aria-hidden />
    );

  return (
    <div className="contact-page">
      <PageSeo
        title="Contact Evecta"
        description="Questions about Evecta? Reach out — we respond to sales, product, and partnership inquiries."
        path="/contact"
      />
      <div className="homepage theme-dark">
        <HomePageHeader isDark />
      </div>
      {/* Content area: Privacy Policy background only here (not header/footer) */}
      <div className="contact-content-area">
      {/* Header – same structure as How It Works on homepage */}
      <header className="contact-header">
        <div className="contact-header-content">
          <p className="homepage-why-choose-badge text-sm font-medium">We're Here to Help</p>
          <h1 className="homepage-why-choose-heading text-white">
            Get in Touch
          </h1>
          <p className="homepage-why-choose-para contact-hero-para">
            <span className="contact-hero-para-desktop">
              <span className="contact-hero-para-desk-row1">
                Have questions? We&apos;d love to hear from you. Send us a message and we&apos;ll
              </span>
              <span className="contact-hero-para-desk-row2">
                respond as soon as possible.
              </span>
            </span>
            <span className="contact-hero-para-mobile">
              Have questions? We&apos;d love to hear from you.
              <br />
              Send us a message and we&apos;ll respond as soon
              <br />
              as possible.
            </span>
          </p>
        </div>
      </header>

      {/* Intro text above form – same structure as How It Works on homepage */}
      <section className="contact-form-intro-section">
        <div className="contact-form-intro-inner">
          <p className="homepage-why-choose-badge">Reach out to us</p>
          <h2 className="homepage-why-choose-heading text-white">Send us a message</h2>
          <p className="homepage-why-choose-para">Fill out the form below and our team will get back to you within 24 hours.</p>
        </div>
      </section>

      {/* Frame section above FAQ – Frame 2121457632.png as transparent frame, form as in design */}
      <section className="contact-frame-section">
        <div className="contact-frame-inner">
          <div className="contact-frame-box">
            <form onSubmit={handleSubmit} className="contact-frame-form">
              <div className="contact-frame-form-grid">
                <div className="contact-frame-col">
                  <div className="contact-frame-field">
                    <label htmlFor="frame-fullName" className="contact-frame-label">
                      Full Name <span className="contact-frame-required-mark">*</span>
                    </label>
                    <input type="text" id="frame-fullName" name="fullName" placeholder="" value={formData.fullName} onChange={handleInputChange} required />
                  </div>
                  <div className="contact-frame-field">
                    <label htmlFor="frame-companyName" className="contact-frame-label">Company Name</label>
                    <input type="text" id="frame-companyName" name="companyName" placeholder="" value={formData.companyName} onChange={handleInputChange} />
                  </div>
                </div>
                <div className="contact-frame-col">
                  <div className="contact-frame-field">
                    <label htmlFor="frame-email" className="contact-frame-label">
                      Email Address <span className="contact-frame-required-mark">*</span>
                    </label>
                    <input type="email" id="frame-email" name="email" placeholder="" value={formData.email} onChange={handleInputChange} required />
                  </div>
                  <div className="contact-frame-field">
                    <label htmlFor="frame-subject" className="contact-frame-label">
                      Subject <span className="contact-frame-required-mark">*</span>
                    </label>
                    <input type="text" id="frame-subject" name="subject" placeholder="" value={formData.subject} onChange={handleInputChange} required />
                  </div>
                </div>
              </div>
              <div className="contact-frame-message-row">
                <div className="contact-frame-field contact-frame-field-message">
                  <label htmlFor="frame-message" className="contact-frame-label">
                    Message <span className="contact-frame-required-mark">*</span>
                  </label>
                  <textarea id="frame-message" name="message" placeholder="" rows={1} value={formData.message} onChange={handleInputChange} required aria-label="Message (required)" />
                </div>
              </div>
              <p className="contact-frame-legal">
                By submitting this form, you agree to our{' '}
                <Link to="/privacy-policy" target="_blank" onClick={handleLinkClick} className="contact-frame-link">Privacy Policy</Link>
                {' '}and{' '}
                <Link to="/terms-of-service" target="_blank" onClick={handleLinkClick} className="contact-frame-link">Terms of Service</Link>.
              </p>
              <div className="contact-frame-actions">
                <button
                  type="submit"
                  className="contact-frame-submit evecta-primary-btn"
                  disabled={isSubmitting}
                >
                  {isSubmitting ? 'Sending…' : 'Send Message'}{' '}
                  <ArrowRight className="contact-frame-submit-icon" aria-hidden />
                </button>
              </div>
            </form>

            <div className="contact-quick-response-panel" style={{ backgroundImage: 'url(/Background+Border+Shadow1.png)' }}>
              <div className="contact-quick-response-inner">
                <Mail className="contact-quick-response-icon" aria-hidden />
                <h3 className="contact-quick-response-title">Quick Response Guarantee</h3>
                <p className="contact-quick-response-desc">
                  We pride ourselves on fast response times. Most inquiries are answered within 2-4 hours during business hours.
                </p>
                <div className="contact-quick-response-tags">
                  <span className="contact-quick-response-tag">
                    <Clock className="contact-quick-response-tag-icon" aria-hidden />
                    2-4 hour response
                  </span>
                  <span className="contact-quick-response-tag">
                    <Clock className="contact-quick-response-tag-icon" aria-hidden />
                    24/7 support available
                  </span>
                </div>
              </div>
            </div>
            <div className="homepage-footer-social contact-frame-social-outside">
              <a href="https://www.facebook.com" target="_blank" rel="noopener noreferrer" className="homepage-footer-social-btn" aria-label="Facebook"><svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"/></svg></a>
              <a href="https://www.instagram.com/evecta_contact?utm_source=ig_web_button_share_sheet&igsh=ZDNlZDc0MzIxNw==" target="_blank" rel="noopener noreferrer" className="homepage-footer-social-btn" aria-label="Instagram"><svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zm0-2.163c-3.259 0-3.667.014-4.947.072-4.358.2-6.78 2.618-6.98 6.98-.059 1.281-.073 1.689-.073 4.948 0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98 1.281.058 1.689.072 4.948.072 3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98-1.281-.059-1.69-.073-4.949-.073zm0 5.838c-3.403 0-6.162 2.759-6.162 6.162s2.759 6.163 6.162 6.163 6.162-2.759 6.162-6.163c0-3.403-2.759-6.162-6.162-6.162zm0 10.162c-2.209 0-4-1.79-4-4 0-2.209 1.791-4 4-4s4 1.791 4 4c0 2.21-1.791 4-4 4zm6.406-11.845c-.796 0-1.441.645-1.441 1.44s.645 1.44 1.441 1.44c.795 0 1.439-.645 1.439-1.44s-.644-1.44-1.439-1.44z"/></svg></a>
              <a href="https://x.com/Evecta_contact?s=20" target="_blank" rel="noopener noreferrer" className="homepage-footer-social-btn" aria-label="Twitter"><svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg></a>
            </div>
          </div>
        </div>
      </section>

      {/* FAQ Section */}
      <section className="discover-faq-section">
        <div className="discover-faq-background">
          <img 
            src="/faq background.svg" 
            alt="FAQ Background" 
            className="discover-faq-bg-svg"
          />
        </div>
        
        <div className="discover-faq-container">
          <h2 className="discover-faq-title">Frequently<br /><span className="discover-faq-title-line2">asked questions</span></h2>
          
          <div className="discover-faq-list">
            <div
              className={`discover-faq-item ${openFaqIndex === 0 ? 'open' : ''}`}
              onClick={() => setOpenFaqIndex(openFaqIndex === 0 ? null : 0)}
            >
              <div className="discover-faq-question">
                <span>What is Evecta?</span>
                <span className="discover-faq-icon">{contactFaqChevron(openFaqIndex === 0)}</span>
              </div>
              <div className="discover-faq-answer">
                <p>
                  Evecta is an AI-powered platform that helps you discover high-quality leads and send effective
                  outreach emails—all in one place. It simplifies prospecting, drafting, sending, and tracking your
                  outreach campaigns.
                </p>
              </div>
            </div>

            <div
              className={`discover-faq-item ${openFaqIndex === 1 ? 'open' : ''}`}
              onClick={() => setOpenFaqIndex(openFaqIndex === 1 ? null : 1)}
            >
              <div className="discover-faq-question">
                <span>Do I need an account to search for leads?</span>
                <span className="discover-faq-icon">{contactFaqChevron(openFaqIndex === 1)}</span>
              </div>
              <div className="discover-faq-answer">
                <p>
                  Yes. You&apos;ll need to sign up to search and access leads. You can quickly create an account using
                  Google or your email.
                </p>
              </div>
            </div>

            <div
              className={`discover-faq-item ${openFaqIndex === 2 ? 'open' : ''}`}
              onClick={() => setOpenFaqIndex(openFaqIndex === 2 ? null : 2)}
            >
              <div className="discover-faq-question">
                <span>What can I do after searching leads?</span>
                <span className="discover-faq-icon">{contactFaqChevron(openFaqIndex === 2)}</span>
              </div>
              <div className="discover-faq-answer">
                <p>Once leads are saved, you can:</p>
                <ol>
                  <li>Build campaigns</li>
                  <li>Draft emails manually, use built-in templates, or generate with AI</li>
                  <li>Run mandatory spam tests</li>
                  <li>Send outreach</li>
                  <li>Track opens, replies, and insights</li>
                </ol>
              </div>
            </div>

            <div
              className={`discover-faq-item ${openFaqIndex === 3 ? 'open' : ''}`}
              onClick={() => setOpenFaqIndex(openFaqIndex === 3 ? null : 3)}
            >
              <div className="discover-faq-question">
                <span>How do I get started?</span>
                <span className="discover-faq-icon">{contactFaqChevron(openFaqIndex === 3)}</span>
              </div>
              <div className="discover-faq-answer">
                <p>
                  Simply sign up, enter your company intelligence engine during onboarding, explore leads, and begin
                  your first outreach campaign in a few steps.
                </p>
              </div>
            </div>

            <div
              className={`discover-faq-item ${openFaqIndex === 4 ? 'open' : ''}`}
              onClick={() => setOpenFaqIndex(openFaqIndex === 4 ? null : 4)}
            >
              <div className="discover-faq-question">
                <span>Is the outreach automated?</span>
                <span className="discover-faq-icon">{contactFaqChevron(openFaqIndex === 4)}</span>
              </div>
              <div className="discover-faq-answer">
                <p>Yes. And in the meantime, you can:</p>
                <ol>
                  <li>Send personalized emails</li>
                  <li>Run mandatory spam tests</li>
                  <li>Track opens and activity</li>
                </ol>
                <p>Automated follow-ups and sequencing will arrive in future updates.</p>
              </div>
            </div>

            <div
              className={`discover-faq-item ${openFaqIndex === 5 ? 'open' : ''}`}
              onClick={() => setOpenFaqIndex(openFaqIndex === 5 ? null : 5)}
            >
              <div className="discover-faq-question">
                <span>Is my data secure?</span>
                <span className="discover-faq-icon">{contactFaqChevron(openFaqIndex === 5)}</span>
              </div>
              <div className="discover-faq-answer">
                <p>
                  Yes. Your data is encrypted and stored securely. Only you can access your saved leads, campaigns, and
                  emails.
                </p>
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

export default ContactPage;

