"""Redis TLS / mutual-TLS configuration across every client, without a Redis server.

Covers the settings (URL, client-certificate options, startup validation of the
secret files), the options each client actually receives (redis-py sync + async,
the slowapi/limits rate limiter, Kombu via Celery, the Celery result backend), the
worker/Beat pool generators that copy the certificate mounts, and that the existing
Upstash (TLS, no client certificate) and plain local setups are unchanged.
"""
from __future__ import annotations

import importlib
import json
import ssl
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import redis

from app.core.config import Settings

BACKEND = Path(__file__).resolve().parents[2]
SCRIPTS = BACKEND / "scripts"

REQUIRED = dict(
    SECRET_KEY="x" * 40, POSTGRES_USER="u", POSTGRES_PASSWORD="p", POSTGRES_DB="d",
    POSTGRES_HOST="localhost", ALGORITHM="HS256", ACCESS_TOKEN_EXPIRE_MINUTES=1,
    REFRESH_TOKEN_EXPIRE_DAYS=1, GOOGLE_CLIENT_ID="x", GOOGLE_CLIENT_SECRET="x",
    GOOGLE_REDIRECT_URI="x", MAILBOX_GOOGLE_REDIRECT_URI="x", GOOGLE_MAPS_API_KEY="x",
    GEMINI_API_KEY="x", GEMINI_MODEL="x", BREVO_API_KEY="x", BREVO_WEBHOOK_TOKEN="x",
    EMAIL_TRACKING_BASE_URL="x", MAILBOX_SECRET_KEY="x",
)


def make_settings(**overrides) -> Settings:
    values = dict(REQUIRED, REDIS_URL=None, REDIS_RESULT_URL=None, REDIS_PASSWORD=None,
                  REDIS_SSL_CERTFILE=None, REDIS_SSL_KEYFILE=None, REDIS_SSL_CA_CERTS=None)
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def tls_files(tmp_path):
    files = {}
    for name in ("client.crt", "client.key", "ca.crt"):
        path = tmp_path / name
        path.write_text(f"-----BEGIN TEST {name}-----\n")
        files[name] = str(path)
    return files


@pytest.fixture
def hostinger(tls_files):
    return make_settings(
        REDIS_HOST="redis.newaflix.com", REDIS_PORT=6380, REDIS_SSL=True,
        REDIS_PASSWORD="p@ss:w/rd#1",
        REDIS_SSL_CERTFILE=tls_files["client.crt"], REDIS_SSL_KEYFILE=tls_files["client.key"],
    )


# ── Existing configurations: unchanged ───────────────────────────────────────

def test_upstash_tls_without_client_certificate_is_unchanged():
    s = make_settings(REDIS_HOST="apt-x.upstash.io", REDIS_SSL=True, REDIS_PASSWORD="p@ss/w:rd")
    assert s.redis_cache_url == "rediss://:p%40ss%2Fw%3Ard@apt-x.upstash.io:6379/0"
    assert s.REDIS_URL == s.redis_cache_url
    assert s.redis_ssl_options == {}

    from app.core.celery_app import redis_tls_options
    assert redis_tls_options(s.REDIS_URL, s) == {"ssl_cert_reqs": ssl.CERT_REQUIRED}

    pool = redis.Redis.from_url(s.redis_cache_url, **s.redis_ssl_options).connection_pool
    assert pool.connection_class is redis.SSLConnection
    assert pool.connection_kwargs.get("ssl_certfile") is None
    assert pool.connection_kwargs["password"] == "p@ss/w:rd"


def test_plain_local_redis_is_unchanged():
    s = make_settings(REDIS_HOST="localhost")
    assert s.redis_cache_url == "redis://localhost:6379/0"
    assert s.redis_ssl_options == {}
    from app.core.celery_app import redis_tls_options
    assert redis_tls_options(s.REDIS_URL, s) is None
    assert redis.Redis.from_url(s.redis_cache_url).connection_pool.connection_class is redis.Connection


