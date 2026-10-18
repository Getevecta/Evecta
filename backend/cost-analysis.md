# Evecta — Search Feature Cost Analysis

**Document Type:** Engineering & Business Cost Documentation
**Scope:** Lead generation search feature — all external API and infrastructure costs
**Last Updated:** Based on current codebase state (post-optimization)

---

## 1. System Overview

### What the Feature Does

The search feature allows authenticated users to find business leads by specifying an industry and city (e.g., "hotels in Mumbai"). The system finds matching businesses with their contact details (phone, website, email) and stores them for the user.

### Services Involved

| Layer | Service | Purpose |
|---|---|---|
| AI / NLP | Google Gemini (LLM) | Extract industry/location from user message, spell correction, response generation |
| Geocoding | Google Maps Geocoding API | Convert city name → coordinates |
| Business Discovery | Google Maps Nearby Search API | Find businesses near coordinates |
| Contact Data | Google Maps Place Details API | Get phone number and website per business |
| Email Discovery | Hunter.io (domain-search + company enrichment) | Find email from business website domain |
| Web Scraping | HTTP + Playwright | Scrape emails from business websites directly |
| DNS | MX Record Lookup | Validate email domain before use |
| Cache | Redis | Store leads, geocode, search results (prevents repeat API calls) |
| Database | PostgreSQL | Store enriched leads permanently |

### Data Flow (Per Search Request)

```
User Message: "find hotels in Mumbai"
        │
        ▼
┌─────────────────────────────────┐
│  Gemini LLM (1–5 calls)         │  ← Extract industry/location, spell check,
│  is_general_question            │    generate response
│  run_extraction                 │
│  suggest_correction (×2)        │
│  generate_human_response        │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│  Redis Cache Check              │  ← If HIT → return instantly, $0 API cost
│  is_country_name cache (7d)     │
│  leads cache (24h)              │
│  geocode cache (7d)             │
└────────────┬────────────────────┘
             │ MISS
             ▼
┌─────────────────────────────────┐
│  PostgreSQL DB Check            │  ← Free SQL query
│  fetch_leads_from_db()          │    Returns fully enriched leads
└────────────┬────────────────────┘
             │ insufficient leads
             ▼
┌─────────────────────────────────┐
│  Rate Limit Check               │  ← Max 10 fresh API searches/user/hour
│  check_user_search_rate()       │
└────────────┬────────────────────┘
             │ allowed
             ▼
┌─────────────────────────────────┐
│  Google Maps APIs               │
│  1. Geocoding API (×1)          │  ← Convert "Mumbai" → (19.07, 72.87)
│  2. Nearby Search (×1–3 pages)  │  ← Find up to 60 businesses
│  3. Place Details (×N results)  │  ← Get phone + website per business
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│  Store in Redis (24h TTL)       │  ← All future requests: $0
│  Store in PostgreSQL            │
│  Fire Background Enrichment     │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│  Background: Email Enrichment   │  ← Per lead with a website
│  HTTP scrape → Hunter.io        │
│  (Celery worker)                │
└─────────────────────────────────┘
```

---

## 2. External Services and Pricing

### Google Maps Platform

| API | Endpoint | Cost per Request | Notes |
|---|---|---|---|
| Geocoding | `/maps/api/geocode/json` | **$0.005** | Convert city → lat/lng. Cached 7 days. |
| Nearby Search | `/maps/api/place/nearbysearch/json` | **$0.032** | Returns up to 20 results per page. Max 3 pages. |
| Place Details | `/maps/api/place/details/json` | **$0.017** | Called once per business. Fields: name, phone, website, address. |

> Google provides a **$200/month free credit** (~6,250 Nearby Search calls or ~11,765 Details calls).

### Google Gemini AI (LLM)

| Model | Input (per 1M tokens) | Output (per 1M tokens) | Typical cost/search |
|---|---|---|---|
| Gemini 1.5 Flash | $0.075 | $0.30 | **~$0.0003** |
| Gemini 1.5 Pro | $1.25 | $5.00 | **~$0.005** |

> The system makes 4–5 LLM calls per user message (~2,500 input tokens + ~450 output tokens total).
> Flash is effectively free per search. Pro adds ~$0.005 per search.

### Hunter.io (Email Enrichment — Background Task)

| Plan | Monthly Cost | Searches Included | Effective Cost/Search |
|---|---|---|---|
| Free | $0 | 25/month | — |
| Starter | $34/month | 500 | $0.068 |
| Growth | $104/month | 2,500 | $0.042 |
| Business | $349/month | 10,000 | $0.035 |

