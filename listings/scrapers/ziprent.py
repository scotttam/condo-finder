"""Ziprent, a national property manager (listings.ziprent.com).

The listings page fetches every listing in the country with one POST to its public search API and
filters by map area in the browser; we do the same and keep our cities. Each listing's page
(/show/<id>) has the full description, its facts (parking, laundry, cooling) and the size.

The search API also returns owner-side fields (contact details, lockbox, bank account); only the
listing fields below are ever read.
"""

import logging
import re
from decimal import Decimal, InvalidOperation

from bs4 import BeautifulSoup

from ..parsing import parse_int
from .base import ScrapedListing, Scraper, detail_priority, is_candidate

log = logging.getLogger(__name__)

SEARCH_URL = "https://listings.ziprent.com/public-api/listings/search"
LISTING_URL = "https://listings.ziprent.com/show/{id}"
PHOTO_URL = "https://cdn.ziprent.com/property_photos/{id}/{fs_name}"


def _number(value, kind):
    try:
        return kind(Decimal(str(value))) if value not in (None, "") else None
    except (InvalidOperation, ValueError):
        return None


def _address(record):
    parsed = record.get("parsed_address") or {}
    unit = (record.get("unit_type") or "").strip()  # despite the name, the unit: "5", "A", "Upper"
    street = f"{parsed.get('street_address', '').strip()}{f' #{unit}' if unit else ''}"
    return f"{street}, {parsed.get('city', '').strip()}, {parsed.get('state', '').strip()} {parsed.get('zip', '').strip()}".strip()


def parse_listings(records):
    items = []
    for entry in records:
        record = entry.get("property")
        if not record or record.get("is_test_property") or record.get("is_for_sale"):
            continue
        photos = record.get("photos") or []
        items.append(
            ScrapedListing(
                external_id=str(record["id"]),
                url=LISTING_URL.format(id=record["id"]),
                address=_address(record),
                price=_number(record.get("rent"), int),
                beds=_number(record.get("bedrooms"), int),
                baths=_number(record.get("bathrooms"), Decimal),
                latitude=_number(record.get("latitude"), float),
                longitude=_number(record.get("longitude"), float),
                photo_url=PHOTO_URL.format(id=record["id"], fs_name=photos[0]["fs_name"]) if photos and photos[0].get("fs_name") else "",
            )
        )
    return items


def parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    section = soup.select_one("div.property-details div.section p")
    description = "\n".join(line.strip() for line in section.get_text("\n").splitlines() if line.strip()) if section else ""
    facts = {}
    for label in soup.select("div.property-details label"):
        value = label.find_next_sibling("p")
        if value is not None:
            facts[label.get_text(strip=True).rstrip(":")] = " ".join(value.get_text(" ", strip=True).split())
    available = re.search(r"^Available:\s*(.+)$", description, re.MULTILINE)
    return {
        "description": description,
        "amenities": "\n".join(f"{name}: {value}" for name, value in facts.items()),
        "sqft": parse_int(facts.get("Size", "")),
        "available": available.group(1).strip() if available else "",
    }


class ZiprentScraper(Scraper):
    platform = "ziprent"

    def scrape(self):
        response = self.fetcher.request("POST", SEARCH_URL, json={}, headers={"Accept": "application/json"})
        items = parse_listings(response.json().get("response") or [])
        fetched = 0
        for item in sorted(items, key=detail_priority):
            if not is_candidate(item) or not self.should_fetch_detail(item, fetched):
                continue
            fetched += 1
            try:
                detail = parse_detail(self.fetcher.get(item.url))
            except Exception as exc:  # one bad listing page shouldn't lose the rest
                log.warning("Ziprent listing fetch failed for %s: %s", item.url, exc)
                continue
            item.description = detail["description"]
            item.amenities = detail["amenities"]
            item.sqft = detail["sqft"] or item.sqft
            item.available = detail["available"]
            item.details_version = self.details_version
        return items
