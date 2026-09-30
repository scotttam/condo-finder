# SQL Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a staff-only `/sql/` page for running ad hoc read-only SQL against the SQLite
database, with grouped starter queries, saved queries, a Recent list, a schema sidebar and CSV
download.

**Architecture:**
- `listings/sql_console.py` opens a fresh SQLite connection for every query. SQLite itself keeps
  it read-only: `mode=ro` URI, `PRAGMA query_only`, and an authorizer that blocks `ATTACH` and
  turning `query_only` off. A progress handler stops queries after 5 s. Django's connection never
  runs user SQL.
- `listings/sql_queries.py` holds the starter ("canned") queries as data. A test runs every one
  of them.
- `listings/sql_views.py` has the page, the CSV download, and save/delete for `SavedQuery`. Each
  run is logged to `QueryRun` through Django's normal connection, and the log is pruned to 50 rows.

**Tech Stack:** Django 6.1, Python 3.13, stdlib `sqlite3` (SQLite 3.47), server-rendered
templates, a few lines of inline JS, pytest + pytest-django, BeautifulSoup in tests.

**Spec:** `docs/plan-decisions.md`. Task 1 moves it to
`docs/superpowers/specs/2026-09-30-sql-console-decisions.md`.

## Global Constraints

- Every `/sql/` endpoint requires a staff session (`is_staff`). Anyone else is redirected to
  `/admin/login/?next=…`, via `django.contrib.admin.views.decorators.staff_member_required`.
- User SQL never runs on Django's `default` connection. Only `sql_console.connect_readonly()`
  runs it.
- Results show at most **1,000** rows (`SQL_CONSOLE_MAX_ROWS`), with a "truncated" note. The CSV
  has no row cap.
- Queries abort after **5 s** (`SQL_CONSOLE_TIMEOUT_SECONDS`), for the HTML page and the CSV alike.
- `QueryRun` keeps only the latest **50** rows.
- No new dependencies and no CDN editor. Use a plain `<textarea>` and small inline scripts.
- Production is live, so add one new migration (`0008_sql_console`) and never edit applied ones.
- CSS goes inline in `listings/templates/listings/base.html`.
- Tests assert on element markup or parsed elements, never on bare class names. Class names also
  appear in the inline stylesheet.
- Deliver as **one PR off `main`** (branch `sql-console`) with one commit per task. Commit
  prefixes are `feat:` / `fix:` / `docs:`, and every commit ends with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. The PR body ends with
  `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
- Commands given to the owner to paste contain no inline `# comments`, and each gets its own code
  block.

## Review Focus

These are the inputs most likely to bite that the decisions don't spell out. Each has a test in the task named.

1. **A write disguised as a query.** For example: `PRAGMA query_only = OFF`, then a write;
   `ATTACH` of a new file; `SELECT 1; DELETE …`. SQLite must refuse it with a readable error,
   leave the data unchanged, and create no files. Covered in Task 2, which also verifies that
   `ATTACH` creates a file even on a `mode=ro` connection unless the authorizer blocks it.
2. **A runaway query**, such as an unbounded recursive CTE or a cross join. It must stop at the
   timeout with "Stopped after 5 s…" on the page, be logged as an error in Recent, and make the
   CSV return 400 rather than a partial file. Covered in Tasks 2 and 4.
3. **Hostile or odd cell values:** notes containing `<script>`, NULLs, duplicate column names,
   non-ASCII addresses. HTML must be escaped, NULL shown distinctly, both duplicate columns
   rendered, and UTF-8 preserved in the CSV. Covered in Task 4.
4. **Non-staff access to every endpoint.** Anonymous or logged-in non-staff users hitting `/sql/`,
   `/sql/csv/`, `POST /sql/save/` or `POST /sql/saved/<pk>/delete/` must be redirected to the admin
   login, with nothing run, saved or deleted. Covered in Tasks 4 and 5.
5. **Long queries in the URL.** Queries run by GET `?q=`, and gunicorn rejects request lines over
   4,094 bytes by default, so a long pasted query would 400 before reaching Django. Task 6 sets
   `limit_request_line = 0` (unlimited) in `deploy/gunicorn.conf.py`. The browser check in Task 6
   runs a query longer than 4 KB through gunicorn.

---

### Task 1: `SavedQuery` and `QueryRun` models

**Files:**
- Move: `docs/plan-decisions.md` → `docs/superpowers/specs/2026-09-30-sql-console-decisions.md`
- Modify: `listings/models.py` (imports at top; append two models at the end)
- Create: `listings/migrations/0008_sql_console.py` (generated)
- Modify: `condofinder/settings.py` (append two settings under `# --- Condo finder ---`)
- Test: `tests/test_sql_models.py`

**Interfaces:**
- Produces:
  - `SavedQuery(name: str ≤100, sql: str, created_at, updated_at)`, ordered by `name, pk`.
  - `QueryRun(sql, user FK|None, ran_at, row_count: int|None, elapsed_ms: int, error: str)`,
    ordered newest first, with `QueryRun.KEEP = 50`.
  - `QueryRun.record(**fields) -> QueryRun` creates a row and prunes to `KEEP`.
  - `settings.SQL_CONSOLE_TIMEOUT_SECONDS = 5` and `settings.SQL_CONSOLE_MAX_ROWS = 1000`.

- [ ] **Step 1: Branch and move the decisions file**

```bash
git checkout -b sql-console
```

```bash
mkdir -p docs/superpowers/specs && mv docs/plan-decisions.md docs/superpowers/specs/2026-09-30-sql-console-decisions.md
```

(`git mv` fails on untracked files, so use `mv`.)

- [ ] **Step 2: Write the failing tests**

`tests/test_sql_models.py`:

```python
import pytest

from listings.models import QueryRun, SavedQuery

pytestmark = pytest.mark.django_db


def test_record_keeps_only_the_latest_runs(monkeypatch):
    monkeypatch.setattr(QueryRun, "KEEP", 3)
    for n in range(5):
        QueryRun.record(sql=f"SELECT {n}", row_count=1, elapsed_ms=2)
    assert [run.sql for run in QueryRun.objects.all()] == ["SELECT 4", "SELECT 3", "SELECT 2"]


def test_record_stores_errors_and_the_user(django_user_model):
    user = django_user_model.objects.create_user("owner", is_staff=True)
    run = QueryRun.record(sql="SELEC 1", user=user, row_count=None, elapsed_ms=1, error='near "SELEC": syntax error')
    run.refresh_from_db()
    assert run.user == user
    assert run.row_count is None
    assert "syntax error" in run.error


def test_deleting_a_user_keeps_their_runs(django_user_model):
    user = django_user_model.objects.create_user("owner", is_staff=True)
    QueryRun.record(sql="SELECT 1", user=user, row_count=1, elapsed_ms=1)
    user.delete()
    assert QueryRun.objects.get().user is None


def test_saved_queries_sort_by_name():
    SavedQuery.objects.create(name="zebra", sql="SELECT 1")
    SavedQuery.objects.create(name="apple", sql="SELECT 2")
    assert [q.name for q in SavedQuery.objects.all()] == ["apple", "zebra"]
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/test_sql_models.py -q`
Expected: collection error, `ImportError: cannot import name 'QueryRun'`.

- [ ] **Step 4: Add the models**

In `listings/models.py`, add `from django.conf import settings` to the imports (above
`from django.db import models`). Then append:

