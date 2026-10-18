// API Configuration
// Supports three backends: localhost, staging, and production
const getBaseURL = () => {
  // 4. Auto-detect based on current hostname FIRST (most reliable)
  const hostname = window.location.hostname;
  const protocol = window.location.protocol; // 'https:' or 'http:'
  const isHttps = protocol === 'https:';
  
  // Substaging environment (separate server) - MUST come first because its
  // hostname contains both "evecta.io" and "staging" as substrings, so the
  // production and staging checks below would otherwise misclassify it.
  if (hostname.includes('substaging')) {
    return 'https://substaging.evecta.io/api';
  }

  // Production environment - ALWAYS use HTTPS
  if (hostname.includes('evecta.io') && !hostname.includes('staging')) {
    // Force HTTPS in production, even if page is somehow loaded over HTTP
    return 'https://evecta.io/api';
  }

  // Staging environment - ALWAYS use HTTPS
  if (hostname.includes('staging.evecta.io') || hostname.includes('staging')) {
    return 'https://staging.evecta.io/api';
  }
  
  //Local development (localhost:5173)
  if (hostname === 'localhost' || hostname === '127.0.0.1') {
    return 'http://localhost:8000';
  }


  
  // 1. Check for explicit environment variable (only if not in production)
  if (import.meta.env.VITE_API_BASE_URL) {
    const envUrl = import.meta.env.VITE_API_BASE_URL;
    // Ensure HTTPS in production
    if (isHttps && envUrl.startsWith('http://')) {
      console.warn('⚠️ VITE_API_BASE_URL uses HTTP but page is HTTPS. Converting to HTTPS.');
      return envUrl.replace('http://', 'https://');
    }
    return envUrl;
  }
  
  // 2. Check for manual override in localStorage (for testing) - but validate it
  const storedApiUrl = localStorage.getItem('api_base_url');
  if (storedApiUrl) {
    // Validate stored URL - if page is HTTPS, stored URL must also be HTTPS
    if (isHttps && storedApiUrl.startsWith('http://')) {
      console.warn('⚠️ Stored API URL uses HTTP but page is HTTPS. Clearing invalid override.');
      localStorage.removeItem('api_base_url');
      // Fall through to auto-detection
    } else {
      return storedApiUrl;
    }
  }
  
  // 3. Check URL parameter (for quick switching)
  const urlParams = new URLSearchParams(window.location.search);
  const apiParam = urlParams.get('api');
  if (apiParam) {
    // Validate - if page is HTTPS, param must also be HTTPS
    if (isHttps && apiParam.startsWith('http://')) {
      console.warn('⚠️ API URL parameter uses HTTP but page is HTTPS. Ignoring.');
    } else {
      // Save to localStorage for persistence
      localStorage.setItem('api_base_url', apiParam);
      return apiParam;
    }
  }
 
  
  // Fallback: use localhost in dev mode, staging otherwise
  if (import.meta.env.DEV) {
    return 'http://localhost:8000';
  }
  
  return 'https://staging.evecta.io/api';
};

const baseURL = getBaseURL();

export const API_CONFIG = {
  BASE_URL: baseURL,
  TIMEOUT: 10000, // 10 seconds
};

// Log which API is being used (helpful for debugging)
console.log(`🔗 API Base URL: ${baseURL}`);

// Helper function to switch API URL manually (for debugging)
export const setApiBaseUrl = (url: string) => {
  localStorage.setItem('api_base_url', url);
  // Reload page to apply changes
  window.location.reload();
};

// Helper function to clear manual override
export const clearApiBaseUrl = () => {
  localStorage.removeItem('api_base_url');
  window.location.reload();
};

// Helper function to fix invalid API URLs (HTTP when page is HTTPS)
export const fixApiBaseUrl = () => {
  const storedApiUrl = localStorage.getItem('api_base_url');
  const isHttps = window.location.protocol === 'https:';
  
  if (storedApiUrl && isHttps && storedApiUrl.startsWith('http://')) {
    console.log('🔧 Fixing invalid HTTP API URL in localStorage...');
    localStorage.removeItem('api_base_url');
    console.log('✅ Cleared invalid API URL. Page will reload with correct HTTPS URL.');
    window.location.reload();
    return true;
  }
  return false;
};

// Auto-fix on load if needed
if (typeof window !== 'undefined') {
  const isHttps = window.location.protocol === 'https:';
  const storedApiUrl = localStorage.getItem('api_base_url');
  
  if (isHttps && storedApiUrl && storedApiUrl.startsWith('http://')) {
    console.warn('⚠️ Detected invalid HTTP API URL in localStorage. Auto-fixing...');
    localStorage.removeItem('api_base_url');
    // Don't reload automatically - let the user see the fix
  }
}

// Get current API URL
export const getCurrentApiUrl = () => API_CONFIG.BASE_URL;

// Environment check - will be overridden by Vite at runtime
export const isDevelopment = import.meta.env.DEV;
export const isProduction = import.meta.env.PROD;
