import {
  CONTEXT_SCORE_HINTS,
  CONTEXT_SCORE_LABELS,
  type LeadContextScore,
} from './leadContextScore';
import './ContextScoreBadge.css';

interface ContextScoreBadgeProps {
  score: LeadContextScore;
  className?: string;
}

export function ContextScoreBadge({ score, className = '' }: ContextScoreBadgeProps) {
  return (
    <span
      className={`context-score-badge context-score-badge--${score} ${className}`.trim()}
      title={CONTEXT_SCORE_HINTS[score]}
    >
      {CONTEXT_SCORE_LABELS[score]}
    </span>
  );
}
