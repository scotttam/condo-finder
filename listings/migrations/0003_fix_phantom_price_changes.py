from collections import defaultdict

from django.db import migrations, models
from django.db.models import Count

# Fields copied onto a split-off listing; the next scrape refreshes them and records its price.
COPIED_FIELDS = [
    "address", "street", "unit", "city", "zip_code", "neighborhood", "quadrant", "latitude", "longitude",
    "geocoded_at", "title", "description", "beds", "baths", "sqft", "property_type", "available",
    "photo_url", "first_seen_at", "last_seen_at",
]


def split_same_source_units(apps, schema_editor):
    """Undo an old merge bug: listings from the same site at one address (building units without
    unit numbers, or hidden addresses) were merged into one listing, so their different prices showed
    up as price changes. Move each extra unit to its own listing and clear the bogus history."""
    Listing = apps.get_model("listings", "Listing")
    SourceListing = apps.get_model("listings", "SourceListing")
    PriceChange = apps.get_model("listings", "PriceChange")

    groups = defaultdict(list)
    for source_listing in SourceListing.objects.select_related("listing", "source").order_by("first_seen_at", "pk"):
        groups[(source_listing.listing_id, source_listing.source_id)].append(source_listing)

    affected = set()
    for members in groups.values():
        listing = members[0].listing
        hidden_address = not listing.street[:1].isdigit()
        if len(members) < 2 and not hidden_address:
            continue
        for source_listing in members if hidden_address else members[1:]:
            key = f"{listing.address_key}|{source_listing.source.key}:{source_listing.external_id}"
            unit = Listing.objects.filter(address_key=key).first() or Listing.objects.create(
                address_key=key, price=None, **{name: getattr(listing, name) for name in COPIED_FIELDS}
            )
            source_listing.listing = unit
            source_listing.save(update_fields=["listing"])
        affected.add(listing.pk)

    for listing in Listing.objects.filter(pk__in=affected):
        PriceChange.objects.filter(listing=listing).delete()
        listing.price = None
        listing.is_active = SourceListing.objects.filter(listing=listing, is_active=True).exists()
        listing.save(update_fields=["price", "is_active"])


def clear_cross_site_flip_flops(apps, schema_editor):
    """On listings found on more than one site, each site's scrape used to overwrite the price, so
    sites disagreeing looked like price changes. Remove those automatic entries (unlabeled, dated
    once we were tracking the listing); hand-entered history from before then is kept."""
    Listing = apps.get_model("listings", "Listing")
    SourceListing = apps.get_model("listings", "SourceListing")
    PriceChange = apps.get_model("listings", "PriceChange")
    multi_site = (
        SourceListing.objects.values("listing").annotate(sites=Count("source", distinct=True)).filter(sites__gt=1)
    )
    for listing in Listing.objects.filter(pk__in=[row["listing"] for row in multi_site]):
        PriceChange.objects.filter(listing=listing, event="", seen_at__gte=listing.first_seen_at).delete()


def label_old_observations(apps, schema_editor):
    """Entries recorded by scrapes before events were tracked have no label (so they'd read as
    entered by hand). Those dated once we were tracking the listing are observations: label them
    with the listing's site, or drop them when they only repeat the previous entry's price."""
    Listing = apps.get_model("listings", "Listing")
    SourceListing = apps.get_model("listings", "SourceListing")
    PriceChange = apps.get_model("listings", "PriceChange")
    for listing in Listing.objects.filter(price_changes__event="").distinct():
        site_names = set(SourceListing.objects.filter(listing=listing).values_list("source__name", flat=True))
        site = site_names.pop() if len(site_names) == 1 else ""
        previous = None
        for change in PriceChange.objects.filter(listing=listing).order_by("seen_at", "pk"):
            if change.event == "" and change.seen_at >= listing.first_seen_at:
                if previous is not None and change.price == previous:
                    change.delete()
                    continue
                change.event = "First seen" if previous is None else "Price change"
                change.source = site
                change.save(update_fields=["event", "source"])
            previous = change.price


class Migration(migrations.Migration):
    dependencies = [
        ("listings", "0002_price_history_and_details_version"),
    ]

    operations = [
        migrations.AddField(
            model_name="sourcelisting",
            name="last_price",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.RunPython(split_same_source_units, migrations.RunPython.noop),
        migrations.RunPython(clear_cross_site_flip_flops, migrations.RunPython.noop),
        migrations.RunPython(label_old_observations, migrations.RunPython.noop),
    ]
