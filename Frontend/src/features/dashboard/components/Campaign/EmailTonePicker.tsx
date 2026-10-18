import { useEffect, useState } from 'react';
import { ChevronDown, Lock } from 'lucide-react';
import { isToneUnlocked, isToneCardSelected, type ToneTierGroup } from './emailToneTiers';
import './EmailTonePicker.css';

interface EmailTonePickerProps {
  value: string;
  selectedTierPlan?: string;
  onChange: (toneId: string, tierPlan: string) => void;
  userPlan?: string;
  tiers: ToneTierGroup[];
}

function buildExpandedState(tiers: ToneTierGroup[]): Record<string, boolean> {
  return Object.fromEntries(tiers.map((tier) => [tier.tierPlan, true]));
}

function countExpanded(expanded: Record<string, boolean>, tiers: ToneTierGroup[]): number {
  return tiers.filter((tier) => expanded[tier.tierPlan]).length;
}

export function EmailTonePicker({
  value,
  selectedTierPlan,
  onChange,
  tiers,
}: EmailTonePickerProps) {
  const [expandedTiers, setExpandedTiers] = useState<Record<string, boolean>>(() =>
    buildExpandedState(tiers),
  );

  useEffect(() => {
    if (!tiers.length) return;
    setExpandedTiers(buildExpandedState(tiers));
  }, [tiers]);

  useEffect(() => {
    if (!selectedTierPlan || !tiers.length) return;
    setExpandedTiers((prev) => {
      if (prev[selectedTierPlan]) return prev;
      return { ...prev, [selectedTierPlan]: true };
    });
  }, [selectedTierPlan, tiers]);

  if (!tiers.length) {
    return null;
  }

  const toggleTier = (tierPlan: string) => {
    setExpandedTiers((prev) => {
      const isOpen = !!prev[tierPlan];
      if (isOpen && countExpanded(prev, tiers) <= 1) {
        return prev;
      }
      return { ...prev, [tierPlan]: !isOpen };
    });
  };

  return (
    <div className="email-tone-picker">
      <label className="email-form-label">Generate AI-Assisted Draft</label>
      <div className="email-tone-tier-list">
        {tiers.map((tier) => {
          const unlocked = isToneUnlocked(tier);
          const badge = tier.badge;
          const isExpanded = !!expandedTiers[tier.tierPlan];
          const badgeClass =
            badge === 'YOUR PLAN'
              ? 'your-plan'
              : badge === 'INCLUDED'
                ? 'included'
                : 'upgrade';

          const headerInner = (
            <>
              <span className="email-tone-tier-name">{tier.tierLabel}</span>
              <span className={`email-tone-tier-badge ${badgeClass}`}>{badge}</span>
              <span className="email-tone-tier-header-line" aria-hidden />
              <ChevronDown
                size={16}
                className={`email-tone-tier-chevron ${isExpanded ? 'expanded' : ''}`}
                aria-hidden
              />
            </>
          );

          return (
            <div
              key={tier.tierPlan}
              className={`email-tone-tier ${!unlocked ? 'email-tone-tier-locked' : ''} ${!isExpanded ? 'email-tone-tier-collapsed' : ''}`}
            >
              <button
                type="button"
                className="email-tone-tier-header email-tone-tier-header-toggle"
                onClick={() => toggleTier(tier.tierPlan)}
                aria-expanded={isExpanded}
                aria-controls={`email-tone-tier-cards-${tier.tierPlan}`}
              >
                {headerInner}
              </button>

              {isExpanded && (
                <div
                  id={`email-tone-tier-cards-${tier.tierPlan}`}
                  className="email-tone-tier-cards"
                >
                  {tier.tones.map((tone) => {
                    const selected = isToneCardSelected(
                      tone.id,
                      tier.tierPlan,
                      value,
                      selectedTierPlan,
                    );
                    const disabled = !unlocked;

                    return (
                      <button
                        key={`${tier.tierPlan}-${tone.id}`}
                        type="button"
                        className={`email-tone-card ${selected ? 'selected' : ''} ${disabled ? 'disabled' : ''}`}
                        onClick={() => {
                          if (!disabled) onChange(tone.id, tier.tierPlan);
                        }}
                        disabled={disabled}
                        aria-pressed={selected}
                      >
                        <span className="email-tone-card-radio" aria-hidden />
                        <span className="email-tone-card-text">
                          <span className="email-tone-card-title-row">
                            <span className="email-tone-card-label">{tone.label}</span>
                            {disabled && (
                              <Lock
                                size={14}
                                strokeWidth={2.25}
                                className="email-tone-card-lock"
                                aria-hidden
                              />
                            )}
                          </span>
                          <span className="email-tone-card-desc">{tone.description}</span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
