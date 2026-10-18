# Master Typography Hierarchy - Implementation Guide

## ✅ COMPLETED

### 1. CSS System Created (`design-system.css`)
- ✅ All 7 typography tokens defined as CSS variables
- ✅ Utility classes created (`.heading-xl`, `.heading-l`, `.heading-m`, `.text-l`, `.text-m`, `.text-s`, `.label-xs`)
- ✅ Global overrides implemented to enforce system

### 2. HomePage.tsx Updated
- ✅ All h1 elements → `.heading-xl` (26px)
- ✅ All h2 elements → `.heading-l` (22px)
- ✅ All h3 elements → `.heading-m` (18px)
- ✅ All h4 elements → `.heading-m` (18px)
- ✅ Hero description → `.text-l` (16px)
- ✅ Badges → `.label-xs` (11px) via CSS

### 3. CSS Files Updated
- ✅ HomePage.css - All hardcoded font-sizes replaced
- ✅ Sidebar.css - All hardcoded font-sizes replaced
- ✅ Template.css - All hardcoded font-sizes replaced
- ✅ dashboard.css - All hardcoded font-sizes replaced
- ✅ index.css - Updated to use typography system

## 🔄 NEEDS UPDATE: Dashboard Components

### Components with Inline Styles (fontSize) that need typography classes:

1. **Template.tsx**
   - h1 (line 940) - needs `.heading-xl`
   - h2 (multiple) - need `.heading-l`
   - h3 (line 84) - needs `.heading-m`

2. **UserProfile.tsx**
   - h1 (line 560) - has `fontSize: '14px'` → should be `.heading-xl`
   - h2 (line 665) - has `fontSize: '20px'` → should be `.heading-l`

3. **LeadLog.tsx**
   - h1 (lines 367, 872) - need `.heading-xl`
   - h2 (line 797) - needs `.heading-l`
   - h3 (lines 814, 827) - need `.heading-m`

4. **LeadGeneration.tsx**
   - h1 (line 767) - needs `.heading-xl`
   - h2 (lines 688, 1681, 1791) - need `.heading-l`

5. **LeadDatabase.tsx**
   - h1 (line 469) - needs `.heading-xl`
   - h2 (lines 1031, 1299, 1733) - need `.heading-l`
   - h3 (multiple with `fontSize: '12px'`) - need `.heading-m` or `.label-xs` depending on context

## Typography Token Reference

| Token | Size | Weight | Usage | Class |
|-------|------|--------|-------|-------|
| **Heading / XL** | 26px | Semi-Bold (600) | Main page titles | `.heading-xl` or `<h1>` |
| **Heading / L** | 22px | Semi-Bold (600) | Major section titles | `.heading-l` or `<h2>` |
| **Heading / M** | 18px | Semi-Bold (600) | Component titles | `.heading-m` or `<h3-h6>` |
| **Text / L** | 16px | Semi-Bold (600) | Long-form content | `.text-l` |
| **Text / M** | 14px | Regular (400) | Default body text | `.text-m` or `<p>` |
| **Text / S** | 12px | Regular (400) | Secondary info | `.text-s` |
| **Label / XS** | 11px | Medium (500) | UI labels/metadata | `.label-xs` or `<label>` |

## How Defaults Work

- **h1** tags automatically get Heading / XL (26px) unless you add `.heading-l` or `.heading-m`
- **h2** tags automatically get Heading / L (22px) unless you add `.heading-xl` or `.heading-m`
- **h3-h6** tags automatically get Heading / M (18px) unless you add `.heading-xl` or `.heading-l`
- **p** tags automatically get Text / M (14px) unless you add `.text-l`, `.text-s`, or `.label-xs`
- **label** tags automatically get Label / XS (11px) unless you add other classes

## Next Steps

1. Update all dashboard components to remove inline fontSize styles
2. Replace with appropriate typography classes
3. Test across all pages to ensure consistency
