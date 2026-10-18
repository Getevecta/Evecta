# Grid Search Cost Documentation

## What is Grid Search?

Grid search divides the search area into a matrix of points and fires a Nearby Search from each point. This allows discovering businesses beyond Google's 60-result single-point limit.

**Grid search is OFF by default** because it multiplies API cost by 10–100x.
Enable only when you need 100+ leads from a fresh DB in a single search.

---

## Grid Search Parameters (from `lead_generation_service.py`)

```python
GRID_CONFIG = {
    "dense_urban": {
        "grid_spacing": 3.0 km,   # distance between grid points
        "radius":       800 m,    # Nearby Search radius per grid point
    },
    "medium_urban": {
        "grid_spacing": 3.5 km,
        "radius":       1000 m,
    },
    "suburban": {
        "grid_spacing": 4.0 km,
        "radius":       1200 m,
    }
}

MAX_PAGES        = 3          # Nearby Search pages per grid point
search_radius_km = 5.0 km    # default; controls how many grid points are generated
```

---

## Grid Points Formula

```
lat_steps       = int(search_radius_km / grid_spacing_km) + 1
total_generated = (lat_steps × 2 + 1)²    ← rectangular grid before filter
after_filter    ≈ π × (search_radius_km / grid_spacing_km)²  ← inside circle
```

### Grid Points by Config and Search Radius

| Config | Spacing | Search Radius | lat_steps | Total Generated | **After Haversine Filter** |
|---|---|---|---|---|---|
| dense_urban | 3 km | 5 km | 2 | 5×5 = 25 | **~9 points** |
| dense_urban | 3 km | 10 km | 4 | 9×9 = 81 | **~35 points** |
| dense_urban | 3 km | 15 km | 6 | 13×13 = 169 | **~79 points** |
| dense_urban | 3 km | 20 km | 7 | 15×15 = 225 | **~140 points** |
| medium_urban | 3.5 km | 5 km | 2 | 5×5 = 25 | **~7 points** |
| medium_urban | 3.5 km | 10 km | 3 | 7×7 = 49 | **~20 points** |
| medium_urban | 3.5 km | 15 km | 5 | 11×11 = 121 | **~49 points** |
| suburban | 4 km | 5 km | 2 | 5×5 = 25 | **~5 points** |
| suburban | 4 km | 10 km | 3 | 7×7 = 49 | **~16 points** |
| suburban | 4 km | 15 km | 4 | 9×9 = 81 | **~36 points** |

---

## Nearby Search Calls = Grid Points × Pages

Each grid point fires up to `MAX_PAGES = 3` Nearby Search pages (20 results per page = 60 max per point).

```
Nearby Search calls = grid_points × pages_per_point
                    = grid_points × 1  (sparse industry, 1 page each)
                    = grid_points × 3  (dense industry, 3 pages each)
```

| Scenario | Grid Points | Pages | Nearby Calls | Nearby Cost |
|---|---|---|---|---|
| dense_urban, 5km, sparse | 9 | 1 | 9 | $0.29 |
| dense_urban, 5km, dense | 9 | 3 | **27** | **$0.86** |
| dense_urban, 10km, sparse | 35 | 1 | 35 | $1.12 |
| dense_urban, 10km, dense | 35 | 3 | **105** | **$3.36** |
| dense_urban, 15km, sparse | 79 | 1 | 79 | $2.53 |
| dense_urban, 15km, dense | 79 | 3 | **237** | **$7.58** |
| dense_urban, 20km, dense | 140 | 3 | **420** | **$13.44** |

---

## Part 1 — 100 Leads with Grid Search ON

### Why use grid search for 100 leads?

Without grid search, Google Nearby Search (single point, 5km) returns **max 60 results**.
To get **100 leads from API in a single search with empty DB**, grid search is required.

> **Alternative:** Keep grid OFF. After 2–3 user searches for the same query, the DB accumulates 100+ leads from combined API pulls — entirely free after that.

---

### Cost: 100 Leads, Grid ON, 5km Radius

Place Details is called for **every result** from Nearby Search, up to 100.

