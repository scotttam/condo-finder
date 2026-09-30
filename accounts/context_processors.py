from django.conf import settings


def dev_accounts(request):
    """In development only: the accounts the header and login page offer one-click logins for."""
    if not settings.DEBUG:
        return {}
    from .models import Profile

    return {"dev_accounts": Profile.objects.select_related("user").filter(user__is_active=True).order_by("display_name")}
