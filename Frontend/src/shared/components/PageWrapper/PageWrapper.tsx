import { ReactNode } from 'react';
import './PageWrapper.css';

interface PageWrapperProps {
  children: ReactNode;
  className?: string;
}

const PageWrapper: React.FC<PageWrapperProps> = ({ children, className = '' }) => {
  return (
    <div className={`page-wrapper ${className}`}>
      {/* Main content area */}
      <div className="page-content">
        {children}
      </div>
    </div>
  );
};

export default PageWrapper;


