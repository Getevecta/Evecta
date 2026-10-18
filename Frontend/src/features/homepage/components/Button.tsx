import React from 'react';
import { ArrowRight } from 'lucide-react';

/* Play icon: inherits #030011 from secondary button wrapper */
function PlayCircleIcon({ className }: { className?: string }) {
  const color = 'currentColor';
  return (
    <svg
      className={className}
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden
    >
      <circle cx="12" cy="12" r="10" stroke={color} strokeWidth="1.5" fill="none" />
      <path
        d="M10 8v8l6-4-6-4z"
        fill={color}
        stroke={color}
        strokeWidth="0.6"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

/* Sizing/colors come from dashboard.css .evecta-primary-btn / .evecta-secondary-btn */
const primaryStyles =
  'evecta-primary-btn cursor-pointer transition-none focus:outline-none';

const secondaryStyles =
  'evecta-secondary-btn cursor-pointer transition-none focus:outline-none';

export function PrimaryButton({
  children,
  onClick,
  className = '',
  ...props
}: {
  children: React.ReactNode;
  onClick?: () => void;
  className?: string;
  [key: string]: unknown;
}) {
  return (
    <button
      type="button"
      className={`homepage-hero-primary-btn ${primaryStyles} ${className}`.trim()}
      onClick={onClick}
      {...props}
    >
      {children}
      <ArrowRight className="h-4 w-4 flex-shrink-0" aria-hidden />
    </button>
  );
}

export function SecondaryButton({
  children,
  onClick,
  className = '',
  ...props
}: {
  children: React.ReactNode;
  onClick?: () => void;
  className?: string;
  [key: string]: unknown;
}) {
  return (
    <button
      type="button"
      className={`homepage-hero-secondary-btn ${secondaryStyles} ${className}`.trim()}
      onClick={onClick}
      {...props}
    >
      {children}
      <span className="flex h-6 w-6 items-center justify-center flex-shrink-0 text-[#030011]" aria-hidden>
        <PlayCircleIcon className="h-5 w-5" />
      </span>
    </button>
  );
}
