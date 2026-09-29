from decimal import Decimal

import pytest

from listings.models import SearchPriorities, TrendReport

pytestmark = pytest.mark.django_db


def test_search_priorities_is_a_single_shared_row():
    first = SearchPriorities.get()
    first.text = "Quiet, near a park"
    first.save()
    assert SearchPriorities.get().text == "Quiet, near a park"
    assert SearchPriorities.objects.count() == 1


def test_trend_report_defaults_and_ordering():
    old = TrendReport.objects.create()
    new = TrendReport.objects.create(trigger=TrendReport.Trigger.AUTO)
    assert old.status == TrendReport.Status.RUNNING
    assert old.trigger == TrendReport.Trigger.MANUAL
    assert old.picks == [] and old.changes == {} and old.cost_usd == Decimal("0")
    assert list(TrendReport.objects.all()) == [new, old]
