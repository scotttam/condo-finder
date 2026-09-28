"""Zillow rentals: search via the JSON API its own search page calls, details from page JSON."""

import json
import logging
import re
from datetime import date
from decimal import Decimal

import httpx

from .base import ScrapedListing, Scraper, detail_priority, is_candidate

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
                latitude=(result.get("latLong") or {}).get("latitude"),
                longitude=(result.get("latLong") or {}).get("longitude"),
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
                       ("Appliances", "appliances"), ("Outdoor", "patioAndPorchFeatures"),
                       ("Interior", "interiorFeatures"), ("Exterior", "exteriorFeatures"), ("Flooring", "flooring")):
        value = facts.get(key)
        if value:
            lines.append(f"{label}: {', '.join(value) if isinstance(value, list) else value}")
    glance = {fact.get("factLabel"): fact.get("factValue") for fact in facts.get("atAGlanceFacts") or []}
    return {
        "description": prop.get("description") or "",
        "amenities": "\n".join(lines),
        "home_type": _type_label(prop.get("homeType")),
        "baths": _baths(facts),
        "available": glance.get("Date available") or "",
        **_rental_history(prop.get("priceHistory") or []),
    }


def _rental_history(entries):
    """Rental events only (Zillow also lists sales), oldest first, plus the current listing's start."""
    history = sorted(
        (date.fromisoformat(entry["date"]), int(entry["price"]), entry.get("event") or "")
        for entry in entries
        if entry.get("postingIsRental") and entry.get("price") is not None and entry.get("date")
    )
    listings_started = [day for day, _, event in history if event == "Listed for rent"]
    return {"price_history": history, "listed_at": listings_started[-1] if listings_started else None}


def _baths(facts):
    """Search results round half baths up (2.5 shows as 3), so count full + half from the detail page."""
    full, half = facts.get("bathroomsFull"), facts.get("bathroomsHalf")
    if full is None and half is None:
        return None
    return Decimal(full or 0) + Decimal(half or 0) / 2


class ZillowScraper(Scraper):
    platform = "zillow"
    details_version = 2  # 2: rental price history and listed date

    def scrape(self):
        by_id = {}
        for slug in self.options["city_slugs"]:
            for item in self._search(slug):
                by_id[item.external_id] = item
        items = list(by_id.values())
        fetched = 0
        for item in sorted(items, key=detail_priority):
            if not is_candidate(item) or "/homedetails/" not in item.url:
                continue  # /apartments/ pages are complex units with a different layout
            if not self.should_fetch_detail(item, fetched):
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
            item.baths = detail["baths"] if detail["baths"] is not None else item.baths
            item.available = detail["available"] or item.available
            item.price_history = detail["price_history"]
            item.listed_at = detail["listed_at"]
            item.details_version = self.details_version
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
