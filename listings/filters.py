from datetime import date, timedelta

from django.db.models import (Case, Count, DateField, ExpressionWrapper, F, FloatField, Func, IntegerField, Max, Min, OuterRef, Q,
                              Subquery, Value, When)
from django.db.models.functions import Cast, Coalesce, Least, TruncDate
from django.utils import timezone

from . import search_index
from .forms import PRICE_SLIDER_MAX
from .models import PriceChange, SourceListing, Status, Vote

FEATURE_FIELDS = {"wd": "has_washer_dryer", "ac": "has_ac", "outdoor": "has_outdoor_space", "furnished": "is_furnished"}

PARKING_Q = {
    "yes": Q(parking_spaces__gt=0) | Q(parking_spaces__isnull=True, has_parking=True),
    "no": Q(parking_spaces=0) | Q(parking_spaces__isnull=True, has_parking=False),
    "unknown": Q(parking_spaces__isnull=True, has_parking__isnull=True),
}
PARKING_Q["yes_or_unknown"] = PARKING_Q["yes"] | PARKING_Q["unknown"]

RANGE_LOOKUPS = [
    ("max_beds", "beds__lte"), ("max_baths", "baths__lte"),
    ("min_sqft", "sqft__gte"), ("max_sqft", "sqft__lte"),
    ("min_effective", "effective_price__gte"), ("max_effective", "effective_price__lte"),
]


def ppsf_expr():
    return ExpressionWrapper(Cast("price", FloatField()) / F("sqft"), output_field=FloatField())


class JulianDay(Func):
    function = "julianday"
    output_field = FloatField()


def first_day_expr():
    """The day the current rental listing started: the site's listed date when it's before we first saw it."""
    seen = TruncDate("first_seen_at")  # in the current time zone, like timezone.localdate()
    return Least(Coalesce("listed_at", seen), seen)


def dom_expr():
    """Listing.days_on_market in SQL: to today, or to the last day seen once off-market."""
    end = Case(When(is_active=True, then=Value(timezone.localdate())), default=TruncDate("last_seen_at"),
               output_field=DateField())
    return Cast(JulianDay(end) - JulianDay(first_day_expr()), IntegerField())


def _with_price_range(queryset):
    """Annotates peak_price and low_price during the current rental listing (all history when the listed date
    is unknown). Safe to call twice."""
    if "peak_price" in queryset.query.annotations:
        return queryset
    in_current_listing = Q(listed_at__isnull=True) | Q(price_changes__seen_at__date__gte=F("listed_at"))
    return queryset.annotate(peak_price=Max("price_changes__price", filter=in_current_listing),
                             low_price=Min("price_changes__price", filter=in_current_listing))


def price_change_count():
    """How many times a site changed the price during the current rental listing."""
    since = Coalesce(OuterRef("listed_at"), Value(date(1900, 1, 1)), output_field=DateField())
    changes = (PriceChange.objects.filter(listing=OuterRef("pk"), event="Price change", seen_at__date__gte=since)
               .order_by().values("listing").annotate(n=Count("pk")).values("n"))
    return Coalesce(Subquery(changes, output_field=IntegerField()), 0)


def active_site_count():
    sites = (SourceListing.objects.filter(listing=OuterRef("pk"), is_active=True)
             .order_by().values("listing").annotate(n=Count("pk")).values("n"))
    return Coalesce(Subquery(sites, output_field=IntegerField()), 0)


def _feature_q(field, choice):
    """Yes / No / Unknown / Yes or unknown (and furnished's older Hide / Only) as a Q; None means Any."""
    return {
        "yes": Q(**{field: True}),
        "only": Q(**{field: True}),
        "no": Q(**{field: False}),
        "unknown": Q(**{f"{field}__isnull": True}),
        "yes_or_unknown": ~Q(**{field: False}),  # negating a nullable column keeps the NULLs
        "hide": ~Q(**{field: True}),
    }.get(choice)


