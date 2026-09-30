from django.db import migrations


def forwards(apps, schema_editor):
    """Statuses set before accounts existed belong to the owners' group (the oldest group)."""
    Listing = apps.get_model("listings", "Listing")
    ListingState = apps.get_model("listings", "ListingState")
    SearchGroup = apps.get_model("accounts", "SearchGroup")
    group = SearchGroup.objects.order_by("pk").first() or SearchGroup.objects.create(name="Our search")
    ListingState.objects.bulk_create([
        ListingState(group=group, listing=listing, status=listing.status, status_at=listing.updated_at)
        for listing in Listing.objects.exclude(status="new")
    ])


def backwards(apps, schema_editor):
    Listing = apps.get_model("listings", "Listing")
    ListingState = apps.get_model("listings", "ListingState")
    SearchGroup = apps.get_model("accounts", "SearchGroup")
    group = SearchGroup.objects.order_by("pk").first()
    for state in ListingState.objects.filter(group=group):
        Listing.objects.filter(pk=state.listing_id).update(status=state.status)


class Migration(migrations.Migration):
    dependencies = [("listings", "0008_listingstate"), ("accounts", "0002_owners_group")]
    operations = [migrations.RunPython(forwards, backwards)]
