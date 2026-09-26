from datetime import datetime
from zoneinfo import ZoneInfo

from listings import scheduler

PACIFIC = ZoneInfo("America/Los_Angeles")


def fire_after(trigger, when):
    return trigger.get_next_fire_time(None, when)


def test_default_schedule_every_four_hours_daytime():
    job = scheduler.build_scheduler().get_job("scrape-all")
    assert fire_after(job.trigger, datetime(2026, 9, 26, 12, 0, tzinfo=PACIFIC)).hour == 15
    late = fire_after(job.trigger, datetime(2026, 9, 26, 23, 30, tzinfo=PACIFIC))
    assert (late.day, late.hour) == (27, 7)


def test_schedule_is_configurable(settings):
    settings.SCRAPE_HOURS = "9,21"
    job = scheduler.build_scheduler().get_job("scrape-all")
    assert fire_after(job.trigger, datetime(2026, 9, 26, 10, 0, tzinfo=PACIFIC)).hour == 21


def test_next_run_time_none_when_not_started():
    assert scheduler.next_run_time() is None
