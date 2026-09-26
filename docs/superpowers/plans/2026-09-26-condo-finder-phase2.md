# Condo Finder Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Redfin, Zillow, and Craigslist as listing sources, delivered as four stacked PRs.

**Architecture:** Each portal gets a scraper class in `listings/scrapers/` registered in `SOURCES`, returning `ScrapedListing`s exactly like the Phase 1 scrapers, so ingest, alerts, UI and health tracking need no changes beyond one ingest addition. Shared groundwork comes first:
- `Fetcher.request` for JSON and PUT calls.
- Per-source request delay and a per-run limit on detail-page fetches.
- `known_ids`, so detail pages are fetched only for listings not yet described.
- A `city` fallback for candidate filtering when the search results have no street address.
- An ingest path that refreshes a known listing when the search results lack an address.

All three sites were verified on 2026-09-26 to answer plain HTTP requests (no headless browser). Realtor.com is **out of scope**: it's protected by Kasada, and the user chose to skip it.

**Tech Stack:** Same as Phase 1 (Django, httpx, BeautifulSoup, pytest).

**Spec:** `docs/superpowers/specs/2026-09-26-condo-finder-design.md` (Sources table, Phase 2 rows)

## Global Constraints

- Target cities: `Portland, Lake Oswego, Beaverton` (setting `TARGET_CITIES`); store only ≥2 beds.
- Polite scraping: Redfin `request_delay` 2s, Zillow 3s, Craigslist 2s; detail-page fetches capped per run (Zillow 40, Craigslist 60) and skipped for listings that already have a description.
- Apartment complexes: Zillow "building" summaries (results with `units`) are skipped (no unit address or single price). Redfin named buildings with more than 1 available unit are hinted `Apartment` (stored, hidden by default in UI).
- Test fixtures must never contain API keys/tokens (a hygiene test enforces this).
- **Stacked PRs:** before opening, confirm repo setting `delete_branch_on_merge=true`. Branches: `p2/01-scraper-infra` → `p2/02-redfin` → `p2/03-zillow` → `p2/04-craigslist`, each based on the previous. User merges bottom-up with "Create a merge commit".
- Run commands from `/Users/scotttam/Claude/Projects/condo-finder`. Fixture sources captured 2026-09-26 live in the session scratchpad: `SP=/private/tmp/claude-501/-Users-scotttam-Claude-Projects-condo-finder/b09fbf2e-ae09-4499-b55a-1a31fd020e8a/scratchpad/p2/fx`.

## File Structure

```
listings/scrapers/base.py        (modify) Fetcher.request/get_json, ScrapedListing.city, Scraper options, should_fetch_detail, is_candidate city fallback
listings/ingest.py               (modify) refresh known source listings that arrive without a parseable address
listings/runner.py               (modify) set scraper.known_ids before scraping
listings/scrapers/redfin.py      (create)
listings/scrapers/zillow.py      (create)
listings/scrapers/craigslist.py  (create)
listings/scrapers/registry.py    (modify) register platforms + sources
tests/helpers.py                 (modify) FakeFetcher.request/get_json + FakeResponse
tests/test_fixture_hygiene.py    (create)
tests/test_scraper_infra.py      (create)
tests/test_redfin.py, test_zillow.py, test_craigslist.py (create)
tests/fixtures/redfin_rentals.json, zillow_search_page.html, zillow_api_page.json, zillow_detail.html,
               craigslist_search.html, craigslist_detail_0.html, craigslist_detail_1.html (create)
README.md                        (modify, Task 4) sources list
```

---

### Task 1: Scraper infrastructure (PR 1, branch `p2/01-scraper-infra`)

**Files:**
- Modify: `listings/scrapers/base.py`, `listings/ingest.py`, `listings/runner.py`, `tests/helpers.py`
- Create: `tests/test_scraper_infra.py`, `tests/test_fixture_hygiene.py`

**Interfaces:**
- Produces:
  - `Fetcher.request(method, url, **kwargs) -> httpx.Response` (polite delay + `raise_for_status`), `Fetcher.get(url, **kwargs) -> str`, `Fetcher.get_json(url, **kwargs) -> Any`.
  - `ScrapedListing.city: str = ""`.
  - `Scraper.__init__(key, name, fetcher=None, request_delay=None, max_detail_fetches=None, **options)` with attributes `known_ids: set[str]`, `max_detail_fetches`, and `should_fetch_detail(item, fetched_so_far) -> bool`.
  - `is_candidate(item)` uses the parsed address city, else `item.city`.
  - `ingest` refreshes an existing `SourceListing` (price, seen, active) when the item's address can't be parsed.
  - The runner sets `known_ids` to the source's external ids whose listing has a non-empty description.
  - Test helpers `FakeFetcher.request/get/get_json` and `FakeResponse(text).json()`.

- [ ] **Step 1: Create the branch and confirm the repo setting**

```bash
git checkout main && git pull --ff-only
git checkout -b p2/01-scraper-infra
gh api repos/scotttam/condo-finder --jq .delete_branch_on_merge   # expect: true
```

- [ ] **Step 2: Extend `tests/helpers.py`**

Replace the `FakeFetcher` class (keep `load_fixture`, `make_listing`, `scraped`, `make_source`) with:

