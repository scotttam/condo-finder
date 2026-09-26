import logging
import threading

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from .geocode import geocode_pending
from .ingest import ingest
from .models import Source, SourceRun
from .notify import alert_new_listings, alert_price_drops, send_push
from .scrapers.registry import SOURCES, build_scraper

log = logging.getLogger(__name__)

_run_lock = threading.Lock()


class EmptyScrape(Exception):
    pass


def _source_for(config):
    source, _ = Source.objects.update_or_create(
        key=config["key"], defaults={"name": config["name"], "platform": config["platform"]}
    )
    return source


def sync_sources():
    for config in SOURCES:
        _source_for(config)


def run_source(config, fetcher=None):
    source = _source_for(config)
    run = SourceRun.objects.create(source=source)
    try:
        items = build_scraper(config, fetcher=fetcher).scrape()
        if not items:
            raise EmptyScrape("scraper returned 0 listings")
        result = ingest(source, items)
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
    alert_new_listings(result.new_listings)
    alert_price_drops(result.price_drops)
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
    sources_url = f"{settings.SITE_URL}/sources/"
    if isinstance(exc, EmptyScrape) and source.consecutive_failures == 1 and source.last_count:
        send_push(
            f"{source.name} returned 0 listings",
            f"It had {source.last_count} last time. The site may have changed or blocked us.",
            url=sources_url,
            tags=["warning"],
        )
    elif source.consecutive_failures == settings.HEALTH_ALERT_AFTER_FAILURES:
        send_push(
            f"Scraper failing: {source.name}",
            f"{source.consecutive_failures} failed runs in a row. {run.error}",
            url=sources_url,
            tags=["warning"],
        )


def is_running():
    return _run_lock.locked()


def run_all(keys=None, geocode=True):
    if not _run_lock.acquire(blocking=False):
        log.info("Scrape already running; skipping")
        return []
    try:
        runs = [run_source(config) for config in SOURCES if keys is None or config["key"] in keys]
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
