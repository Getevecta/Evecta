import { AlertTriangle, Check } from 'lucide-react';
import { CampaignLaunchReadiness } from '../../../../shared/services/api';
import './LaunchReadinessChecklist.css';

interface LaunchReadinessChecklistProps {
  readiness: CampaignLaunchReadiness | null;
  isLoading?: boolean;
  title?: string;
}

/** Handled in Step 3 — omit from Step 5 sidebar */
const HIDDEN_CHECK_KEYS = new Set(['review', 'generation']);

const WARNING_KEYS = new Set(['placeholders']);

export function LaunchReadinessChecklist({
  readiness,
  isLoading,
  title = 'Pre-flight checks',
}: LaunchReadinessChecklistProps) {
  if (isLoading) {
    return (
      <div className="launch-readiness launch-readiness--sidebar">
        <div className="launch-readiness-loading">Checking launch readiness…</div>
      </div>
    );
  }
  if (!readiness) {
    return null;
  }

  const visibleChecks = readiness.checks.filter((check) => !HIDDEN_CHECK_KEYS.has(check.key));

  return (
    <div className="launch-readiness launch-readiness--sidebar">
      <h3 className="launch-readiness-title heading-m">{title}</h3>
      <ul className="launch-readiness-list">
        {visibleChecks.map((check) => {
          const isWarning = !check.passed && WARNING_KEYS.has(check.key);
          const itemClass = check.passed
            ? 'passed'
            : isWarning
              ? 'warning'
              : 'failed';
          return (
            <li key={check.key} className={`launch-readiness-item ${itemClass}`}>
              <span className="launch-readiness-icon" aria-hidden>
                {check.passed ? (
                  <Check size={14} />
                ) : isWarning ? (
                  <AlertTriangle size={14} />
                ) : (
                  <AlertTriangle size={14} />
                )}
              </span>
              <div className="launch-readiness-text">
                <span className="launch-readiness-label">{check.label}</span>
                <span className="launch-readiness-message">{check.message}</span>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
