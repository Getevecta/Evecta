"""Build a Cloud Run Worker Pool deployment for Celery Beat, cloned from the running worker pool.

Usage (Cloud Shell):
    python3 backend/scripts/make_beat_pool.py worker.json pools.json
      worker.json  gcloud run worker-pools describe evecta-celery-worker --format=json
      pools.json   every worker pool's describe output as a JSON array (scanned for other schedulers)
writes beat-env.yaml and deploy-beat-pool.sh to the current directory.

Reads the layout gcloud prints for worker pools (apiVersion/kind/metadata/spec/status):
spec.template.spec.containers[0] for image, command, args, env (plain values and
valueFrom.secretKeyRef) and resources; spec.template.spec.serviceAccountName; Cloud SQL
and Direct VPC from spec.template.metadata.annotations.

Copies the worker's exact image, env (incl. Secret Manager refs and its startup guard),
Secret Manager secrets mounted as files (the Redis client certificate and key), service
account, Cloud SQL instance and Direct VPC settings. Refuses if any other worker
pool already runs Beat (a `beat` command, or a worker started with -B/--beat).

The container runs the worker's guard (hackathon database at the Alembic head, Upstash
Redis over TLS), then a runner that holds a Redis leader lock for as long as Beat runs.
A second Beat on the same Redis (e.g. old and new revision overlapping during a rollout)
waits for the lock instead of scheduling every task twice.
"""
import json
import shlex
import sys

POOL = "evecta-celery-beat"
WORKER = "evecta-celery-worker"
REGION = "asia-southeast1"
INSTANCES = 1
CPU, MEMORY = "1", "512Mi"
INSTANCE = "evecta:asia-southeast1:evecta-hackathon-db"
BEAT_ARGV = ["celery", "-A", "app.core.celery_app", "beat", "--loglevel=info"]
GUARD_ENV = "EVECTA_WORKER_GUARD"
RUNNER_ENV = "EVECTA_BEAT_RUNNER"

RUNNER = f'''
import os, signal, socket, subprocess, sys, threading, time, uuid
import redis
from app.core.config import get_settings

KEY, TTL, RENEW_EVERY = "evecta:celery-beat:leader", 60, 15
RENEW = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end"
RELEASE = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"

_settings = get_settings()
r = redis.Redis.from_url(_settings.REDIS_URL, socket_connect_timeout=10, socket_timeout=10,
                         **getattr(_settings, "redis_ssl_options", {{}}))
me = f"{{os.environ.get('K_REVISION', '?')}}/{{socket.gethostname()}}/{{uuid.uuid4().hex[:8]}}"
stopping = False


def on_term(signum, frame):
    global stopping
    stopping = True
    if proc is not None and proc.poll() is None:
        proc.terminate()


proc = None
signal.signal(signal.SIGTERM, on_term)
signal.signal(signal.SIGINT, on_term)

while not stopping and not r.set(KEY, me, nx=True, ex=TTL):
    print(f"[beat-lock] another Beat holds the leader lock ({{r.get(KEY)!r}}); waiting", flush=True)
    time.sleep(RENEW_EVERY)
if stopping:
    sys.exit(0)
print(f"[beat-lock] acquired as {{me}}; starting Beat", flush=True)
proc = subprocess.Popen({BEAT_ARGV!r})
lost = threading.Event()


def renew():
    last_ok = time.monotonic()
    while proc.poll() is None:
        time.sleep(RENEW_EVERY)
        try:
            if not r.eval(RENEW, 1, KEY, me, TTL):
                print("[beat-lock] lock taken over; stopping Beat", flush=True)
                lost.set()
                proc.terminate()
                return
            last_ok = time.monotonic()
        except Exception as e:
            print(f"[beat-lock] renew failed: {{type(e).__name__}}: {{e}}", flush=True)
            if time.monotonic() - last_ok > TTL - RENEW_EVERY:
                print("[beat-lock] cannot renew before expiry; stopping Beat", flush=True)
                lost.set()
                proc.terminate()
                return


threading.Thread(target=renew, daemon=True).start()
code = proc.wait()
try:
    released = r.eval(RELEASE, 1, KEY, me)
    print("[beat-lock] released" if released else "[beat-lock] not ours any more; left as is", flush=True)
except Exception as e:
    print(f"[beat-lock] release failed (expires in <= {{TTL}}s): {{e}}", flush=True)
sys.exit(1 if lost.is_set() else (0 if stopping else code))
'''

