import logging
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from ..parsing import parse_beds_baths, parse_int, parse_price
from .base import ScrapedListing, Scraper, is_candidate

log = logging.getLogger(__name__)

DETAIL_SECTIONS = ("amenities", "appliances", "utilities included", "pet policy")


def _text(element, separator=" "):
    return element.get_text(separator, strip=True) if element else ""


def parse_list(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for card in soup.select("div.js-listing-item"):
        link = card.select_one(".js-listing-title a") or card.select_one("a[href*='/listings/detail/']")
        if link is None:
            continue
        href = link["href"]
        facts = {
            _text(label).lower(): _text(value)
            for label, value in zip(card.select(".detail-box__label"), card.select(".detail-box__value"))
        }
        beds, baths = parse_beds_baths(facts.get("bed / bath", ""))
        image = card.select_one("img.js-listing-image")
        items.append(
            ScrapedListing(
                external_id=href.rstrip("/").rsplit("/", 1)[-1],
                url=urljoin(base_url, href),
                address=_text(card.select_one(".js-listing-address")),
                price=parse_price(facts.get("rent", "")),
                beds=beds,
                baths=baths,
                sqft=parse_int(facts.get("square feet", "")),
                title=_text(link),
                description=_text(card.select_one(".js-listing-description"), "\n"),
                available=facts.get("available", ""),
                photo_url=(image.get("data-original") or "") if image else "",
            )
        )
    return items


def parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    sections = {}
    for heading in soup.select("h3"):
        items = heading.find_next_sibling("ul")
        if items is not None:
            sections[_text(heading).lower()] = [_text(li) for li in items.select("li")]
    amenities = [
        f"{name.title()}: {', '.join(sections[name])}" for name in DETAIL_SECTIONS if sections.get(name)
    ]
    return {
        "description": _text(soup.select_one(".listing-detail__description"), "\n"),
        "amenities": "\n".join(amenities),
    }


class AppFolioScraper(Scraper):
    platform = "appfolio"

    def scrape(self):
        base_url = f"https://{self.options['subdomain']}.appfolio.com"
        items = parse_list(self.fetcher.get(f"{base_url}/listings"), base_url)
        for item in items:
            if not is_candidate(item):
                continue
            try:
                detail = parse_detail(self.fetcher.get(item.url))
            except httpx.HTTPError as exc:
                log.warning("AppFolio detail fetch failed for %s: %s", item.url, exc)
                continue
            item.description = detail["description"] or item.description
            item.amenities = detail["amenities"]
        return items
