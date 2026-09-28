"""RentEngine-hosted listings (e.g. Chroma Property Management).

RentEngine sits behind a Vercel bot checkpoint that plain HTTP can't pass, so pages are
loaded in headless Chromium (Playwright). The embed page fetches its listings as JSON
(/api/getListingsInView); each listing page embeds its full record in __NEXT_DATA__.
"""

import json
import logging
import re
import time
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

from django.conf import settings

from .base import USER_AGENT, ScrapedListing, Scraper, detail_priority, is_candidate

log = logging.getLogger(__name__)

EMBED_URL = "https://rentengine.io/c/{slug}?paginate=false&sortBy=id&defaultSortDirection=asc"
LISTING_URL = "https://www.rentengine.io/listings/{id}?accounts={account}"
PHOTO_URL = "https://cdn.public-photos.rentengine.io/{path}"
STATES = {"Oregon": "OR", "Washington": "WA"}
TIMEOUT_MS = 60_000


def _address(record):
    street = f"{record.get('street_number', '')} {record.get('street_name', '')}".strip()
    unit = f" #{record['unit']}" if record.get("unit") else ""
    state = STATES.get(record.get("state_name"), record.get("state_name") or "")
    return f"{street}{unit}, {record.get('city_name', '')}, {state} {record.get('zip_code', '')}".strip()


def parse_listings(records, account_id):
    items = []
    for record in records:
        baths = record.get("bathrooms")
        photos = record.get("photos") or []
        items.append(
            ScrapedListing(
                external_id=str(record["id"]),
                url=LISTING_URL.format(id=record["id"], account=account_id),
                address=_address(record),
                price=record.get("target_rental_rate"),
                beds=record.get("bedrooms"),
                baths=Decimal(str(baths)) if baths is not None else None,
                sqft=record.get("sqft"),
                property_type_hint=(record.get("property_type") or "").title(),
                available=record.get("earliest_move_in_date") or "",
                photo_url=PHOTO_URL.format(path=photos[0]) if photos else "",
                latitude=record.get("lat"),
                longitude=record.get("long"),
            )
        )
    return items


def _joined(value):
    return ", ".join(value) if isinstance(value, list) else str(value or "")


def parse_detail(html):
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if match is None:
        raise ValueError("RentEngine listing page has no __NEXT_DATA__ (blocked or page changed)")
    repo = json.loads(match.group(1))["props"]["pageProps"]["repo"]
    lines = []
    if repo.get("num_parking_spots"):
        lines.append(f"{repo['num_parking_spots']} parking spaces")
    for label, key in (("Parking", "parking_type"), ("Laundry", "laundry"), ("Amenities", "amenities"),
                       ("Highlights", "highlighted_amenities"), ("Top features", "top_features"),
                       ("Utilities included", "utilities_included")):
        if repo.get(key):
            lines.append(f"{label}: {_joined(repo[key])}")
    description = "\n\n".join(part for part in (repo.get("marketing_title"), repo.get("marketing_description")) if part)
    return {"description": description, "amenities": "\n".join(lines)}


class RentEngineSession:
    """Headless Chromium that passes RentEngine's bot checkpoint. Starts lazily; call close()."""

    def __init__(self, delay=None):
        self.delay = settings.REQUEST_DELAY_SECONDS if delay is None else delay
        self._playwright = None
        self._browser = None
        self._page = None

    def _open(self):
        if self._page is None:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=True)
            self._page = self._browser.new_page(user_agent=USER_AGENT)
        return self._page

    def listings(self, slug):
        """Returns (account_id, listing records) from the company's embedded listings page."""
        page = self._open()
        with page.expect_response(lambda r: "/api/getListingsInView" in r.url, timeout=TIMEOUT_MS) as info:
            page.goto(EMBED_URL.format(slug=slug), wait_until="domcontentloaded", timeout=TIMEOUT_MS)
        response = info.value
        account_id = parse_qs(urlsplit(response.url).query)["accounts"][0]
        return account_id, response.json()

    def detail_html(self, url):
        time.sleep(self.delay)
        page = self._open()
        page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
        return page.content()

    def close(self):
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._playwright = self._browser = self._page = None


class RentEngineScraper(Scraper):
    platform = "rentengine"

    def default_fetcher(self, request_delay):
        return RentEngineSession(delay=request_delay)

    def scrape(self):
        try:
            account_id, records = self.fetcher.listings(self.options["slug"])
            items = parse_listings(records, account_id)
            fetched = 0
            for item in sorted(items, key=detail_priority):
                if not is_candidate(item) or not self.should_fetch_detail(item, fetched):
                    continue
                fetched += 1
                try:
                    detail = parse_detail(self.fetcher.detail_html(item.url))
                except Exception as exc:  # one bad listing page shouldn't lose the rest
                    log.warning("RentEngine listing fetch failed for %s: %s", item.url, exc)
                    continue
                item.description = detail["description"]
                item.amenities = detail["amenities"]
                item.details_version = self.details_version
            return items
        finally:
            self.fetcher.close()