```python
class SavedQuery(models.Model):
    """A query saved from the SQL console."""

    name = models.CharField(max_length=100)
    sql = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "pk"]
        verbose_name_plural = "saved queries"

    def __str__(self):
        return self.name


class QueryRun(models.Model):
    """One query run in the SQL console, for its Recent list. Only the latest KEEP are kept."""

    KEEP = 50

    sql = models.TextField()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    ran_at = models.DateTimeField(default=timezone.now)
    row_count = models.IntegerField(null=True, blank=True)  # None when the query failed
    elapsed_ms = models.IntegerField(default=0)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-ran_at", "-pk"]

    @classmethod
    def record(cls, **fields):
        run = cls.objects.create(**fields)
        keep = list(cls.objects.values_list("pk", flat=True)[: cls.KEEP])
        cls.objects.exclude(pk__in=keep).delete()
        return run
```

In `condofinder/settings.py`, append after `TRENDS_MANUAL_RUNS_PER_DAY`:

```python
SQL_CONSOLE_TIMEOUT_SECONDS = 5
SQL_CONSOLE_MAX_ROWS = 1000
```

- [ ] **Step 5: Generate the migration**

Run: `uv run python manage.py makemigrations listings --name sql_console`
Expected: `listings/migrations/0008_sql_console.py` with `Create model QueryRun` and
`Create model SavedQuery`. Open it and check that it only creates these two models.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_sql_models.py -q`
Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add docs/superpowers/specs/2026-09-30-sql-console-decisions.md docs/superpowers/plans/2026-09-30-sql-console.md listings/models.py listings/migrations/0008_sql_console.py condofinder/settings.py tests/test_sql_models.py
git commit -m "feat: add SavedQuery and QueryRun models for the SQL console

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Read-only query runner (`listings/sql_console.py`)

**Files:**
- Create: `listings/sql_console.py`
- Test: `tests/test_sql_console.py`

**Interfaces:**
- Consumes: `settings.SQL_CONSOLE_TIMEOUT_SECONDS` (Task 1).
- Produces:
  - `QueryResult`, a dataclass with `sql: str`, `columns: list[str]`, `rows: list[tuple]`,
    `truncated: bool`, `elapsed_ms: int`, `error: str`, and the property `row_count -> int`.
  - `open_readonly(path) -> sqlite3.Connection`
  - `connect_readonly() -> sqlite3.Connection`
  - `run_query(sql: str, *, max_rows: int | None = None, connect=connect_readonly) -> QueryResult`.
    It never raises for bad SQL; failures go in `.error`.
  - `Table`, a dataclass with `name: str` and `columns: list[tuple[str, str]]` (name, type).
  - `schema(connect=connect_readonly) -> list[Table]`
  - `listing_link_columns(sql: str, columns: list[str]) -> set[int]`

Background the implementer needs:
- Django stores the test database as a shared-cache in-memory URI
  (`file:memorydb_default?mode=memory&cache=shared`), and it can't be opened `mode=ro`. For that
  case, `connect_readonly()` opens the same URI with `PRAGMA read_uncommitted = ON`, so it sees
  rows the test's open transaction wrote, plus `query_only`. A probe confirmed that this reads
  rows and refuses writes.
- Even on a `mode=ro` connection, `ATTACH '/path/new.db'` **creates that file**, and
  `PRAGMA query_only = OFF` succeeds. That's verified on SQLite 3.47. The authorizer below blocks
  both.
- Python's `sqlite3` refuses multiple statements in one `execute()` with
  `ProgrammingError: You can only execute one statement at a time.` A trailing `;` is fine.
- A progress handler that returns non-zero aborts the query with
  `OperationalError: interrupted`.

- [ ] **Step 1: Write the failing tests**

`tests/test_sql_console.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_sql_console.py -q`
Expected: collection error, `ImportError: cannot import name 'sql_console'`.

- [ ] **Step 3: Implement `listings/sql_console.py`**

```python
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
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_sql_console.py -q`
Expected: all pass. If `test_missing_database_file_is_an_error_not_a_crash` fails on the message,
print `result.error` and match SQLite's actual wording ("unable to open database file"). Don't
loosen the "no file created" assertion.

- [ ] **Step 5: Commit**

```bash
git add listings/sql_console.py tests/test_sql_console.py
git commit -m "feat: read-only SQL runner with timeout and row cap

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Starter queries (`listings/sql_queries.py`)

**Files:**
- Create: `listings/sql_queries.py`
- Test: `tests/test_sql_queries.py`

**Interfaces:**
- Consumes: `sql_console.run_query` (Task 2).
- Produces:
  - `CannedQuery`, a frozen dataclass with `category: str`, `title: str`, `sql: str`.
  - `CANNED_QUERIES: list[CannedQuery]`
  - `by_category() -> list[tuple[str, list[CannedQuery]]]`, in definition order.

Schema facts the SQL relies on:
- Table names: `listings_listing`, `listings_sourcelisting`, `listings_source`,
  `listings_sourcerun`, `listings_pricechange`, `listings_feedevent`, `listings_trendreport`.
- Booleans are stored as 0/1.
- Django stores datetimes as naive UTC text (`YYYY-MM-DD HH:MM:SS.ffffff`), so comparing with
  `datetime('now', '-30 days')` works. Use `'localtime'` for display days; the Mac mini runs on
  Portland time.
- `address_key` is `street|unit|zip`, with `|site:id` appended for same-site units. The text before
  the first `|` is the normalized street.
- `trigger` is an SQLite keyword, so quote it: `"trigger"`.

- [ ] **Step 1: Write the failing tests**

`tests/test_sql_queries.py`:

```python
import pytest
from django.utils import timezone

from listings.models import FeedEvent, PriceChange, Source, SourceListing, SourceRun, TrendReport
from listings.sql_console import run_query
from listings.sql_queries import CANNED_QUERIES, by_category
from tests.helpers import make_listing

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    zillow = Source.objects.create(key="zillow-t", name="Zillow", platform="zillow")
    redfin = Source.objects.create(key="redfin-t", name="Redfin", platform="redfin")
    with_unit = make_listing(price=2600, beds=2, sqft=1000, special_offer="4 weeks free",
                             status="interested", notes="Nice view")
    no_unit = make_listing(address_key="937 nw glisan st||97209", address="937 NW Glisan Street, Portland, OR 97209",
                           unit="", price=2650, beds=2, sqft=1000)
    for listing, source in ((with_unit, zillow), (with_unit, redfin), (no_unit, redfin)):
        SourceListing.objects.create(listing=listing, source=source, external_id=f"{source.key}-{listing.pk}",
                                     url="https://example.com/")
    for price in (3000, 2900, 2600):
        PriceChange.objects.create(listing=with_unit, price=price, source="Zillow")
    PriceChange.objects.create(listing=with_unit, price=2600, source="")
    SourceRun.objects.create(source=zillow, ok=True, finished_at=timezone.now())
    SourceRun.objects.create(source=redfin, ok=False, finished_at=timezone.now(), error="blocked")
    FeedEvent.objects.create(listing=with_unit, kind="new_listing", happened_at=timezone.now(), summary="New")
    TrendReport.objects.create(status="done", cost_usd="0.51", input_tokens=1000)
    return {"with_unit": with_unit, "no_unit": no_unit}


def canned(title):
    return next(query for query in CANNED_QUERIES if query.title == title)


def rows(title):
    result = run_query(canned(title).sql)
    assert result.error == ""
    return [dict(zip(result.columns, row)) for row in result.rows]


@pytest.mark.parametrize("query", CANNED_QUERIES, ids=lambda query: query.title)
def test_every_canned_query_runs(seeded, query):
    result = run_query(query.sql)
    assert result.error == "", f"{query.title}: {result.error}"
    assert result.columns


def test_every_canned_query_runs_on_an_empty_database():
    for query in CANNED_QUERIES:
        assert run_query(query.sql).error == "", query.title


def test_titles_are_unique():
    titles = [query.title for query in CANNED_QUERIES]
    assert len(titles) == len(set(titles))


def test_categories_in_order():
    assert [category for category, _ in by_category()] == [
        "Listings & market", "Price history", "Scraper health & data quality", "Tracking & costs",
    ]


def test_unit_duplicates_query_finds_the_pair(seeded):
    found = rows("Possible unit-number duplicates")
    assert [(row["listing_id"], row["with_unit_id"]) for row in found] == [(seeded["no_unit"].pk, seeded["with_unit"].pk)]


def test_several_cuts_counts_real_decreases(seeded):
    assert [(row["listing_id"], row["cuts"]) for row in rows("Listings with several price cuts")] == [(seeded["with_unit"].pk, 2)]


def test_biggest_drops_measures_from_the_highest_price(seeded):
    top = rows("Biggest price drops")[0]
    assert (top["listing_id"], top["price_drop"]) == (seeded["with_unit"].pk, 400)


def test_hand_entered_history_is_blank_source_only(seeded):
    assert len(rows("Hand-entered price history")) == 1


def test_median_rent_by_area(seeded):
    assert rows("Median rent by city and quadrant") == [
        {"city": "Portland", "quadrant": "", "listings": 2, "median_price": 2625},
    ]


def test_scrape_runs_by_source(seeded):
    by_source = {row["source"]: row for row in rows("Scrape runs by source (30 days)")}
    assert (by_source["Zillow"]["ok"], by_source["Zillow"]["failed"]) == (1, 0)
    assert (by_source["Redfin"]["ok"], by_source["Redfin"]["failed"]) == (0, 1)


def test_site_overlap(seeded):
    assert rows("Overlap between sites") == [{"site": "Zillow", "also_on": "Redfin", "listings": 1}]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_sql_queries.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'listings.sql_queries'`.

