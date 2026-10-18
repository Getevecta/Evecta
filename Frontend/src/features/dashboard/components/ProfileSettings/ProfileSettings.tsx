import React, { useState, useMemo, useRef, useLayoutEffect, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { ChevronDown } from 'lucide-react';
import { apiService, CompanyCreateRequest, CompanyUpdateRequest } from '../../../../shared/services/api';
import { toast } from 'sonner';
import { PROFILE_ROLE_PRESET_LABELS } from './profileRolePresets';
import { PROFILE_INDUSTRY_PRESET_LABELS, normalizeIndustryValue } from './profileIndustryPresets';
import { PROFILE_LOCATION_PRESET_LABELS } from './profileLocationPresets';
import './ProfileSettings.css';

type ProfileSelectOption = { value: string; label: string };

const ROLE_SELECT_OPTIONS: ProfileSelectOption[] = PROFILE_ROLE_PRESET_LABELS.map((label) => ({
  value: label,
  label,
}));

const INDUSTRY_SELECT_OPTIONS: ProfileSelectOption[] = PROFILE_INDUSTRY_PRESET_LABELS.map((label) => ({
  value: label,
  label,
}));

const LOCATION_SELECT_OPTIONS: ProfileSelectOption[] = PROFILE_LOCATION_PRESET_LABELS.map((label) => ({
  value: label,
  label,
}));

/** Autocomplete-style match: substring, word prefix, or consecutive-char “starts with” feel. */
function optionMatchesSuggestion(label: string, rawQuery: string): boolean {
  const q = rawQuery.trim().toLowerCase();
  if (!q) return true;
  const lower = label.toLowerCase();
  if (lower.includes(q)) return true;
  const parts = lower.split(/[\s/\-_,]+/).filter(Boolean);
  if (parts.some((w) => w.startsWith(q))) return true;
  let pi = 0;
  for (let i = 0; i < lower.length && pi < q.length; i++) {
    if (lower[i] === q[pi]) pi += 1;
  }
  return pi === q.length;
}

function ProfileSearchableSelect({
  value,
  onValueChange,
  options,
  placeholder,
  error,
  allowCustomValue = false,
}: {
  value: string;
  onValueChange: (v: string) => void;
  options: ProfileSelectOption[];
  placeholder: string;
  error?: boolean;
  /** When true, any typed text is kept as the value (free-form job title). */
  allowCustomValue?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const [panelPos, setPanelPos] = useState<{
    left: number;
    width: number;
    placement: 'below' | 'above';
    top?: number;
    bottom?: number;
    maxListHeight: number;
  } | null>(null);
  const filteredCountRef = useRef(0);

  const updatePanelPos = useCallback(() => {
    const el = rootRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const gap = 4;
    const edgeMargin = 8;
    const popoverChrome = 24;
    const vh = window.innerHeight;
    const spaceBelow = vh - r.bottom - gap - edgeMargin;
    const spaceAbove = r.top - gap - edgeMargin;
    const cap = Math.min(360, vh * 0.5);
    const preferBelow = spaceBelow >= 160 || spaceBelow >= spaceAbove;

    let placement: 'below' | 'above' = preferBelow ? 'below' : 'above';
    const n = Math.max(1, filteredCountRef.current);
    const minForOptions = Math.min(cap, n * 48 + 16);
    const targetList = Math.min(cap, Math.max(100, minForOptions));
    const space = placement === 'below' ? spaceBelow : spaceAbove;
    const rawSpace = Math.max(0, space - popoverChrome);
    let maxListHeight = Math.min(cap, rawSpace, targetList);

    if (placement === 'below' && maxListHeight < 120 && spaceAbove > spaceBelow) {
      placement = 'above';
      const rawAbove = Math.max(0, spaceAbove - popoverChrome);
      maxListHeight = Math.min(cap, rawAbove, targetList);
    }

    if (placement === 'below') {
      setPanelPos({
        left: r.left,
        width: r.width,
        placement: 'below',
        top: r.bottom + gap,
        maxListHeight: Math.floor(maxListHeight),
      });
    } else {
      setPanelPos({
        left: r.left,
        width: r.width,
        placement: 'above',
        bottom: vh - r.top + gap,
        maxListHeight: Math.floor(maxListHeight),
      });
    }
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = options.filter((o) => optionMatchesSuggestion(o.label, query));
    if (!q) return list;
    return [...list].sort((a, b) => {
      const al = a.label.toLowerCase();
      const bl = b.label.toLowerCase();
      const aStarts = al.startsWith(q);
      const bStarts = bl.startsWith(q);
      if (aStarts && !bStarts) return -1;
      if (!aStarts && bStarts) return 1;
      const ai = al.indexOf(q);
      const bi = bl.indexOf(q);
      if (ai !== bi) return ai - bi;
      return al.localeCompare(bl);
    });
  }, [options, query]);
  filteredCountRef.current = filtered.length;

  const optionForValue = options.find((o) => o.value === value);
  const displayCommitted =
    optionForValue?.label ?? (allowCustomValue && value.trim() ? value.trim() : '');
  const inputShown = open ? query : displayCommitted;

  const seedQueryFromValue = useCallback(() => {
    const opt = options.find((o) => o.value === value);
    setQuery(opt?.label ?? value ?? '');
  }, [options, value]);

  const applyPreset = (v: string) => {
    onValueChange(v);
    setOpen(false);
  };

  const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value;
    setQuery(v);
    setOpen(true);
    if (allowCustomValue) {
      onValueChange(v);
    }
  };

  const onInputFocus = () => {
    if (!open) {
      seedQueryFromValue();
    }
    setOpen(true);
    requestAnimationFrame(() => updatePanelPos());
  };

  const onInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      setOpen(false);
      return;
    }
    if (e.key !== 'Enter') return;
    e.preventDefault();
    if (filtered.length > 0) {
      applyPreset(filtered[0].value);
      return;
    }
    if (allowCustomValue && query.trim()) {
      onValueChange(query.trim());
      setOpen(false);
    }
  };

  const onChevronMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    if (open) {
      setOpen(false);
    } else {
      seedQueryFromValue();
      setOpen(true);
      requestAnimationFrame(() => {
        inputRef.current?.focus({ preventScroll: true });
        updatePanelPos();
      });
    }
  };

  useLayoutEffect(() => {
    if (!open) {
      setPanelPos(null);
      return;
    }
    updatePanelPos();
    const onReposition = () => updatePanelPos();

    const scrollRoots: (Window | Element)[] = [window];
    let p: HTMLElement | null = rootRef.current?.parentElement ?? null;
    while (p) {
      const { overflowY } = window.getComputedStyle(p);
      if (overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'overlay') {
        scrollRoots.push(p);
      }
      p = p.parentElement;
    }

    window.addEventListener('resize', onReposition);
    window.addEventListener('scroll', onReposition, true);
    scrollRoots.forEach((node) => {
      if (node !== window) node.addEventListener('scroll', onReposition, true);
    });

    return () => {
      window.removeEventListener('resize', onReposition);
      window.removeEventListener('scroll', onReposition, true);
      scrollRoots.forEach((node) => {
        if (node !== window) node.removeEventListener('scroll', onReposition, true);
      });
    };
  }, [open, updatePanelPos]);

  useEffect(() => {
    if (!open) return;
    const onDocMouseDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (rootRef.current?.contains(t)) return;
      if (panelRef.current?.contains(t)) return;
      setOpen(false);
    };
    document.addEventListener('mousedown', onDocMouseDown);
    return () => document.removeEventListener('mousedown', onDocMouseDown);
  }, [open]);

  const dropdown =
    open && panelPos
      ? createPortal(
          <div
            ref={panelRef}
            className="profile-settings-searchable-popover-content profile-settings-searchable-popover-suggestions"
            role="listbox"
            aria-label="Suggestions"
            style={{
              position: 'fixed',
              left: panelPos.left,
              width: panelPos.width,
              maxWidth: panelPos.width,
              boxSizing: 'border-box',
              zIndex: 10050,
              ...(panelPos.placement === 'below'
                ? { top: panelPos.top, bottom: 'auto' }
                : { bottom: panelPos.bottom, top: 'auto' }),
            }}
          >
            <ul
              className="profile-settings-searchable-list"
              style={{ maxHeight: panelPos.maxListHeight }}
            >
              {filtered.length === 0 ? (
                allowCustomValue && query.trim() ? (
                  <li role="presentation">
                    <button
                      type="button"
                      role="option"
                      className="profile-settings-searchable-option"
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => {
                        onValueChange(query.trim());
                        setOpen(false);
                      }}
                    >
                      Use &quot;{query.trim()}&quot;
                    </button>
                  </li>
                ) : (
                  <li className="profile-settings-searchable-empty" role="presentation">
                    {allowCustomValue
                      ? 'Type a city, country, or region. If it’s not in the list below, it still saves.'
                      : 'No matching suggestions'}
                  </li>
                )
              ) : (
                filtered.map((o) => (
                  <li key={o.value} role="presentation">
                    <button
                      type="button"
                      role="option"
                      aria-selected={value === o.value}
                      className="profile-settings-searchable-option"
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => applyPreset(o.value)}
                    >
                      {o.label}
                    </button>
                  </li>
                ))
              )}
            </ul>
          </div>,
          document.body,
        )
      : null;

  return (
    <>
      <div
        ref={rootRef}
        className={`profile-settings-combobox${error ? ' profile-settings-combobox-error' : ''}`}
      >
        <input
          ref={inputRef}
          type="text"
          className={`profile-settings-combobox-input${!inputShown && !open ? ' profile-settings-combobox-input-placeholder' : ''}`}
          value={inputShown}
          onChange={onInputChange}
          onFocus={onInputFocus}
          onKeyDown={onInputKeyDown}
          placeholder={placeholder}
          aria-expanded={open}
          aria-haspopup="listbox"
          autoComplete="off"
          spellCheck={false}
        />
        <button
          type="button"
          className="profile-settings-combobox-chevron"
          tabIndex={-1}
          aria-label={open ? 'Close suggestions' : 'Open suggestions'}
          onMouseDown={onChevronMouseDown}
        >
          <ChevronDown className="size-4 opacity-50" aria-hidden strokeWidth={2} />
        </button>
      </div>
      {dropdown}
    </>
  );
}

