"""Keyword/regex extraction of features from free listing text. None means unknown."""

import re

from .models import PropertyType
from .parsing import WORD_NUMBERS

_NUM = r"(\d|one|two|three|four|single|double)"
_QUALIFIER = (
    r"(?:(?:reserved|assigned|designated|deeded|covered|secured?|garage|off[\s-]street|underground"
    r"|dedicated|private|tandem)\s+)"
)
_PARKING_COUNT_PATTERNS = [
    rf"\b{_NUM}[\s-]*(?:car|vehicle)\s+(?:attached\s+|detached\s+|tandem\s+)?(?:garage|parking|carport)",
    rf"\b{_NUM}\s+garage\b",
    rf"\b{_NUM}\s+{_QUALIFIER}*parking\b",
    rf"\b{_NUM}\s+{_QUALIFIER}+(?:spaces?|spots?|stalls?)\b",
    rf"\bparking\s+for\s+{_NUM}\b",
    rf"\b(an?)\s+{_QUALIFIER}+(?:parking\s+)?(?:spaces?|spots?|stalls?)\b",
    # Fact lists: "Parking: Off Street, 1 spaces", "Parking: 1 Total space".
    rf"\bparking:\s*(?:[a-z][a-z\s-]*,\s*)?{_NUM}\s+(?:total\s+)?(?:spaces?|spots?)\b",
]
_PARKING_POSITIVE = (
    r"\b(?:garage|carport|driveway|w/\s?parking|with parking"
    r"|(?:off[\s-]street|assigned|reserved|covered|secured?|underground|deeded|private|gated) parking"
    r"|parking (?:space|spot|stall|included|available))"
)
_PARKING_NONE = r"\bno (?:off[\s-]street )?parking\b|\bparking (?:is )?not included"

_WD_NONE = r"\bno (?:in[\s-]unit )?(?:washer|w/d|laundry)"
_WD_YES = (
    r"in[\s-](?:unit|home)\s+(?:washer|laundry|w/d)|washer\s*(?:/|&|and|-|,\s*(?:and|&)?)\s*dryer"
    r"|\bw/d\b|laundry in (?:unit|home)|laundry:\s*(?:in[\s-]?unit|hookups)|stackable"
)
_WD_SHARED = (
    r"(?:shared|coin[\s-]op(?:erated)?|common|on[\s-]?site|community) laundry"
    r"|laundry (?:room|facilities|facility|on[\s-]?site|in (?:bldg|building))"
)

_AC_NONE = r"\bno (?:air[\s-]conditioning|a/c|ac)\b|\bcooling:\s*none\b"
_AC_YES = r"air[\s-]condition|\ba/c\b|\bac\b|central air|ductless|mini[\s-]splits?|heat pump|cooling"

_OUTDOOR_NONE = r"\bno (?:balcony|patio|deck|yard|outdoor space)"
_OUTDOOR_YES = r"balcon|patio|\bdecks?\b|\byard\b|back ?yard|terrace|porch|veranda|lanai"

# Offered either way: "furnished or unfurnished", "fully furnished if desired", "furnished options".
_FURNISHED_OPTIONAL = re.compile(
    r"\bfurnished\s*(?:or|/|&|and)\s*un-?furnished|\bun-?furnished\s*(?:or|/|&|and)\s*(?:fully\s+)?furnished"
    r"|\bfurnished\s+(?:if\s+desired|would\s+be|upon\s+request|options?\b)|\b(?:can\s+be|optionally)\s+furnished",
    re.I,
)
# Phrases that say nothing about this unit: an apartment building's "Furnished apartments available",
# "Available furnished" in amenity lists, partial furnishing, photos taken empty.
_FURNISHED_IGNORED = re.compile(
    r"(?:(?:fully|partially)\s+)?furnished\s+(?:available|apartments?\b|apartment\s+homes|homes\b|units\b)"
    r"|\bavailable\s+(?:fully\s+)?furnished|partially\s+furnished|furnished\s+\(partially\)"
    r"|photos?\s+(?:shown\s+)?(?:are\s+)?un-?furnished",
    re.I,
)
_FURNISHED_NONE = re.compile(
    r"\bun-?furnished\b|\b(?:not|non)[\s-]furnished\b|\bfurnishings?\s+(?:are\s+)?not\s+included"
    r"|does\s+not\s+include\s+any\s+furnishing",
    re.I,
)
_FURNISHED_YES = re.compile(
    r"\b(?:fully|completely|comfortably|beautifully|thoughtfully|tastefully|luxury|designer)[\s-]+furnished\b"
    r"|\b(?:comes|delivered|provided|rented|offered|is|be)\s+(?:fully\s+)?furnished\b"
    r"|\bfurnished\s+(?:(?:\d|one|two|three|four|five)[\s-]*(?:bed|br|bd)|home\b|house\b|townho(?:me|use)\b|condo\b"
    r"|rentals?\b|residence|sublet|corporate|executive|mid-century|craftsman|bungalow|historic|floating|with\s+everything)"
    r"|(?:^|\n)\W*furnished\b|\bfurnished[.!]",
    re.I,
)