```python
class FakeResponse:
    def __init__(self, text):
        self.text = text

    def json(self):
        import json

        return json.loads(self.text)


class FakeFetcher:
    """Stands in for scrapers.base.Fetcher; serves canned bodies by URL."""

    def __init__(self, pages, default=None):
        self.pages = pages
        self.default = default
        self.requested = []
        self.calls = []

    def request(self, method, url, **kwargs):
        self.requested.append(url)
        self.calls.append((method, url, kwargs))
        if url in self.pages:
            return FakeResponse(self.pages[url])
        if self.default is not None:
            return FakeResponse(self.default)
        raise httpx.HTTPError(f"no fake page for {url}")

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs).text

    def get_json(self, url, **kwargs):
        return self.request("GET", url, **kwargs).json()
```

- [ ] **Step 3: Write the failing tests**

`tests/test_scraper_infra.py`:
```python
import httpx
import pytest

from listings import runner
from listings.ingest import ingest
from listings.models import Listing, PriceChange
from listings.scrapers.base import Fetcher, ScrapedListing, Scraper, is_candidate
from tests.helpers import make_source, scraped


def test_fetcher_request_supports_methods_and_json():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.params.get("q"), request.content))
        return httpx.Response(200, json={"ok": True})

    fetcher = Fetcher(delay=0, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert fetcher.get_json("https://x.example/api", params={"q": "1"}) == {"ok": True}
    fetcher.request("PUT", "https://x.example/api", json={"a": 1})
    assert seen[0][:2] == ("GET", "1")
    assert seen[1][0] == "PUT" and seen[1][2] == b'{"a":1}'


def test_fetcher_raises_on_http_error():
    fetcher = Fetcher(delay=0, client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403))))
    with pytest.raises(httpx.HTTPStatusError):
        fetcher.get("https://x.example/")


def test_is_candidate_falls_back_to_city_when_no_address():
    assert is_candidate(ScrapedListing(external_id="1", url="u", address="", city="Portland", beds=2))
    assert not is_candidate(ScrapedListing(external_id="2", url="u", address="", city="Vancouver", beds=2))
    assert not is_candidate(ScrapedListing(external_id="3", url="u", address="", city="", beds=2))


def test_should_fetch_detail_respects_known_ids_and_budget():
    scraper = Scraper(key="k", name="K", fetcher=object(), max_detail_fetches=2)
    scraper.known_ids = {"old"}
    new = ScrapedListing(external_id="new", url="u", address="")
    assert scraper.should_fetch_detail(new, 0)
    assert not scraper.should_fetch_detail(new, 2)
    assert not scraper.should_fetch_detail(ScrapedListing(external_id="old", url="u", address=""), 0)


def test_scraper_passes_request_delay_to_default_fetcher():
    scraper = Scraper(key="k", name="K", request_delay=3)
    assert scraper.fetcher.delay == 3


@pytest.mark.django_db
def test_ingest_refreshes_known_listing_without_address():
    source = make_source("craigslist")
    ingest(source, [scraped(external_id="cl1", price=2500)])
    result = ingest(source, [ScrapedListing(external_id="cl1", url="https://example.com/cl1", address="", price=2400, beds=2)])
    listing = Listing.objects.get()
    assert result.seen == 1 and result.skipped == 0
    assert listing.price == 2400
    assert result.price_drops == [(listing, 2500, 2400)]
    assert [p.price for p in PriceChange.objects.order_by("seen_at")] == [2500, 2400]


@pytest.mark.django_db
def test_ingest_skips_unknown_listing_without_address():
    result = ingest(make_source("craigslist"), [ScrapedListing(external_id="new", url="u", address="", beds=2)])
    assert result.skipped == 1 and Listing.objects.count() == 0


@pytest.mark.django_db
def test_refreshed_listing_is_not_marked_missing():
    source = make_source("craigslist")
    other = scraped(external_id="b2", address="100 SW Main St, Portland, OR 97204")
    ingest(source, [scraped(external_id="cl1"), other])
    bare = ScrapedListing(external_id="cl1", url="u", address="", beds=2)
    for _ in range(3):
        ingest(source, [bare, other])
    assert Listing.objects.get(street="937 NW Glisan Street").is_active is True


@pytest.mark.django_db
def test_runner_sets_known_ids_to_described_listings(monkeypatch):
    source = make_source("pearl")
    ingest(source, [scraped(external_id="described"),
                    scraped(external_id="bare", description="", title="", address="100 SW Main St, Portland, OR 97204")])
    captured = {}

    class Spy(Scraper):
        def scrape(self):
            captured["known"] = set(self.known_ids)
            return []

    monkeypatch.setattr(runner, "build_scraper", lambda config, fetcher=None: Spy(key="pearl", name="Pearl", fetcher=object()))
    runner.run_source({"key": "pearl", "name": "Pearl", "platform": "appfolio"})
    assert captured["known"] == {"described"}
```

`tests/test_fixture_hygiene.py`:
```python
import re

import pytest

from tests.helpers import FIXTURES

SECRET_PATTERNS = {
    "Google API key": r"AIza[0-9A-Za-z_-]{30,}",
    "Mapbox token": r"\b(?:pk|sk)\.eyJ[A-Za-z0-9._-]{20,}",
    "key= URL parameter": r"[?&](?:amp;)?key=[A-Za-z0-9_-]{20,}",
}


@pytest.mark.parametrize("path", sorted(FIXTURES.iterdir()), ids=lambda p: p.name)
def test_fixture_contains_no_api_keys(path):
    text = path.read_text(encoding="utf-8", errors="ignore")
    for label, pattern in SECRET_PATTERNS.items():
        assert not re.search(pattern, text), f"{path.name} contains a {label}; redact it before committing"
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest tests/test_scraper_infra.py tests/test_fixture_hygiene.py -q`
Expected: hygiene tests pass (existing fixtures are clean); infra tests FAIL (e.g. `AttributeError: 'Fetcher' object has no attribute 'get_json'`).

