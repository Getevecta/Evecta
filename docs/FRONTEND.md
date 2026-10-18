# Frontend architecture

## Stack

| Layer | Choice |
|-------|--------|
| Build | [Vite](https://vitejs.dev/) 7.x (`Frontend/vite.config.ts`) |
| UI | React 18, TypeScript |
| Routing | `react-router-dom` v7 (`BrowserRouter`) |
| Styling | Tailwind CSS 3.x + global CSS (`App.css`, feature CSS, `design-system.css`) |
| HTTP | Central `apiService` in `Frontend/src/shared/services/api.ts` |
| Notifications | `sonner` toasts |
| Dashboard UI | Mix of [Radix UI](https://www.radix-ui.com/) primitives, [MUI](https://mui.com/) (charts), custom components under `features/dashboard/components/ui/` |
| 3D / motion | Three.js + `@react-three/fiber`, GSAP, Framer Motion (marketing pages) |

**Path alias:** `@/` → `Frontend/src/` (see `vite.config.ts`).

## Entry and providers

- **`index.tsx`** mounts the React root.
- **`App.tsx`** wraps the tree with:
  - `AuthProvider` — session and user (`shared/contexts/AuthContext.tsx`)
  - `PopupProvider` — shared modal/popup state
  - `Router` + `ScrollToTop` (scroll reset on path change)
  - `Toaster` (Sonner)
  - Offline banner via `NoInternetConnection`

## Routing model

Routing is **not** a single flat `<Routes>` tree. `AppContent` inspects `location.pathname` and renders **different layouts** for different sections:

| Area | Behavior |
|------|----------|
| `/` | Standalone home; `RedirectIfAuthenticated` sends logged-in users to `/dashboard` (unless waitlist logic applies). |
| `/blog`, `/blog/:id` | Standalone blog (no app chrome). |
| `/privacy-policy`, `/terms-of-service` | Standalone legal pages. |
| `/waitlist` | Standalone waitlist. |
| `/contact`, `/about`, `/about_us` | Standalone pages. |
| `/404`, `/no-internet` | Standalone utility routes. |
| `/auth`, `/otp-verification`, `/forgot-password`, … `/auth/google/*` | Standalone auth flows; often wrapped in `PublicRoute`. |
| `/billing/success`, `/billing/cancel` | Stripe return URLs; redirect into dashboard billing with state. |
| `/dashboard/*` | Protected: `ProtectedRoute` → `DashboardMobileRestrictor` → `DashboardLayout` → nested `Dashboard`. |
| Everything else (e.g. `/chat`) | Default shell: mobile menu toggle, `Sidebar`, `PageWrapper`, main content. Unknown paths redirect to `/404`. |

**Dashboard URLs** are interpreted inside `features/dashboard/Dashboard.tsx` via `pathToViewMap` / `viewToPathMap` (e.g. `/dashboard/generate`, `/dashboard/leads`, `/dashboard/campaigns`, `/dashboard/inbox`, `/dashboard/billing`). The router entry redirects `/dashboard` → `/dashboard/generate`.

App routes are defined in:

```371:387:Frontend/src/App.tsx
  if (isDashboard) {
    return (
      <Routes>
        <Route path="/dashboard/*" element={
          <ProtectedRoute>
            <DashboardMobileRestrictor>
              <DashboardLayout />
            </DashboardMobileRestrictor>
          </ProtectedRoute>
        }>
          <Route index element={<Navigate to="/dashboard/generate" replace />} />
          <Route path="campaigns/:campaignId/edit" element={<Dashboard />} />
          <Route path="*" element={<Dashboard />} />
        </Route>
      </Routes>
    );
  }
```

## Feature folders (`src/features/`)

Features are grouped by product area:

- **`homepage/`**, **`about/`**, **`blog/`**, **`contact/`**, **`waitlist/`** — Marketing and content.
- **`auth/`** — Login, signup, OTP, Google callback, password reset.
- **`chat/`** — Guest lead discovery chat (public `/chat`).
- **`dashboard/`** — Main product UI: sidebar, lead generation, campaigns, inbox, email accounts, billing, profile, etc.
- **`privacy/`**, **`404/`**, **`noInternet/`** — Static or utility screens.

Shared building blocks live under **`shared/`**: components (`ProtectedRoute`, `Sidebar`, `PageWrapper`, …), contexts, hooks, and **`shared/services/api.ts`**.

## Authentication

- **Access token** is stored and sent by `apiService` (see `request()` implementation in `api.ts`): Bearer auth for API calls.
- **Refresh token** is expected via **HttpOnly cookie** on the backend (`credentials: 'include'` on relevant calls) — see backend auth for cookie names and paths.
- On load, `AuthProvider` calls `getCurrentUser()` if a token exists; on expiry it attempts `refreshToken()` then refetches the user.
- **Waitlist**: `checkWaitlistStatus()` and redirects to `/waitlist` when the account is waitlisted or user limit is reached (dashboard and `RedirectIfAuthenticated`).

## API client

- **Base URL** is resolved in `Frontend/src/config/api.ts`:
  - Production host `evecta.io` → `https://evecta.io/api`
  - Staging → `https://staging.evecta.io/api`
  - Localhost → `http://localhost:8000` (no `/api` segment; matches uvicorn default)
  - Override: `VITE_API_BASE_URL`, `localStorage('api_base_url')`, or `?api=` query param (see file for HTTPS rules).

- **`apiService`** centralizes REST calls: auth, chat, leads, campaigns, inbox, billing, mailboxes, etc. Types for payloads live in the same file.

- **Timeouts and errors**: Chat/lead endpoints use tailored timeout messaging; 402 responses can set `insufficientCredits` for credit exhaustion flows.

## Build and preview

```bash
cd Frontend
npm install
npm run dev      # Vite dev server, port 5173
npm run build    # Output: build/ (see vite.config.ts)
npm run preview  # Serve production build locally
```

The build runs `scripts/updatePrivacyDates.js` before `vite build` (keeps legal pages’ dates in sync).

## Related reading

- `Frontend/deployment/README-CACHE-FIX.md` — caching and hashed assets in production.
