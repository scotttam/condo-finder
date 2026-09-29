# CLAUDE.md

Handoff notes for working on Condo Finder from any machine. Read `INTENT.md` for why the app
exists and `README.md` for setup and deploy. `docs/architecture.html` has diagrams of the whole
system: open it in a browser (it's also published privately at
https://claude.ai/artifact/MASfMv25dYKcHeYTx6eUgq). This file is the current state of the work and
how to continue it.

> **Keep this file current.** Any change that affects what's below (new features, sources, models,
> conventions, open work, known issues) updates this file in the same PR. Update "Current state"
> whenever PRs merge or open. If a change alters what the diagrams show (components, the scrape
> flow, models, pages), update `docs/architecture.html` too, and republish it to the artifact URL
> above.

## Current state (updated 2026-09-29)

- **Merged to `main` through PR #53** (move-in specials). **Open: furnished label** (`furnished`);
  migration 0007. 517 tests pass.
- **Production:** the Mac mini, live since 2026-09-28. It runs gunicorn under launchd and scrapes at
  7, 11, 15, 19 and 23 o'clock. Both users reach it over Tailscale at `http://<mac-mini>:8000`.
- **Deploy:** on the Mac mini, run `git pull && ./deploy/install.sh`. It syncs deps, installs Chromium,
  migrates, collects static files and restarts the service.
