import { useNavigate, Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { useAuth } from '../../shared/contexts/AuthContext';
import { PageSeo } from '../../shared/components/PageSeo/PageSeo';
import './NotFoundPage.css';

export default function NotFoundPage() {
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();

  const handleGoHome = () => {
    if (isAuthenticated) {
      navigate('/dashboard/generate');
    } else {
      navigate('/');
    }
  };

  const homePath = isAuthenticated ? '/dashboard/generate' : '/';

  return (
    <div className="not-found-container">
      <PageSeo
        title="Page not found"
        description="The page you requested is not available on Evecta."
        path="/404"
        noindex
      />
      <Link to={homePath} className="not-found-logo evecta-logo">
        <span className="evecta-logo-text">Evecta</span>
        <span className="evecta-logo-tagline">AI-Powered Platform</span>
      </Link>

      <div className="not-found-content">
        <p className="not-found-oops">Oops!</p>
        <h1 className="not-found-title">Page Not Found</h1>
        <p className="not-found-description">
          <span className="not-found-desc-line">The page you're looking for doesn't exist</span>
          <span className="not-found-desc-line">or has been moved</span>
        </p>
        <button
          type="button"
          className="not-found-button"
          onClick={handleGoHome}
        >
          <ArrowLeft size={20} className="not-found-button-arrow" />
          <span>Go back to Home</span>
        </button>
      </div>
    </div>
  );
}
