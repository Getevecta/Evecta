"""Check the configured Redis end to end without touching application data or queues.

Run inside the application image with the target APP_REDIS_* settings (e.g. as a
one-off Cloud Run job):

    python -m scripts.redis_connection_check [--pings 50]

Every check uses throwaway names (evecta:migration-check:<run id>, a private queue
evecta.migration-check.<run id>) and cleans up after itself; the Celery "celery"
queue, cached data and rate-limit counters of real users are never read or written.
Prints a summary and exits non-zero if any check fails. Never prints the password,
certificate or key contents.
"""
import argparse
import asyncio
import os
import statistics
import sys
import time
import uuid

from app.core.config import get_settings
from app.utils.log_redaction import redact_url_credentials

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{': ' + detail if detail else ''}", flush=True)


def check(name):
    def wrap(fn):
        def run(*args, **kwargs):
            try:
                detail = fn(*args, **kwargs)
                record(name, True, detail or "")
            except Exception as exc:  # report and continue with the next check
                record(name, False, f"{type(exc).__name__}: {exc}")
        return run
    return wrap


def ms(seconds: float) -> str:
    return f"{seconds * 1000:.1f}ms"


@check("TLS files readable")
def check_tls_files(settings):
    files = {
        "APP_REDIS_SSL_CERTFILE": settings.REDIS_SSL_CERTFILE,
        "APP_REDIS_SSL_KEYFILE": settings.REDIS_SSL_KEYFILE,
        "APP_REDIS_SSL_CA_CERTS": settings.REDIS_SSL_CA_CERTS,
    }
    parts = []
    for name, path in files.items():
        if not path:
            continue
        with open(path, "rb") as fh:  # proves this (non-root) user can read the mount
            size = len(fh.read())
        parts.append(f"{name} {size} bytes, uid={os.getuid() if hasattr(os, 'getuid') else '?'}")
    if settings.REDIS_SSL_CERTFILE:
        try:
            from cryptography import x509
            with open(settings.REDIS_SSL_CERTFILE, "rb") as fh:
                cert = x509.load_pem_x509_certificate(fh.read())
            parts.append(f"client cert subject={cert.subject.rfc4514_string()} "
                         f"expires={cert.not_valid_after_utc:%Y-%m-%d}")
        except ImportError:
            pass
    return "; ".join(parts) or "no client certificate configured (plain TLS)"


@check("redis-py ping + latency")
def check_sync(settings, run_id, pings):
    import redis

    client = redis.Redis.from_url(settings.redis_cache_url, socket_connect_timeout=10,
                                  socket_timeout=10, **settings.redis_ssl_options)
    started = time.perf_counter()
    client.ping()
    connect = time.perf_counter() - started
    samples = []
    for _ in range(pings):
        t = time.perf_counter()
        client.ping()
        samples.append(time.perf_counter() - t)
    key = f"evecta:migration-check:{run_id}"
    client.set(key, "ok", ex=60)
    if client.get(key) != b"ok":
        raise RuntimeError("SET/GET round trip returned the wrong value")
    client.delete(key)
    try:
        version = client.info("server").get("redis_version")
    except redis.ResponseError:  # INFO can be disabled/renamed on a hardened server
        version = "unknown (INFO not allowed)"
    client.close()
    samples.sort()
    return (f"server redis {version}; connect+first ping {ms(connect)}; "
            f"{pings} pings p50 {ms(statistics.median(samples))} "
            f"p95 {ms(samples[int(len(samples) * 0.95) - 1])} max {ms(samples[-1])}")


@check("FastAPI async client (app.core.redis)")
def check_async(settings, run_id):
    from app.core import redis as app_redis

    async def run():
        await app_redis.init_redis()
        try:
            client = app_redis.get_redis()
            key = f"evecta:migration-check:{run_id}:async"
            await client.set(key, "ok", ex=60)
            value = await client.get(key)
            await client.delete(key)
            if value != "ok":
                raise RuntimeError("async SET/GET round trip returned the wrong value")
        finally:
            await app_redis.close_redis()

    asyncio.run(run())


@check("rate limiter storage (slowapi/limits)")
def check_limiter(settings, run_id):
    from limits import parse
    from limits.storage import storage_from_string
    from limits.strategies import FixedWindowRateLimiter

    storage = storage_from_string(settings.redis_cache_url, **settings.redis_ssl_options)
    if not storage.check():
        raise RuntimeError("limits storage check() returned False")
    limiter = FixedWindowRateLimiter(storage)
    limit = parse("2/minute")
    hits = [limiter.hit(limit, "evecta-migration-check", run_id) for _ in range(3)]
    limiter.clear(limit, "evecta-migration-check", run_id)
    if hits != [True, True, False]:
        raise RuntimeError(f"unexpected limiter results {hits}")
    return "fixed window allowed 2, blocked the 3rd"


@check("Celery broker (Kombu) private queue round trip")
def check_broker(settings, run_id):
    from app.core.celery_app import celery_app

    queue_name = f"evecta.migration-check.{run_id}"
    with celery_app.connection_for_write() as conn:
        conn.ensure_connection(max_retries=2)
        queue = conn.SimpleQueue(queue_name)
        try:
            started = time.perf_counter()
            queue.put({"run": run_id})
            message = queue.get(block=True, timeout=15)
            message.ack()
            elapsed = time.perf_counter() - started
            if message.payload != {"run": run_id}:
                raise RuntimeError("received a different message")
        finally:
            queue.queue.delete()
            try:
                conn.default_channel.exchange_delete(queue_name)
            except Exception:
                pass
            queue.close()
    return f"publish+consume {ms(elapsed)} on {queue_name}"


@check("Celery result backend")
def check_result_backend(settings, run_id):
    if not settings.REDIS_RESULT_URL:
        return "skipped: APP_REDIS_RESULT_URL unset (results disabled)"
    from app.core.celery_app import celery_app

    celery_app.backend.client.ping()
    return "ping ok"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pings", type=int, default=50)
    args = parser.parse_args()

    settings = get_settings()  # raises here if a configured TLS file is missing/unreadable
    run_id = uuid.uuid4().hex[:12]
    print(f"run {run_id}: cache={redact_url_credentials(settings.redis_cache_url)} "
          f"broker={redact_url_credentials(settings.REDIS_URL)} "
          f"result={redact_url_credentials(settings.REDIS_RESULT_URL) or '-'} "
          f"client_cert={'yes' if settings.REDIS_SSL_CERTFILE else 'no'}", flush=True)

    check_tls_files(settings)
    check_sync(settings, run_id, args.pings)
    check_async(settings, run_id)
    check_limiter(settings, run_id)
    check_broker(settings, run_id)
    check_result_backend(settings, run_id)

    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"SUMMARY: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f"; failed: {', '.join(failed)}" if failed else ""), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