- [ ] **Step 5: Update `listings/scrapers/base.py`**

Replace the `ScrapedListing`, `Fetcher`, `Scraper` definitions and `is_candidate` with:

```python
@dataclass
class ScrapedListing:
    external_id: str
    url: str
    address: str
    price: int | None = None
    beds: int | None = None
    baths: Decimal | None = None
    sqft: int | None = None
    title: str = ""
    description: str = ""
    amenities: str = ""
    property_type_hint: str = ""
    available: str = ""
    photo_url: str = ""
    city: str = ""  # used when search results give a city but no street address (Craigslist)

    @property
    def full_text(self):
        return "\n".join(part for part in (self.title, self.description, self.amenities) if part)


class Fetcher:
    """Polite HTTP: waits `delay` seconds between requests and raises on HTTP errors."""

    def __init__(self, delay=None, client=None):
        self.delay = settings.REQUEST_DELAY_SECONDS if delay is None else delay
        self.client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
            follow_redirects=True,
            timeout=30,
        )
        self._last_request = 0.0

    def request(self, method, url, **kwargs):
        wait = self.delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        try:
            response = self.client.request(method, url, **kwargs)
        finally:
            self._last_request = time.monotonic()
        response.raise_for_status()
        return response

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs).text

    def get_json(self, url, **kwargs):
        return self.request("GET", url, **kwargs).json()


class Scraper:
    platform = ""

    def __init__(self, key, name, fetcher=None, request_delay=None, max_detail_fetches=None, **options):
        self.key = key
        self.name = name
        self.fetcher = fetcher or Fetcher(delay=request_delay)
        self.max_detail_fetches = max_detail_fetches
        self.known_ids = set()  # external ids whose listing already has a description (set by the runner)
        self.options = options

    def scrape(self):
        raise NotImplementedError

    def should_fetch_detail(self, item, fetched_so_far):
        if item.external_id in self.known_ids:
            return False
        return self.max_detail_fetches is None or fetched_so_far < self.max_detail_fetches


def is_candidate(item):
    """Worth a detail-page fetch and storing: target city and 2+ beds (or beds unknown)."""
    parsed = parse_address(item.address)
    city = parsed.city if parsed else item.city
    return bool(city) and is_target_city(city) and (item.beds is None or item.beds >= 2)
```

- [ ] **Step 6: Update `listings/ingest.py`**

In `ingest`, replace the address guard:
```python
        address = parse_address(item.address)
        if address is None or not is_target_city(address.city) or item.beds is None or item.beds < 2:
            result.skipped += 1
            continue
```
with:
```python
        address = parse_address(item.address)
        if address is None and _refresh_known(source, item, now, result, seen_ids):
            continue
        if address is None or not is_target_city(address.city) or item.beds is None or item.beds < 2:
            result.skipped += 1
            continue
```
and add this function after `_upsert_source_listing`:
```python
def _refresh_known(source, item, now, result, seen_ids):
    """A listing we already stored, seen again without its address (detail page skipped)."""
    source_listing = (
        SourceListing.objects.select_related("listing").filter(source=source, external_id=item.external_id).first()
    )
    if source_listing is None:
        return False
    listing = source_listing.listing
    old_price = listing.price
    with transaction.atomic():
        if item.price is not None and "price" not in (listing.overrides or {}):
            listing.price = item.price
        listing.is_active = True
        listing.last_seen_at = now
        listing.save()
        if listing.price is not None and listing.price != old_price:
            PriceChange.objects.create(listing=listing, price=listing.price, seen_at=now)
        _upsert_source_listing(source, listing, item, now)
    seen_ids.add(source_listing.pk)
    result.seen += 1
    if old_price is not None and listing.price is not None and listing.price < old_price:
        result.price_drops.append((listing, old_price, listing.price))
    return True
```

- [ ] **Step 7: Update `listings/runner.py`**

Add `SourceListing` to the models import (`from .models import Source, SourceListing, SourceRun`) and in `run_source` replace
```python
        items = build_scraper(config, fetcher=fetcher).scrape()
```
with
```python
        scraper = build_scraper(config, fetcher=fetcher)
        scraper.known_ids = set(
            SourceListing.objects.filter(source=source)
            .exclude(listing__description="")
            .values_list("external_id", flat=True)
        )
        items = scraper.scrape()
```

- [ ] **Step 8: Run all tests**

Run: `uv run pytest -q`
Expected: all pass (149 existing + new).

- [ ] **Step 9: Commit, push, open PR 1**

```bash
git add -A
git commit -m "feat: scraper infrastructure for portal sources"
git push -u origin p2/01-scraper-infra
gh pr create --base main --head p2/01-scraper-infra --title "[P2 1/4] Scraper infrastructure for portal sources" --body "<summary + stack list + test plan>"
```

---

### Task 2: Redfin scraper (PR 2, branch `p2/02-redfin`)

**Files:**
- Create: `listings/scrapers/redfin.py`, `tests/test_redfin.py`, `tests/fixtures/redfin_rentals.json`
- Modify: `listings/scrapers/registry.py`

**Interfaces:**
- Consumes: `ScrapedListing`, `Scraper`, `Fetcher.get_json` (Task 1).
- Produces: `redfin.parse_rentals(data: dict) -> list[ScrapedListing]`, `RedfinScraper` (option `region_ids: list[int]`), `API_URL`, `PROPERTY_TYPES`.

- [ ] **Step 1: Branch and fixture**

```bash
git checkout -b p2/02-redfin p2/01-scraper-infra
cp $SP/redfin_rentals.json tests/fixtures/redfin_rentals.json
```
(12 real rentals, 3 each of propertyType 3/5/6/13; `staticMapUrl` removed because it embeds a Google API key.)

