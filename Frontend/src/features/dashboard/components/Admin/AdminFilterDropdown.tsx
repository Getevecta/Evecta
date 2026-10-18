import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Check, ChevronDown, Filter } from 'lucide-react';
import { Input } from '../ui/input';
import './AdminFilterDropdown.css';

export type AdminFilterOption = {
  value: string;
  label: string;
  secondary?: string;
};

type AdminFilterDropdownProps = {
  options: AdminFilterOption[];
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  emptyLabel?: string;
  /** Hide the leading empty/"All" option (e.g. required plan pickers). */
  hideEmptyOption?: boolean;
  /** Hide the funnel/filter icon on the trigger (cleaner select-style dropdowns). */
  hideFilterIcon?: boolean;
  /**
   * Render the menu in a portal with fixed positioning.
   * Use inside overflow:auto tables so the list is not clipped.
   */
  portalMenu?: boolean;
  disabled?: boolean;
  className?: string;
  /** Wider dropdown for long labels (e.g. user emails). */
  wide?: boolean;
};

type MenuCoords = {
  top: number;
  left: number;
  width: number;
  maxHeight: number;
  openUp: boolean;
};

export function AdminFilterDropdown({
  options,
  value,
  onChange,
  placeholder = 'Select…',
  emptyLabel = 'All',
  hideEmptyOption = false,
  hideFilterIcon = false,
  portalMenu = false,
  disabled = false,
  className = '',
  wide = false,
}: AdminFilterDropdownProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [coords, setCoords] = useState<MenuCoords | null>(null);

  const selected = useMemo(
    () => options.find((o) => o.value === value) || null,
    [options, value],
  );

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return options;
    return options.filter(
      (o) =>
        o.label.toLowerCase().includes(q) ||
        (o.secondary || '').toLowerCase().includes(q) ||
        o.value.toLowerCase().includes(q),
    );
  }, [options, search]);

  const updateCoords = () => {
    const el = triggerRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const gap = 4;
    const preferredMax = 220;
    const spaceBelow = window.innerHeight - rect.bottom - gap - 8;
    const spaceAbove = rect.top - gap - 8;
    const openUp = spaceBelow < 140 && spaceAbove > spaceBelow;
    const maxHeight = Math.max(
      120,
      Math.min(preferredMax, openUp ? spaceAbove : spaceBelow),
    );
    setCoords({
      top: openUp ? rect.top - gap : rect.bottom + gap,
      left: rect.left,
      width: Math.max(rect.width, 140),
      maxHeight,
      openUp,
    });
  };

  useLayoutEffect(() => {
    if (!open || !portalMenu) return;
    updateCoords();
  }, [open, portalMenu, filtered.length]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node;
      const inRoot = rootRef.current?.contains(t);
      const inMenu = menuRef.current?.contains(t);
      if (!inRoot && !inMenu) {
        setOpen(false);
        setSearch('');
      }
    };
    const onReposition = () => {
      if (portalMenu) updateCoords();
    };
    document.addEventListener('mousedown', onDoc);
    window.addEventListener('resize', onReposition);
    window.addEventListener('scroll', onReposition, true);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      window.removeEventListener('resize', onReposition);
      window.removeEventListener('scroll', onReposition, true);
    };
  }, [open, portalMenu]);

  const displayValue = open ? search : selected?.label || '';

  const pick = (next: string) => {
    onChange(next);
    setOpen(false);
    setSearch('');
  };

  const menu = open && !disabled && (
    <div
      ref={menuRef}
      className={`admin-filter-dropdown__menu${portalMenu ? ' admin-filter-dropdown__menu--portal' : ''}`}
      role="listbox"
      style={
        portalMenu && coords
          ? {
              top: coords.openUp ? undefined : coords.top,
              bottom: coords.openUp
                ? window.innerHeight - coords.top
                : undefined,
              left: coords.left,
              width: coords.width,
              maxHeight: coords.maxHeight,
            }
          : undefined
      }
    >
      {!hideEmptyOption && (
        <button
          type="button"
          className={`admin-filter-dropdown__item${value === '' ? ' admin-filter-dropdown__item--active' : ''}`}
          onClick={() => pick('')}
        >
          <span>{emptyLabel}</span>
          {value === '' && <Check size={14} strokeWidth={2} />}
        </button>
      )}
      {filtered.map((opt) => (
        <button
          key={opt.value}
          type="button"
          className={`admin-filter-dropdown__item${value === opt.value ? ' admin-filter-dropdown__item--active' : ''}`}
          onClick={() => pick(opt.value)}
        >
          <span className="admin-filter-dropdown__item-text">
            <span className="admin-filter-dropdown__item-label">{opt.label}</span>
            {opt.secondary && (
              <span className="admin-filter-dropdown__item-secondary">{opt.secondary}</span>
            )}
          </span>
          {value === opt.value && <Check size={14} strokeWidth={2} />}
        </button>
      ))}
      {filtered.length === 0 && (
        <div className="admin-filter-dropdown__empty">No matches</div>
      )}
    </div>
  );

  return (
    <div
      ref={rootRef}
      className={`admin-filter-dropdown${wide ? ' admin-filter-dropdown--wide' : ''} ${className}`.trim()}
    >
      <div className="admin-filter-dropdown__wrapper">
        <div
          ref={triggerRef}
          className={`admin-filter-dropdown__trigger${disabled ? ' admin-filter-dropdown__trigger--disabled' : ''}`}
          onClick={() => {
            if (disabled) return;
            setOpen(true);
          }}
        >
          {!hideFilterIcon && (
            <Filter className="admin-filter-dropdown__icon" size={14} strokeWidth={2} aria-hidden />
          )}
          <Input
            type="text"
            placeholder={placeholder}
            value={displayValue}
            disabled={disabled}
            onChange={(e) => {
              setSearch(e.target.value);
              setOpen(true);
            }}
            onFocus={() => {
              if (disabled) return;
              setOpen(true);
              setSearch('');
            }}
            className="admin-filter-dropdown__input focus-visible:ring-0 focus-visible:ring-transparent focus-visible:border-none focus-visible:ring-offset-0"
          />
          <ChevronDown
            className="admin-filter-dropdown__icon admin-filter-dropdown__chevron"
            size={14}
            strokeWidth={2}
            aria-hidden
            style={{
              transform: open ? 'rotate(180deg)' : 'rotate(0deg)',
              transition: 'transform 0.2s',
            }}
          />
        </div>

        {!portalMenu && menu}
      </div>
      {portalMenu && open && !disabled && coords && typeof document !== 'undefined'
        ? createPortal(menu, document.body)
        : null}
    </div>
  );
}
