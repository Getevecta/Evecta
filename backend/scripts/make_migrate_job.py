"""Build a Cloud Run Job spec that runs Alembic, cloned from the live service.

Usage (Cloud Shell): python3 backend/scripts/make_migrate_job.py service.json IMAGE_DIGEST > evecta-migrate.json
Copies env (incl. Secret Manager refs), service account, Cloud SQL / VPC
annotations and secret volumes from the service; adds a guard that refuses to
touch anything but the hackathon database.
"""
import json
import sys

INSTANCE = "evecta:asia-southeast1:evecta-hackathon-db"
SOCKET = "/cloudsql/" + INSTANCE
DB = "evecta_hackathon"
COPY_ANNOTATIONS = (
    "run.googleapis.com/cloudsql-instances",
    "run.googleapis.com/vpc-access-connector",
    "run.googleapis.com/vpc-access-egress",
    "run.googleapis.com/network-interfaces",
)

GUARD = f'''
import sys
from urllib.parse import quote
from app.core.config import get_settings
s = get_settings()
print(f"[guard] host={{s.POSTGRES_HOST}} db={{s.POSTGRES_DB}} user={{s.POSTGRES_USER}} "
      f"environment={{s.ENVIRONMENT}} DATABASE_URL_set={{bool(s.DATABASE_URL)}}")
errors = []
if s.DATABASE_URL:
    errors.append("APP_DATABASE_URL is set and would override the target")
if s.POSTGRES_HOST != "{SOCKET}":
    errors.append("APP_POSTGRES_HOST is not {SOCKET}")
if s.POSTGRES_DB != "{DB}":
    errors.append("APP_POSTGRES_DB is not {DB}")
if not hasattr(type(s), "redis_cache_url"):
    errors.append("image predates the Cloud SQL socket fix (commit e7fd77d); rebuild")
elif quote(s.POSTGRES_PASSWORD, safe="") != s.POSTGRES_PASSWORD and \\
        '"%%"' not in open("alembic/env.py").read():
    errors.append("password has URL-special characters and this image's alembic/env.py "
                  "lacks the %% escaping fix; rebuild the image")
if errors:
    print("[guard] REFUSING TO RUN:\\n  - " + "\\n  - ".join(errors))
    sys.exit(1)
print("[guard] OK: target is {DB} on {INSTANCE}")
'''

SCRIPT = f'''set -e
python - <<'PY'
{GUARD}
PY
case "${{ALEMBIC_ACTION:-check}}" in
  check)   alembic heads; alembic current ;;
  upgrade) alembic upgrade head; alembic current ;;
  *) echo "ALEMBIC_ACTION must be check or upgrade"; exit 2 ;;
esac
'''


def main():
    service_path, image = sys.argv[1], sys.argv[2]
    svc = json.load(open(service_path))
    tmpl = svc["spec"]["template"]
    pod = tmpl["spec"]
    container = pod["containers"][0]
    env = [e for e in container.get("env", []) if e["name"] != "ALEMBIC_ACTION"]
    names = {e["name"]: e for e in env}

    problems = []
    annotations = {k: v for k, v in tmpl.get("metadata", {}).get("annotations", {}).items()
                   if k in COPY_ANNOTATIONS}
    if INSTANCE not in annotations.get("run.googleapis.com/cloudsql-instances", ""):
        problems.append(f"service is not connected to Cloud SQL instance {INSTANCE}")
    annotations["run.googleapis.com/cloudsql-instances"] = INSTANCE
    if "APP_DATABASE_URL" in names:
        problems.append("service sets APP_DATABASE_URL (overrides APP_POSTGRES_*)")
    for key, want in (("APP_POSTGRES_HOST", SOCKET), ("APP_POSTGRES_DB", DB)):
        e = names.get(key)
        if e is None:
            problems.append(f"service has no {key}")
        elif "value" in e and e["value"] != want:
            problems.append(f"service {key}={e['value']!r}, expected {want!r}")
    if problems:
        sys.exit("Not generating job:\n  - " + "\n  - ".join(problems))

    job_container = {
        "image": image,
        "command": ["sh", "-c"],
        "args": [SCRIPT],
        "env": env + [{"name": "ALEMBIC_ACTION", "value": "check"}],
        "resources": {"limits": {"cpu": "1", "memory": "1Gi"}},
    }
    if container.get("volumeMounts"):
        job_container["volumeMounts"] = container["volumeMounts"]
    task_spec = {
        "maxRetries": 0,
        "timeoutSeconds": 1800,
        "serviceAccountName": pod.get("serviceAccountName"),
        "containers": [job_container],
    }
    if pod.get("volumes"):
        task_spec["volumes"] = pod["volumes"]

    job = {
        "apiVersion": "run.googleapis.com/v1",
        "kind": "Job",
        "metadata": {"name": "evecta-migrate"},
        "spec": {"template": {
            "metadata": {"annotations": annotations},
            "spec": {"taskCount": 1, "parallelism": 1, "template": {"spec": task_spec}},
        }},
    }
    json.dump(job, sys.stdout, indent=2)
    print(f"\nservice account: {task_spec['serviceAccountName']}\n"
          f"env vars copied: {', '.join(sorted(names))}\n"
          f"annotations: {annotations}", file=sys.stderr)


main()
