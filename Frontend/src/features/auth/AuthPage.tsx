// src/pages/AuthPage.tsx
import { useState, useEffect, useRef } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { useAuth } from "../../shared/contexts/AuthContext";
import { toast } from "sonner";
import MessageBox from "../../shared/components/MessageBox/MessageBox";
import { usePopup } from "../../shared/contexts/PopupProvider";
import {
  getRememberedCredentials,
  setRememberedCredentials,
  clearRememberedCredentials,
} from "../../shared/utils/rememberMeStorage";
import "./AuthPage.css";

interface LoginForm {
  email: string;
  password: string;
}

interface SignupForm {
  username: string;
  email: string;
  password: string;
  confirmPassword: string;
}

interface FormErrors {
  [key: string]: string;
}

interface MessageBoxState {
  isVisible: boolean;
  type: "success" | "error" | "info";
  message: string;
}

/** Fixed-size wrapper so show/hide icons don't appear to shift when toggled */
function AuthPasswordEyeIcons({ visible }: { visible: boolean }) {
  return (
    <span className="auth-password-eye-wrap" aria-hidden>
      {visible ? (
        <svg
          className="auth-password-eye-svg"
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
          <line x1="1" y1="1" x2="23" y2="23" />
        </svg>
      ) : (
        <svg
          className="auth-password-eye-svg"
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
          <circle cx="12" cy="12" r="3" />
        </svg>
      )}
    </span>
  );
}

