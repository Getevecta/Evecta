"""
Create or promote a platform admin without storing credentials in .env or source.

Usage (from the backend directory):

    python -m scripts.create_admin
    python -m scripts.create_admin --email you@company.com
    python -m scripts.create_admin --email you@company.com --reset-password

The password is read interactively (hidden input), validated, hashed with bcrypt,
and only the hash is written to the database. Plaintext never touches disk or logs.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys


def _prompt_email(cli_email: str | None) -> str:
    from app.services.admin_bootstrap import SOLE_ADMIN_EMAIL

    if cli_email and cli_email.strip():
        email = cli_email.strip().lower()
    else:
        raw = input(f"Admin email [{SOLE_ADMIN_EMAIL}]: ").strip().lower()
        email = raw or SOLE_ADMIN_EMAIL
    if not email or "@" not in email:
        print("Error: a valid email is required.", file=sys.stderr)
        sys.exit(1)
    if email != SOLE_ADMIN_EMAIL:
        print(
            f"Error: only {SOLE_ADMIN_EMAIL} may be the platform admin "
            f"(refusing {email}).",
            file=sys.stderr,
        )
        sys.exit(1)
    return email


def _prompt_username(default: str) -> str:
    raw = input(f"Username [{default}]: ").strip()
    return raw or default


def _prompt_password(*, email: str) -> str:
    password = getpass.getpass("Admin password (hidden): ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Error: passwords do not match.", file=sys.stderr)
        sys.exit(1)
    if not password:
        print("Error: password cannot be empty.", file=sys.stderr)
        sys.exit(1)
    # Validate early so we fail before touching the DB
    from app.utils.jwt import validate_password_not_email

    ok, err = validate_password_not_email(password, email)
    if not ok:
        print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)
    return password


async def _run(email: str, username: str | None, reset_password: bool) -> None:
    from app.database.session import async_session_factory
    from app.services.admin_bootstrap import create_or_update_admin

    # Decide whether we need a password before prompting (new user or reset).
    from sqlalchemy import func, select

    from app.models.user import User

    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(func.lower(User.email) == email)
        )
        existing = result.scalar_one_or_none()

        need_password = existing is None or reset_password
        password: str | None = None
        if need_password:
            if not sys.stdin.isatty():
                print(
                    "Error: password must be entered interactively in a terminal "
                    "(not piped). This keeps credentials out of shell history and files.",
                    file=sys.stderr,
                )
                sys.exit(1)
            password = _prompt_password(email=email)
        elif existing is not None and not reset_password:
            print(
                f"User {email} already exists — promoting to admin without changing password.\n"
                "Pass --reset-password to set a new password."
            )

        uname = username
        if uname is None and sys.stdin.isatty():
            default = (existing.username if existing else None) or email.split("@")[0]
            uname = _prompt_username(default)

        user, action = await create_or_update_admin(
            session,
            email=email,
            username=uname,
            password=password,
            reset_password=reset_password,
        )

    messages = {
        "created": f"Admin created: {user.email} (id={user.id})",
        "promoted": f"Existing user promoted to admin: {user.email} (id={user.id})",
        "password_reset": f"Admin password reset + privileges ensured: {user.email} (id={user.id})",
    }
    print(messages.get(action, f"Done ({action}): {user.email}"))
    print("Password is stored as bcrypt only — plaintext was not written anywhere.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Securely create or promote an Evecta admin (interactive password)."
    )
    parser.add_argument("--email", help="Admin email (prompted if omitted)")
    parser.add_argument("--username", help="Admin username (prompted if omitted)")
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="Reset password for an existing user (interactive)",
    )
    args = parser.parse_args()

    email = _prompt_email(args.email)
    try:
        asyncio.run(_run(email, args.username, args.reset_password))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
