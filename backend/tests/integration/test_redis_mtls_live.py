"""Live mutual-TLS checks against a real TLS endpoint: redis-py, the FastAPI async client,
the rate limiter, Kombu and Celery, plus the connection-check script end to end.

Skipped unless an endpoint is supplied:

    EVECTA_TEST_MTLS_URL    rediss://[:password@]host:port/db   (use a spare db)
    EVECTA_TEST_MTLS_CERT   client certificate (PEM)
    EVECTA_TEST_MTLS_KEY    client private key (PEM)
    EVECTA_TEST_MTLS_CA     CA for the server certificate (optional: system CAs)

Every test uses throwaway keys and a private queue and removes them afterwards.
"""
from __future__ import annotations

import asyncio
import os
import ssl
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote, urlsplit

import pytest
import redis

URL = os.environ.get("EVECTA_TEST_MTLS_URL", "")
CERT = os.environ.get("EVECTA_TEST_MTLS_CERT", "")
KEY = os.environ.get("EVECTA_TEST_MTLS_KEY", "")
CA = os.environ.get("EVECTA_TEST_MTLS_CA", "")

pytestmark = pytest.mark.skipif(
    not (URL and CERT and KEY), reason="EVECTA_TEST_MTLS_URL/CERT/KEY not set — no mTLS endpoint"
)

OPTS = {k: v for k, v in {"ssl_certfile": CERT, "ssl_keyfile": KEY, "ssl_ca_certs": CA}.items() if v}
BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture
def run_id():
    return uuid.uuid4().hex[:10]


def test_redis_py_with_client_certificate(run_id):
    client = redis.Redis.from_url(URL, socket_connect_timeout=5, **OPTS)
    key = f"evecta:mtls-test:{run_id}"
    assert client.ping()
    client.set(key, "ok", ex=30)
    assert client.get(key) == b"ok"
    client.delete(key)


def test_server_rejects_connection_without_client_certificate():
    no_cert = {k: v for k, v in OPTS.items() if k == "ssl_ca_certs"}
    client = redis.Redis.from_url(URL, socket_connect_timeout=5, **no_cert)
    with pytest.raises((redis.ConnectionError, ssl.SSLError, OSError)):
        client.ping()


def test_fastapi_async_client(run_id, monkeypatch):
    from app.core import redis as app_redis

    monkeypatch.setattr(app_redis, "settings", SimpleNamespace(redis_cache_url=URL, redis_ssl_options=OPTS))
    monkeypatch.setattr(app_redis, "_redis", None)

    async def run():
        await app_redis.init_redis()
        try:
            client = app_redis.get_redis()
            await client.set(f"evecta:mtls-test:{run_id}:async", "ok", ex=30)
            assert await client.get(f"evecta:mtls-test:{run_id}:async") == "ok"
            await client.delete(f"evecta:mtls-test:{run_id}:async")
        finally:
            await app_redis.close_redis()

    asyncio.run(run())


def test_rate_limiter(run_id):
    from limits import parse
    from slowapi import Limiter
    from slowapi.util import get_remote_address

    limiter = Limiter(key_func=get_remote_address, storage_uri=URL, storage_options=OPTS)
    assert limiter._storage.check()
    limit = parse("2/minute")
    hits = [limiter._limiter.hit(limit, "evecta-mtls-test", run_id) for _ in range(3)]
    limiter._limiter.clear(limit, "evecta-mtls-test", run_id)
    assert hits == [True, True, False]


def _tls_options():
    from app.core.celery_app import redis_tls_options
    return redis_tls_options(URL, SimpleNamespace(redis_ssl_options=OPTS))


def test_kombu_private_queue_round_trip(run_id):
    from kombu import Connection

    name = f"evecta.mtls-test.{run_id}"
    with Connection(URL, ssl=_tls_options()) as conn:
        queue = conn.SimpleQueue(name)
        try:
            queue.put({"run": run_id})
            message = queue.get(block=True, timeout=10)
            message.ack()
            assert message.payload == {"run": run_id}
        finally:
            queue.queue.delete()
            conn.default_channel.exchange_delete(name)
            queue.close()


def test_celery_publishes_task_over_mtls(run_id):
    from celery import Celery

    name = f"evecta.mtls-test.{run_id}"
    app = Celery("mtls-test", broker=URL)
    app.conf.broker_use_ssl = _tls_options()
    with app.connection_for_write() as conn:
        conn.ensure_connection(max_retries=1)
        app.send_task("evecta.mtls_test.noop", kwargs={"run": run_id}, queue=name, connection=conn)
        queue = conn.SimpleQueue(name)
        try:
            message = queue.get(block=True, timeout=10)
            message.ack()
            assert message.headers["task"] == "evecta.mtls_test.noop"
        finally:
            queue.queue.delete()
            conn.default_channel.exchange_delete(name)
            queue.close()


def test_connection_check_script_end_to_end():
    parts = urlsplit(URL)
    env = {k: v for k, v in os.environ.items() if not k.startswith("APP_REDIS")}
    env.update({
        "APP_REDIS_HOST": parts.hostname, "APP_REDIS_PORT": str(parts.port or 6379),
        "APP_REDIS_DB": (parts.path or "/0").lstrip("/") or "0", "APP_REDIS_SSL": "true",
        "APP_REDIS_SSL_CERTFILE": CERT, "APP_REDIS_SSL_KEYFILE": KEY,
    })
    if parts.password:
        env["APP_REDIS_PASSWORD"] = unquote(parts.password)
    if CA:
        env["APP_REDIS_SSL_CA_CERTS"] = CA
    proc = subprocess.run([sys.executable, "-m", "scripts.redis_connection_check", "--pings", "10"],
                          cwd=BACKEND, env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "SUMMARY: 6/6 passed" in proc.stdout
