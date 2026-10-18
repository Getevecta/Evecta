import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import './NoInternetConnection.css';

interface NoInternetConnectionProps {
  onRetry?: () => void;
}

export default function NoInternetConnection({ onRetry }: NoInternetConnectionProps) {
  const [isRetrying, setIsRetrying] = useState(false);

  const handleRetry = () => {
    setIsRetrying(true);
    if (onRetry) {
      onRetry();
    } else {
      window.location.reload();
    }
  };

  return (
    <div className="no-internet-container">
      <Link to="/" className="no-internet-logo evecta-logo">
        <span className="evecta-logo-text">Evecta</span>
        <span className="evecta-logo-tagline">AI-Powered Platform</span>
      </Link>

      <div className="no-internet-content">
        <p className="no-internet-oops">Oops!</p>
        <h1 className="no-internet-title">You're currently offline.</h1>
        <p className="no-internet-description">
          <span className="no-internet-desc-line">
            Please check your network settings
          </span>
          <span className="no-internet-desc-line">and try again.</span>
        </p>
        <button
          type="button"
          className="no-internet-retry-button"
          onClick={handleRetry}
          disabled={isRetrying}
        >
          <Loader2 size={20} className={`no-internet-retry-icon ${isRetrying ? 'no-internet-retry-icon-spin' : ''}`} />
          <span>Retry</span>
        </button>
      </div>
    </div>
  );
}
