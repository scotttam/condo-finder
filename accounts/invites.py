from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from .models import Invite


def create_invite(kind, by, group=None):
    return Invite.objects.create(kind=kind, created_by=by, group=group if kind == Invite.Kind.JOIN else None)


def invite_url(request, invite):
    """The full link to send. PUBLIC_URL wins, because the request may have come in on a local address."""
    path = reverse("invite", args=[invite.token])
    return f"{settings.PUBLIC_URL}{path}" if settings.PUBLIC_URL else request.build_absolute_uri(path)


def usable_invites():
    return Invite.objects.filter(used_at__isnull=True, expires_at__gt=timezone.now())


def claim(invite, user):
    """Marks the invite used by `user`. One conditional UPDATE, so it succeeds once even if two people
    submit at the same moment. False when it was used or expired in the meantime."""
    now = timezone.now()
    return bool(usable_invites().filter(pk=invite.pk).update(used_at=now, used_by=user))