- [ ] **Step 3: Implement `listings/sql_queries.py`**

```python
"""Starter queries for the SQL console, grouped by category. tests/test_sql_queries.py runs every one."""

from dataclasses import dataclass
from textwrap import dedent


@dataclass(frozen=True)
class CannedQuery:
    category: str
    title: str
    sql: str


LISTINGS = "Listings & market"
HISTORY = "Price history"
HEALTH = "Scraper health & data quality"
TRACKING = "Tracking & costs"


def _q(category, title, sql):
    return CannedQuery(category, title, dedent(sql).strip())


CANNED_QUERIES = [
    _q(LISTINGS, "Median rent by city and quadrant", """
        WITH priced AS (
          SELECT city, quadrant, price,
                 ROW_NUMBER() OVER (PARTITION BY city, quadrant ORDER BY price) AS rn,
                 COUNT(*) OVER (PARTITION BY city, quadrant) AS n
          FROM listings_listing
          WHERE is_active AND price IS NOT NULL
        )
        SELECT city, quadrant, n AS listings, CAST(ROUND(AVG(price)) AS INTEGER) AS median_price
        FROM priced
        WHERE rn IN ((n + 1) / 2, (n + 2) / 2)
        GROUP BY city, quadrant, n
        ORDER BY listings DESC
    """),
    _q(LISTINGS, "Price per square foot", """
        SELECT id AS listing_id, address, price, sqft, ROUND(1.0 * price / sqft, 2) AS price_per_sqft
        FROM listings_listing
        WHERE is_active AND price IS NOT NULL AND sqft > 0
        ORDER BY price_per_sqft
        LIMIT 100
    """),
    _q(LISTINGS, "Newest listings", """
        SELECT id AS listing_id, address, price, beds, baths, sqft, first_seen_at
        FROM listings_listing
        WHERE is_active
        ORDER BY first_seen_at DESC
        LIMIT 50
    """),
    _q(LISTINGS, "Longest on the market", """
        SELECT id AS listing_id, address, price, COALESCE(listed_at, date(first_seen_at)) AS since,
               CAST(julianday('now') - julianday(COALESCE(listed_at, first_seen_at)) AS INTEGER) AS days_on_market
        FROM listings_listing
        WHERE is_active
        ORDER BY days_on_market DESC
        LIMIT 50
    """),
    _q(LISTINGS, "Move-in specials", """
        SELECT id AS listing_id, address, price, special_offer
        FROM listings_listing
        WHERE is_active AND special_offer <> ''
        ORDER BY price
    """),
    _q(HISTORY, "Biggest price drops", """
        SELECT l.id AS listing_id, l.address, MAX(pc.price) AS highest_price, l.price AS current_price,
               MAX(pc.price) - l.price AS price_drop,
               ROUND(100.0 * (MAX(pc.price) - l.price) / MAX(pc.price), 1) AS drop_pct
        FROM listings_listing l
        JOIN listings_pricechange pc ON pc.listing_id = l.id
        WHERE l.is_active AND l.price IS NOT NULL
        GROUP BY l.id
        HAVING price_drop > 0
        ORDER BY price_drop DESC
        LIMIT 50
    """),
    _q(HISTORY, "Listings with several price cuts", """
        WITH steps AS (
          SELECT listing_id, price,
                 LAG(price) OVER (PARTITION BY listing_id ORDER BY seen_at, id) AS previous_price
          FROM listings_pricechange
        )
        SELECT l.id AS listing_id, l.address, l.price AS current_price, COUNT(*) AS cuts
        FROM steps
        JOIN listings_listing l ON l.id = steps.listing_id
        WHERE steps.price < steps.previous_price
        GROUP BY l.id
        HAVING cuts >= 2
        ORDER BY cuts DESC, l.price
    """),
    _q(HISTORY, "Recent price changes", """
        SELECT pc.listing_id, l.address, pc.price, pc.event, pc.source, pc.seen_at
        FROM listings_pricechange pc
        JOIN listings_listing l ON l.id = pc.listing_id
        ORDER BY pc.seen_at DESC, pc.id DESC
        LIMIT 100
    """),
    _q(HISTORY, "Hand-entered price history", """
        SELECT pc.listing_id, l.address, pc.price, pc.event, pc.seen_at
        FROM listings_pricechange pc
        JOIN listings_listing l ON l.id = pc.listing_id
        WHERE pc.source = ''
        ORDER BY pc.seen_at DESC
    """),
    _q(HEALTH, "Scrape runs by source (30 days)", """
        SELECT s.name AS source, COUNT(r.id) AS runs,
               COALESCE(SUM(r.ok), 0) AS ok,
               COALESCE(SUM(NOT r.ok AND r.finished_at IS NOT NULL), 0) AS failed,
               MAX(CASE WHEN r.ok THEN r.started_at END) AS last_ok,
               MAX(CASE WHEN NOT r.ok AND r.finished_at IS NOT NULL THEN r.started_at END) AS last_failure
        FROM listings_source s
        LEFT JOIN listings_sourcerun r ON r.source_id = s.id AND r.started_at >= datetime('now', '-30 days')
        GROUP BY s.id
        ORDER BY failed DESC, s.name
    """),
    _q(HEALTH, "Listings per source", """
        SELECT s.name AS source, s.platform,
               COUNT(CASE WHEN sl.is_active THEN 1 END) AS active,
               COUNT(sl.id) AS all_time
        FROM listings_source s
        LEFT JOIN listings_sourcelisting sl ON sl.source_id = s.id
        GROUP BY s.id
        ORDER BY active DESC, s.name
    """),
    _q(HEALTH, "Overlap between sites", """
        SELECT a.name AS site, b.name AS also_on, COUNT(*) AS listings
        FROM listings_sourcelisting x
        JOIN listings_sourcelisting y ON y.listing_id = x.listing_id AND y.source_id > x.source_id
        JOIN listings_source a ON a.id = x.source_id
        JOIN listings_source b ON b.id = y.source_id
        WHERE x.is_active AND y.is_active
        GROUP BY a.id, b.id
        ORDER BY listings DESC
    """),
    _q(HEALTH, "Missing geocode, sqft or beds", """
        SELECT id AS listing_id, address,
               latitude IS NULL AS no_geocode, sqft IS NULL AS no_sqft, beds IS NULL AS no_beds
        FROM listings_listing
        WHERE is_active AND (latitude IS NULL OR sqft IS NULL OR beds IS NULL)
        ORDER BY first_seen_at DESC
    """),
    _q(HEALTH, "Possible unit-number duplicates", """
        SELECT a.id AS listing_id, a.address, b.id AS with_unit_id, b.address AS with_unit_address,
               a.beds, a.baths, a.sqft, b.sqft AS with_unit_sqft, a.price, b.price AS with_unit_price
        FROM listings_listing a
        JOIN listings_listing b
          ON substr(b.address_key, 1, instr(b.address_key, '|') - 1) = substr(a.address_key, 1, instr(a.address_key, '|') - 1)
         AND b.zip_code = a.zip_code AND b.unit <> '' AND b.id <> a.id
        WHERE a.unit = '' AND instr(a.address_key, '|') > 0 AND a.is_active AND b.is_active
        ORDER BY a.address
    """),
    _q(TRACKING, "Listings by status, with notes", """
        SELECT id AS listing_id, address, status, price, is_active, notes, updated_at
        FROM listings_listing
        WHERE status <> 'new' OR notes <> ''
        ORDER BY CASE status WHEN 'applied' THEN 1 WHEN 'toured' THEN 2 WHEN 'interested' THEN 3
                             WHEN 'new' THEN 4 ELSE 5 END,
                 updated_at DESC
    """),
    _q(TRACKING, "Feed events by day and kind (30 days)", """
        SELECT date(created_at, 'localtime') AS day, kind, COUNT(*) AS events
        FROM listings_feedevent
        WHERE created_at >= datetime('now', '-30 days')
        GROUP BY day, kind
        ORDER BY day DESC, events DESC
    """),
    _q(TRACKING, "Trends report costs", """
        SELECT id, datetime(created_at, 'localtime') AS created, "trigger", status, model,
               input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, cost_usd
        FROM listings_trendreport
        ORDER BY created_at DESC
    """),
]


def by_category():
    groups = {}
    for query in CANNED_QUERIES:
        groups.setdefault(query.category, []).append(query)
    return list(groups.items())
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_sql_queries.py -q`
Expected: all pass. If a content test fails, run the query in `uv run python manage.py dbshell`
against a copy of the dev DB to see why. Fix the SQL, not the assertion, unless the assertion's
arithmetic is wrong.

