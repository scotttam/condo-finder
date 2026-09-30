from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.views import PasswordChangeView
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from .forms import SignupForm
from .groups import move_to_group, new_group
from .invites import claim, create_invite, invite_url, usable_invites
from .models import Invite, Profile


def group_settings(request):
    group = request.group
    return render(request, "accounts/group.html", {
        "group": group,
        "members": group.members.select_related("user"),
        "can_leave": group.members.count() > 1,
        "invites": [(invite, invite_url(request, invite)) for invite in _open_invites(request)],
        "invite_days": settings.INVITE_DAYS,
    })


@require_POST
def rename_group(request):
    name = request.POST.get("name", "").strip()[:100]
    if name:
        request.group.name = name
        request.group.save(update_fields=["name"])
        messages.success(request, "Group renamed.")
    return redirect("group_settings")


def _to_solo_group(profile):
    """Leaving or removal: a fresh, empty group of their own. Their comments stay behind; votes go."""
    move_to_group(profile.user, new_group(f"{profile.display_name}'s search"))


@require_POST
def remove_member(request, user_id):
    profile = get_object_or_404(Profile, user_id=user_id, group=request.group)
    if profile.user_id == request.user.pk:
        return HttpResponseBadRequest("Use Leave group to leave.")
    _to_solo_group(profile)
    closed = usable_invites().filter(group=request.group).delete()[0]  # they may have copied a link
    note = f" Its {closed} open invite link{'s were' if closed != 1 else ' was'} revoked; make new ones as needed." if closed else ""
    messages.success(request, f"{profile.display_name} is no longer in {request.group.name}.{note}")
    return redirect("group_settings")


@require_POST
def leave_group(request):
    group = request.group
    if group.members.count() <= 1:
        messages.info(request, "You are the only member, so there is no group to leave.")
    else:
        _to_solo_group(request.profile)
        messages.success(request, f"You left {group.name}. This is your own search now.")
    return redirect("group_settings")


class InviteUsed(Exception):
    pass


@login_not_required
def invite(request, token):
    """An invite link: sign up (logged out), or join the group (logged in, join links only)."""
    invite = Invite.objects.select_related("group").filter(token=token).first()
    if invite is None or not invite.is_usable:
        return render(request, "accounts/invite_gone.html", status=410)
    if request.user.is_authenticated:
        return _invite_existing_user(request, invite)
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            user = _sign_up(invite, form.cleaned_data)
        except InviteUsed:
            return render(request, "accounts/invite_gone.html", status=410)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, f"Welcome, {user.profile.display_name}.")
        return redirect("listing_list")
    return render(request, "accounts/signup.html", {"form": form, "invite": invite})


def _sign_up(invite, data):
    with transaction.atomic():
        user = get_user_model().objects.create_user(username=data["email"], email=data["email"], password=data["password1"])
        if not claim(invite, user):
            raise InviteUsed  # rolls back the new account
        group = invite.group or new_group(f"{data['display_name']}'s search")
        Profile.objects.create(user=user, group=group, display_name=data["display_name"])
    return user


def _invite_existing_user(request, invite):
    if invite.kind == Invite.Kind.NEW_GROUP:
        return render(request, "accounts/invite_existing.html", {"invite": invite, "reason": "new_group"})
    if invite.group_id == request.group.pk:
        messages.info(request, f"You are already in {invite.group.name}.")
        return redirect("group_settings")
    if request.method == "POST":
        if not claim(invite, request.user):
            return render(request, "accounts/invite_gone.html", status=410)
        move_to_group(request.user, invite.group)
        messages.success(request, f"You joined {invite.group.name}.")
        return redirect("group_settings")
    return render(request, "accounts/invite_existing.html", {"invite": invite, "reason": "join"})


def _open_invites(request):
    """The invites this person may see and revoke: their group's join links, plus (staff) the
    new-household links they made."""
    mine = Q(group=request.group)
    if request.user.is_staff:
        mine |= Q(kind=Invite.Kind.NEW_GROUP, created_by=request.user)
    return usable_invites().filter(mine).order_by("-created_at")


@require_POST
def create_invite_view(request):
    kind = request.POST.get("kind")
    if kind not in Invite.Kind.values:
        return HttpResponseBadRequest("invalid invite")
    if kind == Invite.Kind.NEW_GROUP and not request.user.is_staff:
        return HttpResponseForbidden("Only the site admin can invite a new household.")
    create_invite(kind, request.user, request.group)
    messages.success(request, "Invite link created. Copy it below and send it.")
    return redirect("group_settings")


@require_POST
def revoke_invite(request, pk):
    get_object_or_404(_open_invites(request), pk=pk).delete()
    messages.success(request, "Invite link revoked.")
    return redirect("group_settings")


class PasswordChange(PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("group_settings")

    def form_valid(self, form):
        messages.success(self.request, "Password changed.")
        return super().form_valid(form)
