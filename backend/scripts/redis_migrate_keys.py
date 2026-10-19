"""Copy chat thread ids and admin device-trust keys between Redis servers, keeping TTLs.

Optional, one-off, for the Upstash -> Hostinger switch (or back). Everything else in
Redis is disposable: caches refill, rate-limit windows and lockouts reset, OAuth / 2FA
state lives for minutes, and Celery queues must be drained before switching rather
than copied.

    thread:*              chat thread id per user (30-day TTL); without it a user's
                          next chat starts a new thread (history stays in Postgres)
    admin_device_trust:*  "trust this device" for admin 2FA; without it admins
                          repeat 2FA once

Connections come from the environment so passwords never appear in the process list:

    SOURCE_REDIS_URL, TARGET_REDIS_URL      rediss://:password@host:port/db
    SOURCE_REDIS_SSL_CERTFILE / _KEYFILE / _CA_CERTS   (optional, mutual TLS)
    TARGET_REDIS_SSL_CERTFILE / _KEYFILE / _CA_CERTS   (optional, mutual TLS)

    python -m scripts.redis_migrate_keys                 # dry run: count only
    python -m scripts.redis_migrate_keys --execute       # copy
    python -m scripts.redis_migrate_keys --execute --replace   # also overwrite target keys

Keys that already exist on the target are left alone unless --replace is given, so a
re-run after the switch never overwrites state written by the new deployment. Keys
are copied as strings (GET/SET PX); other types fall back to DUMP/RESTORE. Values are
never printed.
"""
import argparse
import os
import sys

import redis

PATTERNS = ("thread:*", "admin_device_trust:*")


def connect(prefix: str) -> redis.Redis:
    url = os.environ.get(f"{prefix}_REDIS_URL")
    if not url:
        sys.exit(f"{prefix}_REDIS_URL is not set")
    options = {
        name: os.environ[f"{prefix}_REDIS_{env}"]
        for name, env in (("ssl_certfile", "SSL_CERTFILE"), ("ssl_keyfile", "SSL_KEYFILE"),
                          ("ssl_ca_certs", "SSL_CA_CERTS"))
        if os.environ.get(f"{prefix}_REDIS_{env}")
    }
    client = redis.Redis.from_url(url, socket_connect_timeout=10, socket_timeout=30, **options)
    client.ping()
    return client


def copy_key(source: redis.Redis, target: redis.Redis, key: bytes, *, replace: bool) -> str:
    """Copy one key. Returns 'copied', 'exists', 'expired' or 'unsupported'."""
    ttl_ms = source.pttl(key)
    if ttl_ms == -2:
        return "expired"
    if not replace and target.exists(key):
        return "exists"
    px = ttl_ms if ttl_ms > 0 else None  # -1 = no expiry
    if source.type(key) == b"string":
        value = source.get(key)
        if value is None:
            return "expired"
        target.set(key, value, px=px)
        return "copied"
    payload = source.dump(key)
    if payload is None:
        return "expired"
    try:
        target.restore(key, px or 0, payload, replace=True)
    except redis.ResponseError:
        return "unsupported"  # e.g. DUMP format from a newer server version
    return "copied"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--execute", action="store_true", help="copy (default: dry run)")
    parser.add_argument("--replace", action="store_true", help="overwrite keys already on the target")
    args = parser.parse_args()

    source, target = connect("SOURCE"), connect("TARGET")
    if source.connection_pool.connection_kwargs.get("host") == target.connection_pool.connection_kwargs.get("host") \
            and source.connection_pool.connection_kwargs.get("port") == target.connection_pool.connection_kwargs.get("port"):
        sys.exit("SOURCE and TARGET point at the same server")

    totals: dict[str, dict[str, int]] = {}
    for pattern in PATTERNS:
        counts = totals.setdefault(pattern, {})
        for key in source.scan_iter(match=pattern, count=500):
            if not args.execute:
                result = "would copy" if source.pttl(key) != -2 else "expired"
            else:
                result = copy_key(source, target, key, replace=args.replace)
            counts[result] = counts.get(result, 0) + 1

    mode = "EXECUTE" if args.execute else "DRY RUN"
    for pattern, counts in totals.items():
        summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "no keys"
        print(f"[{mode}] {pattern}: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
