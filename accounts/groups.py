"""Search groups: which one a person is in, and moving people between them."""

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Profile, SearchGroup


def owners_group():
    """The original group, the site owners', made by accounts' second migration."""
    return SearchGroup.objects.order_by("pk").first() or SearchGroup.objects.create(name="Our search")


def new_group(name):
    return SearchGroup.objects.create(name=name[:100])


def profile_for(user):
    """The person's profile. An account made outside the app (createsuperuser, admin) gets a solo group."""
    try:
        return Profile.objects.select_related("group").get(user=user)
    except Profile.DoesNotExist:
        pass
    name = user.first_name or (user.email or user.get_username()).split("@")[0]
    try:
        with transaction.atomic():
            return Profile.objects.create(user=user, group=new_group(f"{name}'s search"), display_name=name[:60])
    except IntegrityError:  # a parallel request made it first
        return Profile.objects.select_related("group").get(user=user)


def move_to_group(user, group):
    """Puts the person in `group` (a no-op if they're already in it)."""
    profile = profile_for(user)
    if profile.group_id == group.pk:
        return profile
    profile.group = group
    profile.joined_at = timezone.now()
    profile.save(update_fields=["group", "joined_at"])
    return profile
