# Lead Limit Cost Documentation

## How Lead Count Drives API Cost

Every lead returned to the user maps to exactly **one Place Details API call** ($0.017).
Every lead with a website that fails HTTP scraping triggers exactly **one Hunter.io call** (~$0.019 effective).

This makes lead count the **primary cost variable** — increasing `LEADS_LIMIT` directly increases cost.

---

## Code Constants Reference

| Constant | Location | Current Value | Effect on Cost |
|---|---|---|---|
| `LEADS_LIMIT` | `chat_service.py` | **100** | Max leads returned per search |
| `MAX_PAGES` | `lead_generation_service.py` | **3** | Max Nearby Search pages (20 results/page) |
| `radius` | `lead_generation_service.py` | **5000 m** | Search radius for Nearby Search |
| `use_grid_search` | `lead_generation_service.py` | **False** | OFF = max 60 from Google; ON = 100+ possible |
| `google_maps` semaphore | `enrichment_semaphores.py` | **25** | Max concurrent Place Details calls |
| `hunter` semaphore | `enrichment_semaphores.py` | **20** | Max concurrent Hunter.io calls |

---

## Hard Ceiling: Google Nearby Search Limit

Google Nearby Search returns **max 20 results per page**, max **3 pages** = **60 results maximum** from a single-point search.

```
Grid Search OFF (default):
  ┌─────────────────────────────────────────────┐
  │  Nearby Search Page 1 → up to 20 results    │
  │  Nearby Search Page 2 → up to 20 results    │  Max = 60 results
  │  Nearby Search Page 3 → up to 20 results    │
  └─────────────────────────────────────────────┘

Grid Search ON (expensive):
  ┌─────────────────────────────────────────────┐
  │  Grid Point 1: 3 pages = up to 60 results   │
  │  Grid Point 2: 3 pages = up to 60 results   │  15 grid points
  │  ...                                         │  = up to 900 candidates
  │  Grid Point 15: 3 pages = up to 60 results  │  (after dedup: 100–500 unique)
  └─────────────────────────────────────────────┘
```

**Implication:** Setting `LEADS_LIMIT` above 60 without enabling grid search has no extra API cost — Google simply won't return more than 60 from a single point. The DB fills the rest from previous sessions.

---

## Place Details API Cost by Lead Count

Place Details is called once per result from Nearby Search.
Cost = `N leads × $0.017`

| Leads from Google API | Nearby Search Calls | Place Details Calls | Place Details Cost | Nearby Cost | **Total Google Cost** |
|---|---|---|---|---|---|
| 10 | 1 | 10 | $0.170 | $0.032 | **$0.207** |
| 20 | 1 | 20 | $0.340 | $0.032 | **$0.377** |
| 30 | 2 | 30 | $0.510 | $0.064 | **$0.579** |
| 40 | 2 | 40 | $0.680 | $0.064 | **$0.749** |
| 50 | 3 | 50 | $0.850 | $0.096 | **$0.951** |
| 60 (max, grid OFF) | 3 | 60 | $1.020 | $0.096 | **$1.121** |

> Add $0.005 (geocoding) to each row for the first search of a city.
> Geocoding is cached 7 days — subsequent searches of the same city = $0 geocoding.

---

## Hunter.io Cost by Lead Count (Background Enrichment)

Hunter.io is called **only as a fallback** when HTTP website scraping fails.

### How Many Leads Need Hunter

| Total Leads | Have Website (~70%) | HTTP Scrape Succeeds (~60%) | Need Hunter (~40% of website leads) | Hunter Calls |
|---|---|---|---|---|
| 10 | 7 | 4 | 3 | 3 |
| 20 | 14 | 8 | 6 | 6 |
| 40 | 28 | 17 | 11 | 11 |
| 60 | 42 | 25 | 17 | 17 |
| 100 | 70 | 42 | 28 | 28 |
| 200 | 140 | 84 | 56 | 56 |
| 500 | 350 | 210 | 140 | 140 |

> These are realistic estimates. Actual numbers vary by industry and region.
> Leads without a website are skipped entirely — no Hunter call, no cost.

