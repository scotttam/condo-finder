import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class SearchGroup(models.Model):
    """A household searching together. It owns the shared status, comments, votes, default filters,
    priorities, Trends reports and Feed activity. Every user belongs to exactly one."""

    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(default=timezone.now)
    # The filter bar a visit starts from ("Save as our defaults"). Empty means the app defaults.
    default_filters = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return self.name


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    group = models.ForeignKey(SearchGroup, on_delete=models.PROTECT, related_name="members")
    display_name = models.CharField(max_length=60)
    joined_at = models.DateTimeField(default=timezone.now)
    feed_seen_at = models.DateTimeField(null=True, blank=True)  # the Feed's unread line, synced across devices

    class Meta:
        ordering = ["joined_at", "pk"]

    def __str__(self):
        return self.display_name


def new_token():
    return secrets.token_urlsafe(24)


def invite_expiry():
    return timezone.now() + timedelta(days=settings.INVITE_DAYS)


class Invite(models.Model):
    """A copy-paste signup link: into a new household of its own (made by the site admin) or into the
    group of the member who made it. Single use; expires."""

    class Kind(models.TextChoices):
        NEW_GROUP = "new_group", "New household"
        JOIN = "join", "Join a group"

    token = models.CharField(max_length=64, unique=True, default=new_token)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    group = models.ForeignKey(SearchGroup, on_delete=models.CASCADE, null=True, blank=True, related_name="invites")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(default=invite_expiry)
    used_at = models.DateTimeField(null=True, blank=True)
    used_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    def __str__(self):
        return f"{self.get_kind_display()} invite ({'used' if self.used_at else 'open'})"

    @property
    def is_usable(self):
        return self.used_at is None and self.expires_at > timezone.now()


def display_name(user):
    """How a person is shown on comments, votes and the Feed."""
    if user is None:
        return ""
    profile = getattr(user, "profile", None)  # RelatedObjectDoesNotExist is an AttributeError
    return profile.display_name if profile else user.get_username()
