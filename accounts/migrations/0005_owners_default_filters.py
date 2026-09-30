from django.conf import settings
from django.db import migrations


def forwards(apps, schema_editor):
    """The filters that were hard-coded before groups existed become the owners' saved defaults, so a
    later change to the app defaults doesn't move theirs."""
    SearchGroup = apps.get_model("accounts", "SearchGroup")
    group = SearchGroup.objects.order_by("pk").first()
    if group is None or group.default_filters:
        return
    group.default_filters = {
        "min_beds": "2", "min_baths": "2", "min_parking": "2", "parking_unknown": "on",
        "min_price": str(settings.DEFAULT_MIN_PRICE), "max_price": str(settings.DEFAULT_MAX_PRICE),
        "types": ["condo", "townhome", "house", "other", "unknown"],
        "statuses": ["new", "interested", "toured", "applied"],
        "wd": "yes_or_unknown", "ac": "yes_or_unknown", "outdoor": "yes_or_unknown", "furnished": "any",
        "votes": "any", "sort": "price",
    }
    group.save(update_fields=["default_filters"])


class Migration(migrations.Migration):
    dependencies = [("accounts", "0004_searchgroup_default_filters")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
