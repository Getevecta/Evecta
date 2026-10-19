"""Build a Cloud Run Worker Pool deployment for the Celery worker, cloned from the live service.

Usage (Cloud Shell):
    python3 backend/scripts/make_worker_pool.py service.json IMAGE_DIGEST
writes worker-env.yaml and deploy-worker-pool.sh to the current directory.

Copies env (incl. Secret Manager refs), Secret Manager secrets mounted as files (the
Redis client certificate and key), service account, Cloud SQL and Direct VPC
settings and resources from the service. The container runs a guard first that
refuses to start the worker unless the database is the hackathon instance, Redis
is TLS (rediss://, db 0) and not a local/other host, both answer, and the schema
is at the Alembic head — so it cannot attach to production or staging queues.
"""
import json
import shlex
import sys

POOL = "evecta-celery-worker"
REGION = "asia-southeast1"
INSTANCES = 1
INSTANCE = "evecta:asia-southeast1:evecta-hackathon-db"
SOCKET = "/cloudsql/" + INSTANCE
DB = "evecta_hackathon"
WORKER_CMD = "celery -A app.core.celery_app worker -P threads -c 4 --loglevel=info"
GUARD_ENV = "EVECTA_WORKER_GUARD"
SKIP_ENV = {"PORT", GUARD_ENV}
LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}

GUARD = f'''
import asyncio, os, sys
from urllib.parse import urlsplit
from app.core.config import get_settings

s = get_settings()
errors = []


def redis_parts(url):
    u = urlsplit(url)
    return u.scheme, u.hostname or "", u.port, (u.path or "/").lstrip("/") or "0"


broker, result = s.REDIS_URL or "", s.REDIS_RESULT_URL or ""
for label, url in (("broker", broker), ("result", result)):
    if url:
        scheme, host, port, db = redis_parts(url)
        print(f"[worker-guard] {{label}}={{scheme}}://{{host}}:{{port}}/{{db}}")
print(f"[worker-guard] db host={{s.POSTGRES_HOST}} db={{s.POSTGRES_DB}} user={{s.POSTGRES_USER}} "
      f"environment={{s.ENVIRONMENT}} DATABASE_URL_set={{bool(s.DATABASE_URL)}}")

if s.DATABASE_URL:
    errors.append("APP_DATABASE_URL is set and would override the target")
if s.POSTGRES_HOST != "{SOCKET}":
    errors.append("APP_POSTGRES_HOST is not {SOCKET}")
if s.POSTGRES_DB != "{DB}":
    errors.append("APP_POSTGRES_DB is not {DB}")
if not hasattr(type(s), "redis_cache_url"):
    errors.append("image predates the Cloud SQL socket / Redis TLS fix (commit e7fd77d); rebuild")
if os.environ.get("APP_REDIS_SSL_CERTFILE") and not hasattr(type(s), "redis_ssl_options"):
    errors.append("APP_REDIS_SSL_CERTFILE is set but the image predates Redis mutual TLS; rebuild")
tls = getattr(s, "redis_ssl_options", {{}})
print(f"[worker-guard] redis client certificate={{'yes' if tls.get('ssl_certfile') else 'no'}}")
if not broker:
    errors.append("no broker URL (APP_REDIS_URL)")
if not result:
    print("[worker-guard] note: APP_REDIS_RESULT_URL unset; task results are not stored")
for label, url in (("APP_REDIS_URL", broker), ("APP_REDIS_RESULT_URL", result)):
    if not url:
        continue
    scheme, host, port, db = redis_parts(url)
    if scheme != "rediss":
        errors.append(f"{{label}} must be rediss:// (TLS is required)")
    if host in {sorted(LOCAL_HOSTS)!r}:
        errors.append(f"{{label}} points at a local Redis")
    if host != s.REDIS_HOST:
        errors.append(f"{{label}} host {{host}} differs from APP_REDIS_HOST {{s.REDIS_HOST}} "
                      "(the API's Redis); worker and API must share one Redis")
    if db != "0":
        errors.append(f"{{label}} uses db {{db}}; expected db 0 (the only db on Upstash)")

if errors:
    print("[worker-guard] REFUSING TO START:\\n  - " + "\\n  - ".join(errors))
    sys.exit(1)

import redis
for label, url in (("broker", broker), ("result", result)):
    if url:
        try:
            redis.Redis.from_url(url, socket_connect_timeout=10, **tls).ping()
        except Exception as e:
            errors.append(f"{{label}} Redis did not answer: {{type(e).__name__}}: {{e}}")


async def check_db():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
    engine = create_async_engine(s.async_database_url)
    try:
        async with engine.connect() as conn:
            name = (await conn.execute(text("SELECT current_database()"))).scalar()
            try:
                current = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
            except Exception:
                current = None
    finally:
        await engine.dispose()
    print(f"[worker-guard] connected database={{name}} alembic={{current}} head={{head}}")
    if name != "{DB}":
        errors.append(f"connected to database {{name}}, expected {DB}")
    if current != head:
        errors.append(f"schema at {{current}}, expected head {{head}}; run the evecta-migrate job first")

try:
    asyncio.run(check_db())
except Exception as e:
    errors.append(f"database check failed: {{type(e).__name__}}: {{e}}")

if errors:
    print("[worker-guard] REFUSING TO START:\\n  - " + "\\n  - ".join(errors))
    sys.exit(1)
print("[worker-guard] OK: {DB} on {INSTANCE}; Redis reachable over TLS")
'''

ENTRYPOINT = f'python -c "${GUARD_ENV}" && exec {WORKER_CMD}'
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