| Config | Grid Points | Nearby Calls | Nearby Cost | Place Details (100) | Geocode | **Google Total** |
|---|---|---|---|---|---|---|
| dense_urban | 9 | 9–27 | $0.29–$0.86 | $1.70 | $0.005 | **$2.00–$2.57** |
| medium_urban | 7 | 7–21 | $0.22–$0.67 | $1.70 | $0.005 | **$1.93–$2.38** |
| suburban | 5 | 5–15 | $0.16–$0.48 | $1.70 | $0.005 | **$1.87–$2.19** |

### Including Hunter.io Enrichment (100 leads)

Hunter.io is called as a fallback when HTTP scraping fails.
Estimate: 100 leads × 70% have website × 40% fail scraping = **~28 Hunter calls**

| Hunter Plan | Cost per Call | 28 Calls Cost | Google (dense_urban worst) | **Total per Search** |
|---|---|---|---|---|
| Free (25/mo) | — | ~$0.00 (uses free tier) | $2.57 | **~$2.57** |
| Starter ($34/mo) | $0.068 | $1.90 | $2.57 | **$4.47** |
| Growth ($104/mo) | $0.042 | $1.17 | $2.57 | **$3.74** |
| Business ($349/mo) | $0.035 | $0.98 | $2.57 | **$3.55** |

### Grid ON vs Grid OFF — 100 Leads Comparison

| Mode | API Leads | Nearby Calls | Details Calls | Google Cost | Hunter | Total |
|---|---|---|---|---|---|---|
| **Grid OFF** (default) | 60 from API + 40 from DB | 3 | 60 | $1.121 | $1.017 (17 calls) | **$2.14** |
| **Grid ON** dense_urban 5km | up to 100 from API | 9–27 | 100 | $2.00–$2.57 | $1.17 (28 calls) | **$3.17–$3.74** |
| **Grid ON** medium_urban 5km | up to 100 from API | 7–21 | 100 | $1.93–$2.38 | $1.17 | **$3.10–$3.55** |
| **Grid ON** suburban 5km | up to 100 from API | 5–15 | 100 | $1.87–$2.19 | $1.17 | **$3.04–$3.36** |

**Conclusion for 100 leads:** Grid ON costs **$1–$1.60 more** than grid OFF per search, but delivers all 100 leads from Google directly (no DB dependency). If DB is empty and you need 100 leads instantly, grid ON is the only option.

---

## Part 2 — 500+ Leads with Grid Search ON

### Why you NEED grid search for 500 leads

Without grid search:
- Google single-point Nearby Search: **max 60 results**
- Getting 500 leads requires the DB to have 440+ stored from previous searches
- With a fresh DB, only grid search can deliver 500 leads in one search

### How many grid points needed for 500 leads?

Candidate results per grid point = up to 60 (3 pages × 20)
After deduplication across overlapping grid points: estimate **30–40 unique per point**

```
Points needed for 500 leads ≈ 500 / 35 unique_per_point ≈ 14–17 grid points minimum
Search radius needed ≈ 10 km (dense_urban gives ~35 points at 10km)
```

---

### Cost: 500 Leads, Grid ON

#### dense_urban (3km spacing)

| Search Radius | Grid Points | Nearby Calls | Nearby Cost | Place Details (500) | Geocode | **Google Total** |
|---|---|---|---|---|---|---|
| 5 km | 9 | 9–27 | $0.29–$0.86 | $8.50 | $0.005 | **$8.80–$9.37** |
| 10 km | 35 | 35–105 | $1.12–$3.36 | $8.50 | $0.005 | **$9.63–$11.87** |
| 15 km | 79 | 79–237 | $2.53–$7.58 | $8.50 | $0.005 | **$11.04–$16.09** |
| 20 km | 140 | 140–420 | $4.48–$13.44 | $8.50 | $0.005 | **$12.99–$21.95** |

#### medium_urban (3.5km spacing)

| Search Radius | Grid Points | Nearby Calls | Nearby Cost | Place Details (500) | **Google Total** |
|---|---|---|---|---|---|
| 10 km | 20 | 20–60 | $0.64–$1.92 | $8.50 | **$9.15–$10.43** |
| 15 km | 49 | 49–147 | $1.57–$4.70 | $8.50 | **$10.08–$13.21** |
| 20 km | 87 | 87–261 | $2.78–$8.35 | $8.50 | **$11.29–$16.86** |

#### suburban (4km spacing)

