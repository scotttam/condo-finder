# Trends page: design

Decided in a grill-me session on 2026-09-29.

## Goal

Add a top-level **Trends** page, next to Listings and Feed. It uses Claude to read the current
market and recommend the best options right now, taking into account how prices are moving and
what the owners have written in their notes.

## Page layout (top to bottom)

1. **Header.** Shows when the report was generated and what it cost. A "Re-run now" button starts a
   new report, and a dropdown opens older reports.
2. **What changed since the last report.** New picks, dropped picks, and price changes on picks that
   stayed. Hidden when there's no earlier report.
3. **Top 5 picks, ranked.** Each card has:
   - photo, address, location, price, beds, baths and parking
   - a one-line headline
   - "Why it fits"
   - concerns, and questions to ask the landlord
   - a **negotiation angle** (price cuts, days on market, how it compares with similar units) with a
     suggested offer range
   - status pills (Interested / Toured / Applied / Rejected) that save on click, and a link to the
     listing
4. **Market trends.** Three charts computed from the database, plus Claude's short write-up of what
   they mean for the owners:
   - median asking rent by week, one line per city
   - share of active listings that have had a price cut, by week
   - median days on market, by week
5. **What we're looking for.** A shared free-text box that saves automatically. The next report
   uses it.

## What Claude sees

- **Candidates:** listings that pass the default filters (the same ones the Listings page opens
  with), plus every listing with status Interested, Toured or Applied.
- **Passed on:** listings with status Rejected, with their notes. These are context for what the
  owners dislike, and are never picked.
- **Per-candidate facts:**
  - id and address, city, quadrant, neighborhood, property type
  - price, beds, baths, sqft, $/sqft
  - parking, W/D, AC and outdoor space, each shown as yes, no or unknown
  - days on market, and the price history as a list of date and price
  - status and notes
- **Market statistics:** computed in code (the chart data plus current medians), not by Claude.
- **The priorities text.**
- **The previous report's picks,** for continuity.

## Two passes

1. **Shortlist.** Compact facts for all candidates. Claude returns up to 25 ids to look at more
   closely.
2. **Final ranking.** Full descriptions for the shortlist, plus the passed-on listings, priorities,
   market stats and previous picks. Claude returns the top 5 picks and the market write-up.

Both passes use structured JSON output (`output_config.format`). Ids that aren't in the candidate
set are dropped.

## Model and API

- **Model:** Claude Opus 5.5 (`claude-opus-5-5`) through the official `anthropic` Python SDK, with
  streaming and `get_final_message()`.
- **Thinking:** adaptive (always on for this model). Effort is `medium` for pass 1 and `high` for
  pass 2.
- **Refusals:** server-side fallback is on (`fallbacks: "default"`, beta
  `server-side-fallback-2026-07-01`). A final `stop_reason == "refusal"` fails the report with a
  clear message.
- **Credentials:** read by the SDK from `ANTHROPIC_API_KEY` (in `.env`). With no key, the page
  explains how to add one and the Re-run button is disabled.

## Running

- **Automatic:** once a day, after the first scheduled scrape of the day. It runs only when no
  automatic report exists for today and a key is configured.
- **Manual:** the "Re-run now" button, capped at `TRENDS_MANUAL_RUNS_PER_DAY` (default 5) per day.
- **One report at a time:** each report runs in a background thread under a lock. While it runs,
  the page shows "Working…" and polls every few seconds.

## Storage

- **`TrendReport`:**
  - status (running, done or failed), trigger (auto or manual)
  - created_at, finished_at, error
  - model, token usage and cost in USD
  - `stats` (the chart data), `shortlist` (ids)
  - `picks`: a JSON list of `{listing_id, rank, headline, why, concerns[], questions[], leverage,
    offer_low, offer_high, price_at_pick}`
  - `market_read` (text), `summary` (one line)
  - `changes` (JSON diff against the previous completed report)
- **`SearchPriorities`:** a single row holding `text` and `updated_at`.
- Every report is kept.

## Cost

Cost is computed from `usage` at Opus 5.5 rates: $4 per million input tokens, $20 per million
output tokens, $0.20 per million cache-read tokens and $5 per million cache-write tokens. Expect
about $0.40 a run.

## Out of scope

- Chat or Q&A with the data.
- Emailing reports.
- Analyzing the filters currently set on the Listings page.
