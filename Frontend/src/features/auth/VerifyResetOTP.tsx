import React, { useState, useEffect, useRef } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { apiService } from '../../shared/services/api';
import { usePopup } from '../../shared/contexts/PopupProvider';
import { OTP_CODE_LENGTH } from '../../shared/constants/auth';
import './VerifyResetOTP.css';

const VerifyResetOTP = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { popupState, showPopup } = usePopup();
  
  const email = location.state?.email || '';
  const [otp, setOtp] = useState<string[]>(() => Array(OTP_CODE_LENGTH).fill(''));
  const [isLoading, setIsLoading] = useState(false);
  const inputRefs = useRef<(HTMLInputElement | null)[]>([]);

  useEffect(() => {
    if (!email) {
      navigate('/forgot-password');
    }
  }, [email, navigate]);

  useEffect(() => {
    if (inputRefs.current[0]) {
      inputRefs.current[0].focus();
    }
  }, []);

  const handleOtpChange = (index: number, value: string) => {
    if (value.length > 1) {
      value = value.slice(-1);
    }
    
    const newOtp = [...otp];
    newOtp[index] = value;
    setOtp(newOtp);

    if (value && index < OTP_CODE_LENGTH - 1) {
      inputRefs.current[index + 1]?.focus();
    }
  };

  const handleKeyDown = (index: number, e: React.KeyboardEvent) => {
    if (e.key === 'Backspace' && !otp[index] && index > 0) {
      inputRefs.current[index - 1]?.focus();
    }
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    e.preventDefault();
    const pasted = e.clipboardData.getData('text').trim();
    const digits = pasted.replace(/\D/g, '').slice(0, OTP_CODE_LENGTH).split('');
    if (digits.length === 0) return;
    const newOtp = Array(OTP_CODE_LENGTH).fill('') as string[];
    digits.forEach((d, i) => {
      newOtp[i] = d;
    });
    setOtp(newOtp);
    const nextIndex = Math.min(digits.length, OTP_CODE_LENGTH - 1);
    inputRefs.current[nextIndex]?.focus();
  };

  const handleContinue = async () => {
    const code = otp.join('');
    if (code.length !== OTP_CODE_LENGTH) {
      showPopup(`Please enter the ${OTP_CODE_LENGTH}-digit code`);
      return;
    }

    setIsLoading(true);
    try {
      const response = await apiService.verifyResetOTP(email, code);
      if (response.data) {
        // Navigate to reset password with email and code
        navigate('/reset-password', { state: { email, otpCode: code } });
      } else if (response.error) {
        showPopup(response.error, 'error');
      }
    } catch (error) {
      showPopup('Verification failed. Please try again.', 'error');
    } finally {
      setIsLoading(false);
    }
  };

  const handleResend = async () => {
    setIsLoading(true);
    try {
      const response = await apiService.forgotPassword(email);
      if (response.data) {
        showPopup('A new code has been sent to your email', 'success');
      } else if (response.error) {
        showPopup(response.error, 'error');
      }
    } catch (error) {
      showPopup('Failed to resend code. Please try again.', 'error');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="verify-reset-otp-page">
      <Link to="/" className="auth-page-logo evecta-logo no-underline shrink-0">
        <span className="evecta-logo-text">Evecta</span>
        <span className="evecta-logo-tagline">AI-Powered Platform</span>
      </Link>
      <div className="verify-reset-otp-container">
        <div className="verify-reset-otp-card">
          <p className="verify-reset-otp-eyebrow">Authentication Code!</p>
          <h1 className="verify-reset-otp-title">Verification Code</h1>
          <p className="verify-reset-otp-description">
            We've sent a {OTP_CODE_LENGTH}-digit code to
          </p>
          <p className="verify-reset-otp-email">{email}</p>

          <div className="otp-inputs-shell">
            <div className="otp-input-group">
              {otp.map((digit, index) => (
                <input
                  key={index}
                  ref={(el) => { inputRefs.current[index] = el; }}
                  type="text"
                  inputMode="numeric"
                  maxLength={1}
                  value={digit}
                  onChange={(e) => handleOtpChange(index, e.target.value)}
                  onKeyDown={(e) => handleKeyDown(index, e)}
                  onPaste={handlePaste}
                  className={`otp-box ${digit ? 'filled' : ''} ${popupState.isVisible && popupState.type === 'error' ? 'error' : ''}`}
                />
              ))}
            </div>
          </div>

          <button
            type="button"
            className="verify-continue-button"
            onClick={handleContinue}
            disabled={otp.join('').length !== OTP_CODE_LENGTH || isLoading}
          >
            <span>Continue</span>
            <svg className="verify-continue-arrow" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 12h14M12 5l7 7-7 7" />
            </svg>
          </button>

          <div className="resend-text">
            {"Didn't receive the email? "}
            <button type="button" onClick={handleResend} className="resend-link otp-resend-inline-btn" disabled={isLoading}>
              Resend
            </button>
          </div>

          <Link to="/auth" className="back-to-signin-button">
            <ArrowLeft className="back-to-signin-arrow" size={20} />
            <span>Back to Sign In</span>
          </Link>
        </div>
      </div>
    </div>
  );
};

export default VerifyResetOTP;

