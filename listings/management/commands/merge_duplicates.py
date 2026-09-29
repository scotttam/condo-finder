from django.core.management.base import BaseCommand

from listings.merge import merge_unit_duplicates


class Command(BaseCommand):
    help = "Merge listings that are one home listed with and without its unit number."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="List the pairs without merging them.")

    def handle(self, *args, **options):
        merged = merge_unit_duplicates(dry_run=options["dry_run"])
        verb = "Would merge" if options["dry_run"] else "Merged"
        for keep, drop, address in merged:
            self.stdout.write(f"{verb} #{drop} into #{keep}: {address}")
        self.stdout.write(f"{verb} {len(merged)} duplicate listings.")
