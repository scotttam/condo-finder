import re
from dataclasses import dataclass

from django.conf import settings

_ABBREVIATIONS = {
    "street": "st", "avenue": "ave", "boulevard": "blvd", "road": "rd", "drive": "dr",
    "lane": "ln", "court": "ct", "place": "pl", "terrace": "ter", "parkway": "pkwy",
    "highway": "hwy", "circle": "cir", "north": "n", "south": "s", "east": "e", "west": "w",
    "northwest": "nw", "northeast": "ne", "southwest": "sw", "southeast": "se",
}
_ADDRESS_RE = re.compile(
    r"^(?P<street>.+?),\s*(?P<city>[A-Za-z .'-]+?),\s*(?P<state>[A-Za-z]{2})\.?\s*"
    r"(?P<zip>\d{5})?(?:-\d{4})?(?:\s*,?\s*(?:US|USA))?$"
)
_UNIT_RE = re.compile(
    r"(?:\s*#\s*|\s+(?:apt\.?|apartment|unit|suite|ste\.?)\s*#?\s*|\s+-\s+)(?P<unit>[A-Za-z0-9-]+)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedAddress:
    street: str
    unit: str
    city: str
    state: str
    zip_code: str

    @property
    def key(self):
        return "|".join([normalize_street(self.street), self.unit.lower(), self.zip_code or self.city.lower()])

    @property
    def display(self):
        unit = f" #{self.unit}" if self.unit else ""
        return f"{self.street}{unit}, {self.city}, {self.state} {self.zip_code}".strip()


def normalize_street(street):
    words = re.sub(r"[.,]", " ", street.lower()).split()
    return " ".join(_ABBREVIATIONS.get(word, word) for word in words)


def parse_address(raw):
    text = " ".join((raw or "").split())
    match = _ADDRESS_RE.match(text)
    if not match:
        return None
    street = match["street"].strip()
    unit = ""
    unit_match = _UNIT_RE.search(street)
    if unit_match:
        unit = unit_match["unit"]
        street = street[: unit_match.start()].rstrip(" ,")
    return ParsedAddress(
        street=street,
        unit=unit,
        city=match["city"].strip().title(),
        state=match["state"].upper(),
        zip_code=match["zip"] or "",
    )


_QUADRANT_WORDS = {
    "nw": "NW", "northwest": "NW", "ne": "NE", "northeast": "NE",
    "se": "SE", "southeast": "SE", "sw": "SW", "southwest": "SW",
    "n": "N", "north": "N", "s": "S", "south": "S",
}


def portland_quadrant(street, city):
    """NW/NE/SE/SW/N/S from the street's directional prefix; only Portland uses this grid."""
    if (city or "").strip().lower() != "portland":
        return ""
    match = re.match(r"\s*\d+[a-z]?(?:-\d+[a-z]?)?\s+([a-z.]+)\s", (street or "").lower())
    return _QUADRANT_WORDS.get(match.group(1).replace(".", ""), "") if match else ""


def is_target_city(city):
    return (city or "").strip().lower() in {c.lower() for c in settings.TARGET_CITIES}
