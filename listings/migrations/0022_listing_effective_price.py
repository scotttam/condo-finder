from django.db import migrations, models


def fill_effective_price(apps, schema_editor):
    from listings.specials import effective_rent

    Listing = apps.get_model("listings", "Listing")
    for listing in Listing.objects.only("pk", "price", "special_offer").iterator():
        value = (effective_rent(listing.price, listing.special_offer) if listing.special_offer else None) or listing.price
        Listing.objects.filter(pk=listing.pk).update(effective_price=value)


class Migration(migrations.Migration):
    dependencies = [("listings", "0021_trendreport_discoveries")]

    operations = [
        migrations.AddField(model_name="listing", name="effective_price", field=models.IntegerField(blank=True, null=True)),
        migrations.RunPython(fill_effective_price, migrations.RunPython.noop),
    ]