ENTRYPOINT = f'python -c "${GUARD_ENV}" && exec python -c "${RUNNER_ENV}"'
TLS_FILE_ENV = ("APP_REDIS_SSL_CERTFILE", "APP_REDIS_SSL_KEYFILE", "APP_REDIS_SSL_CA_CERTS")


def secret_files(pod, container):
    """Secret Manager secrets mounted as files: ({file path: "secret:version"}, other volumes)."""
    mounts = {m["name"]: m["mountPath"].rstrip("/") for m in container.get("volumeMounts", [])}
    files, unsupported = {}, []
    for v in pod.get("volumes", []):
        secret = v.get("secret") or {}
        items = secret.get("items") or []
        if not secret.get("secretName") or not items or v.get("name") not in mounts:
            unsupported.append(v.get("name"))
            continue
        for item in items:
            files[f"{mounts[v['name']]}/{item['path']}"] = f"{secret['secretName']}:{item.get('key') or 'latest'}"
    return files, unsupported


def read_pool(pool):
    """Reduce a `gcloud run worker-pools describe --format=json` document to what this script uses."""
    meta = pool.get("metadata") or {}
    tmpl = (pool.get("spec") or {}).get("template") or {}
    ann = (tmpl.get("metadata") or {}).get("annotations") or {}
    pod = tmpl.get("spec") or {}
    containers = pod.get("containers") or []
    c = containers[0] if containers else {}

    env = []
    for e in c.get("env", []):
        ref = (e.get("valueFrom") or {}).get("secretKeyRef")
        if ref:
            env.append({"name": e["name"], "secret": f"{ref['name']}:{ref.get('key') or 'latest'}"})
        else:
            env.append({"name": e["name"], "value": e.get("value", "")})
    files, unsupported = secret_files(pod, c)

    return {
        "name": meta.get("name", ""),
        "containers": containers,
        "image": c.get("image"),
        "argv": c.get("command", []) + c.get("args", []),
        "env": env,
        "limits": (c.get("resources") or {}).get("limits") or {},
        "service_account": pod.get("serviceAccountName"),
        "cloudsql": [i.strip() for i in ann.get("run.googleapis.com/cloudsql-instances", "").split(",") if i.strip()],
        "secret_files": files,
        "volumes": unsupported,
        "nets": json.loads(ann.get("run.googleapis.com/network-interfaces") or "[]"),
        "egress": ann.get("run.googleapis.com/vpc-access-egress", ""),
        "connector": ann.get("run.googleapis.com/vpc-access-connector"),
    }


def runs_beat(pool):
    for c in pool["containers"]:
        words = " ".join(c.get("command", []) + c.get("args", [])).split()
        if "beat" in words or "-B" in words or "--beat" in words:
            return True
        # Commands hidden in env-borne scripts (this generator's own pattern).
        for e in c.get("env", []):
            if e.get("name") == RUNNER_ENV:
                return True
    return False