def test_explicit_redis_url_still_wins(tls_files):
    s = make_settings(REDIS_HOST="h", REDIS_SSL=True, REDIS_URL="rediss://:pw@other:6379/0")
    assert s.REDIS_URL == "rediss://:pw@other:6379/0"


# ── Mutual TLS settings ───────────────────────────────────────────────────────

def test_mtls_options_and_url(hostinger, tls_files):
    assert hostinger.redis_cache_url == "rediss://:p%40ss%3Aw%2Frd%231@redis.newaflix.com:6380/0"
    assert hostinger.redis_ssl_options == {
        "ssl_certfile": tls_files["client.crt"], "ssl_keyfile": tls_files["client.key"],
    }
    assert "client" not in hostinger.REDIS_URL  # certificates never go into the (logged) URL


def test_custom_ca_is_optional_and_passed_through(tls_files):
    s = make_settings(REDIS_HOST="h", REDIS_SSL=True, REDIS_SSL_CERTFILE=tls_files["client.crt"],
                      REDIS_SSL_KEYFILE=tls_files["client.key"], REDIS_SSL_CA_CERTS=tls_files["ca.crt"])
    assert s.redis_ssl_options["ssl_ca_certs"] == tls_files["ca.crt"]


# ── Secret file accessibility (startup validation) ────────────────────────────

def test_certificate_without_key_is_rejected(tls_files):
    with pytest.raises(ValueError, match="must be set together"):
        make_settings(REDIS_SSL=True, REDIS_SSL_CERTFILE=tls_files["client.crt"])


def test_key_without_certificate_is_rejected(tls_files):
    with pytest.raises(ValueError, match="must be set together"):
        make_settings(REDIS_SSL=True, REDIS_SSL_KEYFILE=tls_files["client.key"])


def test_missing_secret_file_is_rejected(tls_files, tmp_path):
    with pytest.raises(ValueError, match="APP_REDIS_SSL_KEYFILE=.*not a readable file"):
        make_settings(REDIS_SSL=True, REDIS_SSL_CERTFILE=tls_files["client.crt"],
                      REDIS_SSL_KEYFILE=str(tmp_path / "missing.key"))


def test_directory_instead_of_file_is_rejected(tls_files, tmp_path):
    with pytest.raises(ValueError, match="APP_REDIS_SSL_CERTFILE=.*not a readable file"):
        make_settings(REDIS_SSL=True, REDIS_SSL_CERTFILE=str(tmp_path),
                      REDIS_SSL_KEYFILE=tls_files["client.key"])


def test_unreadable_secret_file_is_rejected(tls_files, monkeypatch):
    import app.core.config as config
    monkeypatch.setattr(config.os, "access", lambda path, mode: not path.endswith("client.key"))
    with pytest.raises(ValueError, match="APP_REDIS_SSL_KEYFILE=.*not a readable file"):
        make_settings(REDIS_SSL=True, REDIS_SSL_CERTFILE=tls_files["client.crt"],
                      REDIS_SSL_KEYFILE=tls_files["client.key"])


def test_client_certificate_requires_tls(tls_files):
    with pytest.raises(ValueError, match="APP_REDIS_SSL is false"):
        make_settings(REDIS_SSL=False, REDIS_SSL_CERTFILE=tls_files["client.crt"],
                      REDIS_SSL_KEYFILE=tls_files["client.key"])


# ── What each client receives ─────────────────────────────────────────────────

def test_redis_py_sync_client_gets_client_certificate(hostinger, tls_files):
    pool = redis.Redis.from_url(hostinger.redis_cache_url, **hostinger.redis_ssl_options).connection_pool
    assert pool.connection_class is redis.SSLConnection
    assert pool.connection_kwargs["ssl_certfile"] == tls_files["client.crt"]
    assert pool.connection_kwargs["ssl_keyfile"] == tls_files["client.key"]
    # Not overridden, so SSLConnection's default ("required") verifies the server.
    assert pool.connection_kwargs.get("ssl_cert_reqs", "required") == "required"
    assert pool.connection_kwargs["host"] == "redis.newaflix.com" and pool.connection_kwargs["port"] == 6380


