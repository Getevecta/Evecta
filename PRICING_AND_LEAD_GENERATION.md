# Evecta — Pricing & Lead Generation Reference

> **⚠️ Credit sections outdated (2026-07-12).** Credits are now split into three
> independent pools — `lead`, `email_gen`, `outreach` — with different costs
> (all charged actions cost 1 credit; enrichment/scraping are free) and different
> per-plan allowances. See `backend/app/core/plans.py` for current numbers and
> `backend/BILLING_API_DOCUMENTATION.md` for the API contract. The Google
> Places / enrichment API-cost sections below are unaffected.

---

## 1. Google Places API Flow

For every search (e.g. "find hotels in Pokhara"), the following APIs are called in order:

| Step | API | Endpoint | Purpose | Cost |
|---|---|---|---|---|
| 1 | Geocoding | `geocode/json` | Convert location name → lat/lng | $0.005 |
| 2 | Nearby Search | `nearbysearch/json` | Find businesses near a point (up to 3 pages) | $0.032/page |
| 3 | Place Details | `place/details/json` | Fetch name, phone, website, address per place | $0.017/place |

- Geocoding result is cached in Redis (no repeat calls)
- Nearby Search paginates up to **3 pages × 20 results = 60 results max per point**
- Place Details is called concurrently for every place found

---

## 2. Search Modes

### Single-Point Search (Grid OFF)
- 1 center point geocoded from city name
- Fixed radius: **5000m**
- Max results: ~60 leads
- Cheap, fast, but misses businesses outside the 5km circle

### Grid Search (Grid ON)
- City area tiled with multiple overlapping search points
- Config used: **dense_urban**
  - Grid spacing: `3.0 km`
  - Per-point radius: `1600m` (200m overlap each side — no coverage gaps)
- Points fire sequentially with 0.5s delay between them
- Results deduplicated by `place_id`
- Loop stops early only if lead limit is hit

---

## 3. Grid Points vs Lead Target

| Target Leads | Mode | Per-point Radius | Grid Points | Nearby Search calls (avg 2.5/pt) | Place Details | Approx API Cost | Cost per Lead |
|---|---|---|---|---|---|---|---|
| 60 | Single point | 5000m | 0 | 3 | 60 | ~$1.12 | ~$0.019 |
| 100 | Grid | 1600m | ~17 | ~43 | 100 | ~$3.07 | ~$0.031 |
| 150 | Grid | 1600m | ~25 | ~63 | 150 | ~$4.56 | ~$0.030 |
| 200 | Grid | 1600m | ~40 | ~100 | 200 | ~$6.61 | ~$0.033 |
| 250 | Grid | 1600m | ~75 | ~188 | 250 | ~$10.27 | ~$0.041 |
| 300 | Grid | 1600m | ~120 | ~300 | 300 | ~$14.70 | ~$0.049 |

> **Note:** Grid points are generated based on `search_radius_km` passed to `get_leads()`.
> The per-point radius (1600m) is always fixed from `dense_urban` config regardless of lead target.

### Early Stop Behaviour
```
The loop breaks only when: len(all_places) >= limit

If the city has fewer businesses than the target:
→ ALL grid points fire
→ You pay for all Nearby Search calls
→ But only pay Place Details for actual leads found
```

---

## 4. Redis Cache

```
1st search  "hotels in pokhara"  →  cold  →  full API cost
2nd search  same query (< 24h)   →  cache →  $0.00
3rd search  same query (< 24h)   →  cache →  $0.00
```

- Cache TTL: **24 hours**
- Cache key: `industry + location`
- Geocoding also cached separately in Redis

---

## 5. Email Enrichment Pipeline

After leads are fetched, enrichment runs in the background:

| Method | Tool | Cost | Credits |
|---|---|---|---|
| Static scraper | httpx | Free | 1 credit/email |
| Playwright scraper | Playwright | Free | 1 credit/email |
| Hunter.io domain search | Hunter API | ~$0.04/call | 2 credits/email |
| Hunter.io company enrichment | Hunter API | ~$0.04/call | 2 credits/email |

**Order:** Static scrape → Hunter fallback (if scrape fails)

---

## 6. Plans

| | **Free** | **Starter** | **Growth** | **Scale** |
|---|---|---|---|---|
| **Price** | $0/mo | $19/mo | $49/mo | $99/mo |
| **Credits/mo** | 100 | 1,000 | 5,000 | 20,000 |
| **Leads per Search** | 20 | 100 | 300 | 500 |
| **Search Mode** | Single point | Single point | Grid | Grid |
| **Grid Points** | 0 | 0 | ~40 | ~120 |
| **Per-point Radius** | 1600m | 1600m | 1600m | 1600m |

---

## 7. Credit Costs Per Action

| Action | Credits | Description |
|---|---|---|
| `lead_found` | 1/lead | Every lead returned from search |
| `email_scraped` | 1/email | Email found via Playwright/static scraper |
| `email_enriched` | 2/email | Email found via Hunter.io |
| `ai_draft` | 10 flat | Per AI campaign draft generated |
| `spam_check` | 2 flat | Per spam check run |
| `email_sent` | 3/lead | Per lead email sent in campaign |

*All plans consume credits the same way — user can do anything until credits hit 0*

---

## 8. How Far Credits Go

*Assumes per search: 100 leads + 40 scraper emails + 10 Hunter emails + 1 AI draft*

| Cost Item | Credits Used |
|---|---|
| 100 leads found | 100 |
| 40 scraper emails | 40 |
| 10 Hunter emails | 20 |
| 1 AI draft | 10 |
| **Total per search** | **170 credits** |

| Plan | Credits | Approx Searches | Approx Leads Total |
|---|---|---|---|
| Free | 100 | ~1 partial search | ~20 leads |
| Starter | 1,000 | ~6 searches | ~600 leads |
| Growth | 5,000 | ~29 searches | ~8,700 leads |
| Scale | 20,000 | ~117 searches | ~58,500 leads |

---

## 9. Your API Cost vs Revenue

*Assumes 60% Redis cache hit rate — repeat searches cost $0*

| Plan | Revenue/mo | Est. API Cost/mo | Margin |
|---|---|---|---|
| Free | $0 | ~$0.35 | — |
| Starter | $19 | ~$6.72 | ~65% |
| Growth | $49 | ~$18.60 | ~62% |
| Scale | $99 | ~$45.00 | ~55% |

---

## 10. GRID_CONFIG (Current Values)

```python
GRID_CONFIG = {
    "dense_urban": {
        "grid_spacing": 3.0,   # km
        "radius": 1600,        # meters — 200m overlap, no gaps
    },
    "medium_urban": {
        "grid_spacing": 3.5,   # km
        "radius": 1800,        # meters — 100m overlap, no gaps
    },
    "suburban": {
        "grid_spacing": 4.0,   # km
        "radius": 2100,        # meters — 200m overlap, no gaps
    }
}
```

### Coverage Rule
```
radius >= grid_spacing / 2 × 1000  →  no gaps
radius >  grid_spacing / 2 × 1000  →  overlap (recommended)

dense_urban:  3.0km / 2 = 1500m minimum → using 1600m ✓
medium_urban: 3.5km / 2 = 1750m minimum → using 1800m ✓
suburban:     4.0km / 2 = 2000m minimum → using 2100m ✓
```