- [ ] **Step 2: Write the failing tests**

`tests/test_redfin.py`:
```python
import json
from decimal import Decimal

from listings.scrapers.redfin import API_URL, RedfinScraper, parse_rentals
from tests.helpers import FakeFetcher, load_fixture


def items_by_address():
    return {i.address: i for i in parse_rentals(json.loads(load_fixture("redfin_rentals.json")))}


def test_parses_every_rental():
    assert len(items_by_address()) == 12


def test_condo_unit():
    item = items_by_address()["12859 SE Stark St Unit A28, Portland, OR 97233"]
    assert item.property_type_hint == "Condo"
    assert (item.price, item.beds, item.baths, item.sqft) == (1695, 2, Decimal("2.0"), 1003)
    assert item.url == "https://www.redfin.com/OR/Portland/12859-SE-Stark-St-97233/unit-A28/home/26504934"
    assert item.external_id.startswith("6f69f705")
    assert item.photo_url.startswith("https://ssl.cdn-redfin.com/photo/rent/6f69f705")
    assert item.photo_url.endswith(".jpg")


def test_type_hints():
    items = items_by_address()
    assert items["1037 NE 104th Ave, Portland, OR 97220"].property_type_hint == "Single Family Home"
    assert items["19465 NW Mahama Pl Apt A, Portland, OR 97229"].property_type_hint == "Townhouse"
    assert items["6142 Bonita Rd, Lake Oswego, OR 97035"].property_type_hint == "Apartment"


def test_named_multi_unit_building_is_apartment_even_if_typed_townhouse():
    tower = items_by_address()["3820 S River Pkwy, Portland, OR 97239"]
    assert tower.property_type_hint == "Apartment"
    assert tower.title == "Willamette Tower"
    assert tower.price == 3471


def test_scraper_queries_each_region_with_filters():
    fetcher = FakeFetcher({API_URL: load_fixture("redfin_rentals.json")})
    items = RedfinScraper(key="redfin", name="Redfin", fetcher=fetcher, region_ids=[30772, 1432]).scrape()
    assert len(items) == 12  # same rentals returned for both regions are de-duplicated
    params = [kwargs["params"] for _, _, kwargs in fetcher.calls]
    assert [p["region_id"] for p in params] == [30772, 1432]
    assert all(p["num_beds"] == 2 and p["num_baths"] == 2 and p["isRentals"] == "true" for p in params)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_redfin.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'listings.scrapers.redfin'`

- [ ] **Step 4: Write `listings/scrapers/redfin.py`**

```python
"""Redfin rentals via the JSON API its own search page uses."""

from decimal import Decimal

from .base import ScrapedListing, Scraper

API_URL = "https://www.redfin.com/stingray/api/v1/search/rentals"
PHOTO_URL = "https://ssl.cdn-redfin.com/photo/rent/{rental_id}/islphoto/genIsl.{position}_{version}.jpg"
# Redfin propertyType codes, verified against live results 2026-09-26.
PROPERTY_TYPES = {3: "Condo", 4: "Multi-family", 5: "Apartment", 6: "Single Family Home", 13: "Townhouse"}


def _photo_url(rental_id, photos_info):
    ranges = (photos_info or {}).get("photoRanges") or []
    if not ranges:
        return ""
    return PHOTO_URL.format(rental_id=rental_id, position=ranges[0]["startPos"], version=ranges[0]["version"])


def parse_rentals(data):
    items = []
    for home in data.get("homes", []):
        info = home.get("homeData") or {}
        rental = home.get("rentalExtension") or {}
        address = info.get("addressInfo") or {}
        street = address.get("formattedStreetLine")
        if not street or not rental.get("rentalId"):
            continue
        baths = (rental.get("bathRange") or {}).get("min")
        is_complex = bool(rental.get("propertyName")) and (rental.get("numAvailableUnits") or 0) > 1
        items.append(
            ScrapedListing(
                external_id=rental["rentalId"],
                url=f"https://www.redfin.com{info.get('url', '')}",
                address=f"{street}, {address.get('city', '')}, {address.get('state', '')} {address.get('zip', '')}",
                price=(rental.get("rentPriceRange") or {}).get("min"),
                beds=(rental.get("bedRange") or {}).get("min"),
                baths=Decimal(str(baths)) if baths is not None else None,
                sqft=(rental.get("sqftRange") or {}).get("min"),
                title=rental.get("propertyName") or "",
                description=rental.get("description") or "",
                property_type_hint="Apartment" if is_complex else PROPERTY_TYPES.get(info.get("propertyType"), ""),
                photo_url=_photo_url(rental["rentalId"], info.get("photosInfo")),
            )
        )
    return items


class RedfinScraper(Scraper):
    platform = "redfin"

    def scrape(self):
        by_id = {}
        for region_id in self.options["region_ids"]:
            data = self.fetcher.get_json(
                API_URL,
                params={
                    "al": 1, "isRentals": "true", "market": "portland", "num_homes": 350,
                    "ord": "days-on-redfin-asc", "page_number": 1, "region_id": region_id,
                    "region_type": 6, "num_beds": 2, "num_baths": 2, "status": 9, "v": 8,
                },
            )
            for item in parse_rentals(data):
                by_id[item.external_id] = item
        return list(by_id.values())
```

- [ ] **Step 5: Register the source**

