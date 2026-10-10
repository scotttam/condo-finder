# Plan decisions: Advanced search page

Decided 2026-10-10 in a grill-me session.

## Problem

Searching today means using the home page's map/cards filter bar or scrolling the Feed. That bar already has
about 20 filters (beds, baths, parking, price, city, quadrant, neighborhood, source, type, status, votes,
W/D, AC, outdoor, furnished, price reduced, specials, off-market, map bounds, 4 sorts), but it has no keyword
search, it's missing many attributes the database holds, it has no dense table layout, and it can't save
named searches. The database holds about 2,600 listings, 1,700 of them active.

## Decisions

### Placement
1. **New `/search/` page** with its own "Search" nav item: a full-width filter panel plus a results table.
   The home map and cards stay as they are.
2. **Shared engine.** New filters go in the shared filter code (`ListingFilterForm` / `apply_filters`), so
   a Search URL opened on the home page applies them too. The home page shows these as an
   "n more filters from Search" chip, and its own controls don't change.
3. **Starting state:** the group's default filters (`default_filter_data(group)`), with "Clear all" to
   search everything.

### Keyword search
4. **SQLite FTS5** over title, description, address and neighborhood. It supports "quoted phrases",
   `-exclude`, `OR` and `prefix*`, ranks by relevance and highlights matched words. A small index table is
   kept in sync on save, with a backfill for existing rows. Comments are not searched.

### New filters
5. **Size and layout ranges:** min/max for beds, baths, sqft and parking, plus $/sqft and effective rent
   (after specials) ranges.
6. **Time on market:** days-on-market range, first seen within N days ("new since"), last seen /
   off-market date, and listed date.
7. **Price movement:** a price drop of at least $X or Y%, the number of price changes, and "price went up".
8. **Location and source detail:** multiple ZIP codes, multiple neighborhoods (pick list), "listed on N+
   sites", a specific source, has photo, has coordinates.
9. **Feature filters are full tri-state:** W/D, AC, outdoor, furnished and parking-known each offer
   Any / Yes / No / Unknown / Yes or unknown.
10. **Availability is skipped.** The free-text `available` field isn't parsed or filtered in this plan.
11. **OR logic:** picks within one multi-select field are ORed (Pearl OR NW; 97209 OR 97210), and keyword
    syntax supports `OR`. Different fields are ANDed. There's no rule builder and no unions of saved searches.

### Results
12. **Results table:** the default columns are photo, address, area, price, beds/baths, sqft, $/sqft,
    parking, features, days on market, status and votes. A "Columns" menu shows or hides other columns.
    Clicking a header sorts by that column. Results page at 100 rows and show the result count, with CSV
    export.
13. **Column choices are saved per person** in a JSON field on `Profile`, so they follow you across
    devices. A saved search can store its own column set.
14. **Live updates via HTMX:** results refresh about 400ms after a change (debounced), and the URL updates
    so Back and shared links work.
15. **Phone width:** below about 700px, each row becomes a two-line compact card in the same sort order,
    and filters collapse into a "Filters (n)" drawer. Nothing scrolls sideways.
16. **Inline actions:** each row has the status pill menu and 👍/👎 buttons, which behave as on the listing
    page (HTMX, Feed items recorded). There's no bulk selection.

### Saved searches
17. **Shared within the group and named:** any member saves the current search under a name, and everyone in
    the group sees it in a "Saved searches" list with its creator. Searches can be renamed, updated or
    deleted. Each is stored as its URL query, so links work too. There are no new-match alerts.

## Rollout: stacked PRs
1. New filter fields and tri-state choices in the shared filter code (tests only).
2. FTS5 index and keyword search (migration, sync on save, backfill).
3. The `/search/` page: filter panel, live results table, header sorting, pagination, phone cards.
4. Column picker (`Profile`), CSV export, inline status and votes.
5. Group saved searches and the home page's "more filters from Search" chip.