> Hunter.io is used as a **fallback only** when HTTP website scraping fails.
> Two endpoints: `/v2/domain-search` and `/v2/companies/find` — each costs 1 credit.
> Leads without a website are skipped entirely (no Hunter call).

### Web Scraping (HTTP + Playwright)

| Method | Cost | Notes |
|---|---|---|
| HTTP scraping | **$0** (compute only) | Tries 6 URLs per domain (3 paths × http/https) |
| Playwright (browser) | **$0** (compute only) | Fallback; higher server CPU/memory cost |
| DNS MX record lookup | **$0** | Standard DNS query |

### Infrastructure

| Service | Estimated Monthly Cost | Purpose |
|---|---|---|
| PostgreSQL (Cloud SQL / RDS) | $30–80/month | Lead storage |
| Redis (Managed) | $15–50/month | Caching + rate limiting |
| Celery Workers | $20–60/month | Background email enrichment |
| Application Server | $20–100/month | FastAPI backend |

> Infrastructure costs are **fixed monthly**, not per-request.

---

## 3. API Calls Per Single Search

### Phase 1 — Chat Message Processing (Every Message)

| Operation | Service | Calls | Always? |
|---|---|---|---|
| `is_general_question()` | Gemini | 1 | ✅ Always |
| `run_extraction()` | Gemini | 1 | ✅ Always |
| `suggest_correction()` for industry | Gemini | 1 | If industry extracted |
| `suggest_correction()` for location | Gemini | 1 | If location extracted |
| `is_country_name()` | Google Geocoding | 1 | If location provided (cached after) |
| `generate_human_response()` | Gemini | 1 | ✅ Always (end of flow) |
| **Subtotal** | | **4–5 Gemini + 0–1 Geocode** | |

### Phase 2 — Lead Fetch (Cold Cache, DB Insufficient)

| Operation | Service | Calls | Condition |
|---|---|---|---|
| DB query `fetch_leads_from_db()` | PostgreSQL | 1 | ✅ Always |
| `get_cached_leads()` | Redis | 1 | ✅ Always |
| `check_user_search_rate()` | Redis | 1 | If cache miss |
| `acquire_search_lock()` | Redis | 1 | If cache miss |
| `geocode_location()` | Google Geocoding | 0–1 | 0 if geocode cached |
| Nearby Search page 1 | Google Nearby | 1 | Cache miss |
| Nearby Search page 2 | Google Nearby | 0–1 | If >20 results exist |
| Nearby Search page 3 | Google Nearby | 0–1 | If >40 results exist |
| `fetch_details()` per result | Google Details | N (1–60) | Per business found |
| `set_cached_leads()` | Redis | 1 | After successful fetch |
| `release_search_lock()` | Redis | 1 | After fetch |

### Phase 3 — Background Email Enrichment (Per Lead with Website)

| Operation | Service | Calls | Condition |
|---|---|---|---|
| HTTP scrape (6 URLs/domain) | HTTP | 6 | Per lead with website |
| `has_mx_record()` | DNS | 1 | Per lead with website |
| `hunter_fallback_company()` | Hunter.io | 1 | Only if HTTP scrape fails |

> Enrichment runs in a Celery background task **after** the main response is returned.
> It does not affect the user-facing response time.

---

## 4. Cost Per Search — Single User (Cold Cache, Empty DB)

### Industry Density Tiers

Google's Nearby Search returns up to 20 results per page, maximum 3 pages = **60 results max**.

| Tier | Industry Examples | Pages | Results | Geocode | Nearby Search | Place Details | **Google Total** |
|---|---|---|---|---|---|---|---|
| **Sparse** | pen manufacturer, niche factory | 1 | ~15 | $0.005 | $0.032 | 15 × $0.017 = $0.255 | **$0.292** |
| **Medium** | dentists, gyms, coffee shops | 2 | ~35 | $0.005 | $0.064 | 35 × $0.017 = $0.595 | **$0.664** |
| **Dense** | hotels, restaurants, pharmacies | 3 | ~60 | $0.005 | $0.096 | 60 × $0.017 = $1.020 | **$1.121** |

### Full Cost Per Search (Dense Industry, Gemini Flash)

| Service | Calls | Unit Cost | Total |
|---|---|---|---|
| Google Geocoding | 1 | $0.005 | $0.005 |
| Google Nearby Search | 3 pages | $0.032 | $0.096 |
| Google Place Details | 60 results | $0.017 | $1.020 |
| Gemini Flash (4–5 calls) | ~2,950 tokens | $0.075/1M in | $0.0003 |
| **Google API Subtotal** | | | **$1.121** |
| Hunter.io (background, ~17 calls) | ~17 | $0.068 | $1.156 |
| HTTP Scraping | 0 | free | $0.00 |
| **Total (including enrichment)** | | | **~$2.28** |

