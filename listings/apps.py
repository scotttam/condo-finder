import os

from django.apps import AppConfig


class ListingsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "listings"

    def ready(self):
        # Only the long-running gunicorn process (launchd sets this) runs scheduled scrapes.
        if os.environ.get("CONDOFINDER_SCHEDULER") == "1":
            from .scheduler import start

            start()
