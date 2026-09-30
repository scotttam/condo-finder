import sqlite3

import pytest

from listings import sql_console
from listings.models import Listing
from tests.helpers import make_listing


@pytest.fixture
def db_file(tmp_path):
    """A WAL database with a writer left open, like the web process's own connection."""
    path = tmp_path / "app.db"
    writer = sqlite3.connect(path)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("CREATE TABLE t (x INTEGER, label TEXT)")
    writer.executemany("INSERT INTO t VALUES (?, ?)", [(n, f"row {n}") for n in range(1, 6)])
    writer.commit()
    yield path
    writer.close()


def run(db_file, sql, **kwargs):
    return sql_console.run_query(sql, connect=lambda: sql_console.open_readonly(db_file), **kwargs)


def count_rows(db_file):
    with sqlite3.connect(db_file) as conn:
        return conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]


def test_select_returns_columns_rows_and_timing(db_file):
    result = run(db_file, "SELECT x, label FROM t ORDER BY x")
    assert result.error == ""
    assert result.columns == ["x", "label"]
    assert result.rows[0] == (1, "row 1")
    assert result.row_count == 5
    assert result.truncated is False
    assert result.elapsed_ms >= 0


def test_row_cap_truncates(db_file):
    result = run(db_file, "SELECT x FROM t ORDER BY x", max_rows=3)
    assert [row[0] for row in result.rows] == [1, 2, 3]
    assert result.truncated is True


def test_exactly_max_rows_is_not_truncated(db_file):
    result = run(db_file, "SELECT x FROM t", max_rows=5)
    assert result.row_count == 5
    assert result.truncated is False


def test_no_cap_returns_everything(db_file):
    assert run(db_file, "SELECT x FROM t").row_count == 5


@pytest.mark.parametrize("sql", [
    "INSERT INTO t VALUES (9, 'x')",
    "UPDATE t SET x = 0",
    "DELETE FROM t",
    "DROP TABLE t",
    "CREATE TABLE u (a)",
])
def test_writes_are_refused(db_file, sql):
    result = run(db_file, sql)
    assert "readonly" in result.error
    assert count_rows(db_file) == 5


def test_query_only_cannot_be_turned_off(db_file):
    assert "not authorized" in run(db_file, "PRAGMA query_only = OFF").error


def test_attach_is_refused_and_creates_no_file(db_file, tmp_path):
    target = tmp_path / "new.db"
    result = run(db_file, f"ATTACH '{target}' AS other")
    assert "not authorized" in result.error
    assert not target.exists()


def test_multiple_statements_are_refused(db_file):
    result = run(db_file, "SELECT 1; DELETE FROM t")
    assert "one statement" in result.error
    assert count_rows(db_file) == 5


def test_trailing_semicolon_is_fine(db_file):
    assert run(db_file, "SELECT COUNT(*) FROM t;").rows == [(5,)]


def test_reading_pragmas_still_works(db_file):
    result = run(db_file, "PRAGMA table_info(t)")
    assert result.error == ""
    assert [row[1] for row in result.rows] == ["x", "label"]


def test_query_only_reports_on(db_file):
    result = run(db_file, "PRAGMA query_only")
    assert result.error == ""
    assert result.rows == [(1,)]


def test_syntax_error_is_reported(db_file):
    result = run(db_file, "SELEC 1")
    assert "syntax error" in result.error
    assert result.rows == []


def test_runaway_query_stops_at_the_timeout(db_file, settings):
    settings.SQL_CONSOLE_TIMEOUT_SECONDS = 0.05
    result = run(db_file, "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 100000000) SELECT COUNT(*) FROM c")
    assert result.error.startswith("Stopped after 0.05 s")
    assert result.rows == []
    assert result.elapsed_ms < 2000


def test_missing_database_file_is_an_error_not_a_crash(tmp_path):
    result = run(tmp_path / "nope.db", "SELECT 1")
    assert "unable to open" in result.error
    assert not (tmp_path / "nope.db").exists()


@pytest.mark.django_db
def test_connect_readonly_sees_test_rows_and_refuses_writes():
    make_listing(price=2500)
    assert sql_console.run_query("SELECT price FROM listings_listing").rows == [(2500,)]
    assert "readonly" in sql_console.run_query("DELETE FROM listings_listing").error
    assert Listing.objects.count() == 1


@pytest.mark.django_db
def test_schema_lists_tables_and_columns():
    tables = {table.name: table for table in sql_console.schema()}
    assert "listings_listing" in tables
    assert not any(name.startswith("sqlite_") for name in tables)
    assert ("price", "integer") in tables["listings_listing"].columns


def test_listing_link_columns():
    assert sql_console.listing_link_columns("SELECT listing_id, price FROM listings_pricechange", ["listing_id", "price"]) == {0}
    assert sql_console.listing_link_columns("select id, address from listings_listing", ["id", "address"]) == {0}
    assert sql_console.listing_link_columns('SELECT id FROM "listings_listing" WHERE 1', ["id"]) == {0}
    assert sql_console.listing_link_columns("SELECT id FROM listings_trendreport", ["id"]) == set()
    assert sql_console.listing_link_columns("SELECT 1 AS id", ["id"]) == set()


# Values that are harmless if a regression lets them through: 0 means "no limit", '' means the default.
@pytest.mark.parametrize("sql", [
    "PRAGMA hard_heap_limit = 0",
    "PRAGMA soft_heap_limit = 0",
    "PRAGMA temp_store_directory = ''",
    "PRAGMA main.cache_size = 10",
])
def test_pragmas_that_change_settings_are_refused(db_file, sql):
    # hard_heap_limit and friends are process-wide: one query could break Django's own connection.
    assert "not authorized" in run(db_file, sql).error


@pytest.mark.parametrize("sql", ["PRAGMA index_list(t)", "PRAGMA table_xinfo(t)", "PRAGMA quick_check", "PRAGMA hard_heap_limit"])
def test_read_pragmas_still_work(db_file, sql):
    assert run(db_file, sql).error == ""
