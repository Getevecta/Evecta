# Celery Worker Concurrency Guide

## Problem
When multiple users generate leads, only the first user's background enrichment task executes. The second user's task is queued but never processes.

## Root Causes Identified

1. **Sequential Task Execution**: Celery worker running with `-P solo` mode processes tasks sequentially (one at a time)
2. **Long-Running Enrichment**: If the first enrichment task takes too long (delays, external API calls), the second task waits indefinitely
3. **Database Connection Pool**: Limited database connections can cause task starvation
4. **Event Loop Issues**: Async event loop conflicts in multi-task scenarios

## Solutions

### Solution 1: Switch to Threaded Concurrency (Recommended for Most Cases)

Use thread-based concurrency which works on Windows, macOS, and Linux:

```bash
celery -A app.core.celery_app worker -P threads -c 4 --loglevel=info
```

**Parameters explained:**
- `-P threads`: Use thread-based concurrency pool
- `-c 4`: Spawn 4 concurrent worker threads (adjust based on CPU cores)
- `--loglevel=info`: Enable INFO level logging to see task execution

**Thread Pool Configuration Options:**
- `-c 2`: For low-traffic environments
- `-c 4`: For medium traffic (default)
- `-c 8`: For high-traffic environments
- `-c 16`: For very high-traffic with many simultaneous users

### Solution 2: Use Prefork Pool (Linux/macOS Only)

For production on Linux/macOS, use process-based concurrency:

```bash
celery -A app.core.celery_app worker -P prefork -c 4 --loglevel=info
```

**Benefits:** Better resource isolation, true parallelism
**Drawbacks:** Not compatible with Windows, higher memory usage

### Solution 3: Check Celery Worker Status

Monitor the worker to ensure it's running with correct settings:

```bash
# In a new terminal, connect to Celery app
celery -A app.core.celery_app inspect active

# See worker pool configuration
celery -A app.core.celery_app inspect stats
```

Expected output should show:
```
pool: {
  'implementation': 'celery.concurrency.thread:ThreadPool',
  'max_concurrency': 4,
  'processes': [1, 2, 3, 4],
}
```

## Current Configuration Changes

The following changes have been made to your codebase:

### 1. Enhanced Logging in Task

**File:** `backend/app/tasks/enrich_leads.py`

- Added comprehensive logging at task start, completion, and error
- Better error handling with exception details
- Proper async engine cleanup

**Example Log Output:**
```
🔄 Starting enrichment task for lead_log_id=42, task_id=abc123def456
📊 Enriching 42 leads with session factory
✅ Enrichment completed for lead_log_id=42
```

### 2. Task Enqueueing Logging

**File:** `backend/app/services/chat_service.py`

- Added logging when task is enqueued
- Logs the lead_log_id and task_id for tracking
- Logs any enqueueing errors

**Example Log Output:**
```
✅ Enqueued enrichment task for lead_log_id=42, task_id=abc123def456, user_id=7
```

### 3. Celery Configuration Updates

**File:** `backend/app/core/celery_app.py`

- Set `worker_prefetch_multiplier=1`: Ensures worker fetches next task only after completing current one
- Set `task_acks_late=True`: Acknowledges task completion only after it finishes (prevents loss on crash)
- Added `task_track_started=True`: Tracks when task actually starts
- Added `broker_pool_limit=10`: Maintains up to 10 Redis connections for better throughput
- Added startup logging to show configuration

## Testing the Fix

### Step 1: Stop Current Celery Worker
```bash
# Kill any existing Celery workers
# On Windows: taskkill /IM celery.exe /F
# On Linux/macOS: pkill -f "celery worker"
```

### Step 2: Start New Celery Worker with Threads

```bash
cd backend
source venv/bin/activate  # or venv\Scripts\activate on Windows
celery -A app.core.celery_app worker -P threads -c 4 --loglevel=info
```

### Step 3: Test with Multiple Users