def test_fastapi_async_client_gets_client_certificate(hostinger, tls_files, monkeypatch):
    import asyncio

    from app.core import redis as app_redis

    captured = {}

    class FakeRedis:
        async def ping(self):
            return True

    def fake_from_url(url, **kwargs):
        captured.update(url=url, **kwargs)
        return FakeRedis()

    monkeypatch.setattr(app_redis, "settings", hostinger)
    monkeypatch.setattr(app_redis.Redis, "from_url", staticmethod(fake_from_url))
    monkeypatch.setattr(app_redis, "_redis", None)
    asyncio.run(app_redis.init_redis())
    assert captured["url"] == hostinger.redis_cache_url
    assert captured["ssl_certfile"] == tls_files["client.crt"]
    assert captured["ssl_keyfile"] == tls_files["client.key"]
    assert captured["decode_responses"] is True


def test_sync_cache_client_module_gets_client_certificate(hostinger, tls_files, monkeypatch):
    import app.core.config as config
    import app.utils.redis_context as redis_context

    saved = {k: getattr(redis_context, k) for k in ("settings", "redis_client", "REDIS_AVAILABLE")}
    captured = {}

    class FakeClient:
        def ping(self):
            return True

    def fake_from_url(url, **kwargs):
        captured.update(url=url, **kwargs)
        return FakeClient()

    monkeypatch.setattr(config, "get_settings", lambda: hostinger)
    monkeypatch.setattr(redis.Redis, "from_url", staticmethod(fake_from_url))
    try:
        importlib.reload(redis_context)
        assert captured["ssl_certfile"] == tls_files["client.crt"]
        assert captured["ssl_keyfile"] == tls_files["client.key"]
        assert captured["health_check_interval"] == 30  # existing options kept
    finally:
        for k, v in saved.items():
            setattr(redis_context, k, v)


def test_rate_limiter_storage_gets_client_certificate(hostinger, tls_files):
    from slowapi import Limiter
    from slowapi.util import get_remote_address

    limiter = Limiter(key_func=get_remote_address, storage_uri=hostinger.redis_cache_url,
                      storage_options=hostinger.redis_ssl_options)
    pool = limiter._storage.storage.connection_pool
    assert pool.connection_class is redis.SSLConnection
    assert pool.connection_kwargs["ssl_certfile"] == tls_files["client.crt"]
    assert pool.connection_kwargs["ssl_keyfile"] == tls_files["client.key"]


def test_app_rate_limiter_is_built_with_the_tls_options():
    from app.core.config import get_settings
    from app.core.limiter import limiter
    assert limiter._storage_options == get_settings().redis_ssl_options


def test_celery_broker_and_backend_get_client_certificate(hostinger, tls_files):
    from celery import Celery
    from app.core.celery_app import redis_tls_options

    url = hostinger.REDIS_URL
    opts = redis_tls_options(url, hostinger)
    assert opts == {"ssl_cert_reqs": ssl.CERT_REQUIRED,
                    "ssl_certfile": tls_files["client.crt"], "ssl_keyfile": tls_files["client.key"]}

    app = Celery("t", broker=url, backend=url)
    app.conf.broker_use_ssl = opts
    app.conf.redis_backend_use_ssl = opts
    assert app.connection_for_write().ssl == opts  # what Kombu copies into its connection params
    params = app.backend.connparams
    assert params["connection_class"] is redis.SSLConnection
    assert params["ssl_certfile"] == tls_files["client.crt"]
    assert params["ssl_keyfile"] == tls_files["client.key"]
    assert params["ssl_cert_reqs"] == ssl.CERT_REQUIRED


# ── Connection check script: secret file readability ──────────────────────────

