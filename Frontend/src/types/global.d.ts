// Global type declarations

declare module '*.js' {
  const content: any;
  export default content;
}

// Vite environment variables
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  readonly VITE_API_URL: string;
  readonly DEV: boolean;
  readonly PROD: boolean;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

// Framer Motion type extensions
declare module 'framer-motion' {
  interface HTMLAttributesWithoutMotionProps {
    className?: string;
  }
}

// Analytics tracking types
interface Window {
  posthog?: {
    capture: (event: string, properties?: Record<string, any>) => void;
    init: (apiKey: string, config: Record<string, any>) => void;
    [key: string]: any;
  };
  gtag?: (...args: any[]) => void;
  dataLayer?: any[];
}
