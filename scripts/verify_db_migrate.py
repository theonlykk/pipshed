"""Verification for db_migrate.py (fake connection)."""
import os
import sys


class FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self._sql = None

    def execute(self, sql, params=None):
        self._sql = sql
        self._conn.executed.append((sql.strip(), params))
        if "INSERT INTO schema_migrations" in sql and params:
            self._conn.applied_versions.add(params[0])
        return self

    def fetchall(self):
        if self._sql and "SELECT version FROM schema_migrations" in self._sql:
            return [(v,) for v in sorted(self._conn.applied_versions)]
        return []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConnection:
    def __init__(self):
        self.executed = []
        self.applied_versions = set()
        self.committed = 0
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.committed += 1

    def close(self):
        self.closed = True


def read_migration_sql():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "migrations", "001_archive_phase1.sql")
    with open(path, "r", encoding="ascii") as handle:
        return handle.read()


def main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import db_migrate

    sql_text = read_migration_sql()
    required_tables = [
        "schema_migrations",
        "send_logs",
        "fill_logs",
        "config_events",
        "ea_events",
        "scalp_history",
    ]
    for table in required_tables:
        assert f"CREATE TABLE {table}" in sql_text or f"CREATE TABLE IF NOT EXISTS {table}" in sql_text, table

    assert "UNIQUE (instance_id, session_id, seq)" in sql_text
    assert "UNIQUE (instance_id, deal_ticket)" in sql_text
    assert (
        "UNIQUE (instance_id, close_time_broker, direction, entry_price, exit_price)"
        in sql_text
    )
    print("SQL file OK: all tables and unique constraints present")

    conn = FakeConnection()
    connections = []

    def conn_factory():
        connections.append(FakeConnection())
        return connections[-1] if len(connections) > 1 else conn

    db_migrate.run_migrations(lambda: conn)

    migration_executes = [
        sql for sql, _ in conn.executed if "CREATE TABLE send_logs" in sql
    ]
    assert migration_executes, "expected 001 migration SQL executed"
    assert "001_archive_phase1" in conn.applied_versions
    first_run_commits = conn.committed
    assert first_run_commits >= 1
    print("first run OK: 001_archive_phase1 applied")

    conn2 = FakeConnection()
    conn2.applied_versions = set(conn.applied_versions)

    def conn_factory_second():
        return conn2

    before = len(conn2.executed)
    db_migrate.run_migrations(conn_factory_second)
    new_executes = [
        sql for sql, _ in conn2.executed[before:] if "CREATE TABLE send_logs" in sql
    ]
    assert not new_executes
    print("second run OK: no pending migrations")

    print("All db_migrate checks passed.")


if __name__ == "__main__":
    main()
