import re
from decimal import Decimal

WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "single": 1, "double": 2}


def parse_price(text):
    match = re.search(r"\$\s*(\d[\d,]*)", text or "")
    return int(match.group(1).replace(",", "")) if match else None


def parse_int(text):
    match = re.search(r"\d[\d,]*", text or "")
    return int(match.group(0).replace(",", "")) if match else None


def parse_beds_baths(text):
    lowered = (text or "").lower()
    beds = 0 if "studio" in lowered else None
    # "Beds: 2" label form first, so "Beds: 2 Baths: 1" isn't misread as "2 baths".
    match = re.search(r"\b(?:beds?|bedrooms?):\s*(\d+(?:\.\d+)?)", lowered) or re.search(
        r"(\d+(?:\.\d+)?)\s*(?:bd|beds?|bedrooms?|br)\b", lowered
    )
    if match:
        beds = int(float(match.group(1)))
    match = re.search(r"\b(?:baths?|bathrooms?):\s*(\d+(?:\.\d+)?)", lowered) or re.search(
        r"(\d+(?:\.\d+)?)\s*(?:ba|baths?|bathrooms?)\b", lowered
    )
    baths = Decimal(match.group(1)) if match else None
    return beds, baths
