from functools import wraps

from django.http import HttpResponseForbidden


def staff_required(view):
    """Shared scraped data (price history, refreshes, sources) is changed only by the site admin."""

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_staff:
            return HttpResponseForbidden("Only the site admin can do that.")
        return view(request, *args, **kwargs)

    return wrapped