- **Recently shipped:**
  - Furnished label (in review): `is_furnished` detected in listing text, a "Furnished" pill on cards,
    the table, the listing page and the Feed, and a Furnished filter (Any / Hide / Only) under More filters.
  - Move-in specials: detected in listing text, shown on cards, pins, the listing page,
    the Feed and Trends, with a "Move-in specials only" filter.
  - Trends page: Claude's top 5 picks with negotiating angles, market charts, report history.
  - Listing page redesign: header card, stat tiles, status pills, notes that save themselves (#43, #44).
  - Feed page with unread markers (#41, #42).
  - Editing price history in place and "Refresh from sites" (earlier PRs).
- **Offered but not started (ask before picking up):**
  - Tidy the display of partial Redfin addresses (e.g. "97230", "SW Gage Lane").
  - Cluster map pins when zoomed out.
  - Let a manual price-history entry update the listing's current price.
  - Speed up the Zillow price-history catch-up.
- **Slow on purpose:** Redfin listing pages are behind a WAF, so detail fetches are paced at 10 per
  run with a 20s delay and stop at the first challenge. Backfilling Redfin history takes days.

## Commands

```bash
uv sync
uv run playwright install chromium          # once; RentEngine (Chroma) uses headless Chromium
uv run python manage.py migrate
uv run python manage.py scrape [--source zillow]
DJANGO_DEBUG=1 uv run python manage.py runserver 127.0.0.1:8000
uv run pytest -q
```

Settings come from `.env` (see `.env.example`). `db.sqlite3` is not in git, so every machine has
its own data. Production data lives only on the Mac mini.

## Stack

- **App:** Django 6.1, SQLite (WAL, IMMEDIATE transactions), uv, pytest + pytest-django.
- **Scraping:** httpx and BeautifulSoup; Playwright for RentEngine.
- **Scheduling and serving:** APScheduler runs inside the web process. gunicorn runs with **1 worker**
  so the scheduler runs only once. WhiteNoise serves static files.
- **Front end:** server-rendered templates with HTMX; no JS build step. Leaflet maps use
  OpenStreetMap tiles (they need the `strict-origin-when-cross-origin` referrer policy). Addresses
  are geocoded with Nominatim.

## Code map

- `listings/scrapers/`
  - `registry.py` lists `SOURCES`, one config dict per site. Adding an AppFolio or Nesthub property
    manager is one entry.
  - `base.py` holds `Fetcher` (polite delays), the `Scraper` base, `RefreshBlocked`, and the
    `known_ids`/`details_version` logic that decides which detail pages get re-fetched.
  - One module per platform: appfolio, nesthub, rentengine, redfin, zillow, craigslist.
  - Per-source options:
    - `request_delay`: pause between requests.
    - `max_detail_fetches`: detail-page budget per run.
    - `skip_details_if_on`: skip listings another source already covers.
    - `detail_priority`: listings matching the default filters are fetched first.
- `listings/ingest.py` turns scraped items into rows. The rules it enforces:
  - **Dedupe key** is normalized address + unit + ZIP. Units from the same site never merge
    (`address_key|site:id`), and hidden addresses never merge.
  - **Price:** each `SourceListing.last_price` stores its own site's price, and `Listing.price` is the
    lowest across active sites. A `PriceChange` is recorded only when one site changes its own price.
  - **Off-market:** a listing goes off-market after 3 missed scrapes. Craigslist listings are
    checked directly before being marked gone, because its search shows only about 350 posts.
  - **Implausible rents:** anything over `MAX_PLAUSIBLE_RENT` (25k) is rejected, e.g. Zillow home
    values.
  - **Empty scrapes:** a scrape that returns 0 items counts as a failure and never marks listings gone.
- `listings/specials.py` finds move-in specials ("4 weeks free", "$500 off first month") and their
  value; `Listing.special_offer` holds the sentence. Unlike features, it's re-read from the listing's
  current text on every update, so it clears when a site drops it (admin override `special_offer: ""`
  silences a false match). `effective_rent` spreads the offer over a 12-month lease.
- `listings/extract.py` and `parsing.py` parse parking, W/D, AC, outdoor space, furnished and property
  type from listing text. `is_furnished` stays unknown when a listing is offered either way ("furnished
  or unfurnished", "furnished if desired") or when the phrase is about the building ("Furnished
  apartments available"). `reextract_all()` re-runs them over stored text after a parser change.
- `listings/feed.py` records `FeedEvent` rows for new listings and for changes to listings with a
  status. `happened_at` is when the change happened; `created_at` is when we learned of it. Unread
  state is per browser, in the `feed_seen_at` cookie.
- **Trends** (spec: `docs/superpowers/specs/2026-09-29-trends-design.md`):
  - `listings/trend_stats.py` computes weekly median rent by city, the price-cut share and days on
    market over comparable listings. Weeks before the first scrape are blank on purpose (only
    survivors are known for them).
  - `listings/analyst.py` makes two Claude calls (Opus 5.5, structured JSON output, server-side
    fallback). Pass 1 shortlists 25 candidates from compact facts; pass 2 ranks the top 5 from full
    descriptions, notes, rejected listings and "What we're looking for" (`SearchPriorities`).
  - Each run is saved as a `TrendReport` with usage and cost. One runs at a time in a background
    thread. The scheduler starts the daily report after the first scrape of the day; manual re-runs
    are capped by `TRENDS_MANUAL_RUNS_PER_DAY`.
  - Tests use a `FakeClient` (`tests/test_analyst.py`) and never call the API. A real run costs
    about $0.50.
- `listings/views.py`:
  - List/map page: the filter bar in `_filter_bar.html`, the split map, "Search this area".
  - Trends page, run/priorities/status endpoints, and the chart helper in `listings/charts.py`.
  - Detail page, Feed, history add/edit/delete, refresh listing, tracking, and Sources (scraper
    health).
- `listings/forms.py` holds `ListingFilterForm`, which carries the default filters: 2 bd / 2 ba /
  2 parking, a $2,000 minimum, and apartments hidden.
- `deploy/`: `install.sh`, the launchd plist template, `launchd-restart.sh` (waits for bootout
  before bootstrapping) and `gunicorn.conf.py`.
- Design docs: `docs/superpowers/specs/` and `plans/`. Architecture diagrams: `docs/architecture.html`.

## Conventions

- **Stacked PRs.** Deliver multi-step work as a stack of small PRs titled `[Feature n/N] …`. Each
  PR body lists the stack and says how to merge it. The owner merges bottom-up with **Create a merge
  commit**; the repo deletes branches on merge. Put one-off changes in a single PR off `main`.
- **Migrations:** production is live, so add new migrations. Never squash or edit applied ones.
  Data fixes go in data migrations.
- **Tests:** write tests alongside every change and keep the full suite green. Tests must assert
  on element markup, not bare class names: class names also appear in the inline stylesheet in
  `base.html`, so matching on them passes even when the element is missing.
  `tests/helpers.py` has `FakeFetcher`/`FakeResponse` and fixtures. Scraper tests use saved HTML
  and JSON in `tests/fixtures/`.
- **Verify in a browser.** Check UI changes against the local dev server with real data, on desktop
  and at phone width. Nothing should scroll sideways and the console should be error-free. Restore
  any status or notes you changed while testing.
- **Admin-style controls on normal pages are fine.** Only the two owners use the app.
- **Scrape politely.** Keep delays and budgets, and stop when a site starts blocking.
  Realtor.com is deliberately skipped because of its Kasada bot protection.
- Commit messages use `feat:` / `fix:` / `docs:` prefixes.

## Gotchas

- The shell is zsh. It doesn't word-split variables, and its arrays are 1-based.
- `git mv` fails on untracked files. Use `mv`.
- Zillow shows a home's *value* on off-market pages. The refresh code checks for `FOR_RENT` and
  treats anything else as removed.
- Redfin's search API has no price history; its listing pages do (fetched slowly, see above).
- The CSS lives inline in `listings/templates/listings/base.html`.