In `listings/scrapers/registry.py` add `from .redfin import RedfinScraper`, add `"redfin": RedfinScraper` to `PLATFORMS`, and append to `SOURCES`:
```python
    # Redfin city region ids: Portland 30772, Lake Oswego 30777, Beaverton 1432.
    {"key": "redfin", "name": "Redfin", "platform": "redfin", "region_ids": [30772, 30777, 1432], "request_delay": 2},
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest -q`
Expected: all pass (the registry test builds the new source too).

- [ ] **Step 7: Live smoke**

Run: `uv run python manage.py scrape --source redfin --no-geocode`
Expected: `redfin: ok — N listings, M new` with N > 0. If Redfin rejects the request, capture the response, fix, and add a regression test.

- [ ] **Step 8: Commit, push, open PR 2 (base `p2/01-scraper-infra`)**

```bash
git add -A
git commit -m "feat: Redfin rentals scraper"
git push -u origin p2/02-redfin
gh pr create --base p2/01-scraper-infra --head p2/02-redfin --title "[P2 2/4] Redfin rentals scraper" --body "<summary + stack list + test plan>"
```

---

### Task 3: Zillow scraper (PR 3, branch `p2/03-zillow`)

**Files:**
- Create: `listings/scrapers/zillow.py`, `tests/test_zillow.py`, `tests/fixtures/zillow_search_page.html`, `tests/fixtures/zillow_api_page.json`, `tests/fixtures/zillow_detail.html`
- Modify: `listings/scrapers/registry.py`

**Interfaces:**
- Consumes: Task 1 infra.
- Produces: `zillow.parse_query_state(html) -> dict`, `zillow.parse_results(data) -> tuple[list[ScrapedListing], int]`, `zillow.parse_detail(html) -> dict(description, amenities, home_type)`, `ZillowScraper` (option `city_slugs: list[str]`), constants `SEARCH_PAGE`, `SEARCH_API`.

- [ ] **Step 1: Branch and fixtures**

```bash
git checkout -b p2/03-zillow p2/02-redfin
cp $SP/zillow_search_page.html $SP/zillow_api_page.json $SP/zillow_detail.html tests/fixtures/
```
(Search page trimmed to its `queryState`; API page = 3 building summaries + 3 APARTMENT + 3 TOWNHOUSE + 1 CONDO real results; detail trimmed to the fields parsed.)

- [ ] **Step 2: Write the failing tests**

`tests/test_zillow.py`:
```python
import json
from decimal import Decimal

from listings.scrapers.zillow import (
    SEARCH_API,
    SEARCH_PAGE,
    ZillowScraper,
    parse_detail,
    parse_query_state,
    parse_results,
)
from tests.helpers import FakeFetcher, load_fixture

PORTLAND = SEARCH_PAGE.format(slug="portland-or")


def results():
    items, pages = parse_results(json.loads(load_fixture("zillow_api_page.json")))
    return {i.external_id: i for i in items}, pages


def test_query_state_has_region_and_bounds():
    state = parse_query_state(load_fixture("zillow_search_page.html"))
    assert state["regionSelection"] == [{"regionId": 13373, "regionType": 6}]
    assert set(state["mapBounds"]) >= {"north", "south", "east", "west"}


def test_building_summaries_are_skipped():
    items, pages = results()
    assert pages == 1
    assert set(items) == {"465501490", "2083535903", "464432454", "54003809", "2083259756", "2077222357", "53856550"}


def test_townhouse_result():
    item = results()[0]["54003809"]
    assert item.address == "5720 SE Duke St, Portland, OR 97206"
    assert (item.price, item.beds, item.baths, item.sqft) == (2850, 2, Decimal("3.0"), 1095)
    assert item.property_type_hint == "Townhouse"
    assert item.url == "https://www.zillow.com/homedetails/5720-SE-Duke-St-Portland-OR-97206/54003809_zpid/"
    assert item.title == ""


def test_building_unit_uses_street_fields_and_building_name():
    item = results()[0]["465501490"]
    assert item.address == "900 NW Lovejoy St #1-207, Portland, OR 97209"
    assert item.title == "Burlington Tower"
    assert item.property_type_hint == "Apartment"


def test_condo_hint():
    assert results()[0]["53856550"].property_type_hint == "Condo"


def test_parse_detail():
    detail = parse_detail(load_fixture("zillow_detail.html"))
    assert detail["description"].startswith("Make room for a little more comfort at 5720 SE Duke Street")
    assert "Date available: Available Now" in detail["amenities"]
    assert "Appliances: Dishwasher, Microwave Oven, Refrigerator" in detail["amenities"]
    assert detail["home_type"] == "Townhouse"


def fetcher():
    return FakeFetcher(
        {PORTLAND: load_fixture("zillow_search_page.html"), SEARCH_API: load_fixture("zillow_api_page.json")},
        default=load_fixture("zillow_detail.html"),
    )


def test_scraper_searches_then_fetches_limited_details():
    fake = fetcher()
    scraper = ZillowScraper(key="zillow", name="Zillow", fetcher=fake, city_slugs=["portland-or"], max_detail_fetches=2)
    scraper.known_ids = {"465501490"}
    items = scraper.scrape()
    assert len(items) == 7
    methods = [(method, url) for method, url, _ in fake.calls]
    assert methods[0] == ("GET", PORTLAND)
    assert methods[1][0] == "PUT" and methods[1][1] == SEARCH_API
    assert len(methods) == 2 + 2  # two detail pages, budget-limited
    body = fake.calls[1][2]["json"]["searchQueryState"]
    assert body["filterState"]["beds"] == {"min": 2} and body["filterState"]["fr"] == {"value": True}
    assert body["regionSelection"] == [{"regionId": 13373, "regionType": 6}]
    described = [i for i in items if i.description]
    assert len(described) == 2 and "465501490" not in {i.external_id for i in described}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_zillow.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'listings.scrapers.zillow'`