def test_connection_check_reads_mounted_certificate(tmp_path):
    from datetime import datetime, timedelta, timezone

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "evecta-client")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(1)
            .not_valid_before(now).not_valid_after(now + timedelta(days=30)).sign(key, hashes.SHA256()))
    crt, pem_key = tmp_path / "client.crt", tmp_path / "client.key"
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    pem_key.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    s = make_settings(REDIS_HOST="h", REDIS_SSL=True, REDIS_SSL_CERTFILE=str(crt), REDIS_SSL_KEYFILE=str(pem_key))

    from scripts import redis_connection_check as check
    check.RESULTS.clear()
    check.check_tls_files(s)
    name, ok, detail = check.RESULTS[-1]
    assert ok, detail
    assert "CN=evecta-client" in detail and "APP_REDIS_SSL_KEYFILE" in detail


# ── Worker / Beat pool generators copy the certificate mounts ─────────────────

def _env(*pairs):
    return [{"name": k, "value": v} for k, v in pairs]


SECRET_VOLUMES = [
    {"name": "redis-cert", "secret": {"secretName": "evecta-redis-client-cert",
                                      "items": [{"key": "1", "path": "client.crt"}]}},
    {"name": "redis-key", "secret": {"secretName": "evecta-redis-client-key",
                                     "items": [{"key": "1", "path": "client.key"}]}},
]
SECRET_MOUNTS = [{"name": "redis-cert", "mountPath": "/secrets/redis-cert"},
                 {"name": "redis-key", "mountPath": "/secrets/redis-key"}]
HOSTINGER_ENV = _env(
    ("APP_POSTGRES_HOST", "/cloudsql/evecta:asia-southeast1:evecta-hackathon-db"),
    ("APP_POSTGRES_DB", "evecta_hackathon"), ("APP_REDIS_HOST", "redis.newaflix.com"),
    ("APP_REDIS_PORT", "6380"), ("APP_REDIS_SSL", "true"),
    ("APP_REDIS_SSL_CERTFILE", "/secrets/redis-cert/client.crt"),
    ("APP_REDIS_SSL_KEYFILE", "/secrets/redis-key/client.key"),
) + [{"name": "APP_REDIS_PASSWORD", "valueFrom": {"secretKeyRef": {"name": "evecta-redis-password", "key": "1"}}}]
FILE_SECRETS = ("/secrets/redis-cert/client.crt=evecta-redis-client-cert:1",
                "/secrets/redis-key/client.key=evecta-redis-client-key:1")


def _template(env, volumes, mounts, args):
    return {
        "metadata": {"annotations": {
            "run.googleapis.com/cloudsql-instances": "evecta:asia-southeast1:evecta-hackathon-db"}},
        "spec": {"serviceAccountName": "sa@evecta.iam.gserviceaccount.com",
                 "volumes": volumes,
                 "containers": [{"image": "img@sha256:abc", "command": ["sh"], "args": args,
                                 "resources": {"limits": {"cpu": "1", "memory": "1Gi"}},
                                 "env": env, "volumeMounts": mounts}]},
    }


def _run(script, workdir, *args):
    return subprocess.run([sys.executable, "-I", str(SCRIPTS / script), *args], cwd=workdir,
                          capture_output=True, text=True)


def test_worker_generator_copies_certificate_mounts(tmp_path):
    svc = {"spec": {"template": _template(HOSTINGER_ENV, SECRET_VOLUMES, SECRET_MOUNTS, [])}}
    (tmp_path / "service.json").write_text(json.dumps(svc))
    proc = _run("make_worker_pool.py", tmp_path, "service.json", "img@sha256:abc")
    assert proc.returncode == 0, proc.stderr + proc.stdout
    deploy = (tmp_path / "deploy-worker-pool.sh").read_text()
    for item in FILE_SECRETS + ("APP_REDIS_PASSWORD=evecta-redis-password:1",):
        assert item in deploy
    guard = json.loads((tmp_path / "worker-env.yaml").read_text().split("EVECTA_WORKER_GUARD: ", 1)[1])
    compile(guard, "guard", "exec")
    assert "**tls" in guard  # guard pings Redis with the client certificate


