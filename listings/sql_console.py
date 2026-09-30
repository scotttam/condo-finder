"""Read-only SQL for the SQL console page.

User SQL never touches Django's connection. Each query opens its own SQLite connection that SQLite
itself keeps read-only (mode=ro plus PRAGMA query_only, with an authorizer so a query can't undo
either), and a progress handler stops it after SQL_CONSOLE_TIMEOUT_SECONDS so the single web worker,
which also runs the scheduler, isn't tied up.
"""

import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings
from django.db import connections


@dataclass
class QueryResult:
    sql: str
    columns: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    truncated: bool = False
    elapsed_ms: int = 0
    error: str = ""

    @property
    def row_count(self):
        return len(self.rows)


@dataclass
class Table:
    name: str
    columns: list  # (name, type) pairs


def _authorize(action, arg1, arg2, db_name, trigger):
    # ATTACH creates (and can write) a new database file even on a mode=ro connection.
    if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH):
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_PRAGMA and (arg1 or "").lower() in ("query_only", "read_uncommitted") and arg2 is not None:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def _lock_down(conn):
    conn.execute("PRAGMA query_only = ON")
    conn.set_authorizer(_authorize)
    return conn


def open_readonly(path):
    """A read-only connection to the SQLite file at path."""
    return _lock_down(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True))


def connect_readonly():
    """A read-only connection to the app's database, separate from Django's."""
    db = connections["default"]
    if db.is_in_memory_db():
        # The test database is shared-cache memory, which can't be opened mode=ro. query_only still
        # refuses writes, and read_uncommitted lets this connection see rows the test's open
        # transaction wrote.
        conn = sqlite3.connect(db.settings_dict["NAME"], uri=True)
        conn.execute("PRAGMA read_uncommitted = ON")
        return _lock_down(conn)
    return open_readonly(db.settings_dict["NAME"])


def run_query(sql, *, max_rows=None, connect=connect_readonly):
    """Run one statement read-only, keeping at most max_rows rows (None keeps all).

    Bad SQL, refused writes and timeouts come back in .error; this never raises for them.
    """
    sql = sql.strip()
    timeout = settings.SQL_CONSOLE_TIMEOUT_SECONDS
    started = time.monotonic()
    deadline = started + timeout
    result = QueryResult(sql=sql)
    conn = None
    try:
        conn = connect()
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1000)
        cursor = conn.execute(sql)
        result.columns = [column[0] for column in cursor.description or []]
        if max_rows is None:
            result.rows = cursor.fetchall()
        else:
            rows = cursor.fetchmany(max_rows + 1)
            result.truncated = len(rows) > max_rows
            result.rows = rows[:max_rows]
    except sqlite3.Error as exc:
        result.columns, result.rows, result.truncated = [], [], False
        if str(exc) == "interrupted" and time.monotonic() > deadline:
            result.error = f"Stopped after {timeout:g} s. Narrow the query or add a LIMIT."
        else:
            result.error = str(exc)
    finally:
        if conn is not None:
            conn.close()
        result.elapsed_ms = round((time.monotonic() - started) * 1000)
    return result


def schema(connect=connect_readonly):
    """Every table with its columns, for the console's sidebar."""
    conn = connect()
    try:
        names = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        return [
            Table(name, [(column[1], column[2].lower()) for column in conn.execute(
                'PRAGMA table_info("{}")'.format(name.replace('"', '""'))
            )])
            for name in names
        ]
    finally:
        conn.close()


_FIRST_FROM = re.compile(r"\bfrom\s+[\"`\[]?(\w+)", re.IGNORECASE)


def listing_link_columns(sql, columns):
    """Indexes of columns holding listing ids: any listing_id, and id when the first FROM is listings_listing."""
    first_from = _FIRST_FROM.search(sql)
    id_is_listing = bool(first_from) and first_from.group(1).lower() == "listings_listing"
    return {
        index for index, name in enumerate(columns)
        if name.lower() == "listing_id" or (id_is_listing and name.lower() == "id")
    }