- [ ] **Step 4: Write `listings/scrapers/zillow.py`**

```python
"""Zillow rentals: search via the JSON API its own search page calls, details from page JSON."""

import json
import logging
import re
from decimal import Decimal

import httpx

from .base import ScrapedListing, Scraper, is_candidate

log = logging.getLogger(__name__)

SEARCH_PAGE = "https://www.zillow.com/{slug}/rentals/"
SEARCH_API = "https://www.zillow.com/async-create-search-page-state"
MAX_PAGES = 20
# Rentals only, 2+ beds, 2+ baths. Zillow ignores home-type filters here, so building
# summaries are dropped in parse_results and types are classified from each listing.
FILTERS = {
    "fr": {"value": True}, "fsba": {"value": False}, "fsbo": {"value": False}, "nc": {"value": False},
    "cmsn": {"value": False}, "auc": {"value": False}, "fore": {"value": False},
    "beds": {"min": 2}, "baths": {"min": 2},
}


def _next_data(html):
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if match is None:
        raise ValueError("Zillow page has no __NEXT_DATA__ (blocked or page changed)")
    return json.loads(match.group(1))


def _type_label(home_type):
    return (home_type or "").replace("_", " ").title()


def parse_query_state(html):
    return _next_data(html)["props"]["pageProps"]["searchPageState"]["queryState"]


def parse_results(data):
    category = data["cat1"]
    items = []
    for result in category["searchResults"]["listResults"]:
        if result.get("units"):  # apartment-complex summary: no unit address or single price
            continue
        street = result.get("addressStreet")
        if not street:
            continue
        home_type = ((result.get("hdpData") or {}).get("homeInfo") or {}).get("homeType")
        building = (result.get("address") or "").split(",")[0].strip()
        url = result.get("detailUrl") or ""
        baths = result.get("baths")
        items.append(
            ScrapedListing(
                external_id=str(result["zpid"]),
                url=url if url.startswith("http") else f"https://www.zillow.com{url}",
                address=f"{street}, {result.get('addressCity', '')}, {result.get('addressState', '')} {result.get('addressZipcode', '')}",
                price=result.get("unformattedPrice"),
                beds=result.get("beds"),
                baths=Decimal(str(baths)) if baths is not None else None,
                sqft=result.get("area"),
                title=building if building != street else "",
                property_type_hint=_type_label(home_type),
                photo_url=result.get("imgSrc") or "",
            )
        )
    return items, category["searchList"].get("totalPages") or 1


def parse_detail(html):
    cache = _next_data(html)["props"]["pageProps"]["componentProps"]["gdpClientCache"]
    if isinstance(cache, str):
        cache = json.loads(cache)
    prop = next(value["property"] for value in cache.values() if isinstance(value, dict) and value.get("property"))
    facts = prop.get("resoFacts") or {}
    lines = [
        f"{fact['factLabel']}: {fact['factValue']}"
        for fact in facts.get("atAGlanceFacts") or []
        if fact.get("factLabel") and fact.get("factValue")
    ]
    for label, key in (("Parking", "parkingFeatures"), ("Laundry", "laundryFeatures"), ("Cooling", "cooling"),
                       ("Appliances", "appliances"), ("Outdoor", "patioAndPorchFeatures")):
        value = facts.get(key)
        if value:
            lines.append(f"{label}: {', '.join(value) if isinstance(value, list) else value}")
    return {
        "description": prop.get("description") or "",
        "amenities": "\n".join(lines),
        "home_type": _type_label(prop.get("homeType")),
    }


class ZillowScraper(Scraper):
    platform = "zillow"

    def scrape(self):
        by_id = {}
        for slug in self.options["city_slugs"]:
            for item in self._search(slug):
                by_id[item.external_id] = item
        items = list(by_id.values())
        fetched = 0
        for item in items:
            if not is_candidate(item) or not self.should_fetch_detail(item, fetched):
                continue
            fetched += 1
            try:
                detail = parse_detail(self.fetcher.get(item.url))
            except (httpx.HTTPError, ValueError, KeyError, StopIteration) as exc:
                log.warning("Zillow detail fetch failed for %s: %s", item.url, exc)
                continue
            item.description = detail["description"]
            item.amenities = detail["amenities"]
            item.property_type_hint = detail["home_type"] or item.property_type_hint
        return items

    def _search(self, slug):
        page_url = SEARCH_PAGE.format(slug=slug)
        query = parse_query_state(self.fetcher.get(page_url))
        items = []
        for page in range(1, MAX_PAGES + 1):
            body = {
                "searchQueryState": {
                    "pagination": {"currentPage": page},
                    "isMapVisible": True,
                    "isListVisible": True,
                    "mapBounds": query["mapBounds"],
                    "regionSelection": query["regionSelection"],
                    "filterState": FILTERS,
                },
                "wants": {"cat1": ["listResults"]},
                "requestId": page,
                "isDebugRequest": False,
            }
            response = self.fetcher.request(
                "PUT", SEARCH_API, json=body, headers={"Origin": "https://www.zillow.com", "Referer": page_url}
            )
            results, total_pages = parse_results(response.json())
            items.extend(results)
            if page >= total_pages:
                break
        return items
```

- [ ] **Step 5: Register the source**

