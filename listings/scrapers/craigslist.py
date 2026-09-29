"""Craigslist apartments/housing for rent: search page structured data + posting pages."""

import json
import logging
import re
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import httpx
from bs4 import BeautifulSoup

from ..parsing import parse_beds_baths, parse_int, parse_price
from .base import ScrapedListing, Scraper, detail_priority, is_candidate

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
                latitude=info.get("latitude"),
                longitude=info.get("longitude"),
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


REMOVED_MARKERS = ("This posting has been deleted", "This posting has expired", "flagged for removal")


class CraigslistScraper(Scraper):
    platform = "craigslist"

    def refresh_listing(self, url):
        try:
            html = self.fetcher.get(url)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (404, 410):
                return {"removed": True}
            raise
        if any(marker in html for marker in REMOVED_MARKERS):
            return {"removed": True}
        detail = parse_detail(html)
        return {key: detail[key] for key in ("price", "description", "amenities", "baths")}

    def check_listing(self, url):
        """Search only shows the newest few hundred posts, so an older post that's still up drops out
        of it. Before calling a post gone, look at the post itself."""
        try:
            html = self.fetcher.get(url)
        except httpx.HTTPStatusError as exc:
            return (False, None) if exc.response.status_code in (404, 410) else (None, None)
        except httpx.HTTPError:
            return None, None
        if any(marker in html for marker in REMOVED_MARKERS):
            return False, None
        detail = parse_detail(html)
        if not (detail["title"] or detail["address"]):
            return None, None
        return True, detail["price"]

    def scrape(self):
        items = parse_search(self.fetcher.get(self.options["search_url"]))
        fetched = 0
        for item in sorted(items, key=detail_priority):
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
            item.details_version = self.details_version
        return items
