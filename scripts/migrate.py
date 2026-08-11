#!/usr/bin/env python3
"""Apply SQL migrations to the PostgreSQL database behind the Data API.

Usage:
  set DATABASE_URL=postgresql://user:pass@host:5432/dbname
  python scripts/migrate.py

Or:
  python scripts/migrate.py --database-url postgresql://...
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = ROOT / "migrations"


def _load_sql_files() -> list[Path]:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        raise SystemExit(f"No .sql files found in {MIGRATIONS_DIR}")
    return files


def _apply_with_psql(database_url: str, sql_path: Path) -> None:
    psql = shutil.which("psql")
    if not psql:
        raise RuntimeError("psql not found on PATH")
    subprocess.run(
        [
            psql,
            database_url,
            "-v",
            "ON_ERROR_STOP=1",
            "-f",
            str(sql_path),
        ],
        check=True,
    )


def _apply_with_psycopg(database_url: str, sql: str) -> None:
    import psycopg
    from psycopg.pq import ExecStatus

    with psycopg.connect(database_url, autocommit=True) as conn:
        # Simple-query protocol supports multi-statement scripts (incl. $$ bodies).
        result = conn.pgconn.exec_(sql.encode("utf-8"))
        if result is None:
            raise RuntimeError(conn.pgconn.error_message or "migration failed")

        current = result
        while current is not None:
            status = current.status
            if status not in (
                ExecStatus.COMMAND_OK,
                ExecStatus.TUPLES_OK,
                ExecStatus.EMPTY_QUERY,
            ):
                message = current.error_message or f"migration failed ({status})"
                raise RuntimeError(message)
            current = current.next


def main() -> int:
    load_dotenv(ROOT / ".env")

    parser = argparse.ArgumentParser(description="Apply TTS-DAI SQL migrations")
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", "").strip(),
        help="PostgreSQL connection URL (or set DATABASE_URL)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print SQL that would be executed without applying it",
    )
    args = parser.parse_args()

    sql_files = _load_sql_files()

    print("Migrations:")
    for path in sql_files:
        print(f"  - {path.name}")
    print()

    if args.dry_run:
        for path in sql_files:
            print(f"\n-- {path.name}\n{path.read_text(encoding='utf-8')}")
        return 0

    if not args.database_url:
        print(
            "DATABASE_URL is not set.\n"
            "Add it to .env (direct Postgres URL), then run:\n"
            "  python scripts/migrate.py\n\n"
            "Or apply SQL manually:\n"
            f"  psql \"$DATABASE_URL\" -f {MIGRATIONS_DIR / '001_init.sql'}"
        )
        return 1

    print(f"Applying {len(sql_files)} migration(s)...")
    for path in sql_files:
        print(f"  -> {path.name}")
        try:
            if shutil.which("psql"):
                _apply_with_psql(args.database_url, path)
            else:
                sql = path.read_text(encoding="utf-8")
                _apply_with_psycopg(args.database_url, sql)
        except ImportError:
            print(
                "psycopg is required when psql is unavailable.\n"
                "Install with: pip install 'psycopg[binary]'\n"
                f"Or run: psql \"$DATABASE_URL\" -f {path}"
            )
            return 1
        except Exception as e:
            print(f"Migration failed: {e}")
            return 1

    print("Done. If Data API still 404s tables, reload the PostgREST schema cache.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