> Hunter cost is per-enrichment-batch and depends on how many businesses have websites and how many fail HTTP scrape.
> Typical: 60 leads, 70% have websites (42), 40% of those fail scrape (17) → 17 Hunter calls.

---

## 5. Scaling Cost Estimation

### Assumptions
- All searches are unique `(industry, location)` pairs on first run
- Subsequent searches of the same query = **$0** (Redis cache + DB reuse)
- Rate limit: 10 fresh API searches per user per hour
- Using dense industry ($1.121 Google + $1.156 Hunter = $2.277/search) as worst case
- Using sparse industry ($0.292 Google + $0.40 Hunter = $0.692/search) as best case

---

### 1 User

#### Google Places API Cost
| Fresh Searches | Sparse ($0.292) | Dense ($1.121) | Avg ($0.707) |
|---|---|---|---|
| 1 | $0.29 | $1.12 | $0.71 |
| 5 | $1.46 | $5.61 | $3.54 |
| 10 (hourly limit) | **$2.92** | **$11.21** | **$7.07** |
| Repeat search (any) | $0.00 | $0.00 | $0.00 |

#### Including Hunter.io Enrichment
| Fresh Searches | Sparse Total | Dense Total |
|---|---|---|
| 1 | $0.69 | $2.28 |
| 5 | $3.45 | $11.40 |
| 10 (limit) | $6.90 | $22.77 |

---

### 10 Users

#### Same Query (Distributed Lock — 1 Real API Call)

| Scenario | Real API Calls | Total Cost |
|---|---|---|
| 10 users, cold cache, same query | 1 | $0.29–$1.12 (Google) |
| 10 users, warm cache, same query | 0 | **$0.00** |

#### Different Queries (Each User Searches Unique Industry + City)

| Fresh Searches/User | Total API Calls | Sparse Total | Dense Total | Avg Total |
|---|---|---|---|---|
| 1 | 10 | $2.92 | $11.21 | $7.07 |
| 5 | 50 | $14.60 | $56.05 | $35.35 |
| 10 (limit/user) | 100 | **$29.20** | **$112.10** | **$70.70** |

---

### 100 Users

#### Same Query

| Scenario | Real API Calls | Total Cost |
|---|---|---|
| 100 users, cold cache, same query | 1 | $0.29–$1.12 |
| 100 users, warm cache | 0 | **$0.00** |

#### Different Queries

| Fresh Searches/User | Total Unique API Calls | Sparse Total | Dense Total | Avg Total |
|---|---|---|---|---|
| 1 | 100 | $29.20 | $112.10 | $70.70 |
| 3 | 300 | $87.60 | $336.30 | $212.10 |
| 5 | 500 | $146.00 | $560.50 | $353.50 |
| 10 (limit/user) | 1,000 | **$292.00** | **$1,121.00** | **$706.50** |

> After the initial cold-cache searches, subsequent searches of the same queries are **free** from Redis cache.
> In practice, popular `(industry, city)` combinations get shared across all users — so real cost is significantly lower.

---

## 6. Database Impact

### Case 1 — Empty Database (First-Ever Use)

Every search fetches everything from Google Places. Full API cost applies.

| Industry Type | Google API Cost | + Hunter Enrichment | Total |
|---|---|---|---|
| Sparse (~15 leads) | $0.292 | ~$0.41 | **$0.70** |
| Medium (~35 leads) | $0.664 | ~$0.95 | **$1.61** |
| Dense (~60 leads) | $1.121 | ~$1.16 | **$2.28** |

---

### Case 2 — Half Database (50% of leads already stored)

`remaining = 50` → only 50 more leads needed from Google.

| Scenario | DB Leads | API Leads Needed | Nearby Pages | Details Calls | Google Cost |
|---|---|---|---|---|---|
| Sparse (15 total, 10 in DB) | 10 | 5 | 1 | 5 | $0.005 + $0.032 + $0.085 = **$0.122** |
| Medium (35 total, 17 in DB) | 17 | 18 | 1 | 18 | $0.005 + $0.032 + $0.306 = **$0.343** |
| Dense (60 total, 30 in DB) | 30 | 30 | 2 | 30 | $0.005 + $0.064 + $0.510 = **$0.579** |
| Any (100 in DB) | 100 | 0 | 0 | 0 | **$0.00** |

**Saving vs Empty DB (dense):** $1.121 → $0.579 = **48% reduction**

