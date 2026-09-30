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

## Current state (updated 2026-09-30)

- **Merged to `main` through PR #58** (#56: the first click on a map no longer scrolls the page and shifts
  the zoom buttons; #57 and #58, docs only). After deploying #55, run
  `uv run python manage.py merge_duplicates --dry-run` on the Mac mini, then without `--dry-run` (the
  post-scrape pass would also do it on the next run).
- **Open: the accounts stack, `[Accounts 1/10]`–`[Accounts 10/10]`** (logins, search groups,
  collaboration; plan: `docs/superpowers/plans/2026-09-30-accounts-and-collaboration.md`). Deploy once
  after the whole stack merges, following the README runbook. 592 tests pass.
  `create_owner` claims the owner's migrated notes (now comments) if the account didn't exist when migrating.
- **Production:** the Mac mini, live since 2026-09-28. It runs gunicorn under launchd and scrapes at
  7, 11, 15, 19 and 23 o'clock. Both users reach it over Tailscale at `http://<mac-mini>:8000`.
- **Deploy:** on the Mac mini, run `git pull && ./deploy/install.sh`. It syncs deps, installs Chromium,
  migrates, collects static files and restarts the service.
- **Recently shipped:**
  - Unit-number duplicates: Redfin often drops the unit, so "821 NW 11th Ave" and
    "821 NW 11th Ave #105" became two listings. Ingest now matches them, and a pass after each scrape
    (and `manage.py merge_duplicates`) merges existing pairs, keeping the copy with notes or a status.
  - Furnished label: `is_furnished` detected in listing text, a "Furnished" pill on cards,
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
uv run playwright install chromium
uv run python manage.py migrate
uv run python manage.py scrape [--source zillow]
DJANGO_DEBUG=1 uv run python manage.py runserver 127.0.0.1:8000
uv run pytest -q
```

Run `playwright install chromium` once per machine; RentEngine (Chroma) uses headless Chromium.
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

- `accounts/`: logins and search groups (spec: `docs/superpowers/specs/2026-09-30-accounts-decisions.md`).
  - `SearchGroup` owns everything a household says about listings; each user has one `Profile` in
    exactly one group. `accounts/groups.py` has `owners_group()` (the oldest group), `profile_for()`
    (makes a solo group for accounts created outside the app) and `move_to_group()`.
  - `LoginRequired` middleware guards every page (views opt out with `@login_not_required`); an HTMX
    request without a login gets `HX-Redirect` to the login page. `CurrentGroup` sets `request.profile`
    and `request.group`.
  - Log in with email (`username` is the lowercased email). `manage.py create_owner --email --name`
    makes the site admin (staff) in the owners' group; `manage.py changepassword <email>` resets a password.
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
  - **Missing unit numbers:** a listing without a unit joins the one listing at that street + ZIP with a
    unit, from a different site, with the same beds/baths and sqft (price when sqft is missing); see
    `listings/merge.py`. A site that omits the unit never erases a known one from the address.
  - **Price:** each `SourceListing.last_price` stores its own site's price, and `Listing.price` is the
    lowest across active sites. A `PriceChange` is recorded only when one site changes its own price.
  - **Off-market:** a listing goes off-market after 3 missed scrapes. Craigslist listings are
    checked directly before being marked gone, because its search shows only about 350 posts.
  - **Implausible rents:** anything over `MAX_PLAUSIBLE_RENT` (25k) is rejected, e.g. Zillow home
    values.
  - **Empty scrapes:** a scrape that returns 0 items counts as a failure and never marks listings gone.
- `listings/collab.py`: everything a search group says about a listing. `ListingState` holds its
  status (no row = New) with who set it and when. `decorate(listings, group, user)` attaches
  `group_status`/`group_status_label`/`state` for templates; `status_expr(group)` annotates querysets
  (the statuses filter). `apply_filters(queryset, data, group)` needs the group.
  `Comment` threads replace notes: author-only edit/delete in `collab_views.py`; the thread polls
  every 30s but not while a comment is being edited; each comment has a Feed item that follows edits
  and deletes.
  `Vote` is one 👍/👎 per person per listing (cleared by clicking again; deleted when the person leaves
  the group). The Votes filter (`everyone_likes`, `someone_likes`, `disagree`, `unvoted`) counts votes
  with subqueries so it composes with the price-history join.
- `listings/merge.py` matches with/without-unit pairs (`unit_match`) and merges two listings (`merge`):
  sites, price history, feed events and Trends picks move over. The survivor is the copy the owners
  touched (status, comments, overrides or hand-entered history), else the one with a unit. If both were
  touched, comments from both are kept and each group keeps one status, the furthest along (new < interested < toured < applied < rejected).
  `merge_unit_duplicates()` runs after every scrape; `manage.py merge_duplicates [--dry-run]` runs it now.
- `listings/specials.py` finds move-in specials ("4 weeks free", "$500 off first month") and their
  value; `Listing.special_offer` holds the sentence. Unlike features, it's re-read from the listing's
  current text on every update, so it clears when a site drops it (admin override `special_offer: ""`
  silences a false match). `effective_rent` spreads the offer over a 12-month lease.
- `listings/extract.py` and `parsing.py` parse parking, W/D, AC, outdoor space, furnished and property
  type from listing text. `is_furnished` stays unknown when a listing is offered either way ("furnished
  or unfurnished", "furnished if desired") or when the phrase is about the building ("Furnished
  apartments available"). `reextract_all()` re-runs them over stored text after a parser change.
- `listings/feed.py` records `FeedEvent` rows. Scraped events (new listings, changes) have no
  `group`, and every group sees them; change events show for listings the group tracks (status ≠ New).
  A group's own activity (status changes, comments, votes) has `group` and `actor` and shows only to
  that group. `happened_at` is when the change happened; `created_at` is when we learned of it. Unread
  state is per person (`Profile.feed_seen_at`); your own actions never count as unread. The nav badge
  polls `/feed/badge/` every 30s.
- **Trends** (spec: `docs/superpowers/specs/2026-09-29-trends-design.md`):
  - `listings/trend_stats.py` computes weekly median rent by city, the price-cut share and days on
    market over comparable listings. Weeks before the first scrape are blank on purpose (only
    survivors are known for them).
  - `listings/analyst.py` makes two Claude calls (Opus 5.5, structured JSON output, server-side
    fallback). Pass 1 shortlists 25 candidates from compact facts; pass 2 ranks the top 5 from full
    descriptions, comments, votes, rejected listings, the group's default filters and "What we're
    looking for" (`SearchPriorities`, one per group). Market charts (`trend_stats`) are shared.
  - Each run is saved as a `TrendReport` with its group, usage and cost. Each group has its own
    reports and re-run cap (`TRENDS_MANUAL_RUNS_PER_DAY`). The scheduler's daily run, after the first
    scrape of the day, makes one report per group with members, one after another in one background
    thread (about $0.50 each). One report runs at a time across all groups.
  - Tests use a `FakeClient` (`tests/test_analyst.py`) and never call the API. A real run costs
    about $0.50.
- `listings/views.py`:
  - List/map page: the filter bar in `_filter_bar.html`, the split map, "Search this area".
  - Trends page, run/priorities/status endpoints, and the chart helper in `listings/charts.py`.
  - Detail page, Feed, history add/edit/delete, refresh listing, tracking, and Sources (scraper
    health).
- `listings/forms.py` holds `ListingFilterForm`. `app_default_filters()` (2 bd / 2 ba / 2 parking, a
  $2,000 minimum, apartments and rejected hidden, Votes: Any) is where a new group starts;
  `default_filter_data(group)` lays the group's saved defaults (`SearchGroup.default_filters`, set by
  "Save as our defaults") over them. The owners' group got the old hard-coded defaults as its saved copy.
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
  The `client` fixture is logged in as Sam, a staff user in the owners' group (`home_group()`);
  `anon_client` is logged out. `make_user()` in `tests/helpers.py` adds more people.
- **Verify in a browser.** Check UI changes against the local dev server with real data, on desktop
  and at phone width. Nothing should scroll sideways and the console should be error-free. Restore
  any status or comments you changed while testing.
- **Staff-only controls.** Price-history edits, Refresh from sites, the Sources page and admin
  overrides are for the site admin (`is_staff`, via `accounts.decorators.staff_required`, and hidden
  in templates with `{% if user.is_staff %}`). Everyone else sees that data read-only.
- **Scrape politely.** Keep delays and budgets, and stop when a site starts blocking.
  Realtor.com is deliberately skipped because of its Kasada bot protection.
- Commit messages use `feat:` / `fix:` / `docs:` prefixes.

## Planning workflow: grill-me, then Superpowers

New features are planned with `/grill-me` and built with Superpowers, as two separate steps.
Superpowers' session-start hook pushes its `brainstorming` skill "before any creative work", so
it takes over a grill-me interview partway through. To avoid that, Superpowers is **off by default**
(user scope, `~/.claude/settings.json`) and turned on only for the build.

1. **Grill the plan (Superpowers off).** Run `/grill-me` and answer until every decision is settled.
2. **Check the decisions file.** The owner's local grill-me saves its final summary to
   `docs/plan-decisions.md`, asking before overwriting. Confirm the file exists before `/clear`, which
   erases the conversation; if it's missing, save the summary there. To keep an earlier plan's
   decisions, rename that file first (e.g. `docs/plan-decisions-<feature>.md`) and use that path below.
3. **Turn Superpowers on.** `/plugin` → enable **superpowers**, then `/clear` (or restart) so the
   plugin and its hook load.
4. **Start from the decisions file.**
   - Everything settled: `/superpowers:writing-plans docs/plan-decisions.md` goes straight to an
     implementation plan.
   - Want a formal spec, or gaps remain: `/superpowers:brainstorming docs/plan-decisions.md` should
     read the decisions back and ask only about what's missing.
   - Specs go in `docs/superpowers/specs/` and plans in `docs/superpowers/plans/`, dated as the
     existing ones are. Deliver the build as a stack of PRs (see Conventions).
5. **Carry out the plan.** Pick **inline** for small or medium plans, **subagents** for long plans with
   many independent tasks (each subagent rebuilds context from scratch, so it costs more tokens).
6. **Turn Superpowers off again** with `/plugin`, so the next grill-me session isn't taken over.

Toggle it everywhere from a shell with `claude plugin enable superpowers@claude-plugins-official --scope user`
(or `disable`). Avoid enabling it at project scope: that brings the takeover back during grill-me.

The grill-me change is local to the owner's machine (`~/.claude/skills/grill-me-skill/SKILL.md`, cloned
from `github.com/RobMitt/grill-me-skill`). Its last step reads: "When finished, provide a concise summary
of all decisions made, and save it to `docs/plan-decisions.md` in the current project. If that file
already exists, ask before overwriting it." On another machine, or after pulling upstream updates,
reapply that line or save the summary by hand.

## Gotchas

- The shell is zsh. It doesn't word-split variables, and its arrays are 1-based.
- Don't put `# comments` after commands you give the owner to paste. Interactive zsh doesn't
  treat `#` as a comment, so the comment is passed to the command as arguments. Explain the command in
  prose instead, and give each command its own code block when they run at different times.
- `git mv` fails on untracked files. Use `mv`.
- Zillow shows a home's *value* on off-market pages. The refresh code checks for `FOR_RENT` and
  treats anything else as removed.
- Redfin's search API has no price history; its listing pages do (fetched slowly, see above).
- The CSS lives inline in `listings/templates/listings/base.html`.
