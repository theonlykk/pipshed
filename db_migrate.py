"""
Manual Postgres migration runner for pipshed archive schema.
Operator runs: railway run python db_migrate.py
Never imported by app.py or archive_worker.py at startup.
"""

import glob
import os
import sys

import psycopg2


MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")

SCHEMA_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);
"""


def discover_migrations():
    paths = sorted(glob.glob(os.path.join(MIGRATIONS_DIR, "[0-9][0-9][0-9]_*.sql")))
    migrations = []
    for path in paths:
        basename = os.path.basename(path)
        version = basename[:-4]
        migrations.append((version, path))
    return migrations


def get_applied_versions(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations ORDER BY version")
        return {row[0] for row in cur.fetchall()}


def apply_migration(conn, version, path):
    with open(path, "r", encoding="ascii") as handle:
        sql = handle.read()
    with conn.cursor() as cur:
        cur.execute(sql)
        cur.execute(
            "INSERT INTO schema_migrations (version) VALUES (%s)",
            (version,),
        )
    conn.commit()
    print(f"Applied {version}")


def run_migrations(conn_factory):
    conn = conn_factory()
    try:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_MIGRATIONS_DDL)
        conn.commit()

        applied = get_applied_versions(conn)
        pending = [
            (version, path)
            for version, path in discover_migrations()
            if version not in applied
        ]
        if not pending:
            print("No pending migrations.")
            return

        for version, path in pending:
            apply_migration(conn, version, path)
    finally:
        conn.close()


def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required.", file=sys.stderr)
        sys.exit(1)

    def conn_factory():
        return psycopg2.connect(database_url)

    run_migrations(conn_factory)


if __name__ == "__main__":
    main()