- [ ] **Step 5: Commit**

```bash
git add listings/sql_queries.py tests/test_sql_queries.py
git commit -m "feat: starter queries for the SQL console

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The `/sql/` page and CSV download

**Files:**
- Create: `listings/sql_views.py`
- Create: `listings/templates/listings/sql_console.html`
- Modify: `listings/urls.py` (add two routes)
- Modify: `listings/templates/listings/base.html` (CSS: add a `/* SQL console */` block before
  the `@media (max-width: 800px)` rule at about line 280, and one line inside that media query)
- Test: `tests/test_sql_page.py`

**Interfaces:**
- Consumes: `run_query`, `schema`, `listing_link_columns` (Task 2); `by_category` (Task 3);
  `QueryRun.record`, `SavedQuery` (Task 1).
- Produces:
  - URL names `sql_console` (`/sql/`) and `sql_csv` (`/sql/csv/`).
  - Template blocks that Task 5 fills in: the element `<div id="sql-saved-controls">` below the run
    form, and the sidebar `<details>` whose `<summary>` reads `Saved`.
  - The helper `_console_url(sql, saved=None) -> str` in `sql_views.py`, which Task 5 uses.

- [ ] **Step 1: Write the failing tests**

`tests/test_sql_page.py`:

```python
import csv
import io
from urllib.parse import parse_qs, urlencode

import pytest
from bs4 import BeautifulSoup

from listings.models import Listing, QueryRun
from tests.helpers import make_listing

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff_client(client, django_user_model):
    client.force_login(django_user_model.objects.create_user("owner", password="pw", is_staff=True))
    return client


def get(client, sql, path="/sql/"):
    return client.get(f"{path}?{urlencode({'q': sql})}")


def soup(response):
    return BeautifulSoup(response.content, "html.parser")


def result_rows(response):
    table = soup(response).select_one("div.sql-results table")
    return [[cell.get_text() for cell in tr.find_all("td")] for tr in table.find_all("tr")[1:]]


@pytest.mark.parametrize("path", ["/sql/", "/sql/csv/?q=SELECT+1"])
def test_anonymous_is_sent_to_admin_login(client, path):
    response = client.get(path)
    assert response.status_code == 302
    assert response["Location"].startswith("/admin/login/?next=/sql/")
    assert not QueryRun.objects.exists()


@pytest.mark.parametrize("path", ["/sql/", "/sql/csv/?q=SELECT+1"])
def test_non_staff_user_is_sent_to_admin_login(client, django_user_model, path):
    client.force_login(django_user_model.objects.create_user("guest", password="pw"))
    response = client.get(path)
    assert response.status_code == 302
    assert response["Location"].startswith("/admin/login/")
    assert not QueryRun.objects.exists()


def test_empty_page_has_editor_canned_queries_and_schema(staff_client):
    page = soup(staff_client.get("/sql/"))
    assert page.select_one("textarea#sql-input[name=q]") is not None
    assert page.find("a", string="Median rent by city and quadrant") is not None
    insert = page.find("button", string="listings_listing")
    assert insert["data-sql"] == "SELECT * FROM listings_listing LIMIT 50"
    assert page.select_one("div.sql-results") is None
    assert not QueryRun.objects.exists()


def test_running_a_query_shows_results_and_logs_it(staff_client):
    listing = make_listing(price=2500)
    response = get(staff_client, "SELECT id, address, price FROM listings_listing")
    page = soup(response)
    assert [th.get_text() for th in page.select("div.sql-results th")] == ["id", "address", "price"]
    link = page.select_one("div.sql-results td a")
    assert link["href"] == f"/listing/{listing.pk}/"
    assert result_rows(response) == [[str(listing.pk), listing.address, "2500"]]
    assert "1 row" in page.select_one("p.sql-summary").get_text()
    run = QueryRun.objects.get()
    assert (run.sql, run.row_count, run.error, run.user.username) == ("SELECT id, address, price FROM listings_listing", 1, "", "owner")
    assert page.select_one("textarea#sql-input").get_text().strip() == "SELECT id, address, price FROM listings_listing"


def test_listing_id_column_links(staff_client):
    listing = make_listing(price=2500)
    page = soup(get(staff_client, "SELECT id AS listing_id FROM listings_listing"))
    assert page.select_one("div.sql-results td a")["href"] == f"/listing/{listing.pk}/"