| Search Radius | Grid Points | Nearby Calls | Nearby Cost | Place Details (500) | **Google Total** |
|---|---|---|---|---|---|
| 10 km | 16 | 16–48 | $0.51–$1.54 | $8.50 | **$9.02–$10.05** |
| 15 km | 36 | 36–108 | $1.15–$3.46 | $8.50 | **$9.66–$11.97** |
| 20 km | 64 | 64–192 | $2.05–$6.14 | $8.50 | **$10.56–$14.65** |

---

### 500 Leads: Including Hunter.io Enrichment

500 leads × 70% have website × 40% fail scraping = **~140 Hunter calls**

| Hunter Plan | 140 Calls Cost | Google (dense_urban, 10km, worst) | **Total per Search** |
|---|---|---|---|
| Starter ($34/mo) | $9.52 | $11.87 | **$21.39** |
| Growth ($104/mo) | $5.88 | $11.87 | **$17.75** |
| Business ($349/mo) | $4.90 | $11.87 | **$16.77** |

---

## Full Comparison: Grid OFF vs Grid ON by Lead Count

### Google Places API Cost Only (excluding Hunter.io, excluding geocode)

| Lead Target | Grid OFF | Grid ON (dense, 5km) | Grid ON (dense, 10km) | Grid ON (dense, 15km) |
|---|---|---|---|---|
| 20 leads | $0.37 | — | — | — |
| 60 leads | $1.12 | — | — | — |
| 100 leads | $1.12 (60 API+40 DB) | **$2.00–$2.57** | $2.57 | $2.57 |
| 200 leads | $1.12 (60 API+140 DB) | ❌ not enough points | **$3.26–$5.06** | $5.06 |
| 300 leads | $1.12 (60 API+240 DB) | ❌ not enough points | **$4.60–$6.81** | $6.81 |
| 500 leads | $1.12 (60 API+440 DB) | ❌ not enough points | **$9.63–$11.87** | **$11.04–$16.09** |

> **Grid OFF rows above 60**: The API still only returns 60 leads. Remaining leads come from DB (previous sessions). If DB is empty, you cannot get more than 60 leads with grid OFF.

---

### Total Cost per Search (Google + Hunter, Growth plan)

| Lead Target | Grid OFF (DB has leads) | Grid ON dense 5km | Grid ON dense 10km | Grid ON dense 15km |
|---|---|---|---|---|
| 60 | **$2.14** | same | same | same |
| 100 | **$2.14** (DB fills 40) | $3.74 | $3.74 | $3.74 |
| 200 | **$2.14** (DB fills 140) | ❌ | $5.88 | $5.88–$6.55 |
| 300 | **$2.14** (DB fills 240) | ❌ | $7.65 | $7.65–$9.33 |
| 500 | **$2.14** (DB fills 440) | ❌ | $17.75 | $17.75–$21.97 |

---

## Cost Per Lead (Marginal Cost)

| Lead Count | Mode | Total Google Cost | Cost per Lead | Hunter per Lead | **Total per Lead** |
|---|---|---|---|---|---|
| 60 | Grid OFF | $1.12 | $0.019 | $0.019 | **$0.038** |
| 100 | Grid ON dense 5km | $2.29 | $0.023 | $0.012 | **$0.035** |
| 100 | Grid ON dense 5km (worst) | $2.57 | $0.026 | $0.012 | **$0.038** |
| 200 | Grid ON dense 10km | $3.27 | $0.016 | $0.012 | **$0.028** |
| 500 | Grid ON dense 10km | $11.87 | $0.024 | $0.012 | **$0.036** |
| 500 | Grid ON dense 15km | $16.09 | $0.032 | $0.012 | **$0.044** |

> Marginal cost per lead stays roughly **$0.035–$0.044** regardless of batch size.
> The main cost driver for large batches is **Nearby Search** (grid points × pages), not Place Details.

---

## Scaling: Multiple Users with Grid ON

### 10 Users, Unique Queries, Grid ON, 100 leads each

| Config | Cost per Search | 10 Users Total |
|---|---|---|
| dense_urban 5km | $3.74 | **$37.40** |
| medium_urban 5km | $3.36 | **$33.60** |
| suburban 5km | $3.20 | **$32.00** |

### 10 Users, Unique Queries, Grid ON, 500 leads each

