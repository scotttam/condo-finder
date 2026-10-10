from django.db.models import Count, ExpressionWrapper, F, FloatField, IntegerField, Max, OuterRef, Q, Subquery
from django.db.models.functions import Cast, Coalesce

from .forms import PRICE_SLIDER_MAX
from .models import Vote

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
    if not data.get("show_inactive"):
        queryset = queryset.filter(is_active=True)
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
        # Peak price during the current rental listing (all history when the listed date is unknown).
        in_current_listing = Q(listed_at__isnull=True) | Q(price_changes__seen_at__date__gte=F("listed_at"))
        queryset = queryset.annotate(peak_price=Max("price_changes__price", filter=in_current_listing)).filter(
            peak_price__gt=F("price")
        )
    for key, field in FEATURE_FIELDS.items():
        condition = _feature_q(field, data.get(key))
        if condition is not None:
            queryset = queryset.filter(condition)
    if data.get("parking") in PARKING_Q:
        queryset = queryset.filter(PARKING_Q[data["parking"]])
    return _sort(queryset, data.get("sort") or "price")


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


def _sort(queryset, sort):
    if sort == "-price":
        return queryset.order_by(F("price").desc(nulls_last=True))
    if sort == "newest":
        return queryset.order_by("-first_seen_at")
    if sort == "ppsf":
        return queryset.annotate(ppsf=ppsf_expr()).order_by(F("ppsf").asc(nulls_last=True), "price")
    return queryset.order_by(F("price").asc(nulls_last=True))
