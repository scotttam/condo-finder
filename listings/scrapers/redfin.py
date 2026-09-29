"""Redfin rentals via the JSON API its own search page uses; listing pages for details."""

import json
import logging
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx

from .base import RefreshBlocked, ScrapedListing, Scraper, detail_priority, is_candidate

log = logging.getLogger(__name__)

API_URL = "https://www.redfin.com/stingray/api/v1/search/rentals"
PHOTO_URL = "https://ssl.cdn-redfin.com/photo/rent/{rental_id}/islphoto/genIsl.{position}_{version}.jpg"
# Redfin propertyType codes, verified against live results 2026-09-26.
PROPERTY_TYPES = {3: "Condo", 4: "Multi-family", 5: "Apartment", 6: "Single Family Home", 13: "Townhouse"}


# Listing pages embed the responses of Redfin's own API calls, each as a JSON string.
PAGE_DATA_MARKER = "root.__reactServerState.InitialContext = "
RENTAL_EVENT = 3  # propertyHistoryInfo historyEventType; 1 and 2 are sale listings and sales
EVENT_NAMES = {  # match Zillow's wording so both sites' history reads (and is handled) the same
    "listed for rent": "Listed for rent",
    "rental removed": "Listing removed",
    "price changed": "Price change",
    "price change": "Price change",
}
PACIFIC = ZoneInfo("America/Los_Angeles")


def _cached_responses(html):
    start = html.find(PAGE_DATA_MARKER)
    if start < 0:
        raise ValueError("Redfin listing page has no embedded data (blocked or page changed)")
    context, _ = json.JSONDecoder().raw_decode(html, start + len(PAGE_DATA_MARKER))
    responses = {}
    for url, entry in context["ReactServerAgent.cache"]["dataCache"].items():
        text = ((entry or {}).get("res") or {}).get("text") or ""
        try:
            responses[url.split("?")[0]] = json.loads(text.removeprefix("{}&&"))
        except ValueError:
            continue
    return responses


def _response(responses, path_suffix):
    return next((body for path, body in responses.items() if path.endswith(path_suffix)), {}) or {}


def _rental_history(events):
    rentals = sorted(
        (event for event in events
         if event.get("historyEventType") == RENTAL_EVENT and event.get("price") is not None and event.get("eventDate")),
        key=lambda event: event["eventDate"],
    )
    history = [
        (
            datetime.fromtimestamp(event["eventDate"] / 1000, PACIFIC).date(),
            int(event["price"]),
            EVENT_NAMES.get((event.get("eventDescription") or "").lower(), event.get("eventDescription") or ""),
        )
        for event in rentals
    ]
    starts = [day for day, _, event in history if event == "Listed for rent"]
    return history, (starts[-1] if starts else None)


def parse_detail(html):
    responses = _cached_responses(html)
    amenities = _response(responses, "/amenities")
    history_info = _response(responses, "/home/details/belowTheFold").get("payload", {}).get("propertyHistoryInfo") or {}
    lines = [
        f"{label}: {', '.join(values)}"
        for label, key in (("Unit amenities", "unitAmenities"), ("Community amenities", "communityAmenities"),
                           ("Amenities", "standardizedAmenities"), ("Other amenities", "otherAmenities"))
        if (values := amenities.get(key))
    ]
    history, listed_at = _rental_history(history_info.get("events") or [])
    return {
        "description": _response(responses, "/about").get("description") or "",
        "amenities": "\n".join(lines),
        "price_history": history,
        "listed_at": listed_at,
    }


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
        centroid = (address.get("centroid") or {}).get("centroid") or {}
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
                latitude=centroid.get("latitude"),
                longitude=centroid.get("longitude"),
            )
        )
    return items


class RedfinScraper(Scraper):
    platform = "redfin"
    details_version = 2  # 2: listing pages (description, amenities, rental history); 1 had none

    def _listing_page(self, url):
        try:
            response = self.fetcher.request("GET", url)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (403, 429):
                raise RefreshBlocked(exc.response.status_code) from exc
            raise
        if response.status_code == 202 or "x-amzn-waf-action" in response.headers:
            raise RefreshBlocked("challenge")
        return response.text

    def refresh_listing(self, url):
        return parse_detail(self._listing_page(url))

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
        items = list(by_id.values())
        fetched = 0
        for item in sorted(items, key=detail_priority):
            if not is_candidate(item) or item.property_type_hint == "Apartment":
                continue  # complexes are hidden by default; their pages are floor-plan listings
            if not self.should_fetch_detail(item, fetched):
                continue
            fetched += 1
            try:
                detail = parse_detail(self._listing_page(item.url))
            except RefreshBlocked as exc:
                # Redfin's bot protection is challenging us; more requests only prolong the block.
                log.warning("Redfin is blocking listing pages (%s); stopping until the next run", exc)
                break
            except httpx.HTTPError as exc:
                log.warning("Redfin listing page failed for %s: %s", item.url, exc)
                continue
            except (ValueError, KeyError) as exc:
                log.warning("Redfin listing page failed for %s: %s", item.url, exc)
                continue
            item.description = detail["description"] or item.description
            item.amenities = detail["amenities"]
            item.price_history = detail["price_history"]
            item.listed_at = detail["listed_at"]
            item.details_version = self.details_version
        return items
