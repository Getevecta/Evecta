# Master Spacing System Guide

## Overview
All spacing values are defined globally in `design-system.css` and can be used via CSS variables or utility classes.

## Spacing Token Structure

### Base Spacing Tokens (8-point system)
- `--spacing-4`: 4px
- `--spacing-8`: 8px
- `--spacing-16`: 16px
- `--spacing-24`: 24px
- `--spacing-32`: 32px
- `--spacing-40`: 40px

### Typography Spacing Tokens (from typography rules)
- `--spacing-6`: 6px
- `--spacing-10`: 10px
- `--spacing-12`: 12px

### Page-Specific Spacing Tokens
All page-specific spacing tokens reference the base tokens or typography tokens where applicable.

## Usage

### Option 1: Generic Spacing Utilities (Recommended for most cases)
```tsx
// Margin
<div className="mt-8">Content</div>
<div className="mb-16">Content</div>
<div className="space-24">Content</div>

// Padding
<div className="p-16">Content</div>
<div className="pt-8 pb-24">Content</div>

// Gap (for flex/grid containers)
<div className="flex gap-8">Items</div>
<div className="grid gap-24">Items</div>
```

### Option 2: Page-Specific Utilities (For HomePage layout)
```tsx
<section className="spacing-hero-section-top">
  <div className="spacing-hero-badge-to-heading">Badge</div>
</section>
```

### Option 3: CSS Variables (Inline styles)
```tsx
<div style={{ paddingTop: 'var(--spacing-8)' }}>
  Content
</div>
```

## Generic Spacing Utilities

### Margin Utilities
- `.mt-4`, `.mt-6`, `.mt-8`, `.mt-10`, `.mt-12`, `.mt-16`, `.mt-24`, `.mt-32`, `.mt-40` - margin-top
- `.mb-4`, `.mb-6`, `.mb-8`, `.mb-10`, `.mb-12`, `.mb-16`, `.mb-24`, `.mb-32`, `.mb-40` - margin-bottom
- `.space-4`, `.space-6`, `.space-8`, `.space-10`, `.space-12`, `.space-16`, `.space-24`, `.space-32`, `.space-40` - margin (all sides)

### Padding Utilities
- `.pt-4`, `.pt-6`, `.pt-8`, `.pt-10`, `.pt-12`, `.pt-16`, `.pt-24`, `.pt-32`, `.pt-40` - padding-top
- `.pb-4`, `.pb-6`, `.pb-8`, `.pb-10`, `.pb-12`, `.pb-16`, `.pb-24`, `.pb-32`, `.pb-40` - padding-bottom
- `.p-4`, `.p-6`, `.p-8`, `.p-10`, `.p-12`, `.p-16`, `.p-24`, `.p-32`, `.p-40` - padding (all sides)

### Gap Utilities (for flex/grid)
- `.gap-4`, `.gap-6`, `.gap-8`, `.gap-10`, `.gap-12`, `.gap-16`, `.gap-24`, `.gap-32`, `.gap-40` - gap

## Page-Specific Spacing Utilities

These are available for HomePage and can be used as reference for other pages:

### Navigation
- `.spacing-nav-padding` - Navbar padding
- `.spacing-nav-logo-to-links` - Logo → Nav links gap
- `.spacing-nav-link-to-link` - Nav link → Nav link gap
- `.spacing-nav-links-to-cta` - Nav links → CTA gap
- `.spacing-nav-icon-to-text` - Icon → Text gap

### Hero Section
- `.spacing-hero-section-top` - Section top padding
- `.spacing-hero-badge-to-heading` - Badge → Heading margin
- `.spacing-hero-heading-to-subtitle` - Heading → Subtitle margin
- `.spacing-hero-subtitle-to-cta` - Subtitle → CTA margin
- `.spacing-hero-cta-to-reassurance` - CTA → Reassurance margin
- `.spacing-hero-reassurance-item-to-item` - Reassurance items gap
- `.spacing-hero-reassurance-to-stats` - Reassurance → Stats margin
- `.spacing-hero-text-to-dashboard` - Text → Dashboard margin