In `registry.py` add `from .zillow import ZillowScraper`, `"zillow": ZillowScraper` in `PLATFORMS`, and append:
```python
    {"key": "zillow", "name": "Zillow", "platform": "zillow", "city_slugs": ["portland-or", "lake-oswego-or", "beaverton-or"],
     "request_delay": 3, "max_detail_fetches": 40},
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 7: Live smoke**

Run: `uv run python manage.py scrape --source zillow --no-geocode`
Expected: `zillow: ok — N listings, M new`, N in the hundreds, completing in a few minutes (≈40 detail pages at 3s). On a 403/captcha, record it and stop to discuss. Don't retry in a tight loop.

- [ ] **Step 8: Commit, push, open PR 3 (base `p2/02-redfin`)**

```bash
git add -A
git commit -m "feat: Zillow rentals scraper"
git push -u origin p2/03-zillow
gh pr create --base p2/02-redfin --head p2/03-zillow --title "[P2 3/4] Zillow rentals scraper" --body "<summary + stack list + test plan>"
```

---

### Task 4: Craigslist scraper + README (PR 4, branch `p2/04-craigslist`)

**Files:**
- Create: `listings/scrapers/craigslist.py`, `tests/test_craigslist.py`, `tests/fixtures/craigslist_search.html`, `tests/fixtures/craigslist_detail_0.html`, `tests/fixtures/craigslist_detail_1.html`
- Modify: `listings/scrapers/registry.py`, `README.md`

**Interfaces:**
- Consumes: Task 1 infra (`ScrapedListing.city`, `should_fetch_detail`, ingest refresh of known ids).
- Produces: `craigslist.parse_search(html) -> list[ScrapedListing]`, `craigslist.parse_detail(html) -> dict(title, price, address, beds, baths, sqft, housing_type, amenities, description, photo_url)`, `CraigslistScraper` (option `search_url`).

- [ ] **Step 1: Branch and fixtures**

```bash
git checkout -b p2/04-craigslist p2/03-zillow
cp $SP/craigslist_search.html $SP/craigslist_detail_0.html $SP/craigslist_detail_1.html tests/fixtures/
```

- [ ] **Step 2: Write the failing tests**

`tests/test_craigslist.py`:
```python
from decimal import Decimal

from listings.scrapers.base import is_candidate
from listings.scrapers.craigslist import CraigslistScraper, parse_detail, parse_search
from tests.helpers import FakeFetcher, load_fixture

SEARCH_URL = "https://www.craigslist.org/search/area/portland?cat=apa&min_bedrooms=2&min_bathrooms=2"
FIRST = "bU7Ug1JzHJCR7gB5ESiHyM"


def test_parse_search_pairs_cards_with_structured_data():
    items = parse_search(load_fixture("craigslist_search.html"))
    assert len(items) == 12
    first = items[0]
    assert first.external_id == FIRST
    assert first.url == f"https://www.craigslist.org/view/d/portland-walk-in-closets-pet-friendly/{FIRST}"
    assert (first.price, first.beds, first.baths, first.city) == (2339, 2, Decimal("2"), "Portland")
    assert first.address == ""
    assert first.title == "Walk-in Closets, Pet-friendly, Wood Style Plank Flooring"


def test_zero_price_means_unknown():
    items = {i.external_id: i for i in parse_search(load_fixture("craigslist_search.html"))}
    assert items["wwzucJoGEbv4zNomuBVi2c"].price is None


def test_candidates_are_target_cities_only():
    items = parse_search(load_fixture("craigslist_search.html"))
    assert sum(is_candidate(i) for i in items) == 6
    assert {i.city for i in items if is_candidate(i)} == {"Portland"}


def test_parse_detail_apartment():
    detail = parse_detail(load_fixture("craigslist_detail_0.html"))
    assert detail["title"] == "Walk-in Closets, Pet-friendly, Wood Style Plank Flooring"
    assert detail["price"] == 2339
    assert detail["address"] == "1314 N Skidmore St, Portland, OR 97217"
    assert (detail["beds"], detail["baths"], detail["sqft"]) == (2, Decimal("2"), 961)
    assert detail["housing_type"] == "apartment"
    assert "Laundry: w/d in unit" in detail["amenities"]
    assert "Parking: carport" in detail["amenities"]
    assert "2 Bedroom, 2 Bath" in detail["description"]
    assert "QR Code" not in detail["description"]
    assert detail["photo_url"] == "https://images.craigslist.org/00H0H_9O33tAoZ4YI_0bT07V_600x450.jpg"


def test_parse_detail_house():
    detail = parse_detail(load_fixture("craigslist_detail_1.html"))
    assert detail["housing_type"] == "house"
    assert (detail["beds"], detail["sqft"]) == (3, 800)
    assert "Parking: off-street parking" in detail["amenities"]
    assert "Laundry: laundry in bldg" in detail["amenities"]


def test_scraper_fetches_details_for_new_candidates_only():
    fake = FakeFetcher({SEARCH_URL: load_fixture("craigslist_search.html")}, default=load_fixture("craigslist_detail_0.html"))
    scraper = CraigslistScraper(key="craigslist", name="Craigslist", fetcher=fake, search_url=SEARCH_URL)
    scraper.known_ids = {FIRST}
    items = {i.external_id: i for i in scraper.scrape()}
    assert len(items) == 12
    assert len(fake.requested) == 1 + 5
    assert items[FIRST].address == ""  # known: refreshed by id during ingest, no detail fetch
    fetched = [i for i in items.values() if i.address]
    assert len(fetched) == 5
    assert all(i.property_type_hint == "apartment" and "w/d in unit" in i.amenities for i in fetched)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_craigslist.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'listings.scrapers.craigslist'`

- [ ] **Step 4: Write `listings/scrapers/craigslist.py`**

```python
"""Craigslist apartments/housing for rent: search page structured data + posting pages."""