const AuthPage = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { login, signup, googleLogin } = useAuth();

  const [isSignUp, setIsSignUp] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(false);
  const [agreeToTerms, setAgreeToTerms] = useState(false);
  const [showPasswordSuggestion, setShowPasswordSuggestion] = useState(false);
  const [suggestedPassword, setSuggestedPassword] = useState<string>("");
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  const [loginForm, setLoginForm] = useState<LoginForm>({ email: "", password: "" });

  // Pre-fill email from navigation (e.g., after password reset). Never pass password in router state.
  useEffect(() => {
    const st = location.state as { email?: string; fromPasswordReset?: boolean } | null;
    if (st?.email) {
      setLoginForm((prev) => ({
        ...prev,
        email: st.email!,
        password: st.fromPasswordReset ? "" : prev.password,
      }));
      setIsSignUp(false);
      if (st.fromPasswordReset) {
        setLoginNotice("Password updated. Please sign in with your new password.");
      }
    }
  }, [location.state]);

  // Load remembered email only (password is never stored client-side)
  useEffect(() => {
    const st = location.state as { fromPasswordReset?: boolean } | null;
    if (st?.fromPasswordReset) {
      return;
    }
    getRememberedCredentials().then((creds) => {
      if (creds) {
        setLoginForm({ email: creds.email, password: '' });
        setRememberMe(true);
      }
    });
  }, [location.state]);
  const [signupForm, setSignupForm] = useState<SignupForm>({
    username: "",
    email: "",
    password: "",
    confirmPassword: "",
  });

  const [errors, setErrors] = useState<FormErrors>({});
  const [globalError, setGlobalError] = useState<string>("");
  const [messageBox, setMessageBox] = useState<MessageBoxState>({ 
    isVisible: false, 
    type: "success", 
    message: "" 
  });
  const [isLoading, setIsLoading] = useState(false);
  const [loginNotice, setLoginNotice] = useState<string>("");
  
  // Popup message hook
  const { popupState, showPopup } = usePopup();
  
  // Track pending error message to show after switching to login
  const pendingErrorTimerRef = useRef<NodeJS.Timeout | null>(null);
  
  // Close password suggestion when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as HTMLElement;
      if (showPasswordSuggestion && !target.closest('.password-input-container')) {
        setShowPasswordSuggestion(false);
      }
    };
    
    if (showPasswordSuggestion) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => {
        document.removeEventListener('mousedown', handleClickOutside);
      };
    }
  }, [showPasswordSuggestion]);

  // Show error popup when switching to login mode after email exists error
  useEffect(() => {
    // Clean up any existing timer
    if (pendingErrorTimerRef.current) {
      clearTimeout(pendingErrorTimerRef.current);
      pendingErrorTimerRef.current = null;
    }
    // Clear inline notice when switching modes
    if (isSignUp) {
      setLoginNotice("");
    }
  }, [isSignUp]);

  // -------------------------------
  // Validation
  // -------------------------------
  
  // Secure password validation
  const validatePassword = (password: string): { isValid: boolean; errors: string[] } => {
    const errors: string[] = [];
    
    if (password.length < 8) {
      errors.push("Password must be 8+ characters");
    }
    
    const hasUppercase = /[A-Z]/.test(password);
    const hasLowercase = /[a-z]/.test(password);
    const hasNumber = /[0-9]/.test(password);
    const hasSpecialChar = /[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/.test(password);
    
    if (!hasUppercase) {
      errors.push("uppercase letter");
    }
    
    if (!hasLowercase) {
      errors.push("lowercase letter");
    }
    
    if (!hasNumber) {
      errors.push("number");
    }
    
    if (!hasSpecialChar) {
      errors.push("special character");
    }
    
    return {
      isValid: errors.length === 0,
      errors
    };
  };

  const validateLogin = (): boolean => {
    const newErrors: FormErrors = {};
    if (!loginForm.email) newErrors.email = "Email is required";
    if (!loginForm.password) newErrors.password = "Password is required";
    setErrors(newErrors);
    
    // Show popup error if there are validation errors
    if (Object.keys(newErrors).length > 0) {
      if (newErrors.email) {
        showPopup(newErrors.email);
      } else if (newErrors.password) {
        showPopup(newErrors.password);
      }
    }
    
    return Object.keys(newErrors).length === 0;
  };

  const validateSignup = (): boolean => {
    const newErrors: FormErrors = {};
    if (!signupForm.username) newErrors.username = "Username is required";
    if (!signupForm.email) {
      newErrors.email = "Email is required";
    } else if (!/\S+@\S+\.\S+/.test(signupForm.email)) {
      newErrors.email = "Please enter a valid email address";
    }
    if (!signupForm.password) newErrors.password = "Password is required";
    
    // Validate password strength
    if (signupForm.password) {
      const passwordValidation = validatePassword(signupForm.password);
      if (!passwordValidation.isValid) {
        // Format error message nicely
        let errorMessage = '';
        if (passwordValidation.errors.length === 1) {
          errorMessage = `Password must include at least one ${passwordValidation.errors[0]}`;
        } else if (passwordValidation.errors.length === 2) {
          errorMessage = `Password must include at least one ${passwordValidation.errors[0]} and ${passwordValidation.errors[1]}`;
        } else {
          const last = passwordValidation.errors[passwordValidation.errors.length - 1];
          const rest = passwordValidation.errors.slice(0, -1).join(', ');
          errorMessage = `Password must include at least one ${rest}, and ${last}`;
        }
        newErrors.password = errorMessage;
      }
    }
    
    if (signupForm.password !== signupForm.confirmPassword) {
      newErrors.confirmPassword = "Passwords do not match";
    }
    
    // Validate terms agreement
    if (!agreeToTerms) {
      newErrors.terms = "You must agree to the Terms of Service and Privacy Policy";
    }
    
    setErrors(newErrors);
    
    // Show popup error if there are validation errors
    if (Object.keys(newErrors).length > 0) {
      // Show specific error messages for each field
      if (newErrors.password) {
        showPopup(newErrors.password);
      } else if (newErrors.terms) {
        showPopup(newErrors.terms);
      } else if (newErrors.username) {
        showPopup(newErrors.username);
      } else if (newErrors.email) {
        showPopup(newErrors.email);
      } else if (newErrors.confirmPassword) {
        showPopup(newErrors.confirmPassword);
      } else {
        showPopup("Please fix the errors below");
      }
    }
    
    return Object.keys(newErrors).length === 0;
  };

  // -------------------------------
  // Handlers
  // -------------------------------
  const handleLoginChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setLoginForm((prev) => ({ ...prev, [name]: value }));
    if (errors[name]) setErrors((prev) => ({ ...prev, [name]: "" }));
    if (globalError) setGlobalError("");
  };

  // Generate a strong password that meets all criteria:
  // - At least 8 characters (we use 16)
  // - At least one uppercase letter
  // - At least one lowercase letter
  // - At least one number
  // - At least one special character
  const generateStrongPassword = (): string => {
    const length = 16;
    const uppercase = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
    const lowercase = 'abcdefghijklmnopqrstuvwxyz';
    const numbers = '0123456789';
    // Use string.punctuation equivalent characters to match backend validation
    const symbols = '!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~';
    const allChars = uppercase + lowercase + numbers + symbols;
    
    // Retry up to 10 times to ensure we generate a valid password
    for (let attempt = 0; attempt < 10; attempt++) {
      let password = '';
      // Ensure at least one of each type to meet all criteria
      password += uppercase[Math.floor(Math.random() * uppercase.length)];
      password += lowercase[Math.floor(Math.random() * lowercase.length)];
      password += numbers[Math.floor(Math.random() * numbers.length)];
      password += symbols[Math.floor(Math.random() * symbols.length)];
      
      // Fill the rest randomly
      for (let i = password.length; i < length; i++) {
        password += allChars[Math.floor(Math.random() * allChars.length)];
      }
      
      // Shuffle the password
      const shuffled = password.split('').sort(() => Math.random() - 0.5).join('');
      
      // Verify the generated password meets all criteria
      const validation = validatePassword(shuffled);
      if (validation.isValid) {
        return shuffled;
      }
    }
    
    // Fallback: return a guaranteed valid password if all retries fail
    return 'A1b2C3d4E5f6G7h8!';
  };

  const handlePasswordFieldClick = () => {
    if (!signupForm.password) {
      // Always generate a new password when clicking the field
      const newPassword = generateStrongPassword();
      setSuggestedPassword(newPassword);
      setShowPasswordSuggestion(true);
    }
  };

  const handleUseSuggestedPassword = (password: string) => {
    if (!password || !password.trim()) return;
    setSignupForm((prev) => ({
      ...prev,
      password,
      confirmPassword: password,
    }));
    setShowPasswordSuggestion(false);
    setErrors((prev) => {
      const next = { ...prev };
      delete next.password;
      delete next.confirmPassword;
      return next;
    });
  };

  const handleSignupChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setSignupForm((prev) => ({ ...prev, [name]: value }));
    // Hide suggestion when user starts typing
    if (name === 'password' && showPasswordSuggestion) {
      setShowPasswordSuggestion(false);
    }
    if (errors[name]) setErrors((prev) => ({ ...prev, [name]: "" }));
    if (globalError) setGlobalError("");
  };

  const handleLoginSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!validateLogin()) return;
    setIsLoading(true);
    setGlobalError(""); // Clear any previous global errors
    const result = await login(loginForm.email, loginForm.password);
    if (result.requires2fa) {
      if (rememberMe) {
        await setRememberedCredentials(loginForm.email);
      } else {
        clearRememberedCredentials();
      }
      navigate("/admin-login-2fa", {
        state: { email: result.email || loginForm.email },
      });
      setIsLoading(false);
      return;
    }
    if (result.success) {
      if (rememberMe) {
        await setRememberedCredentials(loginForm.email);
      } else {
        clearRememberedCredentials();
      }

      // Success toast is shown from AuthContext (fires before redirect unmount race)
      // Don't manually navigate - let RedirectIfAuthenticated handle it
      // This prevents redirect loops between manual navigation and RedirectIfAuthenticated
      // The RedirectIfAuthenticated component will automatically redirect to dashboard
    } else {
      showPopup(result.message || "Login failed. Please check your credentials.");
    }
    setIsLoading(false);
  };

  const handleSignupSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!validateSignup()) return;
    
    // Prevent double submission
    if (isLoading) {
      console.log("⚠️ Signup already in progress, ignoring duplicate submission");
      return;
    }
    
    setIsLoading(true);
    setGlobalError(""); // Clear any previous global errors
    
    console.log("🚀 Starting signup process...", { 
      username: signupForm.username, 
      email: signupForm.email 
    });
    
    try {
      const result = await signup(signupForm.username, signupForm.email, signupForm.password);
      
      console.log("📝 Signup result:", result);
      
      if (result.success) {
        console.log("✅ Signup successful, redirecting to OTP page...");
        showPopup("Account created! OTP sent to your email. Redirecting to verification...", 'success');

        await setRememberedCredentials(signupForm.email);
        
        // Redirect to OTP verification page after a short delay
        setTimeout(() => {
          navigate('/otp-verification', { 
            state: { 
              email: signupForm.email,
              userId: result.userId 
            } 
          });
        }, 1500);
      } else {
        console.log("❌ Signup failed:", result);
        console.log("❌ Signup result.success:", result.success);
        console.log("❌ Signup error message:", result.message);
        console.log("❌ Full result object:", JSON.stringify(result, null, 2));
        
        // Ensure we have a meaningful error message
        let errorMessage = result.message || "Registration failed. Please try again.";
        
        // Normalize error messages for better UX
        const lowerMessage = errorMessage.toLowerCase();
        if (lowerMessage.includes("email already exists") || 
            lowerMessage.includes("email exists")) {
          // Switch to login mode and pre-fill email
          errorMessage = "Email already exists. Please sign in instead.";
          
          // Pre-fill email in login form
          setLoginForm(prev => ({ ...prev, email: signupForm.email }));
          console.log("📝 Pre-filled email in login form:", signupForm.email);
          
          // Additionally show inline message box as a fallback
          setMessageBox({ isVisible: true, type: 'error', message: errorMessage });
          setLoginNotice(errorMessage);

          // Switch to login mode first
          setIsSignUp(false);
          console.log("✅ Switched to login mode");
          
          // Force a re-render and then show popup
          // Use multiple frames to ensure DOM and state are fully updated
          requestAnimationFrame(() => {
            requestAnimationFrame(() => {
              setTimeout(() => {
                console.log("⏰ Showing error popup after delay");
                const finalMessage = "Email already exists. Please sign in instead.";
                console.log("🎯 Calling showPopup with:", finalMessage);
                console.log("🎯 showPopup function:", typeof showPopup);
                showPopup(finalMessage, 'error');
                console.log("✅ Error popup shown with message:", finalMessage);
                
                // Force another check after a bit
                setTimeout(() => {
                  console.log("🔍 Final check - popup should be visible now");
                }, 100);
              }, 600);
            });
          });
        } else if (lowerMessage.includes("username already exists")) {
          errorMessage = "Username already exists. Please choose a different username.";
          showPopup(errorMessage.trim(), 'error');
        } else if (lowerMessage.includes("registration is full") || 
                   lowerMessage.includes("waitlist") ||
                   lowerMessage.includes("added to the waitlist")) {
          // Redirect to waitlist page
          showPopup(errorMessage.trim(), 'error');
          setTimeout(() => {
            navigate('/waitlist', { replace: true });
          }, 2000); // Show message for 2 seconds before redirecting
        } else {
          // For other errors, show on signup page
          showPopup(errorMessage.trim(), 'error');
        }
        
        console.log("📢 Final error message to show:", errorMessage);
        console.log("📢 Message length:", errorMessage.length);
      }
    } catch (error: any) {
      console.log("💥 Signup error:", error);
      // Try to extract a user-friendly error message from various possible locations
      let errorMessage: string = "Registration failed. Please try again.";
      
      // Handle error.response.data.detail (could be object or string)
      let waitlistCode = false;
      if (error?.response?.data?.detail) {
        const detail = error.response.data.detail;
        if (typeof detail === 'object' && detail !== null) {
          if ('message' in detail) {
            errorMessage = detail.message;
          }
          // Check if it's a waitlist error by code
          if ('code' in detail && detail.code === 'WAITLISTED') {
            waitlistCode = true;
          }
        } else if (typeof detail === 'string') {
          errorMessage = detail;
        } else {
          errorMessage = String(detail);
        }
      } else if (error?.response?.data?.message) {
        errorMessage = String(error.response.data.message);
      } else if (error?.message) {
        errorMessage = String(error.message);
      }
      
      // Normalize error messages for better UX
      const lowerMessage = errorMessage.toLowerCase();
      if (lowerMessage.includes("email already exists") || 
          lowerMessage.includes("email exists")) {
        // Switch to login mode and pre-fill email
        errorMessage = "Email already exists. Please sign in instead.";
        
        // Pre-fill email in login form
        setLoginForm(prev => ({ ...prev, email: signupForm.email }));
        console.log("📝 Pre-filled email in login form (catch):", signupForm.email);
        
        // Additionally show inline message box as a fallback
        setMessageBox({ isVisible: true, type: 'error', message: errorMessage });
        setLoginNotice(errorMessage);

        // Switch to login mode first
        setIsSignUp(false);
        console.log("✅ Switched to login mode (catch block)");
        
        // Force a re-render and then show popup
        // Use requestAnimationFrame to ensure DOM is updated
        requestAnimationFrame(() => {
          setTimeout(() => {
            console.log("⏰ Showing error popup after delay (catch)");
            const finalMessage = "Email already exists. Please sign in instead.";
            console.log("🎯 Calling showPopup with (catch):", finalMessage);
            showPopup(finalMessage, 'error');
            console.log("✅ Error popup shown with message (catch):", finalMessage);
          }, 500);
        });
      } else if (waitlistCode || 
                 lowerMessage.includes("registration is full") || 
                 lowerMessage.includes("waitlist") ||
                 lowerMessage.includes("added to the waitlist")) {
        // Redirect to waitlist page
        showPopup(errorMessage, 'error');
        setTimeout(() => {
          navigate('/waitlist', { replace: true });
        }, 2000); // Show message for 2 seconds before redirecting
      } else {
        showPopup(errorMessage);
      }
    } finally {
      setIsLoading(false);
    }
  };

  // -------------------------------
  // Render
  // -------------------------------
  return (
    <div className="auth-page">
      {/* Single card: left = promo (purple), right = form (white) */}
      <div className="auth-card">
        {/* Left column - branding / promotional */}
        <div className={`auth-card-left ${isSignUp ? 'signup-mode' : ''}`}>
          <div className="auth-card-left-inner">
            <Link to="/" className="auth-brand evecta-logo evecta-logo-light no-underline">
              <span className="evecta-logo-text">Evecta</span>
              <span className="evecta-logo-tagline">AI-Powered Platform</span>
            </Link>
            {!isSignUp ? (
              <h2 className="auth-card-headline">
                <span className="auth-card-headline-line1">
                  <span className="auth-card-headline-accent">Fully Automated Lead</span>
                </span>
                <span className="auth-card-headline-line2">Generation & Outreach</span>
              </h2>
            ) : (
              <h2 className="auth-card-headline auth-card-headline--long-copy">
                <span className="auth-card-headline-line1">
                  <span className="auth-card-headline-accent">Discover Leads</span>
                </span>
                <span className="auth-card-headline-line2">That Actually Fit Your Goals</span>
              </h2>
            )}
          </div>
        </div>

        {/* Right column - form */}
        <div className="auth-card-right">
          <div
            className={`auth-form-container ${!isSignUp ? 'login-mode-form' : 'signup-mode-form'}`}
          >
            <div className="auth-header">
              <Link to="/" className="auth-mobile-back-home" aria-label="Back to home page">
                <ArrowLeft className="auth-mobile-back-home-icon" size={22} strokeWidth={2} aria-hidden />
                <span className="auth-mobile-back-home-label">Home</span>
              </Link>
              <p className="auth-header-eyebrow"><span className="auth-header-eyebrow-first">Let's</span> <span className="auth-header-eyebrow-rest">Get You In!</span></p>
              <h1 className="auth-header-title">{!isSignUp ? "Sign in to Get Started" : "Create your account"}</h1>
              <p className="auth-header-desc">
                {!isSignUp
                  ? <>Join a smarter way to find,<br />organize, and grow your business connections</>
                  : <>Join thousands of businesses<br /> using AI to generate high-quality leads</>}
              </p>
            </div>

            <div className="auth-content">
              <div className="auth-forms-wrapper">
                {!isSignUp ? (
                  <>
                    <form onSubmit={handleLoginSubmit} className="signin-form">
                      {loginNotice && (
                        <div className="auth-login-notice">{loginNotice}</div>
                      )}
                      <div className="form-group">
                        <label className="form-label">Email Address</label>
                        <div className="input-with-icon">
                          <input
                            type="email"
                            name="email"
                            placeholder="Enter Email Address"
                            value={loginForm.email}
                            onChange={handleLoginChange}
                            className={`form-input ${errors.email ? "error" : ""}`}
                          />
                        </div>
                      </div>
                      <div className="form-group">
                        <label className="form-label">Password</label>
                        <div className="password-input-container">
                          <input
                            type={showPassword ? "text" : "password"}
                            name="password"
                            placeholder="Enter Password"
                            value={loginForm.password}
                            onChange={handleLoginChange}
                            autoComplete="current-password"
                            className={`form-input ${errors.password ? "error" : ""}`}
                          />
                          <button
                            type="button"
                            className="password-toggle no-button-effects"
                            onClick={(e) => {
                              e.preventDefault();
                              e.stopPropagation();
                              setShowPassword(!showPassword);
                            }}
                            onMouseDown={(e) => e.preventDefault()}
                            aria-label={showPassword ? "Hide password" : "Show password"}
                          >
                            {showPassword ? (
                              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
                                <line x1="1" y1="1" x2="23" y2="23" />
                              </svg>
                            ) : (
                              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                                <circle cx="12" cy="12" r="3" />
                              </svg>
                            )}
                          </button>
                        </div>
                      </div>
                      <div className="form-options">
                        <label className="remember-me">
                          <input
                            type="checkbox"
                            checked={rememberMe}
                            onChange={(e) => setRememberMe(e.target.checked)}
                            className="checkbox-input"
                          />
                          <span className="checkbox-custom" />
                          <span>Remember Me</span>
                        </label>
                        <Link to="/forgot-password" className="forgot-password">Forgot Password?</Link>
                      </div>
                      <button type="submit" className="submit-button submit-button-with-arrow" disabled={isLoading}>
                        {isLoading ? "Signing in..." : "Sign In"}
                        <svg className="submit-arrow" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14M12 5l7 7-7 7" /></svg>
                      </button>
                    </form>
                    <div className="or-separator">
                      <span className="or-text">Or Sign in With</span>
                    </div>
                    <button type="button" className="social-button google-button" onClick={googleLogin} disabled={isLoading}>
                      <span className="google-button-label">Sign In With Google</span>
                      <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden>
                        <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
                        <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                        <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
                        <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
                      </svg>
                    </button>
                    <p className="auth-signup-prompt">
                      Don't have an account?{" "}
                      <button type="button" className="signup-toggle-button" onClick={() => setIsSignUp(true)}>Sign Up</button>
                    </p>
                  </>
                ) : (
                  <>
                    <form onSubmit={handleSignupSubmit} className="signup-form">
                      <div className="form-group">
                        <label className="form-label">Username</label>
                        <div className="input-with-icon">
                          <input
                            name="username"
                            type="text"
                            placeholder="Username"
                            value={signupForm.username}
                            onChange={handleSignupChange}
                            className={`form-input ${errors.username ? "error" : ""}`}
                          />
                        </div>
                      </div>
                      <div className="form-group">
                        <label className="form-label">Email Address</label>
                        <div className="input-with-icon">
                          <input
                            name="email"
                            type="email"
                            placeholder="Enter Email Address"
                            value={signupForm.email}
                            onChange={handleSignupChange}
                            className={`form-input ${errors.email ? "error" : ""}`}
                          />
                        </div>
                      </div>
                      <div className="form-group">
                        <label className="form-label">Password</label>
                        <div className="password-input-container">
                          <input
                            name="password"
                            type={showPassword ? "text" : "password"}
                            placeholder="Password (min 8 chars: A-Z, a-z, 0-9, special)"
                            value={signupForm.password}
                            onChange={handleSignupChange}
                            onClick={handlePasswordFieldClick}
                            onFocus={handlePasswordFieldClick}
                            className={`form-input ${errors.password ? "error" : ""}`}
                          />
                          <button type="button" className="password-toggle no-button-effects" onClick={(e) => { e.preventDefault(); e.stopPropagation(); setShowPassword(!showPassword); }} onMouseDown={(e) => e.preventDefault()} aria-label={showPassword ? "Hide password" : "Show password"}>
                            <AuthPasswordEyeIcons visible={showPassword} />
                          </button>
                        </div>
                        {showPasswordSuggestion && !signupForm.password && suggestedPassword && (
                          <div className="password-suggestion-box">
                            <span>Use suggested password:</span>
                            <button
                              type="button"
                              className="password-suggestion-btn"
                              onMouseDown={(e) => {
                                e.preventDefault();
                                e.stopPropagation();
                                handleUseSuggestedPassword(suggestedPassword);
                              }}
                              onClick={(e) => {
                                e.preventDefault();
                                e.stopPropagation();
                                handleUseSuggestedPassword(suggestedPassword);
                              }}
                            >
                              {suggestedPassword}
                            </button>
                          </div>
                        )}
                      </div>
                      <div className="form-group">
                        <label className="form-label">Confirm Password</label>
                        <div className="password-input-container">
                          <input
                            name="confirmPassword"
                            type={showConfirmPassword ? "text" : "password"}
                            placeholder="Confirm Password"
                            value={signupForm.confirmPassword}
                            onChange={handleSignupChange}
                            className={`form-input ${errors.confirmPassword ? "error" : ""}`}
                          />
                          <button type="button" className="password-toggle no-button-effects" onClick={(e) => { e.preventDefault(); setShowConfirmPassword(!showConfirmPassword); }} onMouseDown={(e) => e.preventDefault()} aria-label={showConfirmPassword ? "Hide password" : "Show password"}>
                            <AuthPasswordEyeIcons visible={showConfirmPassword} />
                          </button>
                        </div>
                      </div>
                      <div className="terms-checkbox">
                        <label className={`terms-label ${errors.terms ? "error" : ""}`}>
                          <input type="checkbox" checked={agreeToTerms} onChange={(e) => setAgreeToTerms(e.target.checked)} className="checkbox-input" />
                          <span className="checkbox-custom" />
                          <span>I agree to the <a href="/terms-of-service" target="_blank" rel="noopener noreferrer" className="terms-link">Terms of Service</a> and <a href="/privacy-policy" target="_blank" rel="noopener noreferrer" className="terms-link">Privacy Policy</a></span>
                        </label>
                      </div>
                      <button type="submit" className="submit-button" disabled={isLoading}>
                        {isLoading ? "Signing up..." : "Sign Up"}
                      </button>
                    </form>
                    <div className="or-separator">
                      <span className="or-text">Or Sign up With</span>
                    </div>
                    <button type="button" className="social-button google-button" onClick={googleLogin} disabled={isLoading}>
                      <span className="google-button-label">Sign up with Google</span>
                      <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden>
                        <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
                        <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                        <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
                        <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
                      </svg>
                    </button>
                    <p className="auth-signup-prompt">
                      Already have an account?{" "}
                      <button type="button" className="signup-toggle-button" onClick={() => setIsSignUp(false)}>Sign In</button>
                    </p>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      <MessageBox
        type={messageBox.type}
        message={messageBox.message}
        isVisible={messageBox.isVisible}
        onClose={() => setMessageBox({ isVisible: false, type: "success", message: "" })}
      />
    </div>
  );
};

export default AuthPage;
