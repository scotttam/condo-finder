import logging
import threading

from django.db import close_old_connections
from django.utils import timezone

from .geocode import geocode_pending
from .ingest import ingest, reextract_all
from .merge import merge_unit_duplicates
from .models import Source, SourceListing, SourceRun
from .scrapers.base import Scraper
from .scrapers.registry import SOURCES, build_scraper

log = logging.getLogger(__name__)

_run_lock = threading.Lock()


class EmptyScrape(Exception):
    """0 results counts as a failure: a blocked or changed site must not mark everything off-market."""


def _source_for(config):
    # platform stays code-driven; name is set once and then left alone so admin edits to it stick.
    source, _ = Source.objects.update_or_create(
        key=config["key"],
        defaults={"platform": config["platform"]},
        create_defaults={"name": config["name"], "platform": config["platform"]},
    )
    return source


def sync_sources():
    for config in SOURCES:
        _source_for(config)


def run_source(config, fetcher=None):
    source = _source_for(config)
    run = SourceRun.objects.create(source=source)
    try:
        scraper = build_scraper(config, fetcher=fetcher)
        # Listings whose details were fetched by the current parser; the rest get (re-)fetched.
        scraper.known_ids = set(
            SourceListing.objects.filter(source=source, details_version__gte=scraper.details_version)
            .values_list("external_id", flat=True)
        )
        if config.get("skip_details_if_on"):
            # Listings this site shares with another source get their details from that source.
            scraper.skip_detail_ids = set(
                SourceListing.objects.filter(
                    source=source, listing__source_listings__source__key=config["skip_details_if_on"]
                ).values_list("external_id", flat=True)
            )
        items = scraper.scrape()
        if not items:
            raise EmptyScrape("scraper returned 0 listings")
        # Sources that can check a listing page directly confirm it before it's called gone.
        overrides_check = type(scraper).check_listing is not Scraper.check_listing
        result = ingest(source, items, verify=scraper.check_listing if overrides_check else None)
    except Exception as exc:  # one broken source must never stop the others
        log.exception("Source %s failed", source.key)
        _record_failure(source, run, exc)
        return run
    now = timezone.now()
    run.ok = True
    run.count = len(items)
    run.new_count = len(result.new_listings)
    run.finished_at = now
    run.save()
    source.consecutive_failures = 0
    source.last_success_at = now
    source.last_count = len(items)
    source.save()
    log.info("Source %s: %d listings (%d stored, %d new)", source.key, len(items), result.seen, run.new_count)
    return run


def _record_failure(source, run, exc):
    now = timezone.now()
    run.error = f"{type(exc).__name__}: {exc}"[:2000]
    run.finished_at = now
    run.save()
    source.consecutive_failures += 1
    source.last_error = run.error
    source.last_error_at = now
    source.save()


def is_running():
    return _run_lock.locked()


def run_all(keys=None, geocode=True):
    if not _run_lock.acquire(blocking=False):
        log.info("Scrape already running; skipping")
        return []
    try:
        disabled = set(Source.objects.filter(is_enabled=False).values_list("key", flat=True))
        runs = [
            run_source(config)
            for config in SOURCES
            if (keys is None or config["key"] in keys) and config["key"] not in disabled
        ]
        # A detail fetch can fill in the size that makes a with/without-unit pair recognizable.
        try:
            merged = merge_unit_duplicates()
            if merged:
                log.info("Merged %d duplicate listings", len(merged))
        except Exception:
            log.exception("Duplicate merge pass failed")
        # Re-run feature detection on stored text so rule fixes reach listings already saved
        # (known listings aren't re-fetched in detail).
        try:
            log.info("Re-detection updated %d listings", reextract_all())
        except Exception:
            log.exception("Re-detection pass failed")
        if geocode:
            try:
                geocode_pending()
            except Exception:
                log.exception("Geocoding pass failed")
        return runs
    finally:
        _run_lock.release()


def run_all_in_background():
    def target():
        try:
            run_all()
        finally:
            close_old_connections()

    thread = threading.Thread(target=target, name="scrape-now", daemon=True)
    thread.start()
    return thread
