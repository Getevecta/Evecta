import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { apiService } from '../../shared/services/api';
import { usePopup } from '../../shared/contexts/PopupProvider';
import './ResetPassword.css';

const ResetPassword = () => {
  const [formData, setFormData] = useState({
    email: '',
    otpCode: '',
    newPassword: '',
    confirmPassword: ''
  });
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const { popupState, showPopup } = usePopup();

  useEffect(() => {
    if (location.state?.email && location.state?.otpCode) {
      setFormData(prev => ({ 
        ...prev, 
        email: location.state.email,
        otpCode: location.state.otpCode
      }));
    } else {
      // If no OTP or email, redirect back to forgot password
      navigate('/forgot-password');
    }
  }, [location.state, navigate]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
  };

  const validatePassword = (password: string): { isValid: boolean; errors: string[] } => {
    const errors: string[] = [];
    
    if (password.length < 8) {
      errors.push("at least 8 characters");
    }
    
    const hasUppercase = /[A-Z]/.test(password);
    const hasLowercase = /[a-z]/.test(password);
    const hasNumber = /[0-9]/.test(password);
    const hasSpecialChar = /[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/.test(password);
    
    if (!hasUppercase) errors.push("uppercase letter");
    if (!hasLowercase) errors.push("lowercase letter");
    if (!hasNumber) errors.push("number");
    if (!hasSpecialChar) errors.push("special character");
    
    return {
      isValid: errors.length === 0,
      errors
    };
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    const passwordValidation = validatePassword(formData.newPassword);
    if (!passwordValidation.isValid) {
      let errorMessage = '';
      if (passwordValidation.errors.length === 1) {
        errorMessage = `Password must include ${passwordValidation.errors[0]}`;
      } else {
        const last = passwordValidation.errors[passwordValidation.errors.length - 1];
        const rest = passwordValidation.errors.slice(0, -1).join(', ');
        errorMessage = `Password must include ${rest}, and ${last}`;
      }
      showPopup(errorMessage, 'error');
      return;
    }

    if (formData.newPassword !== formData.confirmPassword) {
      showPopup('Passwords do not match', 'error');
      return;
    }

    setIsLoading(true);
    try {
      const response = await apiService.resetPassword({
        email: formData.email,
        otp_code: formData.otpCode,
        new_password: formData.newPassword
      });
      
      if (response.data) {
        showPopup(response.data.message, 'success');
        setTimeout(() => {
          navigate('/auth', {
            state: {
              email: formData.email,
              fromPasswordReset: true,
            },
          });
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

  // Enhanced password strength calculation (for UI bars)
  const getPasswordStrength = () => {
    const pwd = formData.newPassword;
    if (!pwd) return 0;
    let strength = 0;
    if (pwd.length >= 8) strength++;
    if (/[A-Z]/.test(pwd)) strength++;
    if (/[0-9]/.test(pwd)) strength++;
    if (/[^A-Za-z0-9]/.test(pwd)) strength++;
    return strength;
  };

  const strength = getPasswordStrength();

  return (
    <div className="reset-password-page">
      <Link to="/" className="auth-page-logo evecta-logo no-underline shrink-0">
        <span className="evecta-logo-text">Evecta</span>
        <span className="evecta-logo-tagline">AI-Powered Platform</span>
      </Link>
      <div className="reset-password-container">
        <div className="reset-password-card">
          <p className="reset-password-eyebrow">Reset Password!</p>
          <h1 className="reset-password-title">Set a New Password</h1>
          <p className="reset-password-description">Must be<br />at least 8 characters</p>

          <form onSubmit={handleSubmit} className="reset-password-form">
            <div className="form-group">
              <label className="form-label">Password</label>
              <div className="password-input-container">
                <input
                  type={showPassword ? "text" : "password"}
                  name="newPassword"
                  placeholder="••••••••"
                  value={formData.newPassword}
                  onChange={handleChange}
                  className="form-input-reset"
                  required
                />
                <button 
                  type="button" 
                  className="password-toggle no-button-effects" 
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    setShowPassword(!showPassword);
                  }}
                  onMouseDown={(e) => {
                    e.preventDefault();
                  }}
                >
                  {showPassword ? (
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" stroke="#9CA3AF" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                      <circle cx="12" cy="12" r="3" stroke="#9CA3AF" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                  ) : (
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" stroke="#9CA3AF" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                      <line x1="1" y1="1" x2="23" y2="23" stroke="#9CA3AF" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                  )}
                </button>
              </div>
              <div className="strength-bars">
                {[1, 2, 3, 4].map((bar) => (
                  <div 
                    key={bar} 
                    className={`strength-bar ${bar <= strength ? 'active' : ''}`}
                  />
                ))}
              </div>
            </div>

            <div className="form-group">
              <label className="form-label">Confirm password</label>
              <div className="password-input-container">
                <input
                  type={showConfirmPassword ? "text" : "password"}
                  name="confirmPassword"
                  placeholder="••••••••"
                  value={formData.confirmPassword}
                  onChange={handleChange}
                  className="form-input-reset"
                  required
                />
                <button 
                  type="button" 
                  className="password-toggle no-button-effects" 
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    setShowConfirmPassword(!showConfirmPassword);
                  }}
                  onMouseDown={(e) => {
                    e.preventDefault();
                  }}
                >
                  {showConfirmPassword ? (
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" stroke="#9CA3AF" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                      <circle cx="12" cy="12" r="3" stroke="#9CA3AF" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                  ) : (
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" stroke="#9CA3AF" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                      <line x1="1" y1="1" x2="23" y2="23" stroke="#9CA3AF" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                  )}
                </button>
              </div>
            </div>

            <button 
              type="submit" 
              className="reset-button" 
              disabled={isLoading || formData.newPassword.length < 8}
            >
              <span>Reset password</span>
              <svg className="reset-button-arrow" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M5 12h14M12 5l7 7-7 7" />
              </svg>
            </button>
          </form>

          <div className="additional-options">
            <Link to="/auth" className="back-to-signin-button">
              <ArrowLeft className="back-to-signin-arrow" size={20} />
              <span>Back to Sign In</span>
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ResetPassword;