def main():
    service_path, image = sys.argv[1], sys.argv[2]
    svc = json.load(open(service_path))
    tmpl = svc["spec"]["template"]
    annotations = tmpl.get("metadata", {}).get("annotations", {})
    pod = tmpl["spec"]
    container = pod["containers"][0]
    env = [e for e in container.get("env", []) if e["name"] not in SKIP_ENV]
    plain = {e["name"]: e["value"] for e in env if "value" in e}
    secrets = {
        e["name"]: f'{e["valueFrom"]["secretKeyRef"]["name"]}:{e["valueFrom"]["secretKeyRef"]["key"]}'
        for e in env if "valueFrom" in e
    }
    names = set(plain) | set(secrets)

    problems, warnings = [], []
    if INSTANCE not in annotations.get("run.googleapis.com/cloudsql-instances", ""):
        problems.append(f"service is not connected to Cloud SQL instance {INSTANCE}")
    if "APP_DATABASE_URL" in names:
        problems.append("service sets APP_DATABASE_URL (overrides APP_POSTGRES_*)")
    for key, want in (("APP_POSTGRES_HOST", SOCKET), ("APP_POSTGRES_DB", DB)):
        if key not in names:
            problems.append(f"service has no {key}")
        elif key in plain and plain[key] != want:
            problems.append(f"service {key}={plain[key]!r}, expected {want!r}")
    if "APP_REDIS_HOST" not in names and "APP_REDIS_URL" not in names:
        problems.append("service has no APP_REDIS_HOST / APP_REDIS_URL (would use localhost)")
    if plain.get("APP_REDIS_HOST", "x").strip() in LOCAL_HOSTS:
        problems.append("service APP_REDIS_HOST is a local address")
    for key in ("APP_REDIS_URL", "APP_REDIS_RESULT_URL"):
        if key in plain and not plain[key].startswith("rediss://"):
            problems.append(f"service {key} is not rediss:// (TLS is required)")
    if "APP_REDIS_URL" not in names and plain.get("APP_REDIS_SSL", "").lower() not in ("true", "1", "yes"):
        if "APP_REDIS_SSL" not in secrets:
            problems.append("APP_REDIS_URL unset and APP_REDIS_SSL is not true; broker would be plain redis://")
    files, unsupported = secret_files(pod, container)
    if unsupported:
        problems.append(f"service uses volumes {unsupported} that are not Secret Manager files; "
                        "add them to the worker pool by hand")
    for key in TLS_FILE_ENV:
        if key in plain and plain[key] not in files:
            problems.append(f"service {key}={plain[key]!r} is not a mounted Secret Manager file")
    if annotations.get("run.googleapis.com/vpc-access-connector"):
        warnings.append("service uses a Serverless VPC connector, which worker pools do not support; "
                        "the worker gets no VPC (fine for the Cloud SQL socket and a public Redis)")
    if problems:
        sys.exit("Not generating worker pool:\n  - " + "\n  - ".join(problems))

    with open("worker-env.yaml", "w", newline="\n") as f:
        for k in sorted(plain):
            f.write(f"{k}: {json.dumps(plain[k])}\n")
        f.write(f"{GUARD_ENV}: {json.dumps(GUARD)}\n")

    limits = container.get("resources", {}).get("limits", {})
    cmd = [
        "gcloud", "run", "worker-pools", "deploy", POOL,
        f"--region={REGION}",
        f"--image={image}",
        f"--instances={INSTANCES}",
        f"--set-cloudsql-instances={INSTANCE}",
        "--env-vars-file=worker-env.yaml",
        "--command=sh",
        f"--args=-c,{ENTRYPOINT}",
        f"--cpu={limits.get('cpu', '1')}",
        f"--memory={limits.get('memory', '1Gi')}",
    ]
    if pod.get("serviceAccountName"):
        cmd.append(f"--service-account={pod['serviceAccountName']}")
    if secrets or files:
        cmd.append("--set-secrets=" + ",".join(
            f"{k}={v}" for k, v in sorted(secrets.items()) + sorted(files.items())))
    nets = json.loads(annotations.get("run.googleapis.com/network-interfaces", "[]") or "[]")
    if nets:
        net = nets[0]
        if net.get("network"):
            cmd.append(f"--network={net['network']}")
        if net.get("subnetwork"):
            cmd.append(f"--subnet={net['subnetwork']}")
        if net.get("tags"):
            cmd.append("--network-tags=" + ",".join(net["tags"]))
        egress = annotations.get("run.googleapis.com/vpc-access-egress")
        if egress:
            cmd.append(f"--vpc-egress={egress}")

    with open("deploy-worker-pool.sh", "w", newline="\n") as f:
        f.write("#!/usr/bin/env bash\nset -euo pipefail\n")
        head, flags = cmd[:5], cmd[5:]
        f.write(" ".join(head) + " \\\n  " + " \\\n  ".join(shlex.quote(c) for c in flags) + "\n")

    print(f"service account: {pod.get('serviceAccountName')}")
    print(f"plain env vars:  {', '.join(sorted(plain))}")
    print(f"secret env vars: {', '.join(f'{k}={v}' for k, v in sorted(secrets.items())) or '-'}")
    print(f"secret files:    {', '.join(f'{k}={v}' for k, v in sorted(files.items())) or '-'}")
    print(f"resources:       cpu={limits.get('cpu', '1')} memory={limits.get('memory', '1Gi')}")
    print(f"network:         {nets[0] if nets else 'none'}")
    for w in warnings:
        print(f"WARNING: {w}")
    print("wrote worker-env.yaml and deploy-worker-pool.sh (review, then: bash deploy-worker-pool.sh)")


main()
