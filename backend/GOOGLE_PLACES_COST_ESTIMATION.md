# Google Places API — Cost Estimation

## API Pricing Reference (Legacy Places API)

| API Call | Price per Request |
|---|---|
| Geocoding API | $0.005 |
| Nearby Search | $0.032 |
| Place Details (name + phone + website + address) | $0.017 |

---

## System Constants (from code)

| Constant | Value | File |
|---|---|---|
| `MAX_PAGES` | 3 | `lead_generation_service.py` |
| `LEADS_LIMIT` | 100 | `chat_service.py` |
| `radius` (Nearby Search) | 5000 m | `lead_generation_service.py` |
| `use_grid_search` | False (off) | `lead_generation_service.py` |
| `USER_SEARCH_LIMIT` | 10 searches/hr | `redis_context.py` |
| Lead cache TTL | 24 hours | `redis_context.py` |
| Geocode cache TTL | 7 days | `redis_context.py` |
| Country check cache TTL | 7 days | `redis_context.py` |

---

## API Calls Per Single Search (Cold Cache, Empty DB)

### What triggers API calls on one search

```
is_country_name("Mumbai")
  └── Geocoding API × 1 = $0.005   ← cached 7 days after this

get_leads("hotels", "Mumbai")
  ├── Geocoding API × 0            ← already cached above
  ├── Nearby Search × 1–3 pages    ← $0.032 per page
  └── Place Details × N results    ← $0.017 per result
```

### Results vary by industry density

| Industry Type | Examples | Pages | Results | Geocode | Nearby | Details | **Total Cold** |
|---|---|---|---|---|---|---|---|
| Sparse | pen manufacturer, niche factory | 1 | ~15 | $0.005 | $0.032 | $0.255 | **$0.292** |
| Medium | dentists, coffee shops, gyms | 2 | ~35 | $0.005 | $0.064 | $0.595 | **$0.664** |
| Dense | hotels, restaurants, pharmacies | 3 | ~60 | $0.005 | $0.096 | $1.020 | **$1.121** |

> Google Nearby Search returns max 20 results per page, max 3 pages = max 60 results.
> Place Details is called for every result returned.

---

## Cost by Database State

### State A — Empty DB (no previous searches ever)

All leads must come from Google Places API. Full cost applies.

| Industry Type | Google API Cost |
|---|---|
| Sparse (~15 leads) | $0.292 |
| Medium (~35 leads) | $0.664 |
| Dense (~60 leads) | $1.121 |

### State B — Half DB (50 of 100 leads already stored)

`remaining = 50` → `api_fetch_limit = 50` → only 2 pages + 50 Details needed.

| Industry Type | Nearby Pages | Details | Google API Cost | Saving vs Empty |
|---|---|---|---|---|
| Sparse (all 15 in DB already) | 0 | 0 | **$0.00** | 100% |
| Medium (17 in DB, need 33) | 2 | 33 | $0.064 + $0.561 = **$0.625** | 6% |
| Dense (50 in DB, need 50) | 2–3 | 50 | $0.096 + $0.850 = **$0.946** | 16% |

### State C — Full DB (100 leads already stored)

`remaining = 0` → Google API is **never called**.

| Any Industry | Google API Cost |
|---|---|
| Any | **$0.00** |

### State D — Redis Cache Warm (any DB state)

Cache hit returns instantly. **Zero API calls regardless of DB state.**

| Any Industry | Any DB State | Google API Cost |
|---|---|---|
| Any | Any | **$0.00** |

---

## Cost by Number of Users

### Scenario 1 — 1 User, 1 Search

| Cache State | DB State | Cost |
|---|---|---|
| Cold | Empty | $0.292 – $1.121 |
| Cold | Half full | $0.00 – $0.946 |
| Cold | Full | $0.00 |
| Warm (Redis hit) | Any | **$0.00** |

### Scenario 2 — 1 User, Multiple Different Searches Per Hour

Each new unique `(industry, location)` pair = one cold API call.
Rate limit caps at **10 fresh API searches per user per hour**.

| Searches/hr | Sparse only | Dense only | Mixed avg |
|---|---|---|---|
| 1 | $0.292 | $1.121 | $0.707 |
| 5 | $1.46 | $5.61 | $3.54 |
| 10 (rate limit cap) | $2.92 | $11.21 | $7.07 |
| 11+ | **blocked** | **blocked** | **blocked** |

> After the 11th unique search, user gets: "You've reached your search limit for this hour."
> Repeated searches of the same query are always free (Redis cache).

---

### Scenario 3 — 10 Users, All Searching the Same Query

Distributed lock ensures **only 1 API call** fires. The other 9 wait and get the Redis cache.

| Cache State | API Calls | Cost |
|---|---|---|
| Cold | 1 real + 9 from cache | $0.292 – $1.121 |
| Warm | 0 | **$0.00** |

### Scenario 4 — 10 Users, All Different Queries (Cold Cache)

No lock benefit (different keys). Each user pays for their own first search.

