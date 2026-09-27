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
