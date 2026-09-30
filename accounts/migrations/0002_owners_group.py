from django.db import migrations


def create_owners_group(apps, schema_editor):
    """The owners' group comes first, so it is always the oldest group. Existing statuses, notes,
    priorities and Trends reports move into it in later migrations."""
    SearchGroup = apps.get_model("accounts", "SearchGroup")
    if not SearchGroup.objects.exists():
        SearchGroup.objects.create(name="Our search")


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]
    operations = [migrations.RunPython(create_owners_group, migrations.RunPython.noop)]
