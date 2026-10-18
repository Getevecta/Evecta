import React from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Check, ArrowRight } from 'lucide-react';
import { PageSeo } from '../../shared/components/PageSeo/PageSeo';
import './WaitlistPage.css';

const WaitlistPage: React.FC = () => {
  const navigate = useNavigate();

  const handleExplore = () => {
    navigate('/');
  };

  return (
    <div className="waitlist-page">
      <PageSeo
        title="You're on the Evecta waitlist"
        description="Your spot is reserved. We'll notify you when your Evecta access is ready."
        path="/waitlist"
        noindex
      />
      <div className="waitlist-card">
        {/* Left: Logo + Hot air balloon */}
        <div className="waitlist-left">
          <Link to="/" className="waitlist-logo evecta-logo">
            <span className="evecta-logo-text">Evecta</span>
            <span className="evecta-logo-tagline">AI-Powered Platform</span>
          </Link>
          <div className="waitlist-illustration-wrap">
            <img
              src="/hot-air-balloon.png"
              alt=""
              className="waitlist-balloon"
            />
          </div>
        </div>

        {/* Right: Content */}
        <div className="waitlist-right">
          <p className="waitlist-eyebrow">You Are On Our List!</p>
          <h1 className="waitlist-title">
            We've received your request<br />
            and your spot in line is reserved.
          </h1>
          <p className="waitlist-paragraph">
            To ensure every member enjoys a seamless and high-quality<br />
            experience from day one, we are welcoming new users with our<br />
            full attention.
          </p>
          <p className="waitlist-paragraph">
            We've received your request and your spot in line is reserved. Our<br />
            team will reach out via email as soon as a seat opens up for you.
          </p>

          <h2 className="waitlist-while-title">While You Wait!</h2>
          <p className="waitlist-while-intro">
            We'll keep you<br />
            informed and engaged with:
          </p>
          <ul className="waitlist-benefits-list">
            <li>
              <span className="waitlist-check-circle">
                <Check className="waitlist-check" strokeWidth={3} />
              </span>
              <span className="waitlist-benefit-text-nowrap">
                Weekly updates on product development and new features
              </span>
            </li>
            <li>
              <span className="waitlist-check-circle">
                <Check className="waitlist-check" strokeWidth={3} />
              </span>
              <span>Exclusive lead generation tips and best practices</span>
            </li>
            <li>
              <span className="waitlist-check-circle">
                <Check className="waitlist-check" strokeWidth={3} />
              </span>
              <span>Early access to educational resources and guides</span>
            </li>
            <li>
              <span className="waitlist-check-circle">
                <Check className="waitlist-check" strokeWidth={3} />
              </span>
              <span>Priority support when you get access</span>
            </li>
          </ul>

          <button type="button" className="waitlist-explore-button" onClick={handleExplore}>
            <span>Let's Explore</span>
            <ArrowRight size={20} className="waitlist-explore-arrow" />
          </button>
        </div>
      </div>
    </div>
  );
};

export default WaitlistPage;
