# Redis migration: Upstash → Hostinger (mutual TLS)

Runbook for moving the Cloud Run deployment (API service, `evecta-celery-worker`,
`evecta-celery-beat`) from Upstash to the Hostinger Redis at `redis.newaflix.com:6380`
(TLS only, client certificate required, password auth, Let's Encrypt server certificate).

**Status: code ready, nothing deployed.** Every step below that changes Google Cloud is
marked **[approval]** and must not be run until approved.

## What changed in the code

| File | Change |
|---|---|
| `backend/app/core/config.py` | `APP_REDIS_SSL_CERTFILE`, `APP_REDIS_SSL_KEYFILE`, `APP_REDIS_SSL_CA_CERTS`; `redis_ssl_options`; startup fails with the variable name if cert/key are not set together, a file is missing/unreadable, or `APP_REDIS_SSL` is off |
| `backend/app/core/redis.py`, `backend/app/utils/redis_context.py` | async and sync clients pass `redis_ssl_options` |
| `backend/app/core/limiter.py` | rate limiter storage gets `storage_options=redis_ssl_options` |
| `backend/app/core/celery_app.py` | `redis_tls_options()`: `CERT_REQUIRED` + client certificate for broker and result backend (rediss:// only) |
| `backend/scripts/make_worker_pool.py` | guard pings Redis with the certificate; copies Secret Manager **file** mounts; refuses a certificate path that is not a mounted secret |
| `backend/scripts/make_beat_pool.py` | Beat leader lock uses the certificate; copies file mounts |
| `backend/scripts/redis_connection_check.py` | new: standalone check (private keys / private queue, latency) |
| `backend/scripts/redis_migrate_keys.py` | new, optional: copy `thread:*` and `admin_device_trust:*` with TTLs |
| `backend/.env.example` | documents the new settings |

With the new variables unset (Upstash today) every client is configured exactly as before.

## Cost and approvals

Nothing here creates a new paid resource by itself, but several steps are billable
usage. Get approval before each:

- **Secret Manager**: three secrets already exist (active versions are billed); every
  Cloud Run instance start reads them (access operations are billed per 10,000).
- **Cloud Build / Artifact Registry**: building and storing the new image.
- **Cloud Run job** (`evecta-redis-hostinger-check`): billed per execution (seconds).
- **Not planned, needs separate approval if required**: Cloud NAT + static IP (only if
  Hostinger must allowlist Cloud Run's egress IP — see pre-flight).

## Worker pools and secret files

Cloud Run worker pools support Secret Manager secrets mounted as files
([docs](https://docs.cloud.google.com/run/docs/configuring/workerpools/secrets)); the
volume is owned by root. Two things are not documented and are checked in pre-flight:

1. The `gcloud run worker-pools deploy` reference documents `--set-secrets` for
   environment variables; the generators use the same `PATH=SECRET:VERSION` form as
   services. **Fallback (documented):** add the volume in YAML
   (`volumes[].secret.items` + `volumeMounts`) and apply with
   `gcloud run worker-pools replace FILE --dry-run`, then without `--dry-run`.
2. Whether the image's non-root user (uid 10001) can read the root-owned files. The
   connection check job opens both files as that user.

Cloud Run does not allow two secrets at the same path, so each secret gets its own
directory: `/secrets/redis-cert/client.crt` and `/secrets/redis-key/client.key`.

## 0. Pre-flight (read-only)

```bash
gcloud config set project evecta
REGION=asia-southeast1
SERVICE=evecta                                   # confirm: gcloud run services list --region $REGION
SA=$(gcloud run services describe $SERVICE --region $REGION --format='value(spec.template.spec.serviceAccountName)')

# 1. Worker-pool flag syntax for file mounts (local help, no API call)
gcloud run worker-pools deploy --help | sed -n '/--set-secrets/,/--clear-secrets/p'

# 2. Pin secret versions (use the numbers below instead of :1 if different)
for s in evecta-redis-password evecta-redis-client-cert evecta-redis-client-key; do
  gcloud secrets versions list $s --filter=state=enabled --format='value(name)' --limit=1; done

# 3. Who can read the secrets (service account must have secretAccessor)
for s in evecta-redis-password evecta-redis-client-cert evecta-redis-client-key; do
  gcloud secrets get-iam-policy $s --format=json; done

# 4. Back up the current configuration (needed for rollback)
mkdir -p redis-migration-backup && cd redis-migration-backup
gcloud run services describe $SERVICE --region $REGION --format=export > service.upstash.yaml
gcloud run worker-pools describe evecta-celery-worker --region $REGION --format=export > worker.upstash.yaml
gcloud run worker-pools describe evecta-celery-beat --region $REGION --format=export > beat.upstash.yaml
OLD_REV=$(gcloud run services describe $SERVICE --region $REGION --format='value(status.latestReadyRevisionName)'); echo $OLD_REV > old-revision.txt
```

On the Hostinger server (by whoever administers it):

| Setting | Required | Why |
|---|---|---|
| `maxmemory-policy` | `noeviction` | otherwise queued Celery tasks can be evicted |
| `appendonly` | `yes` | queued tasks survive a Redis restart |
| `timeout` | `0` | Celery keeps idle connections open |
| `maxclients` | ≥ 200 | API instances + worker + Beat pools |
| `tls-auth-clients` | `yes` | mutual TLS (already the case) |
| firewall | open to Cloud Run egress, or plan Cloud NAT | Cloud Run's outbound IPs are not fixed |
| Redis version | ≥ 6 | |

## 1. Grant secret access **[approval]**

```bash
for s in evecta-redis-password evecta-redis-client-cert evecta-redis-client-key; do
  gcloud secrets add-iam-policy-binding $s --member="serviceAccount:$SA" \
    --role=roles/secretmanager.secretAccessor; done
```

## 2. Build the image **[approval]**

Push the branch first (separate approval), then build with the project's usual
pipeline. Record the digest:

```bash
NEW_IMAGE=asia-southeast1-docker.pkg.dev/evecta/<repo>/evecta@sha256:<digest>
```

Optional, recommended: deploy `NEW_IMAGE` to the service while still on Upstash
(`gcloud run services update $SERVICE --region $REGION --image $NEW_IMAGE`). With the
new variables unset nothing changes — this proves no regression before the switch.

## 3. Test Hostinger without production traffic **[approval]**

A one-off job with only Redis settings (plus placeholders the settings model requires —
no application secrets are copied into it):

```bash
FERNET=$(python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())")
cat > hostinger-check-env.yaml <<EOF
APP_REDIS_HOST: "redis.newaflix.com"
APP_REDIS_PORT: "6380"
APP_REDIS_DB: "0"
APP_REDIS_SSL: "true"
APP_REDIS_SSL_CERTFILE: "/secrets/redis-cert/client.crt"
APP_REDIS_SSL_KEYFILE: "/secrets/redis-key/client.key"
APP_SECRET_KEY: "check-job-placeholder-not-a-real-secret-00000"
APP_MAILBOX_SECRET_KEY: "$FERNET"
APP_ALGORITHM: "HS256"
APP_ACCESS_TOKEN_EXPIRE_MINUTES: "1"
APP_REFRESH_TOKEN_EXPIRE_DAYS: "1"
APP_POSTGRES_USER: "unused"
APP_POSTGRES_PASSWORD: "unused"
APP_POSTGRES_DB: "unused"
APP_POSTGRES_HOST: "unused"
APP_GOOGLE_CLIENT_ID: "unused"
APP_GOOGLE_CLIENT_SECRET: "unused"
APP_GOOGLE_REDIRECT_URI: "unused"
APP_MAILBOX_GOOGLE_REDIRECT_URI: "unused"
APP_GOOGLE_MAPS_API_KEY: "unused"
APP_GEMINI_API_KEY: "unused"
APP_GEMINI_MODEL: "unused"
APP_BREVO_API_KEY: "unused"
APP_BREVO_WEBHOOK_TOKEN: "unused"
APP_EMAIL_TRACKING_BASE_URL: "unused"
EOF

gcloud run jobs create evecta-redis-hostinger-check --region $REGION --image $NEW_IMAGE \
  --service-account $SA --max-retries 0 --task-timeout 300 \
  --command python --args=-m,scripts.redis_connection_check,--pings,50 \
  --env-vars-file hostinger-check-env.yaml \
  --set-secrets APP_REDIS_PASSWORD=evecta-redis-password:1,/secrets/redis-cert/client.crt=evecta-redis-client-cert:1,/secrets/redis-key/client.key=evecta-redis-client-key:1
gcloud run jobs execute evecta-redis-hostinger-check --region $REGION --wait
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="evecta-redis-hostinger-check"' \
  --freshness=15m --limit=50 --order=asc --format='value(textPayload)'
```

Expected: `SUMMARY: 6/6 passed`, the client certificate subject and expiry, and the ping
p50/p95 from asia-southeast1 to Hostinger. **Decide on latency here**: every cache and
rate-limit call pays it. Do not use a tagged no-traffic API revision for testing — its
startup runs the reply fetcher, whose Redis lock would then be split across two servers.

Delete the job afterwards: `gcloud run jobs delete evecta-redis-hostinger-check --region $REGION`.

## 4. Cutover **[approval]** — quiet period, in this order

Why this order: Beat stops first so nothing new is scheduled; the API moves next so new
tasks queue on Hostinger and simply wait; the old worker drains Upstash; only then does
the worker move; Beat restarts last, on Hostinger only. No task is ever enqueued to a
Redis that no worker will read.

### 4.1 Stop the old Beat (no duplicate schedulers)

The Beat leader lock lives in one Redis, so it cannot stop a Beat on Upstash and a Beat
on Hostinger from running together. Worker pools need at least one instance, so stop
Beat by deleting the pool (it is recreated from the worker in 4.5; config is in
`beat.upstash.yaml`):

```bash
gcloud run worker-pools delete evecta-celery-beat --region $REGION
gcloud run worker-pools list --region $REGION     # only evecta-celery-worker remains
```

On SIGTERM the runner releases the leader lock. The dispatcher claims each email job
with a conditional `UPDATE … WHERE status='queued'`, so even an overlap cannot send the
same email twice — but a job claimed on a Redis nobody reads stays `sending` forever.

### 4.2 Move the API service to Hostinger

If `APP_REDIS_PASSWORD` is currently a plain variable, add it to `--remove-env-vars`
(a name cannot be both a plain variable and a secret).

```bash
gcloud run services update $SERVICE --region $REGION --image $NEW_IMAGE \
  --remove-env-vars APP_REDIS_URL,APP_REDIS_RESULT_URL \
  --update-env-vars APP_REDIS_HOST=redis.newaflix.com,APP_REDIS_PORT=6380,APP_REDIS_DB=0,APP_REDIS_SSL=true,APP_REDIS_SSL_CERTFILE=/secrets/redis-cert/client.crt,APP_REDIS_SSL_KEYFILE=/secrets/redis-key/client.key \
  --update-secrets APP_REDIS_PASSWORD=evecta-redis-password:1,/secrets/redis-cert/client.crt=evecta-redis-client-cert:1,/secrets/redis-key/client.key=evecta-redis-client-key:1
curl -s https://evecta-50244447908.asia-southeast1.run.app/api/ready      # {"status":"ready"}
```

From here new tasks (enrichment, email generation, sends) wait in Hostinger's queue.

### 4.3 Drain Upstash (old worker still running)

Countdown tasks can be held for up to ~20 minutes (20 jobs per batch, staggered 60 s per
user), so wait **at least 20 minutes after 4.1**, then until all of these are zero:

```bash
UPSTASH="rediss://default:<upstash-token>@<db>.upstash.io:6379"
redis-cli -u "$UPSTASH" --scan --pattern 'celery*' | while read q; do echo "$q $(redis-cli -u "$UPSTASH" LLEN "$q")"; done
redis-cli -u "$UPSTASH" HLEN unacked          # tasks reserved by the worker (incl. countdowns)
redis-cli -u "$UPSTASH" ZCARD unacked_index
```

In Postgres, nothing should be left claimed but unsent:

```sql
SELECT status, count(*), min(updated_at) FROM email_jobs
WHERE status IN ('queued', 'sending') GROUP BY status;
-- 'sending' rows older than ~25 minutes = tasks that were lost; investigate before 4.4
SELECT id, campaign_id, updated_at FROM email_jobs
WHERE status = 'sending' AND updated_at < now() - interval '25 minutes';
```

Pending AI email generation (`campaign_lead_emails` rows in `pending`) needs no action:
Beat's stalled-resume job re-dispatches them once Beat runs on Hostinger (4.5).

### 4.4 Move the worker

```bash
gcloud run services describe $SERVICE --region $REGION --format=json > service.json   # now Hostinger
python3 backend/scripts/make_worker_pool.py service.json "$NEW_IMAGE"
cat deploy-worker-pool.sh     # must list both /secrets/... files in --set-secrets
bash deploy-worker-pool.sh
gcloud logging read 'resource.type="cloud_run_worker_pool" AND resource.labels.worker_pool_name="evecta-celery-worker"' \
  --freshness=10m --limit=100 --order=asc --format='value(textPayload)'
# expect: [worker-guard] broker=rediss://redis.newaflix.com:6380/0, client certificate=yes, OK, then "ready."
```

If the deploy rejects the `/secrets/...=` entries, use the YAML fallback above.

### 4.5 Start Beat on Hostinger

```bash
gcloud run worker-pools describe evecta-celery-worker --region $REGION --format=json > worker.json
for p in $(gcloud run worker-pools list --region $REGION --format='value(metadata.name)'); do
  gcloud run worker-pools describe "${p##*/}" --region $REGION --format=json; done | jq -s . > pools.json
python3 backend/scripts/make_beat_pool.py worker.json pools.json
bash deploy-beat-pool.sh
```

### 4.6 Verify

- Beat log: `[beat-lock] acquired`, then `beat: Starting...`; worker log shows
  `dispatch_due_jobs` within 60 s.
- Sign in, start one chat, run one AI email generation, send one scheduled email.
- `/api/ready` returns ready; no `Redis connection failed` in service logs.
- Remove local copies: `rm service.json worker.json pools.json worker-env.yaml beat-env.yaml hostinger-check-env.yaml`.

## 5. Optional: carry over chat threads and admin device trust

Without this, users' next chat starts a new thread (history stays in Postgres) and admins
repeat 2FA once. Run between 4.2 and 4.6, dry run first; existing target keys are never
overwritten unless `--replace`:

```bash
export SOURCE_REDIS_URL="rediss://default:<upstash-token>@<db>.upstash.io:6379/0"
export TARGET_REDIS_URL="rediss://:<hostinger-password>@redis.newaflix.com:6380/0"
export TARGET_REDIS_SSL_CERTFILE=./client.crt TARGET_REDIS_SSL_KEYFILE=./client.key   # from Secret Manager, delete afterwards
python -m scripts.redis_migrate_keys            # dry run: counts only
python -m scripts.redis_migrate_keys --execute
```

## 6. Rollback

Same principle in reverse: stop Beat, move the API, drain Hostinger, move the worker,
start Beat — on Upstash. Upstash still holds its data (caches will be stale; nothing
breaks).

```bash
gcloud run worker-pools delete evecta-celery-beat --region $REGION                    # 1. stop Beat
gcloud run services update-traffic $SERVICE --region $REGION --to-revisions=$(cat old-revision.txt)=100   # 2. API back (old image + Upstash config)
# 3. drain Hostinger: same LLEN / HLEN unacked / email_jobs checks as 4.3, against redis.newaflix.com
gcloud run worker-pools replace worker.upstash.yaml --region $REGION                  # 4. worker back
gcloud run worker-pools replace beat.upstash.yaml --region $REGION                    # 5. Beat back (one Beat only)
```

`worker.upstash.yaml` / `beat.upstash.yaml` are exports; if `replace` rejects them,
regenerate with the scripts from the restored service as in 4.4–4.5.

If something fails **before 4.3 completes** (only the API has moved), rolling the API
back is enough: tasks queued on Hostinger in the meantime must still be drained by
running the worker against Hostinger once, or re-queued by their own recovery paths
(email generation resumes; email sends are re-claimed only if their rows are still
`queued`).

## Known gaps

- File-mount syntax for `worker-pools deploy` and non-root readability of root-owned
  secret files are unverified until pre-flight step 1 and the check job.
- Local tests ran against a TLS harness (fakeredis behind a client-certificate TLS
  server), not a real Redis: the rate limiter's first-use `SCRIPT LOAD` path fails there
  because the harness drops the connection after any error reply; plain fakeredis and
  production Upstash handle it. The check job exercises it against Hostinger.
- `campaign_lead_emails` rows missing for a campaign are still not recreated by resume
  (separate, unfixed issue).
