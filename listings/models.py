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
    def days_on_market(self):
        end = timezone.now() if self.is_active else self.last_seen_at
        return (end - self.first_seen_at).days


class SourceListing(models.Model):
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="source_listings")
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="source_listings")
    external_id = models.CharField(max_length=200)
    url = models.URLField(max_length=500)
    is_active = models.BooleanField(default=True)
    missed_runs = models.IntegerField(default=0)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source", "external_id"], name="unique_source_external_id")
        ]


class PriceChange(models.Model):
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="price_changes")
    price = models.IntegerField()
    seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["seen_at"]