---

### Case 3 — Full Database (100 leads stored for this industry + city)

`remaining = 0` — Google API is **never called**.

| Any Industry | DB Leads | Google API Calls | Google Cost |
|---|---|---|---|
| Any | 100 | 0 | **$0.00** |

The system self-populates over time. Once a popular `(industry, city)` combination reaches 100 leads in the DB, that query is permanently free from Google API costs.

---

## 7. Cache Impact

### Cache Configuration (from `redis_context.py`)

| Cache Type | Redis Key Pattern | TTL | What It Stores |
|---|---|---|---|
| Lead Results | `leads:{md5(industry:location)[:12]}` | **24 hours** | Full list of leads |
| Geocode | `geo:{md5(location)[:12]}` | **7 days** | `(lat, lng)` for a city |
| Country Check | `isctry:{md5(location)[:12]}` | **7 days** | Whether a location is a country |
| User Rate Limit | `search_rate:{user_id}` | **1 hour** | Number of fresh API calls this hour |
| Search Lock | `lock:{md5(industry:location)[:12]}` | **45 seconds** | Prevents concurrent duplicate fetches |

### Cost Comparison — With vs Without Cache

#### Single Query, 10 Requests (Same Industry + City)

| Request | Without Cache | With Cache |
|---|---|---|
| Request 1 (cold) | $1.121 | $1.121 |
| Request 2 | $1.121 | **$0.00** |
| Request 3 | $1.121 | **$0.00** |
| ... | ... | ... |
| Request 10 | $1.121 | **$0.00** |
| **Total** | **$11.21** | **$1.121** |
| **Saving** | — | **90%** |

#### 20 Concurrent Users, Same Query (Cold Cache)

| Scenario | Without Lock | With Lock (Current) |
|---|---|---|
| API calls fired | 20 × full fetch | 1 real + 19 poll cache |
| Google API cost | 20 × $1.121 = $22.42 | **$1.121** |
| Saving | — | **95%** |

#### Load Test: 20 Users × 5 Seconds (Same Query)

| | Before All Optimizations | After All Optimizations |
|---|---|---|
| Grid search | ON (15 grid points) | OFF |
| Nearby Search calls/search | 15 × 3 = **45** | **1–3** |
| Place Details calls/search | **100** | **15–60** |
| Cache | None | Redis 24h |
| Concurrent dedup | None | Distributed lock |
| **Cost per search** | **~$3.20** | **$0.29–$1.12** |
| **20 users, same query** | **$64** | **$1.12** |
| **Actual load test result** | **~$600** | **< $2** |

---

## 8. Cost Comparison Summary

### Google Places API Only (per batch of fresh searches, avg industry)

| Scenario | 1 User | 10 Users | 100 Users |
|---|---|---|---|
| **Empty DB, no cache** | $0.71 | $7.07 | $70.70 |
| **Half DB, no cache** | $0.34 | $3.40 | $34.00 |
| **Full DB (any cache state)** | $0.00 | $0.00 | $0.00 |
| **Warm Redis cache** | $0.00 | $0.00 | $0.00 |
| **Same query, concurrent (lock)** | $0.71 | $0.71 | $0.71 |

> Values above represent **one round** of unique searches. Repeat queries are always $0.

---

## 9. Worst Case Cost

### Conditions
- All users search completely different `(industry, city)` pairs
- Database is empty
- Redis cache is empty (cold start or cache expired)
- All searches hit the dense industry tier (60 results, 3 pages)
- All users hit their full rate limit (10 searches/hour)

### Worst Case Per Hour

| Users | Searches/User/hr | Total API Searches | Google Places | Hunter.io | Gemini Flash | **Total/hr** |
|---|---|---|---|---|---|---|
| 1 | 10 | 10 | $11.21 | $11.56 | $0.003 | **$22.77** |
| 10 | 10 | 100 | $112.10 | $115.60 | $0.03 | **$227.70** |
| 100 | 10 | 1,000 | $1,121.00 | $1,156.00 | $0.30 | **$2,277.30** |

> **This is a theoretical maximum** that assumes every single search is a brand new query that has never been made by anyone.
> In practice, popular queries accumulate in the DB and cache rapidly. After the first week, cost drops by 60–80%.
>
> The rate limit of **10 searches/user/hour** acts as the hard cost ceiling.
> A single user can never cost more than **$22.77/hour** regardless of usage.

---

## 10. Optimizations Already Applied

The following optimizations are already implemented in the codebase:

