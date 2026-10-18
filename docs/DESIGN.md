# Design system and UI conventions

## Marketing site vs dashboard

- **Public / marketing pages** (`features/homepage`, `features/about`, etc.) use global styles, Tailwind utilities, Framer Motion / GSAP / Three.js for hero and motion, and shared typography/spacing tokens.
- **Dashboard** (`features/dashboard/`) uses a dedicated layout (`DashboardLayout.tsx`, `dashboard.css`) and a **shadcn-style** component set under `features/dashboard/components/ui/` (Radix primitives + Tailwind variants via `class-variance-authority`, `tailwind-merge`).

Keep visual changes consistent with the layer you are editing—dashboard tokens may differ slightly from the marketing `design-system.css` usage.

## Tailwind

Configuration: `Frontend/tailwind.config.js`.

Extended theme includes:

- **Font:** `Urbanist` as the primary sans stack.
- **Semantic colors:** `primary` (purple scale), `secondary` (teal/cyan), `accent`, `neutral`, etc.

Content globs include `./index.html` and `./src/**/*` so all TSX is scanned for class names.

## Global design tokens (CSS)

- **`design-system.css`** (referenced from the app stylesheet chain) defines **spacing** and **typography** CSS variables and utility classes used across pages.
- **Spacing** — 8-point–style scale (`--spacing-4`, `--spacing-8`, …) plus utilities like `.mt-8`, `.gap-24`, `.p-16`. See repository root **`SPACING_SYSTEM_GUIDE.md`** for the full list and patterns.
- **Typography** — hierarchy classes such as `.heading-xl`, `.heading-l`, `.text-l`, `.text-m`. See **`TYPOGRAPHY_MAPPING.md`** and **`TYPOGRAPHY_IMPLEMENTATION_GUIDE.md`** for roles (headings vs body) and implementation status.

## Components

- **Lucide React** — icons (`lucide-react`).
- **Charts** — MUI X Charts and Recharts in dashboard/analytics-style views.
- **Toasts** — Sonner (`App.tsx`).

## Dashboard mobile policy

`DashboardMobileRestrictor` blocks the full dashboard on small viewports (product decision—desktop-first CRM workflow). Respect this when adding new dashboard routes.

## Assets and branding

Favicons and PWA manifest live under `Frontend/public/` (see `manifest.json`).

## Files to read before large UI changes

1. `SPACING_SYSTEM_GUIDE.md` — spacing utilities and page-specific classes.
2. `TYPOGRAPHY_MAPPING.md` — type scale and when to use each class.
3. `Frontend/src/features/dashboard/components/ui/*` — button, input, dialog patterns for dashboard.
