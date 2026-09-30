from django.db import migrations


def forwards(apps, schema_editor):
    """Reports and priorities from before groups existed are the owners'."""
    TrendReport = apps.get_model("listings", "TrendReport")
    SearchPriorities = apps.get_model("listings", "SearchPriorities")
    SearchGroup = apps.get_model("accounts", "SearchGroup")
    group = SearchGroup.objects.order_by("pk").first()
    if group is None:
        return
    TrendReport.objects.filter(group__isnull=True).update(group=group)
    row = SearchPriorities.objects.filter(group__isnull=True).order_by("pk").first()
    if row and not SearchPriorities.objects.filter(group=group).exists():
        row.group = group
        row.save(update_fields=["group"])


class Migration(migrations.Migration):
    dependencies = [("listings", "0016_trends_per_group"), ("accounts", "0002_owners_group")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