def apply_filters(queryset, data, group):
    if not data.get("show_inactive") and not data.get("gone_within"):
        queryset = queryset.filter(is_active=True)
    queryset = search_index.filter_listings(queryset, data.get("q"))
    if data.get("min_beds") is not None:
        queryset = queryset.filter(beds__gte=data["min_beds"])
    if data.get("min_baths") is not None:
        queryset = queryset.filter(baths__gte=data["min_baths"])
    parking = Q()
    if data.get("min_parking") is not None:
        parking &= Q(parking_spaces__gte=data["min_parking"])
    if data.get("max_parking") is not None:
        parking &= Q(parking_spaces__lte=data["max_parking"])
    if parking:
        if data.get("parking_unknown"):
            parking |= Q(parking_spaces__isnull=True)
        queryset = queryset.filter(parking)
    if data.get("min_price") is not None:
        queryset = queryset.filter(price__gte=data["min_price"])
    # The home slider's top value means "no maximum"; a typed value above it (on Search) still filters.
    if data.get("max_price") is not None and data["max_price"] != PRICE_SLIDER_MAX:
        queryset = queryset.filter(price__lte=data["max_price"])
    for name, lookup in RANGE_LOOKUPS:
        if data.get(name) is not None:
            queryset = queryset.filter(**{lookup: data[name]})
    if data.get("min_ppsf") is not None or data.get("max_ppsf") is not None:
        queryset = queryset.alias(ppsf_value=ppsf_expr())
        if data.get("min_ppsf") is not None:
            queryset = queryset.filter(ppsf_value__gte=float(data["min_ppsf"]))
        if data.get("max_ppsf") is not None:
            queryset = queryset.filter(ppsf_value__lte=float(data["max_ppsf"]))
    bounds = [data.get(side) for side in ("north", "south", "east", "west")]
    if all(value is not None for value in bounds):
        north, south, east, west = bounds
        queryset = queryset.filter(latitude__range=(south, north), longitude__range=(west, east))
    if data.get("cities"):
        queryset = queryset.filter(city__in=data["cities"])
    if data.get("quadrants"):
        queryset = queryset.filter(quadrant__in=data["quadrants"])
    if data.get("neighborhood"):
        queryset = queryset.filter(neighborhood__icontains=data["neighborhood"])
    if data.get("zips"):
        queryset = queryset.filter(zip_code__in=data["zips"])
    if data.get("neighborhoods"):
        queryset = queryset.filter(neighborhood__in=data["neighborhoods"])
    if data.get("min_sites"):
        queryset = queryset.alias(site_count=active_site_count()).filter(site_count__gte=data["min_sites"])
    if data.get("has_photo"):
        queryset = queryset.exclude(photo_url="")
    if data.get("has_location"):
        queryset = queryset.filter(latitude__isnull=False, longitude__isnull=False)
    if data.get("sources"):
        queryset = queryset.filter(source_listings__source__key__in=data["sources"]).distinct()
    if data.get("types"):
        queryset = queryset.filter(property_type__in=data["types"])
    if data.get("statuses"):
        from .collab import status_expr

        queryset = queryset.annotate(our_status=status_expr(group)).filter(our_status__in=data["statuses"])
    if data.get("votes") and data["votes"] != "any":
        queryset = _filter_votes(queryset, data["votes"], group)
    if data.get("specials"):
        queryset = queryset.exclude(special_offer="")
    if data.get("price_reduced"):
        queryset = _with_price_range(queryset).filter(peak_price__gt=F("price"))
    if data.get("min_drop_amount"):
        queryset = _with_price_range(queryset).filter(peak_price__gte=F("price") + data["min_drop_amount"])
    if data.get("min_drop_percent"):
        drop_x100 = ExpressionWrapper((F("peak_price") - F("price")) * 100, output_field=IntegerField())
        queryset = (_with_price_range(queryset).alias(drop_x100=drop_x100)
                    .filter(drop_x100__gte=F("peak_price") * data["min_drop_percent"]))
    if data.get("price_raised"):
        queryset = _with_price_range(queryset).filter(low_price__lt=F("price"))
    if data.get("min_price_changes"):
        queryset = queryset.alias(change_count=price_change_count()).filter(change_count__gte=data["min_price_changes"])
    for key, field in FEATURE_FIELDS.items():
        condition = _feature_q(field, data.get(key))
        if condition is not None:
            queryset = queryset.filter(condition)
    if data.get("parking") in PARKING_Q:
        queryset = queryset.filter(PARKING_Q[data["parking"]])
    now = timezone.now()
    if data.get("min_dom") is not None or data.get("max_dom") is not None:
        queryset = queryset.alias(dom=dom_expr())
        if data.get("min_dom") is not None:
            queryset = queryset.filter(dom__gte=data["min_dom"])
        if data.get("max_dom") is not None:
            queryset = queryset.filter(dom__lte=data["max_dom"])
    if data.get("new_within"):
        queryset = queryset.filter(first_seen_at__gte=now - timedelta(days=data["new_within"]))
    if data.get("gone_within"):
        queryset = queryset.filter(is_active=False, last_seen_at__gte=now - timedelta(days=data["gone_within"]))
    if data.get("listed_from") or data.get("listed_to"):
        queryset = queryset.alias(listed_day=first_day_expr())
        if data.get("listed_from"):
            queryset = queryset.filter(listed_day__gte=data["listed_from"])
        if data.get("listed_to"):
            queryset = queryset.filter(listed_day__lte=data["listed_to"])
    return _sort(queryset, data, group)