import json
import logging
import re
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import httpx
from bs4 import BeautifulSoup

from ..parsing import parse_beds_baths, parse_int, parse_price
from .base import ScrapedListing, Scraper, is_candidate

log = logging.getLogger(__name__)

ATTRIBUTE_PARAMS = ("housing_type", "laundry", "parking")


def _text(element):
    return " ".join(element.get_text(" ", strip=True).split()) if element else ""


def parse_search(html):
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="ld_searchpage_results")
    structured = json.loads(script.string)["itemListElement"] if script and script.string else []
    items = []
    for position, card in enumerate(soup.select("li.cl-static-search-result")):
        link = card.find("a", href=True)
        if link is None:
            continue
        info = {}
        if position < len(structured):
            candidate = structured[position].get("item") or {}
            if candidate.get("name") == card.get("title"):  # guard against misaligned lists
                info = candidate
        baths = info.get("numberOfBathroomsTotal")
        items.append(
            ScrapedListing(
                external_id=link["href"].rstrip("/").rsplit("/", 1)[-1],
                url=link["href"],
                address="",
                price=parse_price(_text(card.select_one(".price"))) or None,  # "$0" means not stated
                beds=info.get("numberOfBedrooms"),
                baths=Decimal(str(baths)) if baths is not None else None,
                title=card.get("title", ""),
                city=((info.get("address") or {}).get("addressLocality") or ""),
            )
        )
    return items


def parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    attributes = {}
    for link in soup.select(".mapAndAttrs a[href]"):
        query = parse_qs(urlsplit(link["href"]).query)
        for name in ATTRIBUTE_PARAMS:
            if name in query:
                attributes[name] = _text(link)
    headline = " ".join(_text(span) for span in soup.select(".mapAndAttrs .attr.important"))
    beds, baths = parse_beds_baths(headline)
    sqft = re.search(r"(\d[\d,]*)\s*ft", headline)
    body = soup.select_one("#postingbody")
    if body is not None:
        for junk in body.select(".print-information, .print-qrcode-container"):
            junk.decompose()
    description = body.get_text("\n", strip=True).replace("QR Code Link to This Post", "").strip() if body else ""
    image = soup.select_one('img[src^="https://images.craigslist.org"]')
    return {
        "title": _text(soup.select_one("#titletextonly")),
        "price": parse_price(_text(soup.select_one("span.price"))) or None,
        "address": _text(soup.select_one("h2.street-address")),
        "beds": beds,
        "baths": baths,
        "sqft": parse_int(sqft.group(1)) if sqft else None,
        "housing_type": attributes.get("housing_type", ""),
        "amenities": "\n".join(
            f"{name.title()}: {value}" for name, value in attributes.items() if name != "housing_type"
        ),
        "description": description,
        "photo_url": image["src"] if image else "",
    }


class CraigslistScraper(Scraper):
    platform = "craigslist"

    def scrape(self):
        items = parse_search(self.fetcher.get(self.options["search_url"]))
        fetched = 0
        for item in items:
            if not is_candidate(item) or not self.should_fetch_detail(item, fetched):
                continue
            fetched += 1
            try:
                detail = parse_detail(self.fetcher.get(item.url))
            except httpx.HTTPError as exc:
                log.warning("Craigslist posting fetch failed for %s: %s", item.url, exc)
                continue
            item.address = detail["address"]
            item.title = detail["title"] or item.title
            item.price = detail["price"] or item.price
            item.beds = detail["beds"] if detail["beds"] is not None else item.beds
            item.baths = detail["baths"] if detail["baths"] is not None else item.baths
            item.sqft = detail["sqft"]
            item.description = detail["description"]
            item.amenities = detail["amenities"]
            item.property_type_hint = detail["housing_type"]
            item.photo_url = detail["photo_url"]
        return items
```

Note: `parse_beds_baths("2BR / 2Ba 961ft2")` lower-cases to `2br / 2ba`, which matches the `br` and `ba` patterns in `parsing.py`.

- [ ] **Step 5: Register the source**

In `registry.py` add `from .craigslist import CraigslistScraper`, `"craigslist": CraigslistScraper` in `PLATFORMS`, and append:
```python
    {"key": "craigslist", "name": "Craigslist", "platform": "craigslist",
     "search_url": "https://www.craigslist.org/search/area/portland?cat=apa&min_bedrooms=2&min_bathrooms=2",
     "request_delay": 2, "max_detail_fetches": 60},
```

- [ ] **Step 6: README**

In `README.md`, replace the intro sentence's "from local property managers" with "from local property managers, Redfin, Zillow, and Craigslist", and add under "Adding a property manager":
```markdown
Portal sources (Redfin, Zillow, Craigslist) fetch detail pages only for listings not yet described,
capped per run (`max_detail_fetches` in the registry), so the first few runs fill in details gradually.
Realtor.com isn't scraped: it's protected by Kasada bot protection.
```

- [ ] **Step 7: Run tests**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 8: Live smoke**

Run: `uv run python manage.py scrape --source craigslist --no-geocode`
Expected: `craigslist: ok — ~360 listings, M new`.

- [ ] **Step 9: Commit, push, open PR 4 (base `p2/03-zillow`)**

```bash
git add -A
git commit -m "feat: Craigslist scraper"
git push -u origin p2/04-craigslist
gh pr create --base p2/03-zillow --head p2/04-craigslist --title "[P2 4/4] Craigslist scraper" --body "<summary + stack list + test plan>"
```

Then edit all four PR bodies so each lists the full stack with its PR number, and gives merge instructions (bottom-up, "Create a merge commit").