interface ProfileSettingsProps {
  onComplete: () => void;
  onCancel?: () => void;
  inline?: boolean;
  existingCompanyData?: any;
  onSkip?: () => void;
}

export function ProfileSettings({ onComplete, inline = false, existingCompanyData, onSkip }: ProfileSettingsProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);

  const [role, setRole] = useState(existingCompanyData?.role || '');
  const [companySize, setCompanySize] = useState(existingCompanyData?.company_size || '');
  const [targetIndustry, setTargetIndustry] = useState(
    normalizeIndustryValue(existingCompanyData?.target_industry || ''),
  );
  const [targetLocation, setTargetLocation] = useState(existingCompanyData?.target_location || '');
  const [experience, setExperience] = useState(existingCompanyData?.experience_with_lead_gen_tools || '');
  const [leadExpectation, setLeadExpectation] = useState(existingCompanyData?.lead_generation_expect_monthly || '');

  const companySizeOptions: ProfileSelectOption[] = [
    '1-10',
    '11-50',
    '51-200',
    '201-500',
    '501-1000',
    '1000+',
  ].map((label) => ({ value: label, label }));

  const experienceOptions = [
    { value: 'beginner', label: 'Beginner' },
    { value: 'intermediate', label: 'Intermediate' },
    { value: 'expert', label: 'Expert' },
    { value: 'other', label: 'Other' },
  ];

  const leadExpectationOptions = [
    { value: '1-50', label: '1-50 Leads' },
    { value: '50-100', label: '50-100 Leads' },
    { value: '50-200', label: '50-200 Leads' },
    { value: '200-500', label: '200-500 Leads' },
    { value: 'other', label: 'Other' },
  ];

  const handleSubmit = async () => {
    if (
      !role.trim() ||
      !companySize.trim() ||
      !targetIndustry.trim() ||
      !targetLocation.trim() ||
      !experience.trim() ||
      !leadExpectation.trim()
    ) {
      toast.error('Please fill in all required fields');
      return;
    }

    setIsSubmitting(true);
    try {
      const payload: CompanyCreateRequest = {
        role: role.trim(),
        company_name: 'N/A',
        company_size: companySize.trim(),
        target_industry: targetIndustry.trim(),
        target_location: targetLocation.trim(),
        experience_with_lead_gen_tools: experience.trim(),
        lead_generation_expect_monthly: leadExpectation.trim(),
      };

      let response;
      if (existingCompanyData?.id) {
        const updatePayload: CompanyUpdateRequest = {
          role: role.trim(),
          company_name: existingCompanyData?.company_name || 'N/A',
          company_size: companySize.trim(),
          target_industry: targetIndustry.trim(),
          target_location: targetLocation.trim(),
          experience_with_lead_gen_tools: experience.trim(),
          lead_generation_expect_monthly: leadExpectation.trim(),
        };
        response = await apiService.updateCompany(existingCompanyData.id, updatePayload);
      } else {
        response = await apiService.createCompany(payload);
      }

      if (response.error) {
        let errorMessage = 'Failed to save profile settings';
        if (typeof response.error === 'string') errorMessage = response.error;
        else if (Array.isArray(response.error)) {
          errorMessage = response.error
            .map((err: any) => (typeof err === 'string' ? err : err?.message || ''))
            .filter(Boolean)
            .join(', ');
        } else if (typeof response.error === 'object') {
          errorMessage = (response.error as any)?.message || (response.error as any)?.detail || errorMessage;
        }
        toast.error(errorMessage);
        return;
      }

      toast.success('Profile settings saved successfully!');
      if (onSkip) onSkip();
      else onComplete();
    } catch (error: any) {
      console.error('Error saving profile settings:', error);
      toast.error(error?.message || 'Failed to save profile settings. Please try again.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const content = (
    <div className={inline ? 'profile-settings-inline' : 'profile-settings-modal'}>
      <div className="profile-settings-header">
        <h1 className="profile-settings-title">Profile Settings</h1>
        <p className="profile-settings-subtitle">
          Complete your profile to personalise your lead generation experience
        </p>
      </div>

      <div className="profile-settings-content">
        <div className="profile-settings-form profile-settings-form-grid">
          <div className="profile-settings-field">
            <label>Your Role</label>
            <ProfileSearchableSelect
              value={role}
              onValueChange={setRole}
              options={ROLE_SELECT_OPTIONS}
              placeholder="Select or type your role"
              allowCustomValue
            />
          </div>

          <div className="profile-settings-field">
            <label>Company size</label>
            <ProfileSearchableSelect
              value={companySize}
              onValueChange={setCompanySize}
              options={companySizeOptions}
              placeholder="Select Company Size"
            />
          </div>

          <div className="profile-settings-field">
            <label>Industry you want to target</label>
            <ProfileSearchableSelect
              value={targetIndustry}
              onValueChange={setTargetIndustry}
              options={INDUSTRY_SELECT_OPTIONS}
              placeholder="Select or type an industry"
              allowCustomValue
            />
          </div>

          <div className="profile-settings-field">
            <label>Target location</label>
            <ProfileSearchableSelect
              value={targetLocation}
              onValueChange={setTargetLocation}
              options={LOCATION_SELECT_OPTIONS}
              placeholder="Select or type a location"
              allowCustomValue
            />
          </div>

          <div className="profile-settings-field">
            <label>Experience with lead generation tools</label>
            <ProfileSearchableSelect
              value={experience}
              onValueChange={setExperience}
              options={experienceOptions}
              placeholder="Select your experience level"
            />
          </div>

          <div className="profile-settings-field profile-settings-field-lead-expectation">
            <label>How many leads do you expect monthly?</label>
            <ProfileSearchableSelect
              value={leadExpectation}
              onValueChange={setLeadExpectation}
              options={leadExpectationOptions}
              placeholder="Select expected monthly leads"
            />
          </div>
        </div>
      </div>

      <div className="profile-settings-footer profile-settings-footer-single">
        <button
          type="button"
          className="profile-settings-button profile-settings-button-primary profile-settings-button-complete evecta-primary-btn"
          onClick={handleSubmit}
          disabled={isSubmitting}
        >
          {isSubmitting ? 'Saving...' : 'Complete Setup'}
        </button>
      </div>
    </div>
  );

  if (inline) {
    return content;
  }

  return <div className="profile-settings-overlay">{content}</div>;
}
