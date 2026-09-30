import pytest

from listings.models import QueryRun, SavedQuery

pytestmark = pytest.mark.django_db


def test_record_keeps_only_the_latest_runs(monkeypatch):
    monkeypatch.setattr(QueryRun, "KEEP", 3)
    for n in range(5):
        QueryRun.record(sql=f"SELECT {n}", row_count=1, elapsed_ms=2)
    assert [run.sql for run in QueryRun.objects.all()] == ["SELECT 4", "SELECT 3", "SELECT 2"]


def test_record_stores_errors_and_the_user(django_user_model):
    user = django_user_model.objects.create_user("owner", is_staff=True)
    run = QueryRun.record(sql="SELEC 1", user=user, row_count=None, elapsed_ms=1, error='near "SELEC": syntax error')
    run.refresh_from_db()
    assert run.user == user
    assert run.row_count is None
    assert "syntax error" in run.error


def test_deleting_a_user_keeps_their_runs(django_user_model):
    user = django_user_model.objects.create_user("owner", is_staff=True)
    QueryRun.record(sql="SELECT 1", user=user, row_count=1, elapsed_ms=1)
    user.delete()
    assert QueryRun.objects.get().user is None


def test_saved_queries_sort_by_name():
    SavedQuery.objects.create(name="zebra", sql="SELECT 1")
    SavedQuery.objects.create(name="apple", sql="SELECT 2")
    assert [q.name for q in SavedQuery.objects.all()] == ["apple", "zebra"]
