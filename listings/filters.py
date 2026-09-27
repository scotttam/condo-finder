from django.db.models import ExpressionWrapper, F, FloatField, Q
from django.db.models.functions import Cast

FEATURE_FIELDS = {"wd": "has_washer_dryer", "ac": "has_ac", "outdoor": "has_outdoor_space"}


def apply_filters(queryset, data):
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
    if data.get("max_price") is not None:
        queryset = queryset.filter(price__lte=data["max_price"])
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
        queryset = queryset.filter(status__in=data["statuses"])
    for key, field in FEATURE_FIELDS.items():
        if data.get(key) == "yes":
            queryset = queryset.filter(**{field: True})
        elif data.get(key) == "yes_or_unknown":
            queryset = queryset.exclude(**{field: False})
    return _sort(queryset, data.get("sort") or "price")


def _sort(queryset, sort):
    if sort == "-price":
        return queryset.order_by(F("price").desc(nulls_last=True))
    if sort == "newest":
        return queryset.order_by("-first_seen_at")
    if sort == "ppsf":
        per_sqft = ExpressionWrapper(Cast("price", FloatField()) / F("sqft"), output_field=FloatField())
        return queryset.annotate(ppsf=per_sqft).order_by(F("ppsf").asc(nulls_last=True), "price")
    return queryset.order_by(F("price").asc(nulls_last=True))