def main():
    raw_worker = json.load(open(sys.argv[1]))
    if not isinstance(raw_worker, dict) or "spec" not in raw_worker:
        sys.exit(f"{sys.argv[1]} must be the output of: gcloud run worker-pools describe {WORKER} --format=json")
    raw_pools = json.load(open(sys.argv[2]))
    if isinstance(raw_pools, dict):
        raw_pools = raw_pools.get("items", [raw_pools])
    worker = read_pool(raw_worker)
    pools = [read_pool(p) for p in raw_pools]
    problems, notes = [], []

    if worker["name"] != WORKER:
        problems.append(f"{sys.argv[1]} describes {worker['name']!r}, expected {WORKER!r}")
    image = worker["image"]
    if not image:
        sys.exit("Could not find spec.template.spec.containers[0].image in the worker description.")
    if "@sha256:" not in image:
        notes.append(f"worker image is a tag, not a digest: {image}")

    if "worker" not in " ".join(worker["argv"]).split():
        problems.append("worker pool command does not look like a Celery worker")
    if runs_beat(worker):
        problems.append(f"{WORKER} already runs Beat (-B/--beat); a second Beat would duplicate schedules")

    seen = [p["name"] for p in pools]
    if WORKER not in seen:
        problems.append(f"{WORKER} not found in {sys.argv[2]}; is the list from region {REGION}?")
    for p in pools:
        if p["name"] not in (POOL, WORKER) and runs_beat(p):
            problems.append(f"worker pool {p['name']!r} already runs Celery Beat")
    if POOL in seen:
        notes.append(f"{POOL} exists; deploying rolls out a new revision (the leader lock prevents overlap)")

    env, secrets = {}, {}
    for e in worker["env"]:
        if "secret" in e:
            secrets[e["name"]] = e["secret"]
        elif e["name"] not in ("PORT", RUNNER_ENV):
            env[e["name"]] = e["value"]
    if GUARD_ENV not in env:
        problems.append(f"worker has no {GUARD_ENV}; deploy it with make_worker_pool.py first")
    for key in ("APP_POSTGRES_HOST", "APP_POSTGRES_DB"):
        if key not in env and key not in secrets:
            problems.append(f"worker has no {key}")

    if INSTANCE not in worker["cloudsql"]:
        problems.append(f"worker is not connected to Cloud SQL instance {INSTANCE} "
                        f"(found {worker['cloudsql'] or 'none'})")
    if worker["volumes"]:
        problems.append(f"worker uses volumes {worker['volumes']} that are not Secret Manager files; "
                        "add them to the Beat pool by hand")
    files = worker["secret_files"]
    for key in TLS_FILE_ENV:
        if key in env and env[key] not in files:
            problems.append(f"worker {key}={env[key]!r} is not a mounted Secret Manager file")

    if problems:
        sys.exit("Not generating Beat pool:\n  - " + "\n  - ".join(problems))

    with open("beat-env.yaml", "w", newline="\n") as f:
        for k in sorted(env):
            f.write(f"{k}: {json.dumps(env[k])}\n")
        f.write(f"{RUNNER_ENV}: {json.dumps(RUNNER)}\n")

    flags = [
        f"--region={REGION}",
        f"--image={image}",
        f"--instances={INSTANCES}",
        f"--set-cloudsql-instances={INSTANCE}",
        "--env-vars-file=beat-env.yaml",
        "--command=sh",
        f"--args=-c,{ENTRYPOINT}",
        f"--cpu={CPU}",
        f"--memory={MEMORY}",
    ]
    if worker["service_account"]:
        flags.append(f"--service-account={worker['service_account']}")
    if secrets or files:
        flags.append("--set-secrets=" + ",".join(
            f"{k}={v}" for k, v in sorted(secrets.items()) + sorted(files.items())))
    if worker["connector"]:
        notes.append("worker has a VPC connector; worker pools only support Direct VPC, so it is not copied")
    nets = worker["nets"]
    if nets:
        if nets[0].get("network"):
            flags.append(f"--network={nets[0]['network']}")
        if nets[0].get("subnetwork"):
            flags.append(f"--subnet={nets[0]['subnetwork']}")
        if nets[0].get("tags"):
            flags.append("--network-tags=" + ",".join(nets[0]["tags"]))
        if worker["egress"]:
            flags.append(f"--vpc-egress={worker['egress']}")

    with open("deploy-beat-pool.sh", "w", newline="\n") as f:
        f.write("#!/usr/bin/env bash\nset -euo pipefail\n")
        f.write(f"gcloud run worker-pools deploy {POOL} \\\n  "
                + " \\\n  ".join(shlex.quote(c) for c in flags) + "\n")

    print(f"image:           {image}")
    print(f"service account: {worker['service_account']}")
    print(f"cloud sql:       {', '.join(worker['cloudsql'])}")
    print(f"plain env vars:  {', '.join(sorted(env))}")
    print(f"secret env vars: {', '.join(f'{k}={v}' for k, v in sorted(secrets.items())) or '-'}")
    print(f"secret files:    {', '.join(f'{k}={v}' for k, v in sorted(files.items())) or '-'}")
    print(f"resources:       cpu={CPU} memory={MEMORY} (worker has cpu={worker['limits'].get('cpu')} "
          f"memory={worker['limits'].get('memory')})")
    print(f"network:         {nets[0] if nets else 'none'}")
    print(f"pools scanned:   {', '.join(seen)}; no other Beat found")
    for n in notes:
        print(f"NOTE: {n}")
    print("wrote beat-env.yaml and deploy-beat-pool.sh (review, then: bash deploy-beat-pool.sh)")


main()
