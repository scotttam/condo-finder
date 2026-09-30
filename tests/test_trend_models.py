from decimal import Decimal

import pytest

from accounts.groups import new_group
from listings.models import SearchPriorities, TrendReport
from tests.helpers import home_group

pytestmark = pytest.mark.django_db


def test_search_priorities_are_one_row_per_group():
    first = SearchPriorities.get(home_group())
    first.text = "Quiet, near a park"
    first.save()
    assert SearchPriorities.get(home_group()).text == "Quiet, near a park"
    assert SearchPriorities.get(new_group("Pat's search")).text == ""
    assert SearchPriorities.objects.count() == 2


def test_trend_report_defaults_and_ordering():
    old = TrendReport.objects.create()
    new = TrendReport.objects.create(trigger=TrendReport.Trigger.AUTO)
    assert old.status == TrendReport.Status.RUNNING
    assert old.trigger == TrendReport.Trigger.MANUAL
    assert old.picks == [] and old.changes == {} and old.cost_usd == Decimal("0")
    assert list(TrendReport.objects.all()) == [new, old]
