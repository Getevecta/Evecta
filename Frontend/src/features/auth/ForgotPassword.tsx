import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { apiService } from '../../shared/services/api';
import { usePopup } from '../../shared/contexts/PopupProvider';
import './AuthPage.css';

const ForgotPassword = () => {
  const [email, setEmail] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const navigate = useNavigate();
  const { showPopup } = usePopup();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email) {
      showPopup('Email is required');
      return;
    }

    setIsLoading(true);
    try {
      const response = await apiService.forgotPassword(email);
      if (response.data) {
        showPopup(response.data.message, 'success');

        setTimeout(() => {
          navigate('/verify-reset-otp', { state: { email } });
        }, 2000);
      } else if (response.error) {
        showPopup(response.error, 'error');
      }
    } catch (error: any) {
      showPopup('Something went wrong. Please try again.', 'error');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        {/* Left column - same as sign up / sign in */}
        <div className="auth-card-left">
          <div className="auth-card-left-inner">
            <Link to="/" className="auth-brand evecta-logo evecta-logo-light no-underline">
              <span className="evecta-logo-text">Evecta</span>
              <span className="evecta-logo-tagline">AI-Powered Platform</span>
            </Link>
            <h2 className="auth-card-headline auth-card-headline--long-copy">
              <span className="auth-card-headline-line1">
                <span className="auth-card-headline-accent">Discover Leads</span>
              </span>
              <span className="auth-card-headline-line2">That Actually Fit Your Goals</span>
            </h2>
          </div>
        </div>

        {/* Right column - form (centered vertically) */}
        <div className="auth-card-right auth-card-right-centered">
          <div className="auth-form-container login-mode-form">
            <div className="auth-header">
              <Link to="/" className="auth-mobile-back-home" aria-label="Back to home page">
                <ArrowLeft className="auth-mobile-back-home-icon" size={22} strokeWidth={2} aria-hidden />
                <span className="auth-mobile-back-home-label">Home</span>
              </Link>
              <p className="auth-header-eyebrow">
                <span className="auth-header-eyebrow-first">Reset</span>{' '}
                <span className="auth-header-eyebrow-rest">Password</span>
              </p>
              <h1 className="auth-header-title">Forgot password?</h1>
              <p className="auth-header-desc">
                Don't worry! <br/>Please enter your email to regain access.
              </p>
            </div>

            <div className="auth-content">
              <div className="auth-forms-wrapper">
                <form onSubmit={handleSubmit} className="signin-form forgot-password-form" noValidate>
                  <div className="form-group">
                    <label className="form-label">Email Address</label>
                    <div className="input-with-icon">
                      <input
                        type="email"
                        placeholder="Enter your email"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        className="form-input"
                      />
                    </div>
                  </div>

                  <button
                    type="submit"
                    className="submit-button submit-button-with-arrow"
                    disabled={isLoading}
                  >
                    {isLoading ? 'Sending...' : 'Reset password'}
                    <svg
                      className="submit-arrow"
                      width="20"
                      height="20"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <path d="M5 12h14M12 5l7 7-7 7" />
                    </svg>
                  </button>
                </form>

                <Link to="/auth" className="back-to-signin-button">
                  <ArrowLeft className="back-to-signin-arrow" size={20} />
                  <span>Back to Sign In</span>
                </Link>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ForgotPassword;
