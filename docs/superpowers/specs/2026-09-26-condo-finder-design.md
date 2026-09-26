# Condo Finder — Design Spec

**Date:** 2026-09-26
**Status:** Approved (design interview), ready for implementation

## Purpose

A small, self-hosted Python web app that aggregates rental listings in the Portland, OR
area into one browsable, regularly updated database, so two people can find and track a
nice condo to rent together.

## Search target

- **Cities:** Portland, Lake Oswego, Beaverton. Listings outside these cities are discarded.
- **Property type:** condos are the focus. Every listing is classified as
  `condo`, `townhome`, `house`, `apartment`, `other`, or `unknown`; `apartment` is hidden by
  default in the UI (one click to show).
- **Ideal:** ≥2 bedrooms, ≥2 bathrooms, ≥2 parking spaces.
- **Must-have filters:** in-unit washer/dryer, air conditioning, outdoor space
  (balcony/patio/deck/yard).
- **Budget:** default UI max $5,000/mo, no cap at storage time.

## Storage policy

- Store every listing in a target city with **≥2 bedrooms** (bathrooms/parking unfiltered).
- Parking, W/D, AC, outdoor space, property type are extracted from structured fields and
  regex/keyword matching over title + description + amenities. Each is **tri-state**
  (yes / no / unknown). Unknown is never hidden by default; it's shown with an "unknown"
  badge.
- Also captured: monthly price, beds, baths, sqft, full address + unit, available date,
  one photo URL, title, description, source URL(s), lat/lng, neighborhood.

## Sources

| Source | Platform | Phase |
|---|---|---|
| Pearl Property Management (managethepearl.com) | AppFolio `pearlpropertymanagement` | 1 |
| Living Room Realty rentals | AppFolio `livingroomproperty` | 1 |
| The Management Group | AppFolio `tmgoregon` | 1 |
| Mainlander | AppFolio `mainlander` | 1 |
| PropM | AppFolio `propmhomes` + Nesthub site | 1 |
| Utopia Management | AppFolio `utopiamanagement` (multi-state; city filter applies) | 1 |
| Uptown Properties | Nesthub (`uptownpm.com/portland-homes-for-rent`) | 1 |
| Craigslist (Portland) | direct | 2 |
| Realtor.com rentals | direct | 2 |
| Zillow | direct, headless browser (Playwright) | 2 |
| Redfin | direct, headless browser (Playwright) | 2 |

- AppFolio and Nesthub are each implemented once as a **generic, config-driven scraper**;
  adding another property manager is one registry entry.
- Zillow/Redfin are scraped directly by the user's choice despite their ToS and anti-bot
  measures. Scraping must be polite (low rate, runs only on schedule), and each source is
  isolated so one blocked source never affects others.
- Phase 1 delivers the full app with the AppFolio + Nesthub sources. Phase 2 adds the four
  portal/classifieds scrapers under a separate plan.

## Data lifecycle

- **De-duplication:** listings from different sources are merged into one `Listing` when
  their normalized address key (street + unit + ZIP5) matches. Each source's copy is a
  `SourceListing` linking back with its own URL.
- **Off-market:** after a *successful* run of a source (≥1 result), any of that source's
  listings not seen get `missed_runs += 1`; at 3 misses the source listing goes inactive.
  A `Listing` is off-market when none of its source listings are active. Off-market
  listings keep status/notes and are hidden by default. A listing that reappears is
  reactivated.
- **Price history:** every observed price change creates a `PriceChange` row; first-seen /
  last-seen timestamps give days on market.

## User workflow

- Shared (no login; LAN-only) **status**: New / Interested / Toured / Applied / Rejected,
  plus a shared free-text **notes** field. Rejected is hidden by default.
- **Browse:** filterable list + Leaflet map. Filters: city, neighborhood, min beds/baths/
  parking (with "include unknown"), max price, property types, W/D / AC / outdoor
  (any / yes-or-unknown / yes), status, show off-market. Sort by price, newest, $/sqft.
- **Detail page:** all fields, source links, price history, status + notes editing (HTMX).
- **Sources page:** each source's last success, last listing count, last error,
  consecutive failures; a "Scrape now" button.
- **Django admin** for manual correction of any field.

## Location

Addresses are geocoded with OpenStreetMap Nominatim (≤1 req/s, identifying User-Agent,
results stored on the listing so each address is geocoded once). Neighborhood comes from
Nominatim's `neighbourhood`/`suburb` address component.

## Alerts (ntfy.sh push to both phones)

- **New match:** a newly seen listing where beds ≥2, baths ≥2, price ≤ alert max
  (default $5,000), property type ≠ apartment, and parking/W/D/AC/outdoor are not known
  to fail (unknown passes).
- **Price drop** on a listing with status Interested.
- **Source health:** a source fails 3 runs in a row, or returns 0 listings after
  previously returning some.
- Topic configured by `NTFY_TOPIC`; if unset, alerts are logged only.

## Runtime & deployment

- Django + SQLite, runs 24/7 on the user's Mac mini.
- Served by gunicorn (1 worker, several threads — the scheduler must exist exactly once),
  bound to `0.0.0.0:8000` for LAN access; static files via WhiteNoise.
- launchd `KeepAlive` job starts it at boot and restarts on crash.
- In-process APScheduler: cron trigger, default every 4 hours between 7am and 11pm
  (07, 11, 15, 19, 23), configurable via `SCRAPE_HOURS`. Scheduler only starts when
  `CONDOFINDER_SCHEDULER=1` (set by the launchd job), never in tests/management commands.
- Every run is recorded in a `SourceRun` table (start, end, ok, count, error).
- `manage.py scrape [--source KEY]` runs scrapes manually.

## Configuration (env vars, `.env` supported)

`NTFY_TOPIC`, `SCRAPE_HOURS` (default `7,11,15,19,23`), `ALERT_MAX_PRICE` (default `5000`),
`TARGET_CITIES` (default `Portland,Lake Oswego,Beaverton`), `REQUEST_DELAY_SECONDS`
(default `1.5`), `NOMINATIM_EMAIL` (optional), `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`.

## Out of scope (v1)

Per-person ratings, commute times, logins, LLM-based extraction, cloud hosting.
