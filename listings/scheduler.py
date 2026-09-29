import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from django.conf import settings

log = logging.getLogger(__name__)

JOB_ID = "scrape-all"
_scheduler = None


def _scheduled_run():
    from django.db import close_old_connections

    from . import analyst, runner

    try:
        runner.run_all()
    finally:
        try:
            analyst.run_daily_if_due()  # the day's Trends report, after the first scrape of the day
        except Exception:
            log.exception("Could not start the daily trend report")
        close_old_connections()


def build_scheduler():
    scheduler = BackgroundScheduler(timezone=settings.TIME_ZONE)
    scheduler.add_job(
        _scheduled_run,
        CronTrigger(hour=settings.SCRAPE_HOURS, minute=0, timezone=settings.TIME_ZONE),
        id=JOB_ID,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    return scheduler


def start():
    global _scheduler
    if _scheduler is None:
        _scheduler = build_scheduler()
        _scheduler.start()
        log.info("Scheduler started; scraping at hours %s", settings.SCRAPE_HOURS)
    return _scheduler


def next_run_time():
    if _scheduler is None:
        return None
    job = _scheduler.get_job(JOB_ID)
    return job.next_run_time if job else None
