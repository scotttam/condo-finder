from django.db import migrations


def delete_group_activity(apps, schema_editor):
    """Rolling back past group accounts: a group's own Feed items (statuses, comments, votes) would
    otherwise lose their group and show to everyone, and the old Feed can't label their kinds."""
    FeedEvent = apps.get_model("listings", "FeedEvent")
    FeedEvent.objects.filter(group__isnull=False).delete()
    FeedEvent.objects.filter(kind__in=["status", "comment", "vote"]).delete()


class Migration(migrations.Migration):
    dependencies = [("listings", "0017_trends_to_owners_group")]
    operations = [migrations.RunPython(migrations.RunPython.noop, delete_group_activity)]
