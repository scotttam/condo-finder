from django.db import migrations


def forwards(apps, schema_editor):
    """Each listing's notes become the first comment in the owners' group, by the site admin if their
    account exists yet (create_owner claims author-less comments otherwise), dated at the listing's
    last update."""
    Listing = apps.get_model("listings", "Listing")
    Comment = apps.get_model("listings", "Comment")
    SearchGroup = apps.get_model("accounts", "SearchGroup")
    Profile = apps.get_model("accounts", "Profile")
    noted = [listing for listing in Listing.objects.exclude(notes="") if listing.notes.strip()]
    if not noted:
        return
    group = SearchGroup.objects.order_by("pk").first() or SearchGroup.objects.create(name="Our search")
    owner = Profile.objects.filter(group=group, user__is_staff=True).order_by("joined_at", "pk").first()
    Comment.objects.bulk_create([
        Comment(listing=listing, group=group, author_id=owner.user_id if owner else None,
                author_name=owner.display_name if owner else "", body=listing.notes.strip(), created_at=listing.updated_at)
        for listing in noted
    ])


def backwards(apps, schema_editor):
    Listing = apps.get_model("listings", "Listing")
    Comment = apps.get_model("listings", "Comment")
    SearchGroup = apps.get_model("accounts", "SearchGroup")
    group = SearchGroup.objects.order_by("pk").first()
    bodies = {}
    for comment in Comment.objects.filter(group=group).order_by("created_at", "pk"):
        bodies.setdefault(comment.listing_id, []).append(comment.body)
    for listing_id, texts in bodies.items():
        Listing.objects.filter(pk=listing_id).update(notes="\n\n".join(texts))


class Migration(migrations.Migration):
    dependencies = [("listings", "0012_comment"), ("accounts", "0003_profile_feed_seen_at")]
    operations = [migrations.RunPython(forwards, backwards)]