def test_other_ids_do_not_link(staff_client):
    page = soup(get(staff_client, "SELECT 5 AS id"))
    assert page.select_one("div.sql-results td a") is None


def test_results_are_capped_and_marked_truncated(staff_client, settings):
    settings.SQL_CONSOLE_MAX_ROWS = 2
    response = get(staff_client, "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 5) SELECT x FROM c")
    assert result_rows(response) == [["1"], ["2"]]
    assert "truncated" in soup(response).select_one("p.sql-summary").get_text()


def test_refused_write_shows_error_and_changes_nothing(staff_client):
    make_listing(price=2500)
    page = soup(get(staff_client, "DELETE FROM listings_listing"))
    assert "readonly" in page.select_one('p.sql-error[role="alert"]').get_text()
    assert Listing.objects.count() == 1
    run = QueryRun.objects.get()
    assert run.row_count is None
    assert "readonly" in run.error


def test_timeout_is_shown_and_logged(staff_client, settings):
    settings.SQL_CONSOLE_TIMEOUT_SECONDS = 0.05
    page = soup(get(staff_client, "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 100000000) SELECT COUNT(*) FROM c"))
    assert page.select_one('p.sql-error[role="alert"]').get_text().startswith("Stopped after")
    assert QueryRun.objects.get().error.startswith("Stopped after")


def test_values_are_escaped_and_nulls_marked(staff_client):
    make_listing(notes="<script>alert(1)</script>")
    response = get(staff_client, "SELECT notes, NULL AS nothing FROM listings_listing")
    assert b"<script>alert(1)</script>" not in response.content
    cells = soup(response).select("div.sql-results td")
    assert cells[0].get_text() == "<script>alert(1)</script>"
    assert cells[1].select_one("span.sql-null").get_text() == "NULL"


def test_duplicate_column_names_both_render(staff_client):
    response = get(staff_client, "SELECT 1 AS a, 2 AS a")
    assert [th.get_text() for th in soup(response).select("div.sql-results th")] == ["a", "a"]
    assert result_rows(response) == [["1", "2"]]


def test_statement_with_no_rows(staff_client):
    page = soup(get(staff_client, "SELECT id FROM listings_listing"))
    assert "0 rows" in page.select_one("p.sql-summary").get_text()


def test_recent_lists_earlier_runs(staff_client):
    get(staff_client, "SELECT 42 AS answer")
    recent = soup(staff_client.get("/sql/")).find("summary", string="Recent").parent
    assert recent.find("a", string="SELECT 42 AS answer") is not None


def test_csv_has_every_row_and_utf8(staff_client, settings):
    settings.SQL_CONSOLE_MAX_ROWS = 1
    make_listing(address_key="a|1|97209", address="1 Café Row #1", price=2000)
    make_listing(address_key="b|2|97209", address="2 Main St #2", price=3000)
    response = get(staff_client, "SELECT address, price FROM listings_listing ORDER BY price", path="/sql/csv/")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert response["Content-Disposition"].startswith('attachment; filename="query-')
    assert list(csv.reader(io.StringIO(response.content.decode("utf-8")))) == [
        ["address", "price"], ["1 Café Row #1", "2000"], ["2 Main St #2", "3000"],
    ]


def test_csv_error_is_a_400_not_a_partial_file(staff_client, settings):
    settings.SQL_CONSOLE_TIMEOUT_SECONDS = 0.05
    response = get(staff_client, "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 100000000) SELECT x FROM c", path="/sql/csv/")
    assert response.status_code == 400
    assert response.content.decode().startswith("Query failed: Stopped after")


def test_csv_without_query_is_a_400(staff_client):
    assert staff_client.get("/sql/csv/").status_code == 400


def test_csv_link_carries_the_query(staff_client):
    page = soup(get(staff_client, "SELECT 1 AS one"))
    path, _, query = page.find("a", string="Download CSV")["href"].partition("?")
    assert (path, parse_qs(query)) == ("/sql/csv/", {"q": ["SELECT 1 AS one"]})
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_sql_page.py -q`
Expected: failures with 404s, since `/sql/` doesn't exist yet.

- [ ] **Step 3: Implement `listings/sql_views.py`**

```python
import csv
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from . import sql_console
from .models import QueryRun, SavedQuery
from .sql_queries import by_category


def _console_url(sql, saved=None):
    params = {"q": sql}
    if saved is not None:
        params["saved"] = saved.pk
    return f"{reverse('sql_console')}?{urlencode(params)}"


def _cells(result):
    """Rows as cells with a link to the listing page where the column holds a listing id."""
    links = sql_console.listing_link_columns(result.sql, result.columns)
    return [
        [
            {"value": value, "href": reverse("listing_detail", args=[value]) if index in links and isinstance(value, int) else ""}
            for index, value in enumerate(row)
        ]
        for row in result.rows
    ]


@staff_member_required
def sql_console_page(request):
    sql = request.GET.get("q", "").strip()
    result = None
    if sql:
        result = sql_console.run_query(sql, max_rows=settings.SQL_CONSOLE_MAX_ROWS)
        QueryRun.record(sql=sql, user=request.user, row_count=None if result.error else result.row_count,
                        elapsed_ms=result.elapsed_ms, error=result.error)
    saved_pk = request.GET.get("saved", "")
    saved = SavedQuery.objects.filter(pk=saved_pk).first() if saved_pk.isdigit() else None
    return render(request, "listings/sql_console.html", {
        "sql": sql,
        "result": result,
        "cells": _cells(result) if result and not result.error else [],
        "max_rows": settings.SQL_CONSOLE_MAX_ROWS,
        "timeout": settings.SQL_CONSOLE_TIMEOUT_SECONDS,
        "canned": by_category(),
        "saved": saved,
        "saved_queries": SavedQuery.objects.all(),
        "recent": QueryRun.objects.all(),
        "schema": sql_console.schema(),
    })


@staff_member_required
def sql_csv(request):
    sql = request.GET.get("q", "").strip()
    if not sql:
        return HttpResponseBadRequest("No query.", content_type="text/plain")
    result = sql_console.run_query(sql)  # no row cap; the timeout still applies
    if result.error:
        return HttpResponseBadRequest(f"Query failed: {result.error}", content_type="text/plain; charset=utf-8")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="query-{timezone.localtime():%Y%m%d-%H%M}.csv"'
    writer = csv.writer(response)
    writer.writerow(result.columns)
    writer.writerows(result.rows)
    return response
```

- [ ] **Step 4: Add routes**

In `listings/urls.py`, add `from . import sql_views` below `from . import views`. Then append to
`urlpatterns`:

```python
    path("sql/", sql_views.sql_console_page, name="sql_console"),
    path("sql/csv/", sql_views.sql_csv, name="sql_csv"),
