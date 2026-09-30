from django.contrib import messages
from django.contrib.auth.views import PasswordChangeView
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from .groups import move_to_group, new_group
from .models import Profile


def group_settings(request):
    group = request.group
    return render(request, "accounts/group.html", {
        "group": group,
        "members": group.members.select_related("user"),
        "can_leave": group.members.count() > 1,
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
    messages.success(request, f"{profile.display_name} is no longer in {request.group.name}.")
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


class PasswordChange(PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("group_settings")

    def form_valid(self, form):
        messages.success(self.request, "Password changed.")
        return super().form_valid(form)
