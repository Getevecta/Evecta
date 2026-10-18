# Master Typography Hierarchy - Implementation Mapping

## Typography Tokens and Their Usage

### Heading / XL (26px, Semi-Bold, -0.02em)
**Usage:** Main page titles and top-level screen headings
**Examples:**
- Main hero heading on homepage
- Page title (h1) on each page
- Top-level screen headings in dashboard

**CSS Class:** `.heading-xl` or use `<h1>` tag

---

### Heading / L (22px, Semi-Bold, -0.01em)
**Usage:** Major section titles within a page
**Examples:**
- "Recent Activity" section header
- "Features" section header
- "How It Works" section header
- Major content blocks

**CSS Class:** `.heading-l` or use `<h2>` tag

---

### Heading / M (18px, Semi-Bold, -0.01em)
**Usage:** Component-level titles
**Examples:**
- Card titles
- Feature card titles
- List headers
- Modal titles
- Sub-sections within a section
- Notification titles

**CSS Class:** `.heading-m` or use `<h3>`, `<h4>`, `<h5>`, `<h6>` tags

---

### Text / L (16px, Semi-Bold, 0)
**Usage:** Long-form reading content
**Examples:**
- Descriptions
- Help text blocks
- Onboarding explanations
- Long-form content
- Primary paragraph text
- Help or guidance text

**CSS Class:** `.text-l`

---

### Text / M (14px, Regular, 0)
**Usage:** Default body text for most UI elements
**Examples:**
- Table rows
- Sidebar text
- Forms helper text
- General UI content
- Standard body text
- Table content
- Form field descriptions
- Card descriptions

**CSS Class:** `.text-m` or use `<p>` tag (default)

---

### Text / S (12px, Regular, 0)
**Usage:** Secondary or supporting information
**Examples:**
- Timestamps
- Secondary notes
- Inline hints
- Small paragraphs

**CSS Class:** `.text-s`

---

### Label / XS (11px, Medium, 0.03em)
**Usage:** UI labels and metadata (NOT for reading content)
**Examples:**
- Form labels
- Tags
- Badges
- Status labels
- Table column headers
- Light information

**CSS Class:** `.label-xs` or use `<label>` tag

---

## Page-by-Page Implementation

### HomePage.tsx
- **h1** (line 440): Main hero heading → `.heading-xl`
- **h2** (line 718, 772, 870, etc.): Section headers → `.heading-l`
- **h3** (line 562, 794, 826, etc.): Card/component titles → `.heading-m`
- **h4** (line 1464, 1486, 1503): Footer section titles → `.heading-m`
- **p** (line 447): Hero description → `.text-l`
- **Badges** (line 436, etc.): Trust badges → `.label-xs`
- **Paragraphs**: Default body text → `.text-m`

### Dashboard Pages
- **Page titles**: `.heading-xl`
- **Section headers**: `.heading-l`
- **Card titles**: `.heading-m`
- **Table headers**: `.label-xs`
- **Table content**: `.text-m`
- **Form labels**: `.label-xs`
- **Form descriptions**: `.text-m`
- **Timestamps**: `.text-s`
