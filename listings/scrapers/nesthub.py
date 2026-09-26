import json
import logging
import re
from decimal import Decimal
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from ..parsing import parse_int, parse_price
from .base import ScrapedListing, Scraper, is_candidate

log = logging.getLogger(__name__)


def _text(element):
    return " ".join(element.get_text(" ", strip=True).split()) if element else ""


def parse_list(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for card in soup.select("div.nhw-list__item"):
        link = card.find("a", href=True)
        if link is None:
            continue
        href = link["href"]
        id_match = re.search(r"/_system/listings/(\d+)", href)
        details = _text(card.select_one(".nhw-list__details")).lower()
        beds = re.search(r"beds?:\s*(\d+)", details)
        baths = re.search(r"baths?:\s*(\d+(?:\.\d+)?)", details)
        image = card.select_one("img[data-src]")
        title = (image.get("alt") or "").removesuffix(" property image").strip() if image else ""
        items.append(
            ScrapedListing(
                external_id=id_match.group(1) if id_match else href,
                url=urljoin(base_url, href),
                address=_text(card.select_one(".nhw-list__location")),
                price=parse_price(_text(card.select_one(".nhw-list__price"))),
                beds=int(beds.group(1)) if beds else (0 if "studio" in details else None),
                baths=Decimal(baths.group(1)) if baths else None,
                title=title,
                property_type_hint=_text(card.select_one(".nhw-list__prop-type")),
                available=_text(card.select_one(".nhw-list__availability")).removeprefix("Available:").strip(),
                photo_url=urljoin(base_url, image["data-src"]) if image else "",
            )
        )
    return items


def parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    sub_details = {}
    for row in soup.select(".sub-detail"):
        label, value = row.select_one(".sub-detail__label"), row.select_one(".sub-detail__value")
        if label and value:
            sub_details[_text(label).rstrip(":").lower()] = _text(value)
    description = ""
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or "", strict=False)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("description"):
            description = data["description"]
            break
    amenities = ""
    if "Amenities:" in description:
        description, rest = description.split("Amenities:", 1)
        amenities = f"Amenities: {rest.strip()}"
    return {
        "sqft": parse_int(_text(soup.select_one(".key-detail.sqft .value"))),
        "property_type_hint": sub_details.get("building type", ""),
        "description": description.strip(),
        "amenities": amenities,
        "available": sub_details.get("date available", ""),
    }


class NesthubScraper(Scraper):
    platform = "nesthub"

    def scrape(self):
        list_url = self.options["list_url"]
        parts = urlsplit(list_url)
        items = parse_list(self.fetcher.get(list_url), f"{parts.scheme}://{parts.netloc}")
        for item in items:
            if not is_candidate(item):
                continue
            try:
                detail = parse_detail(self.fetcher.get(item.url))
            except httpx.HTTPError as exc:
                log.warning("Nesthub detail fetch failed for %s: %s", item.url, exc)
                continue
            item.sqft = detail["sqft"] or item.sqft
            item.property_type_hint = detail["property_type_hint"] or item.property_type_hint
            item.description = detail["description"] or item.description
            item.amenities = detail["amenities"]
            item.available = detail["available"] or item.available
        return items