_TYPE_HINTS = [
    ("condo", PropertyType.CONDO),
    ("town", PropertyType.TOWNHOME),
    ("single family", PropertyType.HOUSE),
    ("house", PropertyType.HOUSE),
    ("apartment", PropertyType.APARTMENT),
    ("plex", PropertyType.OTHER),
    ("loft", PropertyType.OTHER),
    ("other", PropertyType.OTHER),
]
_TYPE_TEXT_RULES = [
    # Not "HOA": boilerplate like "this home may have an HOA" appears on houses too.
    (r"\bcondo(?:minium)?s?\b", PropertyType.CONDO),
    (r"\btown\s?(?:home|house)s?\b", PropertyType.TOWNHOME),
    (
        r"leasing office|apartment homes|apartment community|our community|resident portal"
        r"|community amenities|\bapartments\b",
        PropertyType.APARTMENT,
    ),
    (r"single[\s-]family|\bhouse\b|\bbungalow\b|\bcraftsman\b|\branch[\s-]style\b", PropertyType.HOUSE),
]


def _to_int(word):
    if word in ("a", "an"):
        return 1
    return int(word) if word.isdigit() else WORD_NUMBERS[word]


def extract_parking(text):
    lowered = (text or "").lower()
    counts = [_to_int(m.group(1)) for p in _PARKING_COUNT_PATTERNS for m in re.finditer(p, lowered)]
    if re.search(r"\btandem\b", lowered):
        counts.append(2)
    if counts:
        return max(counts)
    if re.search(_PARKING_NONE, lowered):
        return 0
    if re.search(r"\bgarage\b", lowered) and re.search(r"\bdriveway\b", lowered):
        return 2
    if re.search(_PARKING_POSITIVE, lowered):
        return None  # parking exists but the count isn't stated
    if re.search(r"\bstreet parking\b|\bparking:\s*street\b", lowered):  # after "off-street parking"
        return 0
    return None


def has_parking(text):
    """Whether any off-street parking comes with the unit, even when the number of spaces isn't stated."""
    spaces = extract_parking(text)
    if spaces is not None:
        return spaces > 0
    if re.search(_PARKING_POSITIVE, (text or "").lower()):
        return True
    return None


def _tri_state(text, none_pattern, yes_pattern, no_pattern=None):
    lowered = (text or "").lower()
    if re.search(none_pattern, lowered):
        return False
    if re.search(yes_pattern, lowered):
        return True
    if no_pattern and re.search(no_pattern, lowered):
        return False
    return None


def has_washer_dryer(text):
    return _tri_state(text, _WD_NONE, _WD_YES, _WD_SHARED)


def has_ac(text):
    return _tri_state(text, _AC_NONE, _AC_YES)


def has_outdoor_space(text):
    return _tri_state(text, _OUTDOOR_NONE, _OUTDOOR_YES)


def is_furnished(text):
    """True for a furnished rental, False when it says unfurnished, None when it doesn't say or is
    offered either way ("available furnished or unfurnished", an apartment building's "furnished
    apartments available")."""
    if _FURNISHED_OPTIONAL.search(text or ""):
        return None
    text = _FURNISHED_IGNORED.sub(" ", text or "")
    unfurnished = bool(_FURNISHED_NONE.search(text))
    furnished = bool(_FURNISHED_YES.search(_FURNISHED_NONE.sub(" ", text)))
    if furnished and unfurnished:
        return None  # e.g. separate furnished and unfurnished rents
    return True if furnished else False if unfurnished else None


def _type_from_hint(hint):
    lowered = (hint or "").lower()
    for needle, property_type in _TYPE_HINTS:
        if needle in lowered:
            return property_type
    return None


def _type_from_text(text):
    lowered = (text or "").lower()
    for pattern, property_type in _TYPE_TEXT_RULES:
        if re.search(pattern, lowered):
            return property_type
    return PropertyType.UNKNOWN


def classify_property_type(hint, text):
    hinted = _type_from_hint(hint)
    from_text = _type_from_text(text)
    # Property managers often label individually owned condos as "Apartment".
    if hinted == PropertyType.APARTMENT and from_text == PropertyType.CONDO:
        return PropertyType.CONDO
    if hinted and hinted != PropertyType.OTHER:
        return hinted
    if from_text != PropertyType.UNKNOWN:
        return from_text
    return hinted or PropertyType.UNKNOWN