| Industry Mix | Cost |
|---|---|
| All sparse | 10 × $0.292 = **$2.92** |
| All dense | 10 × $1.121 = **$11.21** |
| Mixed avg | 10 × $0.707 = **$7.07** |

> Subsequent searches of the same query by any user = $0.00 (Redis cache shared across all users)

---

### Scenario 5 — 100 Users, All Searching the Same Query

Same logic as 10 users. Lock fires 1 API call, 99 get cache.

| Cache State | Cost |
|---|---|
| Cold | $0.292 – $1.121 |
| Warm | **$0.00** |

### Scenario 6 — 100 Users, All Different Queries (Cold Cache, Worst Case)

| Metric | Value |
|---|---|
| Users | 100 |
| Max unique API searches | 100 × 10/hr = **1,000/hr** |
| Cost/hr (all sparse) | 1,000 × $0.292 = **$292/hr** |
| Cost/hr (all dense) | 1,000 × $1.121 = **$1,121/hr** |
| Cost/hr (mixed avg) | 1,000 × $0.707 = **$707/hr** |

> This is the theoretical maximum with every user hitting their rate limit with all-new queries every hour.
> In practice, repeat queries cost $0, so real cost is significantly lower.

---

## Cache Impact — Before vs After Caching

### Single User, Dense Industry, 5 Searches/hr

| | No Cache (old) | With Cache (new) |
|---|---|---|
| Search 1 (new query) | $1.121 | $1.121 |
| Search 2 (same query) | $1.121 | **$0.00** |
| Search 3 (same query) | $1.121 | **$0.00** |
| Search 4 (new query) | $1.121 | $1.121 |
| Search 5 (same query) | $1.121 | **$0.00** |
| **Total** | **$5.61** | **$2.24** |
| **Saving** | — | **60%** |

---

## Before vs After All Optimizations

### Load Test: 20 Users × 5 Seconds (same query, cold cache)

| | Before Optimization | After Optimization |
|---|---|---|
| Grid search | ON (15 grid points) | OFF |
| Nearby Search per search | 15 × 3 = 45 calls | 1–3 calls |
| Place Details per search | 100 calls | 15–60 calls |
| Caching | None | Redis 24h |
| Concurrent dedup | None | Distributed lock |
| Rate limiting | None | 10/hr per user |
| **Cost per search** | **~$3.20** | **$0.29–$1.12** |
| **20 users, same query** | **20 × $3.20 = $64** | **$0.29–$1.12** |
| **Load test total** | **~$600** | **< $2** |

---

## Real-World Monthly Estimate

Assumptions:
- 100 active users
- Each user does 3 unique searches/day (cached repeats are free)
- Mix: 50% sparse, 50% dense → avg $0.707/search

| Period | Unique Searches | Cost |
|---|---|---|
| Per day | 100 × 3 = 300 | 300 × $0.707 = **$212/day** |
| Per month | 300 × 30 = 9,000 | **$6,360/month** |

With typical repeat query rate (40% of searches hit cache):

| Period | API Searches | Cache Hits | Cost |
|---|---|---|---|
| Per day | 180 | 120 | 180 × $0.707 = **$127/day** |
| Per month | 5,400 | 3,600 | **$3,816/month** |

> Cache hit rate grows over time as the DB fills up with previously-searched queries.
> Once DB has leads for a query, `remaining = 0` → Google API is never called again for that query.

---

## Cost Floor — When DB is Populated

As users search, leads accumulate in `lead_log_leads`.
Future searches for the same `(industry, location)` hit the DB first:

| DB Population | Google API Calls | Cost per Search |
|---|---|---|
| 0% (empty) | Full (1 Geocode + 1–3 Nearby + N Details) | $0.292–$1.121 |
| 50% (half leads stored) | Partial (fewer Details needed) | $0.00–$0.946 |
| 100% (all leads stored) | None | **$0.00** |
| Cache warm (any DB state) | None | **$0.00** |

> The system self-optimizes: the more users search, the cheaper each subsequent search becomes.
> After a few weeks, most common `(industry, city)` combinations will be in the DB or cache.

---

## Summary Table

| Scenario | Cost |
|---|---|
| 1 user, 1 sparse search, cold cache, empty DB | $0.292 |
| 1 user, 1 dense search, cold cache, empty DB | $1.121 |
| 1 user, repeat search (warm cache) | **$0.00** |
| 1 user, 10 searches/hr (rate limit max, dense) | $11.21 |
| 10 users, same query, cold cache | $0.292–$1.121 |
| 10 users, 10 different queries, cold | $2.92–$11.21 |
| 100 users, same query, cold cache | $0.292–$1.121 |
| 100 users, all different, rate limit max | $292–$1,121/hr |
| Any search, full DB hit | **$0.00** |
| Any search, Redis cache hit | **$0.00** |
| Original load test (20 users, 5s) | ~$600 |
| Optimized load test (20 users, 5s) | **< $2** |
