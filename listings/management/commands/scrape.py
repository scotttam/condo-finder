from django.core.management.base import BaseCommand

from listings.runner import run_all


class Command(BaseCommand):
    help = "Scrape listing sources now."

    def add_arguments(self, parser):
        parser.add_argument("--source", action="append", dest="sources", help="Source key (repeatable). Default: all.")
        parser.add_argument("--no-geocode", action="store_true", help="Skip geocoding new listings.")

    def handle(self, *args, **options):
        for run in run_all(keys=options["sources"], geocode=not options["no_geocode"]):
            status = "ok" if run.ok else f"FAILED ({run.error})"
            self.stdout.write(f"{run.source.key}: {status} — {run.count} listings, {run.new_count} new")
