# Plan decisions: admin SQL console

Settled in a grill-me session on 2026-09-30.

## Goal

A staff-only page for running ad hoc read-only SQL against the SQLite database, with pre-canned
starter queries.

## Decisions

- **Access:** require a Django staff session (`is_staff`, same login as `/admin/`). Anyone without one
  is redirected to the admin login. Only one owner has a login on the Mac mini today, so the deploy
  notes include `uv run python manage.py createsuperuser` for the other, and the README gets a line
  about it.
- **Read-only, enforced by the database:** queries run on a separate SQLite connection opened with
  `mode=ro` (URI) plus `PRAGMA query_only`, so any write fails in SQLite itself. The Django default
  connection is never used for user SQL.
- **Canned queries:** defined in a Python module (versioned and tested), grouped by category:
  - *Listings & market:* active listings by city/quadrant with median price, price per sqft
    ranking, newest listings, longest on market, listings with move-in specials.
  - *Price history:* biggest price drops, listings with several cuts, recent `PriceChange` rows,
    hand-entered history (blank `source`).
  - *Scraper health & data quality:* `SourceRun` success and failure by source, listings per source,
    overlap across sites, missing geocode/sqft/beds, possible unit-number duplicates.
  - *Tracking & costs:* listings by status with notes, `FeedEvent` counts by kind and day,
    `TrendReport` cost and token usage over time.
  - A test runs every canned query against the test database.
- **Your own queries:** a new `SavedQuery` model (name, SQL, timestamps) with save, edit and
  delete on the page, listed alongside the canned ones.
- **History:** a new `QueryRun` model (sql, user, ran_at, row count, elapsed ms, error), pruned to
  the last 50. It's shown as a "Recent" list and written through the normal (writable) connection.
- **Results:** an HTML table with the row count and elapsed time. It shows at most 1,000 rows, with
  a "truncated" note beyond that. Queries abort after 5s (SQLite progress handler), which protects
  the single gunicorn worker that also runs the scheduler. A CSV download runs the full query
  without the row cap, under the same timeout.
- **Writing queries:** a plain textarea plus a collapsible schema sidebar (tables, then columns
  and types, from `sqlite_master` and `PRAGMA table_info`). Clicking a table inserts
  `SELECT * FROM <table> LIMIT 50`. No CDN editor.
- **URL and navigation:** `/sql/`, styled with `base.html`. A "SQL console" link on the Sources page
  is shown only to staff. No top-nav entry.
- **Running a query:** via GET `?q=`, so every query has a permalink and back/forward work. A
  `listing_id` column (or `id` from `listings_listing`) links to the listing's page.
- **Delivery:** a single PR off `main`. It includes the migrations for `SavedQuery` and `QueryRun`,
  tests, updates to CLAUDE.md and README, and `docs/architecture.html` if the diagrams change.
