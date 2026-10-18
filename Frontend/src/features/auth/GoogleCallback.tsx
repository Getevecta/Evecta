import { useEffect } from "react";
import { useAuth } from "../../shared/contexts/AuthContext";
import { useNavigate, useLocation } from "react-router-dom";
import { apiService } from "../../shared/services/api";
import { toast } from "sonner";
import "./GoogleCallback.css";

/** Dedupe OAuth handling: React Strict Mode runs effects twice; parallel refreshToken() calls revoke each other's session. */
let googleOAuthHandlePromise: Promise<void> | null = null;

const GoogleCallback = () => {
  const { setUser } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    const runOnce = async () => {
      if (!googleOAuthHandlePromise) {
        googleOAuthHandlePromise = (async () => {
          try {
            let userResponse = await apiService.getCurrentUser();

            if (!userResponse.data) {
              const refreshed = await apiService.refreshToken();
              if (refreshed.error || !refreshed.data) {
                throw new Error(refreshed.error || "No authentication session found");
              }
              userResponse = await apiService.getCurrentUser();
            }

            if (!userResponse.data) {
              throw new Error(userResponse.error || "Failed to get user data");
            }

            setUser(userResponse.data);
            toast.success("Signed in successfully!", { duration: 4500 });
            const dashboardUrl = location.state?.from?.pathname || "/dashboard";
            navigate(dashboardUrl, { replace: true });
          } catch (error) {
            console.error("Google callback error:", error);
            const errorMessage = error instanceof Error ? error.message : "Authentication failed";
            toast.error(
              errorMessage ||
                "Could not finish Google sign-in. Try again or use email and password."
            );
            setTimeout(() => navigate("/auth", { replace: true }), 1000);
          } finally {
            googleOAuthHandlePromise = null;
          }
        })();
      }

      await googleOAuthHandlePromise;
    };

    runOnce();
    // Intentionally one-shot per mount: location is read once; avoid re-running OAuth if Strict Mode or parent re-renders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navigate, setUser]);

  return (
    <div className="google-callback-container">
      <div className="google-callback-spinner"></div>
      <p className="google-callback-text">Processing authentication...</p>
    </div>
  );
};

export default GoogleCallback;
