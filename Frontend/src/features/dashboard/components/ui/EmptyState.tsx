import React from 'react';
import { cn } from './utils';
import './EmptyState.css';

interface EmptyStateProps {
  /** SVG path for icon (e.g. /finger-cricle.svg) - same gradient applied */
  iconPath: string;
  title: string;
  description: string;
  children?: React.ReactNode;
  /** Use inside tables or tight areas — same typography, no min-height */
  compact?: boolean;
  /** Extra classes on the description line (e.g. inbox accent color) */
  descriptionClassName?: string;
}

/**
 * Shared dashboard empty state (icon 60×60, title 30px / medium / 120%, description 18px / regular / 145%).
 */
export function EmptyState({
  iconPath,
  title,
  description,
  children,
  compact,
  descriptionClassName,
}: EmptyStateProps) {
  return (
    <div
      className={cn('dashboard-empty-state', compact && 'dashboard-empty-state--compact')}
    >
      <span
        className="dashboard-empty-state-icon dashboard-empty-state-icon-gradient"
        style={{
          WebkitMaskImage: `url(${iconPath})`,
          maskImage: `url(${iconPath})`,
        }}
        aria-hidden
      />
      <p className="dashboard-empty-state-title">{title}</p>
      <p
        className={cn('dashboard-empty-state-description', descriptionClassName)}
      >
        {description}
      </p>
      {children}
    </div>
  );
}
