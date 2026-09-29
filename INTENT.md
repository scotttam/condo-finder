# Intent

Why Condo Finder exists, who it's for, and the decisions that shape it. The README covers how to run
it. This file covers what it's for, so future changes stay pointed the same way.

## The problem

Two of us are looking for a place to rent together in Portland, Lake Oswego or Beaverton. The places
we want are condos: units in small, owner-occupied buildings. They're scattered across a dozen
property-manager sites, Zillow, Redfin and Craigslist. Each site shows only part of the market,
most filters can't express what we care about, and the big sites bury condos under apartment
complexes. Price drops, the listings that give us negotiating room, are hard to spot unless you
check every day.

## What it does

One private, always-current list of every rental that could plausibly fit, gathered from all of
those sites:

- **Everything in one place.** Scrapes each source several times a day and merges duplicates, so a
  unit listed on three sites shows up once with links to all three.
- **Filters for what we actually want.** The defaults are 2+ beds, 2+ baths, 2+ parking spaces and a
  price floor. In-unit washer/dryer, AC and outdoor space are must-haves we can filter on. Apartment
  complexes are hidden by default.
- **Honest about unknowns.** Listing text is parsed for parking and amenities. Anything not stated
  shows as "unknown" instead of a guess, and can be corrected by hand.
- **Price history.** Every price change is recorded and past history is imported from Zillow and
  Redfin where available, so drops and time on market are visible at a glance.
- **Shared tracking.** A status (Interested, Toured, Applied, Rejected) and notes on each listing,
  shared between us. The Feed shows what's new and what changed on listings we're tracking.
- **Map-first browsing.** A map beside the list, with quadrant, neighborhood and "search this area"
  filters.

## Who it's for

Just the two of us, on laptops and phones. There are no other users, accounts or permissions to
design for. Admin-style controls on normal pages (editing price history, refreshing a listing) are
fine.

## Principles

- **Coverage over polish at the source.** Store listings broadly (2+ beds, any price) and narrow them
  in the UI, so a filter change never needs a re-scrape.
- **Don't lose or invent data.** A failed or empty scrape never marks listings gone. Listings go
  off-market only after repeated misses, confirmed directly when the site allows it. A price change
  is recorded only when one site changes its own price.
- **Be a polite scraper.** Small request volumes with delays, per-source budgets, and back off at
  the first sign of blocking. Slow and steady beats getting banned.
- **Keep it small.** One Django app, SQLite and one process on a Mac mini at home. No cloud services,
  queues or separate workers unless something actually needs them.
- **Prefer fixing data at the source.** Improve the parser or scraper and re-extract, rather than
  patching individual rows by hand.

## Key decisions

- **Runs at home on a Mac mini, reached over Tailscale.** A residential IP keeps Zillow and Redfin
  scraping workable; cloud IPs get blocked. Tailscale gives both of us private access from anywhere
  without exposing anything publicly.
- **Django + SQLite + HTMX.** Server-rendered pages with small HTMX swaps. No front-end build step.
- **In-process scheduler.** Scrapes run at 7am, 11am, 3pm, 7pm and 11pm from inside the web process.
- **Scraper health lives on the Sources page.** Push notifications were tried and removed.
- **Realtor.com is out of scope.** Its bot protection isn't worth fighting.

## Non-goals

- A public or multi-user product.
- Buying, sales listings or market analytics.
- Contacting landlords or applying from inside the app.
- Perfect coverage of every site. If a source costs more to maintain than it finds, drop it.

## When we're done

The app has done its job when we've signed a lease. Until then, the bar for new work is: does it
help us find, compare or negotiate for the right place faster?
