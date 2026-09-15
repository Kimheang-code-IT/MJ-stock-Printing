"""Delete ALL application data (keeps the schema and `alembic_version`).

Usage:
    python scripts/clear_data.py            # asks for confirmation
    python scripts/clear_data.py --yes      # no prompt
    python scripts/clear_data.py --no-redis # keep Redis (sessions, locks, tokens)

Inside Compose (recommended; uses the api image + DATABASE_URL/REDIS_URL):
    docker compose -f infrastructure/docker-compose.yml run --rm api \
        python scripts/clear_data.py --yes

Run locally without DATABASE_URL set: the connection is derived from
infrastructure/.env (Postgres on localhost:55432, Redis on localhost:56379).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INFRA_ENV = REPO_ROOT / "infrastructure" / ".env"


def _env_file_value(path: Path, key: str) -> str | None:
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        if name.strip() == key:
            return value.strip().strip('"').strip("'")
    return None


def resolve_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    user = os.environ.get("POSTGRES_USER") or _env_file_value(INFRA_ENV, "POSTGRES_USER") or "stock_pos"
    password = os.environ.get("POSTGRES_PASSWORD") or _env_file_value(INFRA_ENV, "POSTGRES_PASSWORD") or "stock_pos"
    database = os.environ.get("POSTGRES_DB") or _env_file_value(INFRA_ENV, "POSTGRES_DB") or "stock_pos"
    return f"postgresql+asyncpg://{user}:{password}@localhost:55432/{database}"


def resolve_redis_url() -> str:
    return os.environ.get("REDIS_URL") or "redis://localhost:56379/0"


def mask_url(url: str) -> str:
    return re.sub(r"(://[^:/@]+:)[^@]+(@)", r"\1***\2", url)


async def clear_postgres(database_url: str) -> list[str]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(database_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' ORDER BY tablename"
                )
            )
            tables = [row[0] for row in result if row[0] != "alembic_version"]
            if not tables:
                return []
            quoted = ", ".join(f'"{name}"' for name in tables)
            await conn.execute(
                text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE")
            )
            return tables
    finally:
        await engine.dispose()


async def clear_redis(redis_url: str) -> None:
    from redis.asyncio import from_url

    client = from_url(redis_url, decode_responses=True)
    try:
        await client.flushdb()
    finally:
        await client.aclose()


async def run(args: argparse.Namespace) -> int:
    database_url = resolve_database_url()
    redis_url = resolve_redis_url()

    print("This will permanently DELETE ALL rows in:")
    print(f"  PostgreSQL: {mask_url(database_url)}")
    if not args.no_redis:
        print(f"  Redis:      {mask_url(redis_url)}")
    print("The schema and alembic_version are kept; the app starts empty.")

    if not args.yes:
        answer = input("Type 'yes' to continue: ").strip().lower()
        if answer not in ("yes", "y"):
            print("Cancelled.")
            return 1

    tables = await clear_postgres(database_url)
    print(f"PostgreSQL: cleared {len(tables)} table(s).")

    if not args.no_redis:
        try:
            await clear_redis(redis_url)
            print("Redis: flushed.")
        except Exception as exc:
            print(f"Redis: skipped ({exc}).")

    print("Done. Open the app and create the first administrator on the Setup page.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete all Stock & POS data.")
    parser.add_argument("--yes", "-y", action="store_true", help="skip confirmation")
    parser.add_argument(
        "--no-redis",
        action="store_true",
        help="do not flush Redis (sessions, locks, revoked tokens)",
    )
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except ModuleNotFoundError as exc:
        print(f"Missing dependency: {exc}. Run this inside the api container.")
        return 2


if __name__ == "__main__":
    sys.exit(main())