```

- [ ] **Step 5: Write the template**

`listings/templates/listings/sql_console.html`:

```html
{% extends "listings/base.html" %}
{% load humanize %}
{% block title %}SQL console · Condo Finder{% endblock %}
{% block content %}
<h1>SQL console</h1>
<p class="muted">Read-only. One statement per run, stopped after {{ timeout }} s. Cmd/Ctrl+Enter runs. <a href="{% url 'sources' %}">Back to Sources</a></p>
<div class="sql-layout">
  <section class="sql-main">
    <form method="get" action="{% url 'sql_console' %}" id="sql-form">
      <textarea name="q" id="sql-input" rows="9" spellcheck="false" autocapitalize="off" placeholder="SELECT …">{{ sql }}</textarea>
      {% if saved %}<input type="hidden" name="saved" value="{{ saved.pk }}">{% endif %}
      <div class="sql-actions">
        <button type="submit">Run</button>
        {% if result and not result.error %}<a href="{% url 'sql_csv' %}?q={{ sql|urlencode:'' }}">Download CSV</a>{% endif %}
      </div>
    </form>
    <div id="sql-saved-controls"></div>
    {% if result %}
      {% if result.error %}
        <p class="sql-error" role="alert">{{ result.error }}</p>
      {% else %}
        <p class="muted sql-summary">
          {% if result.truncated %}Showing the first {{ max_rows|intcomma }} rows (truncated). Download CSV for all of them.{% else %}{{ result.row_count|intcomma }} row{{ result.row_count|pluralize }}{% endif %}
          · {{ result.elapsed_ms|intcomma }} ms
        </p>
        {% if result.columns %}
        <div class="sql-results">
          <table>
            <tr>{% for column in result.columns %}<th>{{ column }}</th>{% endfor %}</tr>
            {% for row in cells %}
            <tr>{% for cell in row %}<td>{% if cell.href %}<a href="{{ cell.href }}">{{ cell.value }}</a>{% elif cell.value is None %}<span class="sql-null">NULL</span>{% else %}{{ cell.value }}{% endif %}</td>{% endfor %}</tr>
            {% endfor %}
          </table>
        </div>
        {% endif %}
      {% endif %}
    {% endif %}
  </section>
  <aside class="sql-side">
    {% for category, queries in canned %}
    <details open>
      <summary>{{ category }}</summary>
      <ul>{% for query in queries %}<li><a href="?q={{ query.sql|urlencode:'' }}">{{ query.title }}</a></li>{% endfor %}</ul>
    </details>
    {% endfor %}
    <details open>
      <summary>Saved</summary>
      <ul>{% for query in saved_queries %}<li><a href="?q={{ query.sql|urlencode:'' }}&amp;saved={{ query.pk }}">{{ query.name }}</a></li>{% empty %}<li class="muted">None yet.</li>{% endfor %}</ul>
    </details>
    <details>
      <summary>Recent</summary>
      <ul>{% for run in recent %}<li><a href="?q={{ run.sql|urlencode:'' }}" title="{{ run.sql }}">{{ run.sql|truncatechars:80 }}</a><br><span class="muted">{{ run.ran_at|naturaltime }} · {% if run.error %}error{% else %}{{ run.row_count }} row{{ run.row_count|pluralize }}, {{ run.elapsed_ms }} ms{% endif %}</span></li>{% empty %}<li class="muted">Nothing yet.</li>{% endfor %}</ul>
    </details>
    <details>
      <summary>Schema</summary>
      <ul>
      {% for table in schema %}
        <li>
          <button type="button" class="sql-insert" data-sql="SELECT * FROM {{ table.name }} LIMIT 50" title="Insert SELECT * FROM {{ table.name }} LIMIT 50">{{ table.name }}</button>
          <details class="sql-columns"><summary>{{ table.columns|length }} columns</summary>
            <ul>{% for name, type in table.columns %}<li><code>{{ name }}</code> <span class="muted">{{ type }}</span></li>{% endfor %}</ul>
          </details>
        </li>
      {% endfor %}
      </ul>
    </details>
  </aside>
</div>
{% endblock %}
{% block scripts %}
<script>
  (function () {
    var input = document.getElementById('sql-input');
    document.querySelectorAll('.sql-insert').forEach(function (button) {
      button.addEventListener('click', function () {
        if (input.value.trim()) {
          input.setRangeText(button.dataset.sql, input.selectionStart, input.selectionEnd, 'end');
        } else {
          input.value = button.dataset.sql;
        }
        input.focus();
      });
    });
    input.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        document.getElementById('sql-form').requestSubmit();
      }
    });
  })();
</script>
{% endblock %}
```

Note on the test helper `get_text()` for the textarea: Django renders `{{ sql }}` escaped inside
`<textarea>`, and BeautifulSoup unescapes it.

- [ ] **Step 6: Add CSS**

In `base.html`, just before `@media (max-width: 800px) {` (about line 280), add:

```css
    /* SQL console */
    .sql-layout { display:grid; grid-template-columns:minmax(0, 1fr) 300px; gap:24px; align-items:start; }
    #sql-input { width:100%; box-sizing:border-box; padding:10px; border:1px solid var(--line); border-radius:8px;
                 font:13px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace; resize:vertical; }
    .sql-actions { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:8px 0; }
    .sql-results { overflow-x:auto; max-width:100%; }
    .sql-results td { font-size:13px; white-space:pre-wrap; max-width:48ch; overflow-wrap:anywhere; }
    .sql-null { color:var(--muted); font-style:italic; }
    .sql-error { color:var(--no); white-space:pre-wrap; font:13px/1.45 ui-monospace, Menlo, monospace; }
    .sql-side > details { margin-bottom:14px; }
    .sql-side summary { font-weight:600; cursor:pointer; }
    .sql-side ul { list-style:none; padding:0; margin:6px 0 0; font-size:14px; }
    .sql-side li { margin:5px 0; overflow-wrap:anywhere; }
    .sql-columns summary { font-weight:400; font-size:12px; color:var(--muted); }
    .sql-columns ul { padding-left:10px; font-size:13px; }
    .sql-insert { border:0; background:none; padding:0; color:var(--accent); cursor:pointer; font:inherit; font-size:14px; }
```

Inside the existing `@media (max-width: 800px) { … }` block, add:

```css
      .sql-layout { grid-template-columns:1fr; }
```

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/test_sql_page.py -q`
Expected: all pass.

- [ ] **Step 8: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass (528 before this work, plus the new tests).

- [ ] **Step 9: Commit**

```bash
git add listings/sql_views.py listings/templates/listings/sql_console.html listings/urls.py listings/templates/listings/base.html tests/test_sql_page.py
git commit -m "feat: staff-only SQL console page with CSV download

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Save, edit and delete your own queries

**Files:**
- Modify: `listings/forms.py` (add `SavedQueryForm`)
- Modify: `listings/sql_views.py` (add `sql_save`, `sql_delete`)
- Modify: `listings/urls.py` (two routes)
- Modify: `listings/templates/listings/sql_console.html` (fill `#sql-saved-controls` and add a
  small script)
- Test: `tests/test_sql_saved.py`

**Interfaces:**
- Consumes: `SavedQuery` (Task 1), `_console_url` and the template from Task 4.
- Produces:
  - URL names `sql_save` (`POST /sql/save/`) and `sql_delete` (`POST /sql/saved/<pk>/delete/`).
  - `SavedQueryForm(ModelForm)` with fields `name` and `sql`.

Behavior:
- Save posts `name`, `sql`, and optionally `pk` and `as_new`.
- With `pk` and without `as_new`, it updates that saved query. Otherwise it creates a new one.
- On success it redirects to `_console_url(saved.sql, saved)`, which runs the query and shows the
  saved controls. On invalid input it shows an error message and redirects to `_console_url(sql)`.
- Delete redirects to `_console_url(sql)`, so the SQL is still on screen after deleting.

- [ ] **Step 1: Write the failing tests**

`tests/test_sql_saved.py`:

