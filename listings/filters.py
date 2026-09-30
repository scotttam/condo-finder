from django.db.models import Count, ExpressionWrapper, F, FloatField, IntegerField, Max, OuterRef, Q, Subquery
from django.db.models.functions import Cast, Coalesce

from .forms import PRICE_SLIDER_MAX
from .models import Vote

FEATURE_FIELDS = {"wd": "has_washer_dryer", "ac": "has_ac", "outdoor": "has_outdoor_space"}


def apply_filters(queryset, data, group):
    if not data.get("show_inactive"):
        queryset = queryset.filter(is_active=True)
    if data.get("min_beds") is not None:
        queryset = queryset.filter(beds__gte=data["min_beds"])
    if data.get("min_baths") is not None:
        queryset = queryset.filter(baths__gte=data["min_baths"])
    if data.get("min_parking") is not None:
        parking = Q(parking_spaces__gte=data["min_parking"])
        if data.get("parking_unknown"):
            parking |= Q(parking_spaces__isnull=True)
        queryset = queryset.filter(parking)
    if data.get("min_price") is not None:
        queryset = queryset.filter(price__gte=data["min_price"])
    if data.get("max_price") is not None and data["max_price"] < PRICE_SLIDER_MAX:  # slider top = no max
        queryset = queryset.filter(price__lte=data["max_price"])
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
    if data.get("furnished") == "hide":
        queryset = queryset.exclude(is_furnished=True)
    elif data.get("furnished") == "only":
        queryset = queryset.filter(is_furnished=True)
    if data.get("specials"):
        queryset = queryset.exclude(special_offer="")
    if data.get("price_reduced"):
        # Peak price during the current rental listing (all history when the listed date is unknown).
        in_current_listing = Q(listed_at__isnull=True) | Q(price_changes__seen_at__date__gte=F("listed_at"))
        queryset = queryset.annotate(peak_price=Max("price_changes__price", filter=in_current_listing)).filter(
            peak_price__gt=F("price")
        )
    for key, field in FEATURE_FIELDS.items():
        if data.get(key) == "yes":
            queryset = queryset.filter(**{field: True})
        elif data.get(key) == "yes_or_unknown":
            queryset = queryset.exclude(**{field: False})
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
        per_sqft = ExpressionWrapper(Cast("price", FloatField()) / F("sqft"), output_field=FloatField())
        return queryset.annotate(ppsf=per_sqft).order_by(F("ppsf").asc(nulls_last=True), "price")
    return queryset.order_by(F("price").asc(nulls_last=True))
