// src/contexts/AuthContext.tsx
import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { toast } from "sonner";
import { apiService, UserResponse } from "../services/api";
import { clearLeadGenSessionOnAuthEnd } from "../clearLeadGenSession";

// Types
interface User {
  id: string;
  username: string;
  email: string;
  is_active: boolean;
  [key: string]: any; // Allow for additional user properties
}

interface AuthResponse {
  success: boolean;
  message: string;
  userId?: string;
  requires2fa?: boolean;
  email?: string;
}

interface AuthContextType {
  user: User | null;
  setUser: (user: User | null) => void;
  loading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<AuthResponse>;
  signup: (username: string, email: string, password: string) => Promise<AuthResponse>;
  googleLogin: () => void;
  logout: () => Promise<void>;
}

interface AuthProviderProps {
  children: ReactNode;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
};

export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true); // Start with loading true to check auth status

  // Check if user is authenticated on app load
  useEffect(() => {
    let isMounted = true;
    let timeoutId: NodeJS.Timeout | null = null;
    let hasCompleted = false;

    const setLoadingFalse = () => {
      if (isMounted && !hasCompleted) {
        hasCompleted = true;
        setLoading(false);
        if (timeoutId) {
          clearTimeout(timeoutId);
        }
      }
    };

    const checkAuthStatus = async () => {
      // Set a timeout to ensure loading is always set to false (fail open)
      timeoutId = setTimeout(() => {
        console.warn('Auth check timed out after 5 seconds, setting loading to false');
        setLoadingFalse();
      }, 5000); // 5 second timeout - fail open to show content

      try {
        try {
          const response = await apiService.getCurrentUser();
          
          if (!isMounted || hasCompleted) return;

          if (response.data) {
            setUser(response.data);
          } else if (response.error && response.error.includes('expired')) {
            // Token expired - clear everything
            apiService.setAccessToken(null);
            setUser(null);
          } else {
            // Token might be invalid, try to refresh (but don't wait too long)
            try {
              const refreshResponse = await apiService.refreshToken();
              
              if (!isMounted || hasCompleted) return;

              if (refreshResponse.data) {
                const userResponse = await apiService.getCurrentUser();
                
                if (!isMounted || hasCompleted) return;

                if (userResponse.data) {
                  setUser(userResponse.data);
                } else {
                  apiService.setAccessToken(null);
                  setUser(null);
                }
              } else {
                apiService.setAccessToken(null);
                setUser(null);
              }
            } catch (refreshError) {
              console.error('Token refresh failed:', refreshError);
              if (isMounted && !hasCompleted) {
                apiService.setAccessToken(null);
                setUser(null);
              }
            }
          }
        } catch (error) {
          console.error('Auth check failed:', error);
          if (isMounted && !hasCompleted) {
            apiService.setAccessToken(null);
            setUser(null);
          }
        }
      } catch (error) {
        console.error('Auth check error:', error);
        if (isMounted && !hasCompleted) {
          apiService.setAccessToken(null);
          setUser(null);
        }
      } finally {
        setLoadingFalse();
      }
    };

    checkAuthStatus();

    // Cleanup function
    return () => {
      isMounted = false;
      hasCompleted = true;
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
    };
  }, []);

  // Real login using backend API
  const login = async (email: string, password: string): Promise<AuthResponse> => {
    setLoading(true);
    
    try {
      const normalizedEmail = email.trim();
      const response = await apiService.login({ email: normalizedEmail, password });

      if (response.data?.requires_2fa) {
        return {
          success: false,
          requires2fa: true,
          email: response.data.email || normalizedEmail,
          message:
            response.data.message ||
            "Enter the verification code sent to your email to finish signing in.",
        };
      }
      
      if (response.data && !response.error && !response.data.requires_2fa) {
        const userResponse = await apiService.getCurrentUser();
        if (userResponse.data) {
          setUser(userResponse.data);
          const successMessage = "Logged in successfully!";
          toast.success(successMessage, { duration: 4500 });
          return { success: true, message: successMessage };
        }
        return {
          success: false,
          message:
            userResponse.error ||
            "Signed in but could not load your profile. Try again or refresh the page.",
        };
      }

      return {
        success: false,
        message: response.error || "Login failed. Please check your credentials.",
      };
    } catch (error) {
      return { 
        success: false, 
        message: "Network error. Please try again." 
      };
    } finally {
      setLoading(false);
    }
  };

  // Real signup using backend API
  const signup = async (username: string, email: string, password: string): Promise<AuthResponse> => {
    setLoading(true);
    
    try {
      console.log("🔗 Calling API service signup...");
      const response = await apiService.signup({ username, email, password });
      
      console.log("📡 API response:", response);
      console.log("📡 Response data:", response.data);
      console.log("📡 Response error:", response.error);
      console.log("📡 Response message:", response.message);
      console.log("📡 Has response.data?", !!response.data);
      console.log("📡 Has response.error?", !!response.error);
      console.log("📡 Full response object:", JSON.stringify(response, null, 2));
      
      // Check if we have a successful response with data
      if (response.data && !response.error) {
        console.log("✅ API returned user data:", response.data);
        return { 
          success: true, 
          message: "Account created successfully! Please verify your email.",
          userId: response.data.id
        };
      }
      
      // Extract error message - check multiple possible locations
      let errorMessage: string = "Registration failed. Please try again.";
      
      // Handle response.error (could be string or object)
      if (response.error) {
        if (typeof response.error === 'object' && response.error !== null) {
          errorMessage = (response.error as any)?.message || (response.error as any)?.detail || String(response.error);
        } else {
          errorMessage = String(response.error);
        }
      } else if (response.message) {
        errorMessage = String(response.message);
      } else if ((response.data as any)?.detail) {
        const detail = (response.data as any).detail;
        if (typeof detail === 'object' && detail !== null && 'message' in detail) {
          errorMessage = detail.message;
        } else if (typeof detail === 'string') {
          errorMessage = detail;
        } else {
          errorMessage = String(detail);
        }
      }
      
      console.log("🔍 Extracted raw error message:", errorMessage);
      
      // Normalize common error messages for better user experience
      const lowerMessage = errorMessage.toLowerCase();
      if (lowerMessage.includes("email already exists") || 
          lowerMessage.includes("email exists") ||
          // Some environments only surface generic 400 text
          lowerMessage === "bad request") {
        errorMessage = "Email already exists. Please use a different email or sign in.";
      } else if (lowerMessage.includes("username already exists")) {
        errorMessage = "Username already exists. Please choose a different username.";
      }
      
      console.log("❌ API returned error. Final error message:", errorMessage);
      console.log("❌ Returning AuthResponse with success=false and message:", errorMessage);
      
      return { 
        success: false, 
        message: errorMessage
      };
    } catch (error: any) {
      console.log("💥 Signup error:", error);
      // Read both message and detail from possible locations
      let msg: string = "Registration failed. Please try again.";
      
      // Handle error.response.data.detail (could be object or string)
      if (error?.response?.data?.detail) {
        const detail = error.response.data.detail;
        if (typeof detail === 'object' && detail !== null && 'message' in detail) {
          msg = detail.message;
        } else if (typeof detail === 'string') {
          msg = detail;
        } else {
          msg = String(detail);
        }
      } else if (error?.response?.data?.message) {
        msg = String(error.response.data.message);
      } else if (error?.message) {
        msg = String(error.message);
      }

      const raw = (msg || '').toString();
      const lower = raw.toLowerCase();

      // Map the exact backend detail to friendly CTA
      if (raw === "Email already exists" || lower.includes("email already exists") || lower.includes("email exists")) {
        msg = "Email already exists. Please sign in instead.";
      }

      return {
        success: false,
        message: msg
      };
    } finally {
      setLoading(false);
    }
  };

  // Google login - redirect to backend Google OAuth endpoint
  const googleLogin = (): void => {
    // In production: use relative path that goes through Nginx proxy
    // In development: use full backend URL
    if (import.meta.env.PROD) {
      // Production: use /api/auth/google/login, Nginx will proxy /api/ to backend
      window.location.href = '/api/auth/google/login';
    } else {
      // Development: use full backend URL
      const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
      window.location.href = `${apiUrl}/auth/google/login`;
    }
  };

  // Real logout using backend API
  const logout = async (): Promise<void> => {
    setLoading(true);
    
    try {
      await apiService.logout();
      // Set logout flag in localStorage to notify other tabs
      localStorage.setItem('user_logged_out', Date.now().toString());
      // Dispatch storage event for same-origin tabs
      window.dispatchEvent(new StorageEvent('storage', {
        key: 'user_logged_out',
        newValue: Date.now().toString()
      }));
    } catch (error) {
      console.error('Logout error:', error);
    } finally {
      clearLeadGenSessionOnAuthEnd();
      setUser(null);
      setLoading(false);
    }
  };

  const isAuthenticated = !!user;

  return (
    <AuthContext.Provider
      value={{ user, setUser, loading, isAuthenticated, login, signup, googleLogin, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
};
