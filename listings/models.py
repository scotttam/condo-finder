from django.db import models
from django.urls import reverse
from django.utils import timezone


class PropertyType(models.TextChoices):
    CONDO = "condo", "Condo"
    TOWNHOME = "townhome", "Townhome"
    HOUSE = "house", "House"
    APARTMENT = "apartment", "Apartment"
    OTHER = "other", "Other"
    UNKNOWN = "unknown", "Unknown"


class Quadrant(models.TextChoices):
    """Portland's address sextants (the four quadrants plus North and South Portland)."""

    NW = "NW", "NW"
    NE = "NE", "NE"
    SE = "SE", "SE"
    SW = "SW", "SW"
    N = "N", "N"
    S = "S", "S"


class Status(models.TextChoices):
    NEW = "new", "New"
    INTERESTED = "interested", "Interested"
    TOURED = "toured", "Toured"
    APPLIED = "applied", "Applied"
    REJECTED = "rejected", "Rejected"


class Source(models.Model):
    key = models.SlugField(unique=True)
    name = models.CharField(max_length=100)
    platform = models.CharField(max_length=30)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_count = models.IntegerField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    last_error_at = models.DateTimeField(null=True, blank=True)
    consecutive_failures = models.IntegerField(default=0)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class SourceRun(models.Model):
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="runs")
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    ok = models.BooleanField(default=False)
    count = models.IntegerField(default=0)
    new_count = models.IntegerField(default=0)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]


class Listing(models.Model):
    address_key = models.CharField(max_length=255, unique=True)
    address = models.CharField(max_length=255)
    street = models.CharField(max_length=255)
    unit = models.CharField(max_length=50, blank=True)
    city = models.CharField(max_length=100)
    zip_code = models.CharField(max_length=10, blank=True)
    neighborhood = models.CharField(max_length=100, blank=True)
    quadrant = models.CharField(max_length=2, choices=Quadrant.choices, blank=True, db_index=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    geocoded_at = models.DateTimeField(null=True, blank=True)

    title = models.CharField(max_length=300, blank=True)
    description = models.TextField(blank=True)
    price = models.IntegerField(null=True, blank=True)
    beds = models.PositiveSmallIntegerField(null=True, blank=True)
    baths = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)
    sqft = models.IntegerField(null=True, blank=True)
    parking_spaces = models.IntegerField(null=True, blank=True)
    has_parking = models.BooleanField(null=True, blank=True)  # known even when the space count isn't
    has_washer_dryer = models.BooleanField(null=True, blank=True)
    has_ac = models.BooleanField(null=True, blank=True)
    has_outdoor_space = models.BooleanField(null=True, blank=True)
    property_type = models.CharField(
        max_length=20, choices=PropertyType.choices, default=PropertyType.UNKNOWN
    )
    available = models.CharField(max_length=100, blank=True)
    photo_url = models.URLField(max_length=500, blank=True)
    overrides = models.JSONField(
        default=dict,
        blank=True,
        help_text='Manual corrections that survive re-scrapes, e.g. {"parking_spaces": 2, "has_ac": true}',
    )

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    notes = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)
    listed_at = models.DateField(null=True, blank=True, help_text="When the current rental listing started, per the listing site")
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-first_seen_at"]

    def __str__(self):
        return self.address

    def get_absolute_url(self):
        return reverse("listing_detail", args=[self.pk])

    @property
    def location_label(self):
        return " · ".join(part for part in (self.city, self.quadrant, self.neighborhood) if part)

    @property
    def price_per_sqft(self):
        if self.price and self.sqft:
            return round(self.price / self.sqft, 2)
        return None

    @property
    def price_drop(self):
        """How far the price has fallen from its peak during the current rental listing."""
        if not self.price:
            return 0
        prices = [
            change.price
            for change in self.price_changes.all()
            if self.listed_at is None or timezone.localdate(change.seen_at) >= self.listed_at
        ]
        return max(max(prices, default=self.price) - self.price, 0)

    @property
    def price_drop_percent(self):
        return round(self.price_drop * 100 / (self.price + self.price_drop)) if self.price_drop else 0

    @property
    def price_history_rows(self):
        """Price history oldest first, each with its change from the previous entry. A new
        'Listed for rent' starts a new rental period, so it isn't shown as a change."""
        rows, previous = [], None
        for change in self.price_changes.all():
            label = ""
            if previous and change.price != previous and change.event != "Listed for rent":
                delta = change.price - previous
                sign = "−" if delta < 0 else "+"
                label = f"{sign}${abs(delta):,} ({sign}{abs(round(delta * 100 / previous))}%)"
            rows.append({"change": change, "label": label, "is_drop": label.startswith("−")})
            previous = change.price
        return rows

    @property
    def days_on_market(self):
        """From the site's listed date when known (often before we first saw it), else first seen."""
        start = timezone.localdate(self.first_seen_at)
        if self.listed_at and self.listed_at < start:
            start = self.listed_at
        end = timezone.localdate() if self.is_active else timezone.localdate(self.last_seen_at)
        return (end - start).days


class SourceListing(models.Model):
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="source_listings")
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="source_listings")
    external_id = models.CharField(max_length=200)
    url = models.URLField(max_length=500)
    is_active = models.BooleanField(default=True)
    missed_runs = models.IntegerField(default=0)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    # Parser version that last fetched this listing's detail page; a scraper re-fetches details
    # (within its per-run budget) when its details_version is higher.
    details_version = models.PositiveSmallIntegerField(default=0)
    last_price = models.IntegerField(null=True, blank=True)  # this site's latest price for the listing

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source", "external_id"], name="unique_source_external_id")
        ]


class PriceChange(models.Model):
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="price_changes")
    price = models.IntegerField()
    seen_at = models.DateTimeField(default=timezone.now)
    event = models.CharField(max_length=40, blank=True)  # e.g. "Listed for rent", "Price change", "First seen"
    source = models.CharField(max_length=100, blank=True)  # where the entry came from; blank = entered by hand

    class Meta:
        ordering = ["seen_at"]