### Hunter Cost by Plan

| Leads | Hunter Calls | Free (25/mo) | Starter $34/mo (500) | Growth $104/mo (2,500) | Business $349/mo (10,000) |
|---|---|---|---|---|---|
| 10 | 3 | $0.00 | $0.20 | $0.13 | $0.11 |
| 20 | 6 | $0.00 | $0.41 | $0.25 | $0.21 |
| 40 | 11 | $0.00 | $0.75 | $0.46 | $0.39 |
| 60 | 17 | $0.00 | $1.16 | $0.71 | $0.60 |
| 100 | 28 | — | $1.90 | $1.17 | $0.98 |
| 200 | 56 | — | — | $2.34 | $1.96 |
| 500 | 140 | — | — | $5.88 | $4.90 |

---

## Full Cost Per Search by Lead Limit

Combines: Geocoding + Nearby Search + Place Details + Hunter.io (Growth plan)

### Grid Search OFF (default — max 60 leads from Google, DB fills rest)

| `LEADS_LIMIT` | Google API Leads | Geocode | Nearby Search | Place Details | Hunter.io | **Total Per Search** |
|---|---|---|---|---|---|---|
| 10 | 10 | $0.005 | $0.032 | $0.170 | $0.13 | **$0.34** |
| 20 | 20 | $0.005 | $0.032 | $0.340 | $0.25 | **$0.63** |
| 50 | 50 | $0.005 | $0.096 | $0.850 | $0.63 | **$1.58** |
| 100 | 60 (max) | $0.005 | $0.096 | $1.020 | $0.71 | **$1.83** |
| 200 | 60 (max) | $0.005 | $0.096 | $1.020 | $0.71 | **$1.83** |
| 500 | 60 (max) | $0.005 | $0.096 | $1.020 | $0.71 | **$1.83** |

> Setting `LEADS_LIMIT` above 60 with grid search OFF gives no extra API cost.
> The additional leads (61–100+) come from the DB (previous sessions) at $0.00.

### Grid Search ON (100–500 leads from Google, very expensive)

| `LEADS_LIMIT` | Grid Points | Nearby Calls | Place Details | Nearby Cost | Details Cost | Hunter.io | **Total Per Search** |
|---|---|---|---|---|---|---|---|
| 100 | ~15 | 45 | 100 | $1.440 | $1.700 | $1.17 | **$4.32** |
| 200 | ~15 | 45 | 200 | $1.440 | $3.400 | $2.34 | **$7.19** |
| 300 | ~15 | 45 | 300 | $1.440 | $5.100 | $3.51 | **$10.06** |
| 500 | ~25 | 75 | 500 | $2.400 | $8.500 | $5.88 | **$16.79** |

> Grid search generates ~15 grid points for a 5km radius with 3km spacing (dense_urban config).
> Each grid point fires up to 3 Nearby Search pages = 45 total Nearby Search calls.
> **Grid search is extremely expensive and disabled by default.**

---

## Cost Comparison: Grid ON vs Grid OFF

| Lead Target | Grid OFF Cost | Grid ON Cost | Extra Cost for Grid | Worth It? |
|---|---|---|---|---|
| 60 leads | $1.83 | $1.83 | $0 (both get 60) | N/A |
| 100 leads | $1.83 (60 from API + 40 from DB) | $4.32 | +$2.49 | ❌ Use DB instead |
| 200 leads | $1.83 (60 from API) | $7.19 | +$5.36 | ❌ Very expensive |
| 500 leads | $1.83 (60 from API) | $16.79 | +$14.96 | ❌ Extremely expensive |

**Recommendation:** Keep grid search OFF. Let the DB accumulate leads from multiple sessions instead of paying for grid search.

After 3–5 user searches for the same `(industry, city)`, the DB will have 100–300 leads from combined Google API pulls — all at $0 additional cost.

---

## Cost Per Individual Lead

This is the marginal cost of each additional lead fetched.

