from django.core.management.base import BaseCommand

from listings.ingest import reextract_all


class Command(BaseCommand):
    help = "Re-run parking/laundry/AC/outdoor/type detection on stored listings after the rules change."

    def handle(self, *args, **options):
        self.stdout.write(f"Updated {reextract_all()} listings")
