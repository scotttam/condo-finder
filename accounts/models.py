from django.conf import settings
from django.db import models
from django.utils import timezone


class SearchGroup(models.Model):
    """A household searching together. It owns the shared status, comments, votes, default filters,
    priorities, Trends reports and Feed activity. Every user belongs to exactly one."""

    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return self.name


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    group = models.ForeignKey(SearchGroup, on_delete=models.PROTECT, related_name="members")
    display_name = models.CharField(max_length=60)
    joined_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["joined_at", "pk"]

    def __str__(self):
        return self.display_name


def display_name(user):
    """How a person is shown on comments, votes and the Feed."""
    if user is None:
        return ""
    profile = getattr(user, "profile", None)  # RelatedObjectDoesNotExist is an AttributeError
    return profile.display_name if profile else user.get_username()