```python
from urllib.parse import parse_qs, urlencode

import pytest
from bs4 import BeautifulSoup

from listings.models import SavedQuery

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff_client(client, django_user_model):
    client.force_login(django_user_model.objects.create_user("owner", password="pw", is_staff=True))
    return client


def soup(response):
    return BeautifulSoup(response.content, "html.parser")


def test_save_creates_and_redirects_to_it(staff_client):
    response = staff_client.post("/sql/save/", {"name": "Cheap ones", "sql": "  SELECT 1  "})
    saved = SavedQuery.objects.get()
    assert (saved.name, saved.sql) == ("Cheap ones", "SELECT 1")
    assert response["Location"] == "/sql/?" + urlencode({"q": "SELECT 1", "saved": saved.pk})


def test_save_with_pk_updates(staff_client):
    saved = SavedQuery.objects.create(name="Old", sql="SELECT 1")
    staff_client.post("/sql/save/", {"name": "New", "sql": "SELECT 2", "pk": saved.pk})
    saved.refresh_from_db()
    assert (saved.name, saved.sql) == ("New", "SELECT 2")
    assert SavedQuery.objects.count() == 1


def test_save_as_new_keeps_the_original(staff_client):
    saved = SavedQuery.objects.create(name="Old", sql="SELECT 1")
    staff_client.post("/sql/save/", {"name": "Copy", "sql": "SELECT 2", "pk": saved.pk, "as_new": "1"})
    assert sorted(SavedQuery.objects.values_list("name", "sql")) == [("Copy", "SELECT 2"), ("Old", "SELECT 1")]


@pytest.mark.parametrize("data", [{"name": "", "sql": "SELECT 1"}, {"name": "Blank", "sql": "   "}])
def test_invalid_save_is_refused_with_a_message(staff_client, data):
    response = staff_client.post("/sql/save/", data, follow=True)
    assert not SavedQuery.objects.exists()
    assert "Give the query a name and some SQL" in soup(response).select_one("ul.messages").get_text()


def test_save_unknown_pk_is_404(staff_client):
    assert staff_client.post("/sql/save/", {"name": "X", "sql": "SELECT 1", "pk": 999}).status_code == 404


def test_delete(staff_client):
    saved = SavedQuery.objects.create(name="Gone", sql="SELECT 3")
    response = staff_client.post(f"/sql/saved/{saved.pk}/delete/")
    assert not SavedQuery.objects.exists()
    assert response["Location"] == "/sql/?" + urlencode({"q": "SELECT 3"})


def test_delete_requires_post(staff_client):
    saved = SavedQuery.objects.create(name="Stays", sql="SELECT 3")
    assert staff_client.get(f"/sql/saved/{saved.pk}/delete/").status_code == 405
    assert SavedQuery.objects.exists()


def test_anonymous_cannot_save_or_delete(client):
    saved = SavedQuery.objects.create(name="Stays", sql="SELECT 3")
    save = client.post("/sql/save/", {"name": "X", "sql": "SELECT 1"})
    delete = client.post(f"/sql/saved/{saved.pk}/delete/")
    assert save["Location"].startswith("/admin/login/")
    assert delete["Location"].startswith("/admin/login/")
    assert list(SavedQuery.objects.values_list("name", flat=True)) == ["Stays"]


def test_page_without_saved_offers_plain_save(staff_client):
    page = soup(staff_client.get("/sql/"))
    form = page.select_one("form#sql-save")
    assert form["action"] == "/sql/save/"
    assert form.select_one("input[name=pk]") is None
    assert form.find("button", string="Save") is not None
    assert page.select_one("form.sql-delete") is None


def test_loaded_saved_query_offers_update_copy_and_delete(staff_client):
    saved = SavedQuery.objects.create(name="Mine", sql="SELECT 7 AS n")
    page = soup(staff_client.get("/sql/?" + urlencode({"q": saved.sql, "saved": saved.pk})))
    form = page.select_one("form#sql-save")
    assert form.select_one("input[name=pk]")["value"] == str(saved.pk)
    assert form.select_one("input[name=name]")["value"] == "Mine"
    assert form.find("button", string="Save changes") is not None
    assert form.find("button", string="Save as new")["name"] == "as_new"
    assert page.select_one("form.sql-delete")["action"] == f"/sql/saved/{saved.pk}/delete/"
    assert page.select_one("form#sql-form input[name=saved]")["value"] == str(saved.pk)


def test_saved_list_links_to_each_query(staff_client):
    saved = SavedQuery.objects.create(name="Mine", sql="SELECT 7 AS n")
    sidebar = soup(staff_client.get("/sql/")).find("summary", string="Saved").parent
    href = sidebar.find("a", string="Mine")["href"]
    assert href.startswith("?")
    assert parse_qs(href[1:]) == {"q": ["SELECT 7 AS n"], "saved": [str(saved.pk)]}


def test_bad_saved_param_is_ignored(staff_client):
    assert staff_client.get("/sql/?saved=abc").status_code == 200
    assert staff_client.get("/sql/?saved=999").status_code == 200
```

Django's `urlencode` filter encodes spaces as `%20`, while `urllib.parse.urlencode` uses `+`. So
tests on links built in templates compare parsed query strings with `parse_qs`. Redirect
`Location`s come from `_console_url`, which uses `urllib.parse.urlencode`, so those compare exactly.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_sql_saved.py -q`
Expected: failures with 404 on `/sql/save/` and missing `form#sql-save`.

- [ ] **Step 3: Add the form**

In `listings/forms.py`, add `SavedQuery` to the `from .models import …` line, and append:

```python
class SavedQueryForm(forms.ModelForm):
    class Meta:
        model = SavedQuery
        fields = ["name", "sql"]
```