def _vote_count(group, value):
    # A subquery, not Count() over a join: joins would multiply with the price-history join below.
    votes = (Vote.objects.filter(listing=OuterRef("pk"), group=group, value=value)
             .order_by().values("listing").annotate(n=Count("pk")).values("n"))
    return Coalesce(Subquery(votes, output_field=IntegerField()), 0)


def _filter_votes(queryset, choice, group):
    queryset = queryset.annotate(up_votes=_vote_count(group, Vote.Value.UP), down_votes=_vote_count(group, Vote.Value.DOWN))
    if choice == "everyone_likes":
        return queryset.filter(up_votes=group.members.count(), up_votes__gt=0)
    if choice == "someone_likes":
        return queryset.filter(up_votes__gt=0)
    if choice == "disagree":
        return queryset.filter(up_votes__gt=0, down_votes__gt=0)
    if choice == "unvoted":
        return queryset.filter(up_votes=0, down_votes=0)
    return queryset


def _fields(*names):
    return lambda queryset, group: (queryset, [F(name) for name in names])


def _sort_drop(queryset, group):
    queryset = _with_price_range(queryset)
    return queryset, [Coalesce(F("peak_price") - F("price"), 0)]


def _sort_status(queryset, group):
    from .collab import status_expr

    queryset = queryset.alias(sort_status=status_expr(group))
    stages = Case(*[When(sort_status=value, then=Value(rank)) for rank, value in enumerate(Status.values)],
                  output_field=IntegerField())
    return queryset, [stages]


def _sort_votes(queryset, group):
    up, down = _vote_count(group, Vote.Value.UP), _vote_count(group, Vote.Value.DOWN)
    return queryset, [up - down, up]


SORTS = {
    "price": _fields("price"),
    "effective": _fields("effective_price"),
    "ppsf": lambda queryset, group: (queryset, [ppsf_expr(), F("price")]),
    "beds": _fields("beds", "baths"),
    "baths": _fields("baths", "beds"),
    "sqft": _fields("sqft"),
    "parking": _fields("parking_spaces"),
    "dom": lambda queryset, group: (queryset, [dom_expr()]),
    "drop": _sort_drop,
    "address": _fields("street", "unit"),
    "area": _fields("city", "quadrant", "neighborhood"),
    "zip": _fields("zip_code"),
    "type": _fields("property_type"),
    "sites": lambda queryset, group: (queryset, [active_site_count()]),
    "listed": lambda queryset, group: (queryset, [first_day_expr()]),
    "first_seen": _fields("first_seen_at"),
    "last_seen": _fields("last_seen_at"),
    "status": _sort_status,
    "votes": _sort_votes,
}


def _sort(queryset, data, group):
    """A chosen sort; with none, best match when there are keywords to rank by, else price."""
    sort = data.get("sort") or ""
    if not sort:
        keywords = search_index.parse(data.get("q"))
        if keywords and keywords.include:
            return queryset.order_by(search_index.rank_expr(keywords).asc(), "pk")
        sort = "price"
    descending = sort.startswith("-")
    key = sort.lstrip("-")
    if key == "newest":
        key, descending = "first_seen", True
    if key not in SORTS:
        key, descending = "price", False
    queryset, expressions = SORTS[key](queryset, group)
    order = [e.desc(nulls_last=True) if descending else e.asc(nulls_last=True) for e in expressions]
    return queryset.order_by(*order, "pk")  # pk breaks ties, so pages never repeat or skip a listing