| API | Cost per Lead | Condition |
|---|---|---|
| Place Details | **$0.017** | Every lead from Google API |
| Hunter.io (Growth) | **$0.042** | ~28% of leads (website + scrape fails) |
| Effective Hunter per lead | **$0.012** | 28% × $0.042 |
| **Total marginal cost/lead** | **~$0.029** | Place Details + effective Hunter |

### Implication: Each Additional Lead Costs ~$0.029

| Leads | Place Details Total | Hunter Total | **Total Marginal Cost** |
|---|---|---|---|
| 10 | $0.17 | $0.12 | **$0.29** |
| 20 | $0.34 | $0.25 | **$0.59** |
| 50 | $0.85 | $0.63 | **$1.48** |
| 60 (grid OFF max) | $1.02 | $0.71 | **$1.73** |
| 100 (grid ON) | $1.70 | $1.17 | **$2.87** |
| 200 (grid ON) | $3.40 | $2.34 | **$5.74** |
| 500 (grid ON) | $8.50 | $5.88 | **$14.38** |

---

## Scaling: Multiple Users, Multiple Lead Counts

### 10 Users, All Unique Queries (Cold Cache, Grid OFF)

| LEADS_LIMIT | Cost per Search | 10 Users Total | Hunter Included |
|---|---|---|---|
| 20 | $0.63 | $6.30 | ✅ |
| 50 | $1.58 | $15.80 | ✅ |
| 100 | $1.83 | $18.30 | ✅ |
| 200 | $1.83 | $18.30 | ✅ (same — DB fills 61–200) |

### 100 Users, All Unique Queries (Cold Cache)

| LEADS_LIMIT | Grid | Cost per Search | 100 Users Total | Per Hour (10 searches max) |
|---|---|---|---|---|
| 20 | OFF | $0.63 | $63 | $630 |
| 60 | OFF | $1.83 | $183 | $1,830 |
| 100 | OFF | $1.83 | $183 | $1,830 |
| 100 | ON | $4.32 | $432 | $4,320 |
| 200 | ON | $7.19 | $719 | $7,190 |

---

## When to Increase LEADS_LIMIT

| LEADS_LIMIT | Recommended When | API Cost Impact | Grid Needed |
|---|---|---|---|
| 20–30 | Testing / low-traffic | Very low ($0.34–$0.63) | No |
| 50 | Standard usage | Low ($1.58) | No |
| 100 | **Current default — recommended** | Low ($1.83 from API, rest from DB) | No |
| 200 | Power users needing large lists | Medium if DB full; expensive if grid ON | Optional |
| 500+ | Enterprise bulk lead export | High (grid ON required) | Yes |

---

## Summary Decision Table

| Scenario | Best LEADS_LIMIT | Grid Search | Estimated Cost/Search |
|---|---|---|---|
| Startup / testing | 20–50 | OFF | $0.34–$1.58 |
| Standard SaaS product | **100** | **OFF** | **$1.83** |
| Power users (fresh DB) | 100 | OFF | $1.83 (60 from API + 40 from DB over time) |
| High-volume enterprise | 200–500 | ON | $7.19–$16.79 |
| Cold DB + 100 leads instantly | 60 | OFF | $1.83 (max from single-point) |
| Any limit, warm Redis cache | Any | Any | **$0.00** |
| Any limit, full DB | Any | Any | **$0.00** |

---

## Key Takeaway

```
Cost Formula (Cold Cache, Grid OFF):
─────────────────────────────────────────────────────────────
Total = $0.005 (geocode)
      + (pages × $0.032) (nearby search, 1–3 pages)
      + (api_leads × $0.017) (place details)
      + (api_leads × 0.70 × 0.40 × plan_rate) (hunter.io)
─────────────────────────────────────────────────────────────

Where api_leads = min(LEADS_LIMIT, 60)  [grid OFF]
      api_leads = min(LEADS_LIMIT, 500) [grid ON, expensive]

After first search: ALL subsequent searches = $0.00 (Redis cache)
After DB fills up:  Google API = $0.00 (DB serves all leads)
─────────────────────────────────────────────────────────────
```