| Config | Cost per Search | 10 Users Total |
|---|---|---|
| dense_urban 10km | $17.75 | **$177.50** |
| dense_urban 15km | $21.97 | **$219.70** |
| medium_urban 15km | $19.09 | **$190.90** |

### 100 Users, Unique Queries, Grid ON

| Lead Limit | Config | Cost per Search | 100 Users | Per Hour (10 searches max) |
|---|---|---|---|---|
| 100 | dense 5km | $3.74 | $374 | **$3,740/hr** |
| 200 | dense 10km | $9.80 | $980 | **$9,800/hr** |
| 500 | dense 10km | $17.75 | $1,775 | **$17,750/hr** |
| 500 | dense 15km | $21.97 | $2,197 | **$21,970/hr** |

> ⚠️ These are worst-case numbers (all users, all new queries, rate limit hit, grid ON).
> With caching and DB reuse, real costs are 80–95% lower after the first week.

---

## Recommendations by Use Case

| Use Case | LEADS_LIMIT | Grid Search | Search Radius | Expected Cost/Search |
|---|---|---|---|---|
| Standard product (new DB) | 100 | OFF | 5km | **$2.14** (60 from API, 40 from DB over time) |
| Standard product (mature DB) | 100 | OFF | 5km | **$0.00** (DB has all leads) |
| Need 100 leads instantly (empty DB) | 100 | ON dense_urban | 5km | **$3.74** |
| Need 200 leads (some DB data) | 200 | OFF | 5km | **$2.14** (60 from API, 140 from DB) |
| Need 200 leads (empty DB) | 200 | ON dense_urban | 10km | **$9.80** |
| Need 500 leads (empty DB) | 500 | ON dense_urban | 10km | **$17.75** |
| Need 500 leads (some DB data) | 500 | ON dense_urban | 5km | Only 9 grid points → ~250 unique max |
| Need 500 leads (empty DB, wide area) | 500 | ON dense_urban | 15km | **$21.97** |
| Repeat search any size | Any | Any | Any | **$0.00** (Redis cache) |

---

## Time Cost of Grid Search (Latency Impact)

Grid search is sequential — each grid point waits for results before the next (with 0.5s delay between points).

```python
# from lead_generation_service.py
if idx < len(grid_points) - 1:
    await asyncio.sleep(0.5)    # 0.5s delay between grid points

# page token delay
PAGE_DELAY = 2.2               # 2.2s between pages within a grid point
```

| Grid Points | Pages/Point | Delay/Point | Total Latency |
|---|---|---|---|
| 9 (5km dense) | 1 | 0.5s | ~4.5s |
| 9 (5km dense) | 3 | 0.5s + 2×2.2s | ~49s |
| 35 (10km dense) | 3 | 0.5s + 2×2.2s | ~192s (~3.2 min) |
| 79 (15km dense) | 3 | 0.5s + 2×2.2s | ~432s (~7.2 min) |
| 140 (20km dense) | 3 | 0.5s + 2×2.2s | ~767s (~12.8 min) |

> ⚠️ Large grid searches are **very slow**. For 500 leads with 15km radius: ~7 minutes response time.
> Consider running grid search as a background task and returning to the user when complete.

---

## Summary Table

| Scenario | Leads from API | Nearby Calls | Place Details | Hunter Calls | **Total Cost** | **Latency** |
|---|---|---|---|---|---|---|
| Grid OFF, 60 leads | 60 | 3 | 60 | 17 | **$2.14** | ~7s |
| Grid ON dense, 5km, 100 leads | 100 | 9–27 | 100 | 28 | **$3.17–$3.74** | ~15–49s |
| Grid ON dense, 10km, 200 leads | 200 | 35–105 | 200 | 56 | **$7.80–$12.50** | ~90–192s |
| Grid ON dense, 10km, 500 leads | 500 | 35–105 | 500 | 140 | **$17.75–$22.43** | ~90–192s |
| Grid ON dense, 15km, 500 leads | 500 | 79–237 | 500 | 140 | **$18.96–$24.18** | ~432s |
| Any, Redis cache warm | 0 (from cache) | 0 | 0 | 0 | **$0.00** | <100ms |
| Any, full DB | 0 (from DB) | 0 | 0 | 0 | **$0.00** | ~200ms |
