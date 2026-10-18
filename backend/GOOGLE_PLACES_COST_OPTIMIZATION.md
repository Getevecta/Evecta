# Google Places API Cost Optimization

## Problem

Load test with **20 concurrent users for 5 seconds** caused the Google Places API bill to spike to **~$600**.

### Root Cause Analysis

Every user search triggered the full API pipeline with zero caching:

| Step | API Calls | Cost per Search |
|---|---|---|
| Geocoding | 1 call | ~$0.005 |
| Grid search (15 grid points × 3 pages) | **45 Nearby Search calls** | ~$1.44 |
| Place Details (100 results) | **100 Detail calls** | ~$1.70 |
| Quick check (pre-flight) | 1 Geocode + 1 Nearby | ~$0.037 |
| **Total per search** | **~148 API calls** | **~$3.20** |

With 20 users × multiple searches × no caching = **$600+**

The 3 compounding problems:
1. **Grid search on by default** — multiplied Nearby Search calls by ~15x
2. **No caching** — every user, even identical queries, paid the full price
3. **No rate limiting** — load test users could fire unlimited unique queries

---

## What We Changed

### 1. Redis Cache for Lead Results
**File:** `app/utils/redis_context.py`

Added `get_cached_leads` / `set_cached_leads` with a **24-hour TTL**.

- Cache key: MD5 hash of `"{industry}:{location}"` (case-insensitive)
- On cache HIT: returns instantly, **$0 Google API cost**
- On cache MISS: fetches from Google, stores result, all future requests are free for 24h

```
leads:restaurants:kathmandu → [list of 100 businesses] (expires in 24h)
```

### 2. Redis Cache for Quick-Check Results
**File:** `app/utils/chat_helper.py`

`quick_check_results()` runs before every full search to verify the location has results. It was making 2 API calls (Geocode + Nearby) every single time.

Added `get_cached_quick_check` / `set_cached_quick_check` with **2-hour TTL**.

- Cache HIT: skips both API calls entirely
- Cache MISS: makes the 2 calls, stores `True/False` in Redis

### 3. Redis Cache for Geocoding
**File:** `app/utils/redis_context.py`, `app/utils/chat_helper.py`, `app/services/lead_generation_service.py`

Added `get_cached_geocode` / `set_cached_geocode` with **7-day TTL**.

- Location strings like `"Kathmandu, Nepal"` always resolve to the same coordinates
- No need to call the Geocoding API more than once per location per week

### 4. Grid Search Disabled by Default
**File:** `app/services/lead_generation_service.py`

```python
# Before
async def get_leads(..., use_grid_search: bool = True, ...):

# After
async def get_leads(..., use_grid_search: bool = False, ...):
```

Grid search generates ~15 grid points and fires up to 3 Nearby Search pages per point = **45 API calls** instead of 3. For most queries a single-point search returns sufficient results (up to 60 places across 3 pages). Grid search can still be enabled explicitly for specialized use cases.

### 5. Distributed Search Lock (Concurrent Deduplication)
**File:** `app/utils/redis_context.py`, `app/services/chat_service.py`

Added `acquire_search_lock` / `release_search_lock` using Redis `SET NX EX`.

**Problem it solves:** 20 users simultaneously search `"restaurants, Kathmandu"` with a cold cache. Without a lock, all 20 fire Google API calls in parallel.

**How it works:**
1. First request acquires the lock and fetches from Google API
2. All other requests for the same query fail to acquire the lock
3. They enter a polling loop (8 × 0.5s = up to 4 seconds)
4. When the first request finishes and writes to cache, the pollers get the result
5. **Result: 1 API call instead of 20**

```python
lock_acquired = acquire_search_lock(industry, location, ttl=45)
if not lock_acquired:
    # Poll cache until lock holder finishes
    for _ in range(8):
        await asyncio.sleep(0.5)
        cached = get_cached_leads(industry, location)
        if cached:
            break
```

### 6. Per-User Hourly Rate Limit
**File:** `app/utils/redis_context.py`, `app/services/chat_service.py`

Added `check_user_search_rate` / `increment_user_search_rate`.

- Limit: **10 fresh API searches per user per hour** (configurable via `USER_SEARCH_LIMIT`)
- Cache hits are **never counted** — only real Google API calls consume quota
- Uses Redis `INCR` + `EXPIRE` (atomic pipeline)
- When limit is reached: user gets a friendly message, no API call is made

```
search_rate:{user_id} → 7  (expires in 3600s)
```

---

## Files Modified

| File | Change |
|---|---|
| `app/utils/redis_context.py` | Added 8 new cache/lock/rate-limit helper functions |
| `app/services/lead_generation_service.py` | Cache check in `get_leads`, cache geocoding, grid search off by default |
| `app/utils/chat_helper.py` | Cache `quick_check_results` and geocoding |
| `app/services/chat_service.py` | Added rate limit check + distributed lock around Google API call |

---

## Cost Comparison

### Before (no optimizations)

| Scenario | API Calls | Cost |
|---|---|---|
| 1 search (cold) | ~148 | ~$3.20 |
| 20 users, same query | ~2,960 | ~$64 |
| 20 users, different queries | ~2,960 | ~$64 |
| 20 users × 5s load test | ~thousands | **~$600** |

### After (all optimizations)

| Scenario | API Calls | Cost |
|---|---|---|
| 1st search, cold cache | ~65 (no grid, 3 Nearby + ~60 Details) | ~$1.20 |
| 20 users, same query (cold) | ~65 (lock dedup) | **~$1.20** |
| 20 users, same query (warm) | 0 | **$0.00** |
| 20 users, different queries (cold) | ~65 × unique queries | ~$1.20 each |
| User hits rate limit | 0 | **$0.00** |
| Same load test (20 users × 5s) | Minimal | **< $2** |

---

## Configuration

Tunable constants:

| Constant | File | Default | Description |
|---|---|---|---|
| `USER_SEARCH_LIMIT` | `redis_context.py` | `10` | Max fresh API searches per user per hour |
| `USER_SEARCH_WINDOW` | `redis_context.py` | `3600` | Rate limit window in seconds |
| `set_cached_leads(..., ttl)` | `redis_context.py` | `86400` | Lead cache TTL (24h) |
| `set_cached_quick_check(..., ttl)` | `chat_helper.py` | `7200` | Quick-check cache TTL (2h) |
| `set_cached_geocode(..., ttl)` | `redis_context.py` | `604800` | Geocode cache TTL (7 days) |
| `use_grid_search` | `lead_generation_service.py` | `False` | Enable grid search (expensive) |
| `LEADS_LIMIT` | `chat_service.py` | `100` | Max leads returned per search |
