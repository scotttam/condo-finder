from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from accounts.groups import new_group
from accounts.models import Profile
from tests.helpers import home_group

pytestmark = pytest.mark.django_db


def run(**options):
    out = StringIO()
    call_command("create_owner", stdout=out, **options)
    return out.getvalue()


def test_creates_a_staff_account_in_the_owners_group():
    out = run(email="Scott.T@Example.com", name="Scott", password="a long pass phrase")
    user = get_user_model().objects.get()
    assert user.username == user.email == "scott.t@example.com"
    assert user.is_staff and user.is_superuser and user.check_password("a long pass phrase")
    assert user.profile.group == home_group() and user.profile.display_name == "Scott"
    assert 'Created scott.t@example.com (Scott) in "Our search".' in out


def test_rerunning_updates_the_name_and_keeps_the_password():
    run(email="scott@example.com", name="Scott", password="a long pass phrase")
    run(email="scott@example.com", name="Scott T")
    user = get_user_model().objects.get()
    assert user.profile.display_name == "Scott T" and user.check_password("a long pass phrase")
    assert Profile.objects.count() == 1


def test_adopts_an_existing_superuser_by_email_and_moves_it_in():
    old = get_user_model().objects.create_superuser("scott", "scott@example.com", "old password")
    Profile.objects.create(user=old, group=new_group("scott's search"), display_name="scott")
    run(email="scott@example.com", name="Scott")
    old.refresh_from_db()
    assert old.username == "scott@example.com" and old.profile.group == home_group()