1. User 1: Generate leads for "restaurants in delhi"
2. User 2 (simultaneously): Generate leads for "coffee shops in bangalore"
3. Check logs - both enrichment tasks should start immediately
4. Both tasks should complete and update database

### Step 4: Monitor Task Execution

In another terminal:

```bash
# See active tasks
celery -A app.core.celery_app inspect active

# See completed tasks
celery -A app.core.celery_app inspect reserved
```

## Expected Behavior After Fix

**Before:**
```
User 1: Leads generated ✅, enrichment task fires and completes ✅
User 2: Leads generated ✅, enrichment task queued but never executes ❌
```

**After:**
```
User 1: Leads generated ✅, enrichment task starts ✅, completes ✅
User 2: Leads generated ✅, enrichment task starts ✅, completes ✅
Both run concurrently! No waiting!
```

## Production Deployment

### AWS Lightsail Deployment

To deploy the concurrent worker on your production server:

1. **Create a systemd service for Celery worker:**

```bash
sudo nano /etc/systemd/system/celery-worker.service
```

Add:
```ini
[Unit]
Description=Celery Worker Service
After=network.target redis-server.service

[Service]
Type=forking
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/Evecta/backend
ExecStart=/home/ubuntu/Evecta/backend/venv/bin/celery -A app.core.celery_app worker -P threads -c 4 --loglevel=info --logfile=/var/log/celery/celery-worker.log --pidfile=/var/run/celery/celery-worker.pid

[Install]
WantedBy=multi-user.target
```

2. **Create log and pid directories:**

```bash
sudo mkdir -p /var/log/celery /var/run/celery
sudo chown ubuntu:ubuntu /var/log/celery /var/run/celery
```

3. **Enable and start the service:**

```bash
sudo systemctl daemon-reload
sudo systemctl enable celery-worker
sudo systemctl start celery-worker
sudo systemctl status celery-worker
```

4. **Monitor logs:**

```bash
sudo tail -f /var/log/celery/celery-worker.log
```

## Troubleshooting

### Issue: Tasks Still Not Executing

**Check 1:** Verify Celery worker is running
```bash
celery -A app.core.celery_app inspect active
# If this hangs or shows no workers, worker is not running
```

**Check 2:** Verify Redis is running
```bash
redis-cli ping
# Should return: PONG
```

**Check 3:** Check Celery logs for errors
```bash
# Look for task registration errors or connection issues
```

### Issue: "No workers available"

**Solution:** 
1. Ensure Celery worker is actually started
2. Check Redis connection with `redis-cli`
3. Verify `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` environment variables

### Issue: "Threading module not available"

**Solution:**
- Threading support should be available in all Python installations
- If issue persists, try: `pip install eventlet` for alternative concurrency
- Or use: `celery -A app.core.celery_app worker -P eventlet -c 100`

## Performance Tuning

For different workload profiles:

| Scenario | Pool | Concurrency | Comment |
|----------|------|-------------|---------|
| Light (< 10 tasks/hour) | threads | 2 | Low resource usage |
| Medium (10-100 tasks/hour) | threads | 4 | Good balance |
| Heavy (100+ tasks/hour) | threads/eventlet | 8-16 | More concurrent tasks |
| Production | prefork | 4-8 | Best performance on Linux |

## Files Modified

1. `backend/app/tasks/enrich_leads.py` - Added logging and error handling
2. `backend/app/services/chat_service.py` - Added task enqueueing logging
3. `backend/app/core/celery_app.py` - Enhanced configuration for concurrency
4. `backend/requirements.txt` - Already contains redis package

## Next Steps

1. Deploy the updated code to production
2. Restart FastAPI and Celery services
3. Test with concurrent users
4. Monitor logs and Celery task queue
5. Adjust concurrency level based on server load

## References

- [Celery Concurrency Documentation](https://docs.celeryproject.io/en/stable/userguide/concurrency/index.html)
- [Celery Configuration](https://docs.celeryproject.io/en/stable/userguide/configuration.html)
- [Celery Task Best Practices](https://docs.celeryproject.io/en/stable/userguide/tasks.html)