def test_worker_generator_refuses_unmounted_certificate_path(tmp_path):
    svc = {"spec": {"template": _template(HOSTINGER_ENV, SECRET_VOLUMES[:1], SECRET_MOUNTS[:1], [])}}
    (tmp_path / "service.json").write_text(json.dumps(svc))
    proc = _run("make_worker_pool.py", tmp_path, "service.json", "img")
    assert proc.returncode != 0
    assert "APP_REDIS_SSL_KEYFILE" in proc.stderr and "not a mounted Secret Manager file" in proc.stderr
    assert not (tmp_path / "deploy-worker-pool.sh").exists()


def test_worker_generator_refuses_non_secret_volume(tmp_path):
    volumes = SECRET_VOLUMES + [{"name": "scratch", "emptyDir": {}}]
    mounts = SECRET_MOUNTS + [{"name": "scratch", "mountPath": "/scratch"}]
    svc = {"spec": {"template": _template(HOSTINGER_ENV, volumes, mounts, [])}}
    (tmp_path / "service.json").write_text(json.dumps(svc))
    proc = _run("make_worker_pool.py", tmp_path, "service.json", "img")
    assert proc.returncode != 0 and "['scratch']" in proc.stderr


def test_worker_generator_upstash_output_has_no_secret_files(tmp_path):
    env = _env(("APP_POSTGRES_HOST", "/cloudsql/evecta:asia-southeast1:evecta-hackathon-db"),
               ("APP_POSTGRES_DB", "evecta_hackathon"), ("APP_REDIS_HOST", "apt-x.upstash.io"),
               ("APP_REDIS_SSL", "true"))
    (tmp_path / "service.json").write_text(json.dumps({"spec": {"template": _template(env, [], [], [])}}))
    proc = _run("make_worker_pool.py", tmp_path, "service.json", "img")
    assert proc.returncode == 0, proc.stderr
    assert "/secrets/" not in (tmp_path / "deploy-worker-pool.sh").read_text()
    assert "secret files:    -" in proc.stdout


def test_beat_generator_copies_certificate_mounts(tmp_path):
    worker_args = ["-c", 'python -c "$EVECTA_WORKER_GUARD" && exec celery -A app.core.celery_app '
                         "worker -P threads -c 4 --loglevel=info"]
    env = HOSTINGER_ENV + _env(("EVECTA_WORKER_GUARD", "print('guard')"))
    worker = {"apiVersion": "run.googleapis.com/v1", "kind": "WorkerPool",
              "metadata": {"name": "evecta-celery-worker"},
              "spec": {"template": _template(env, SECRET_VOLUMES, SECRET_MOUNTS, worker_args)}}
    (tmp_path / "worker.json").write_text(json.dumps(worker))
    (tmp_path / "pools.json").write_text(json.dumps([worker]))
    proc = _run("make_beat_pool.py", tmp_path, "worker.json", "pools.json")
    assert proc.returncode == 0, proc.stderr + proc.stdout
    deploy = (tmp_path / "deploy-beat-pool.sh").read_text()
    for item in FILE_SECRETS:
        assert item in deploy
    runner = json.loads((tmp_path / "beat-env.yaml").read_text().split("EVECTA_BEAT_RUNNER: ", 1)[1])
    compile(runner, "runner", "exec")
    assert 'getattr(_settings, "redis_ssl_options", {})' in runner  # leader lock uses the certificate


def test_beat_generator_still_refuses_duplicate_beat(tmp_path):
    args = ["-c", "celery -A app.core.celery_app worker -B"]
    env = HOSTINGER_ENV + _env(("EVECTA_WORKER_GUARD", "print('guard')"))
    worker = {"metadata": {"name": "evecta-celery-worker"},
              "spec": {"template": _template(env, SECRET_VOLUMES, SECRET_MOUNTS, args)}}
    (tmp_path / "worker.json").write_text(json.dumps(worker))
    (tmp_path / "pools.json").write_text(json.dumps([worker]))
    proc = _run("make_beat_pool.py", tmp_path, "worker.json", "pools.json")
    assert proc.returncode != 0 and "already runs Beat" in proc.stderr
