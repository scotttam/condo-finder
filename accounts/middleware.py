from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.contrib.auth.middleware import LoginRequiredMiddleware
from django.http import HttpResponse
from django.shortcuts import resolve_url

from .groups import profile_for


class LoginRequired(LoginRequiredMiddleware):
    """Every page needs a login except views marked @login_not_required. An HTMX request (a poll or a
    swap) is told to load the login page, instead of having the login form swapped into part of a page."""

    def handle_no_permission(self, request, view_func):
        if not request.headers.get("HX-Request"):
            return super().handle_no_permission(request, view_func)
        current = urlsplit(request.headers.get("HX-Current-URL", "")).path or "/"
        response = HttpResponse("")
        response["HX-Redirect"] = f"{resolve_url(settings.LOGIN_URL)}?{urlencode({'next': current})}"
        return response


class CurrentGroup:
    """Sets request.profile and request.group for the logged-in person (None when logged out)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        profile = profile_for(request.user) if request.user.is_authenticated else None
        request.profile = profile
        request.group = profile.group if profile else None
        return self.get_response(request)