### Dashboard Preview
- `.spacing-dashboard-card-padding` - Card padding
- `.spacing-dashboard-title-to-helper` - Title → Helper margin
- `.spacing-dashboard-helper-to-chart` - Helper → Chart margin
- `.spacing-dashboard-stat-to-stat` - Stat → Stat gap

### Before/After Section
- `.spacing-beforeafter-section-top` - Section top padding
- `.spacing-beforeafter-badge-to-heading` - Badge → Heading margin
- `.spacing-beforeafter-heading-to-cards` - Heading → Cards margin
- `.spacing-beforeafter-card-to-card` - Card → Card gap
- `.spacing-beforeafter-card-padding` - Card padding
- `.spacing-beforeafter-title-to-bullets` - Title → Bullets margin
- `.spacing-beforeafter-bullet-to-bullet` - Bullet → Bullet gap

### Steps Section
- `.spacing-steps-section-top` - Section top padding
- `.spacing-steps-badge-to-heading` - Badge → Heading margin
- `.spacing-steps-heading-to-row` - Heading → Row margin
- `.spacing-steps-card-to-card` - Card → Card gap
- `.spacing-steps-icon-to-title` - Icon → Title margin
- `.spacing-steps-title-to-description` - Title → Description margin
- `.spacing-steps-card-padding` - Card padding

### Features Section
- `.spacing-features-section-top` - Section top padding
- `.spacing-features-badge-to-heading` - Badge → Heading margin
- `.spacing-features-heading-to-grid` - Heading → Grid margin
- `.spacing-features-card-to-card` - Card → Card gap
- `.spacing-features-card-padding` - Card padding
- `.spacing-features-icon-to-title` - Icon → Title margin
- `.spacing-features-title-to-description` - Title → Description margin
- `.spacing-features-description-to-bullets` - Description → Bullets margin

### Blog Section
- `.spacing-blog-section-top` - Section top padding
- `.spacing-blog-label-to-heading` - Label → Heading margin
- `.spacing-blog-heading-to-cards` - Heading → Cards margin
- `.spacing-blog-card-to-card` - Card → Card gap
- `.spacing-blog-card-padding` - Card padding
- `.spacing-blog-title-to-snippet` - Title → Snippet margin
- `.spacing-blog-snippet-to-meta` - Snippet → Meta margin

### CTA Banner
- `.spacing-cta-section-padding` - Section padding (top & bottom)
- `.spacing-cta-heading-to-description` - Heading → Description margin
- `.spacing-cta-description-to-button` - Description → Button margin

### Footer
- `.spacing-footer-top` - Footer top padding
- `.spacing-footer-column-to-column` - Column → Column gap
- `.spacing-footer-title-to-links` - Title → Links margin
- `.spacing-footer-link-to-link` - Link → Link gap
- `.spacing-footer-content-to-copyright` - Content → Copyright margin

## Implementation Notes

1. **Single Source of Truth**: All spacing values are defined in `design-system.css` only
2. **Global Access**: Imported via `index.css`, available everywhere
3. **Consistency**: Use these tokens instead of hardcoded values
4. **Maintainability**: Change spacing globally by updating CSS variables
5. **No !important**: Utilities don't use `!important` to allow component overrides
6. **Generic + Specific**: Use generic utilities (`.gap-8`) for most cases, page-specific utilities for layout structure

## Best Practices

1. **Prefer Generic Utilities**: Use `.gap-8`, `.mt-16`, `.p-24` for most spacing needs
2. **Use Page-Specific for Layout**: Use `.spacing-hero-section-top` for structural spacing
3. **Avoid Hardcoded Values**: Don't use `margin-top: 16px`, use `.mt-16` or `var(--spacing-16)`
4. **Component Overrides**: Since utilities don't use `!important`, components can override when needed

## Result

✅ **Base tokens (4, 8, 16, 24, 32, 40) available**
✅ **Typography tokens (6, 10, 12) available**
✅ **Generic utilities (`.gap-8`, `.mt-16`, etc.) for all pages**
✅ **Page-specific utilities for HomePage layout**
✅ **No `!important` - allows component overrides**