| Optimization | Impact | Status |
|---|---|---|
| Redis lead cache (24h TTL) | Eliminates 100% of repeat Google API costs | ✅ Done |
| Redis geocode cache (7d TTL) | Eliminates repeat Geocoding calls | ✅ Done |
| Redis country-check cache (7d TTL) | Eliminates `is_country_name` API calls | ✅ Done |
| Grid search disabled by default | Reduced Nearby Search from 45 calls → 1–3 | ✅ Done |
| DB-first lead fetch | Free SQL query before any API call | ✅ Done |
| Distributed lock (concurrent dedup) | 20 concurrent same-query → 1 API call | ✅ Done |
| Per-user rate limit (10/hr) | Hard ceiling on per-user API spend | ✅ Done |
| In-memory rate limit fallback | Rate limit enforced even when Redis is down | ✅ Done |
| qcheck removed from main path | Saved 1 duplicate Nearby Search per cold search | ✅ Done |
| Quota counted on 0-result searches | Prevents quota bypass via empty queries | ✅ Done |
| Stale country context cleared | Prevents wrong `search_location` (e.g., "Mumbai, Nepal") | ✅ Done |

### Remaining Optimization Opportunities

| Optimization | Potential Saving | Complexity |
|---|---|---|
| Merge `is_general_question` + `run_extraction` into 1 LLM call | Save 1 Gemini call/message | Medium |
| Hunter.io result caching by domain | Avoid re-enriching same domain | Low |
| Batch Place Details using New Places API | Field-level billing can reduce detail cost | High (requires API migration) |

---

## 11. Final Cost Projection — Realistic Usage

### Assumptions
- 100 active users
- 3 unique searches per user per day (popular cities repeat — 40% cache hits)
- Mixed industry density (avg $0.707 Google + $0.80 Hunter = $1.51/fresh search)
- Gemini Flash used

### Daily Cost

| Searches/day | Cache Hit Rate | Fresh API Searches | Google Cost | Hunter Cost | Gemini Cost | **Daily Total** |
|---|---|---|---|---|---|---|
| 300 (100 users × 3) | 40% | 180 | $127.26 | $144.00 | $0.05 | **$271.31** |
| 300 | 60% | 120 | $84.84 | $96.00 | $0.04 | **$180.88** |
| 300 | 80% | 60 | $42.42 | $48.00 | $0.02 | **$90.44** |

> Cache hit rate grows as the DB fills up. After 2–4 weeks, popular `(industry, city)` pairs are in the DB permanently → cache hit rate trends toward 80%+.

### Monthly Cost Estimate (100 Users)

| Month | Cache Hit Rate | Google API | Hunter.io | Gemini | Infrastructure | **Monthly Total** |
|---|---|---|---|---|---|---|
| Month 1 (empty DB) | ~30% | $2,667 | $3,024 | $1.50 | $150 | **~$5,843** |
| Month 2 | ~55% | $1,524 | $1,728 | $0.90 | $150 | **~$3,403** |
| Month 3+ (mature DB) | ~80% | $508 | $576 | $0.30 | $150 | **~$1,234** |

### Monthly Cost Summary by Service (Month 3 — Mature State)

| Service | Monthly Cost | Notes |
|---|---|---|
| Google Maps (Geocoding + Nearby + Details) | ~$508 | After $200 free credit → ~$308 net |
| Hunter.io | ~$576 | Growth plan ($104/mo) covers ~2,500 searches |
| Google Gemini Flash | ~$0.30 | Negligible |
| PostgreSQL | ~$40 | Managed cloud DB |
| Redis | ~$25 | Managed cache |
| Celery Workers | ~$30 | Background enrichment |
| Application Server | ~$30 | FastAPI backend |
| **Total** | | **~$1,033/month** |

> Google's $200/month free credit reduces the effective Google Maps bill to ~$308 in Month 3.
> Hunter.io Growth plan ($104/month for 2,500 searches) is sufficient for mature usage at 80% cache hit rate.

---

## Quick Reference Card

| Question | Answer |
|---|---|
| Cost of 1 search, cold cache, sparse industry | **$0.29** |
| Cost of 1 search, cold cache, dense industry | **$1.12** |
| Cost of any repeat search (warm Redis) | **$0.00** |
| Cost of 100 users searching the same thing | **$0.29–$1.12** (lock dedup) |
| Max cost any single user can generate per hour | **~$22.77** (rate limited) |
| Max cost 100 users per hour (all unique) | **~$2,277** (theoretical worst case) |
| Monthly cost — 100 users, mature system | **~$1,033/month** |
| Monthly cost — original code (load test rate) | **~$180,000+/month** |
| Cost reduction after all optimizations | **>99%** |
