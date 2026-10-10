"""The Search page's table columns: which exist, which show by default, and how each header sorts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    sort: str = ""  # a SORT_FIELDS key; "" when the column doesn't sort
    default: bool = False


COLUMNS = [
    Column("photo", "Photo", default=True),
    Column("address", "Address", "address", True),
    Column("area", "Area", "area", True),
    Column("price", "Price", "price", True),
    Column("beds_baths", "Bd / Ba", "beds", True),
    Column("sqft", "Sqft", "sqft", True),
    Column("ppsf", "$/sqft", "ppsf", True),
    Column("parking", "Parking", "parking", True),
    Column("features", "Features", default=True),
    Column("dom", "On market", "dom", True),
    Column("status", "Status", "status", True),
    Column("votes", "Votes", "votes", True),
    Column("effective", "Effective rent", "effective"),
    Column("drop", "Price drop", "drop"),
    Column("special", "Special"),
    Column("type", "Type", "type"),
    Column("zip", "ZIP", "zip"),
    Column("sources", "Sources", "sites"),
    Column("listed", "Listed", "listed"),
    Column("first_seen", "First seen", "first_seen"),
    Column("last_seen", "Last seen", "last_seen"),
]
BY_KEY = {column.key: column for column in COLUMNS}
DEFAULT_KEYS = [column.key for column in COLUMNS if column.default]


def keys_from(keys):
    """The known keys among keys, in registry order; the defaults when there are none."""
    wanted = set(keys or [])
    return [column.key for column in COLUMNS if column.key in wanted] or list(DEFAULT_KEYS)


def headers(keys, current_sort, url_for):
    """Header cells for the table. Clicking a header sorts by it ascending, or flips it if it's the sort now."""
    cells = []
    for key in keys:
        column = BY_KEY[key]
        cell = {"key": key, "label": column.label, "sort_key": column.sort, "next_sort": "", "arrow": "", "url": ""}
        if column.sort:
            ascending, descending = current_sort == column.sort, current_sort == f"-{column.sort}"
            cell["next_sort"] = f"-{column.sort}" if ascending else column.sort
            cell["arrow"] = "↑" if ascending else "↓" if descending else ""
            cell["url"] = url_for(cell["next_sort"])
        cells.append(cell)
    return cells


def _known(value):
    return {True: "yes", False: "no"}.get(value, "")


# Every useful fact, whatever the table shows: a spreadsheet can hide columns, it can't add them.
CSV_FIELDS = [
    ("Address", lambda l: l.street), ("Unit", lambda l: l.unit), ("City", lambda l: l.city),
    ("Quadrant", lambda l: l.quadrant), ("Neighborhood", lambda l: l.neighborhood), ("ZIP", lambda l: l.zip_code),
    ("Price", lambda l: l.price), ("Effective rent", lambda l: l.effective_price), ("Beds", lambda l: l.beds),
    ("Baths", lambda l: l.baths), ("Sqft", lambda l: l.sqft), ("$/sqft", lambda l: l.price_per_sqft),
    ("Parking", lambda l: l.parking_spaces), ("W/D", lambda l: _known(l.has_washer_dryer)),
    ("AC", lambda l: _known(l.has_ac)), ("Outdoor", lambda l: _known(l.has_outdoor_space)),
    ("Furnished", lambda l: _known(l.is_furnished)), ("Type", lambda l: l.get_property_type_display()),
    ("Special", lambda l: l.special_offer), ("Price drop", lambda l: l.price_drop or ""),
    ("Days on market", lambda l: l.days_on_market), ("Listed", lambda l: l.listed_at or ""),
    ("First seen", lambda l: l.first_seen_at.date()), ("Last seen", lambda l: l.last_seen_at.date()),
    ("Active", lambda l: _known(l.is_active)), ("Status", lambda l: l.group_status_label),
    ("Up votes", lambda l: l.up_count), ("Down votes", lambda l: l.down_count),
    ("Sources", lambda l: ", ".join(sl.source.name for sl in l.source_listings.all() if sl.is_active)),
    ("Photo", lambda l: l.photo_url),
]


def csv_cell(value):
    """A cell a spreadsheet won't run as a formula."""
    if value is None:
        return ""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{value}"
    return value