(ModelForm's `CharField` strips whitespace by default, so a whitespace-only `sql` fails as blank.)

- [ ] **Step 4: Add the views**

In `listings/sql_views.py`, extend the imports:

```python
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import SavedQueryForm
```

(Replace the existing `from django.shortcuts import render` line.) Append:

```python
@staff_member_required
@require_POST
def sql_save(request):
    pk = request.POST.get("pk", "")
    instance = get_object_or_404(SavedQuery, pk=pk) if pk.isdigit() and not request.POST.get("as_new") else None
    form = SavedQueryForm(request.POST, instance=instance)
    if not form.is_valid():
        messages.error(request, "Give the query a name and some SQL before saving.")
        return redirect(_console_url(request.POST.get("sql", "").strip()))
    saved = form.save()
    messages.success(request, f"Saved “{saved.name}”.")
    return redirect(_console_url(saved.sql, saved))


@staff_member_required
@require_POST
def sql_delete(request, pk):
    saved = get_object_or_404(SavedQuery, pk=pk)
    saved.delete()
    messages.success(request, f"Deleted “{saved.name}”.")
    return redirect(_console_url(saved.sql))
```

In `listings/urls.py`, append:

```python
    path("sql/save/", sql_views.sql_save, name="sql_save"),
    path("sql/saved/<int:pk>/delete/", sql_views.sql_delete, name="sql_delete"),
```

- [ ] **Step 5: Fill the template**

Replace `<div id="sql-saved-controls"></div>` in `sql_console.html` with:

```html
    <div id="sql-saved-controls">
      <form method="post" action="{% url 'sql_save' %}" id="sql-save" class="sql-actions">
        {% csrf_token %}
        <input type="hidden" name="sql" id="sql-save-sql">
        {% if saved %}<input type="hidden" name="pk" value="{{ saved.pk }}">{% endif %}
        <input type="text" name="name" value="{{ saved.name|default:'' }}" placeholder="Name this query" maxlength="100" required>
        {% if saved %}
          <button type="submit">Save changes</button>
          <button type="submit" name="as_new" value="1">Save as new</button>
        {% else %}
          <button type="submit">Save</button>
        {% endif %}
      </form>
      {% if saved %}
      <form method="post" action="{% url 'sql_delete' saved.pk %}" class="sql-actions sql-delete" onsubmit="return confirm('Delete “{{ saved.name|escapejs }}”?')">
        {% csrf_token %}
        <button type="submit">Delete saved query</button>
      </form>
      {% endif %}
    </div>
```

In the `{% block scripts %}` IIFE, after the keydown listener, add:

```javascript
    document.getElementById('sql-save').addEventListener('submit', function () {
      document.getElementById('sql-save-sql').value = input.value;
    });
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_sql_saved.py tests/test_sql_page.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add listings/forms.py listings/sql_views.py listings/urls.py listings/templates/listings/sql_console.html tests/test_sql_saved.py
git commit -m "feat: save, edit and delete queries in the SQL console

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Sources link, gunicorn line limit, docs, browser check, PR

**Files:**
- Modify: `listings/templates/listings/sources.html`
- Modify: `deploy/gunicorn.conf.py`
- Modify: `README.md`, `CLAUDE.md`, `docs/architecture.html`
- Test: `tests/test_sources_page.py`

**Interfaces:**
- Consumes: URL name `sql_console` (Task 4).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sources_page.py`:

```python
def test_sources_page_links_staff_to_sql_console(client, django_user_model):
    client.force_login(django_user_model.objects.create_user("owner", password="pw", is_staff=True))
    link = BeautifulSoup(client.get("/sources/").content, "html.parser").find("a", string="SQL console")
    assert link["href"] == "/sql/"


def test_sources_page_hides_sql_console_from_others(client):
    assert BeautifulSoup(client.get("/sources/").content, "html.parser").find("a", string="SQL console") is None
```

Add `from bs4 import BeautifulSoup` to that file's imports.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_sources_page.py -q`
Expected: `test_sources_page_links_staff_to_sql_console` fails (`TypeError: 'NoneType' object is not subscriptable`).

- [ ] **Step 3: Add the link**

In `sources.html`, directly after `<h1>Sources</h1>`:

```html
{% if user.is_staff %}<p><a href="{% url 'sql_console' %}">SQL console</a></p>{% endif %}
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_sources_page.py -q`
Expected: all pass.

- [ ] **Step 5: Raise gunicorn's request-line limit**

Append to `deploy/gunicorn.conf.py`:

```python
# The SQL console runs queries by GET ?q= so each has a permalink; the 4094-byte default rejects long ones.
limit_request_line = 0
```

- [ ] **Step 6: Update the docs**

- `README.md`:
  - In "Run on the Mac mini", change step 5 to: "Create an admin user for each of you, for data
    corrections and the SQL console: `uv run python manage.py createsuperuser`."
  - Add a section after "Scraper health":

    ```markdown
    ## SQL console

    `/sql/` (linked from Sources when you're logged in as staff) runs read-only SQL against the database.
    Pick a starter query from the sidebar, click a table in Schema to insert `SELECT * FROM … LIMIT 50`,
    or write your own and save it. Results show up to 1,000 rows; "Download CSV" gets all of them.
    Queries stop after 5 seconds. Writes are refused by SQLite itself.
    ```
- `CLAUDE.md`:
  - "Current state": add **Open: #NN** (SQL console) once the PR exists, and the deploy note to
    run `createsuperuser` for the second owner on the Mac mini.
  - "Recently shipped" gets a bullet after merge. Leave it for the owner's follow-up if that's the
    convention in the moment.
  - Code map, under `listings/views.py`, add:

    ```markdown
    - `listings/sql_console.py`, `sql_queries.py`, `sql_views.py`: the staff-only SQL console at `/sql/`.
      User SQL runs on its own SQLite connection (`mode=ro`, `query_only`, an authorizer blocking
      `ATTACH` and `query_only = OFF`) with a 5 s progress-handler timeout and a 1,000-row page cap
      (`SQL_CONSOLE_*` settings). Starter queries live in `sql_queries.py`, and a test runs each one. `SavedQuery`
      holds saved queries; `QueryRun` logs runs for "Recent", pruned to 50. In tests the database is
      shared-cache memory, so `connect_readonly()` opens it with `read_uncommitted` instead of `mode=ro`.
    ```
  - Gotchas, add: "`ATTACH` creates a file even on a `mode=ro` SQLite connection. The SQL console's
    authorizer blocks it."
- `docs/architecture.html`:
  - Pages table, add a row before Admin:
    `<tr><td>SQL console</td><td>Staff-only read-only SQL: starter queries, saved queries, recent runs, schema, CSV</td><td>Queries run by GET <code>?q=</code> (permalinks) on a separate read-only SQLite connection with a 5 s timeout. Save and delete POST.</td></tr>`
  - After the paragraph at about line 317 (TrendReport/SearchPriorities), add:
    `<p>The SQL console adds two more standalone tables: <code>SavedQuery</code> (name and SQL) and <code>QueryRun</code> (the last 50 runs, with who ran them, row count, time and any error).</p>`
  - Then republish it to https://claude.ai/artifact/MASfMv25dYKcHeYTx6eUgq: Artifact tool, `url`
    set to that link, `file_path` set to `docs/architecture.html`. Read the artifact first.

- [ ] **Step 7: Full suite**

Run: `uv run pytest -q`
Expected: all pass. Report the count.

- [ ] **Step 8: Verify in a browser**

The laptop's launchd service shares `db.sqlite3`. Migration 0008 only adds two tables, so the
service's older code keeps working, but back the file up first:

```bash
cp db.sqlite3 /private/tmp/sqlconsole-backup.sqlite3
```

Then migrate and run the dev server on the real data:

```bash
uv run python manage.py migrate
```

```bash
DJANGO_DEBUG=1 uv run python manage.py runserver 127.0.0.1:8001
```

Check at desktop width and at 390 px wide:
- `/sql/` logged out redirects to `/admin/login/?next=/sql/`. After logging in as staff, the page
  loads.
- Each starter category runs. Listing ids link to the listing page.
- Clicking a table in Schema inserts its SELECT at the cursor. Cmd+Enter runs.
- Save, then edit ("Save changes"), then "Save as new", then delete. Recent fills in.
- `DELETE FROM listings_listing` shows the readonly error, and the listings still exist.
- The CSV downloads and opens.
- Nothing scrolls sideways at phone width. The results table scrolls inside its own box. The
  console has no errors.
- A query longer than 4 KB (for example a long `IN (…)` list) runs. The dev server has no line
  limit; to exercise the gunicorn setting, run
  `uv run gunicorn -c deploy/gunicorn.conf.py condofinder.wsgi --bind 127.0.0.1:8002` and repeat
  it there.

Delete any saved queries you created while testing.

- [ ] **Step 9: Commit and open the PR**

```bash
git add listings/templates/listings/sources.html deploy/gunicorn.conf.py README.md CLAUDE.md docs/architecture.html tests/test_sources_page.py
git commit -m "docs: SQL console link on Sources, docs and gunicorn line limit

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

```bash
git push -u origin sql-console
```

Open the PR with `gh pr create` and the title `feat: staff-only read-only SQL console`. The body
should summarize the feature and say how to deploy:
1. `git pull && ./deploy/install.sh` on the Mac mini. This migrates and restarts gunicorn with the
   new line limit.
2. `uv run python manage.py createsuperuser` for the second owner.

Put each command in its own code block, with no inline comments. End the body with
`🤖 Generated with [Claude Code](https://claude.com/claude-code)`. Then put the PR number into
CLAUDE.md's "Current state" in a follow-up commit on the same branch
(`docs: note PR #NN in CLAUDE.md`) and push.
