import csv
import io
from urllib.parse import parse_qs, urlencode

import pytest
from bs4 import BeautifulSoup

from listings.models import Listing, QueryRun
from tests.helpers import make_listing

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff_client(client, django_user_model):
    client.force_login(django_user_model.objects.create_user("owner", password="pw", is_staff=True))
    return client


def get(client, sql, path="/sql/"):
    return client.get(f"{path}?{urlencode({'q': sql})}")


def soup(response):
    return BeautifulSoup(response.content, "html.parser")


def result_rows(response):
    table = soup(response).select_one("div.sql-results table")
    return [[cell.get_text() for cell in tr.find_all("td")] for tr in table.find_all("tr")[1:]]


@pytest.mark.parametrize("path", ["/sql/", "/sql/csv/?q=SELECT+1"])
def test_anonymous_is_sent_to_admin_login(client, path):
    response = client.get(path)
    assert response.status_code == 302
    assert response["Location"].startswith("/admin/login/?next=/sql/")
    assert not QueryRun.objects.exists()


@pytest.mark.parametrize("path", ["/sql/", "/sql/csv/?q=SELECT+1"])
def test_non_staff_user_is_sent_to_admin_login(client, django_user_model, path):
    client.force_login(django_user_model.objects.create_user("guest", password="pw"))
    response = client.get(path)
    assert response.status_code == 302
    assert response["Location"].startswith("/admin/login/")
    assert not QueryRun.objects.exists()


def test_empty_page_has_editor_canned_queries_and_schema(staff_client):
    page = soup(staff_client.get("/sql/"))
    assert page.select_one("textarea#sql-input[name=q]") is not None
    assert page.find("a", string="Median rent by city and quadrant") is not None
    insert = page.find("button", string="listings_listing")
    assert insert["data-sql"] == "SELECT * FROM listings_listing LIMIT 50"
    assert page.select_one("div.sql-results") is None
    assert not QueryRun.objects.exists()


def test_running_a_query_shows_results_and_logs_it(staff_client):
    listing = make_listing(price=2500)
    response = get(staff_client, "SELECT id, address, price FROM listings_listing")
    page = soup(response)
    assert [th.get_text() for th in page.select("div.sql-results th")] == ["id", "address", "price"]
    link = page.select_one("div.sql-results td a")
    assert link["href"] == f"/listing/{listing.pk}/"
    assert result_rows(response) == [[str(listing.pk), listing.address, "2500"]]
    assert "1 row" in page.select_one("p.sql-summary").get_text()
    run = QueryRun.objects.get()
    assert (run.sql, run.row_count, run.error, run.user.username) == ("SELECT id, address, price FROM listings_listing", 1, "", "owner")
    assert page.select_one("textarea#sql-input").get_text().strip() == "SELECT id, address, price FROM listings_listing"


def test_listing_id_column_links(staff_client):
    listing = make_listing(price=2500)
    page = soup(get(staff_client, "SELECT id AS listing_id FROM listings_listing"))
    assert page.select_one("div.sql-results td a")["href"] == f"/listing/{listing.pk}/"


def test_other_ids_do_not_link(staff_client):
    response = get(staff_client, "SELECT 5 AS id")
    assert result_rows(response) == [["5"]]
    assert soup(response).select_one("div.sql-results td a") is None


def test_results_are_capped_and_marked_truncated(staff_client, settings):
    settings.SQL_CONSOLE_MAX_ROWS = 2
    response = get(staff_client, "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 5) SELECT x FROM c")
    assert result_rows(response) == [["1"], ["2"]]
    assert "truncated" in soup(response).select_one("p.sql-summary").get_text()


def test_refused_write_shows_error_and_changes_nothing(staff_client):
    make_listing(price=2500)
    page = soup(get(staff_client, "DELETE FROM listings_listing"))
    assert "readonly" in page.select_one('p.sql-error[role="alert"]').get_text()
    assert Listing.objects.count() == 1
    run = QueryRun.objects.get()
    assert run.row_count is None
    assert "readonly" in run.error


def test_timeout_is_shown_and_logged(staff_client, settings):
    settings.SQL_CONSOLE_TIMEOUT_SECONDS = 0.05
    page = soup(get(staff_client, "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 100000000) SELECT COUNT(*) FROM c"))
    assert page.select_one('p.sql-error[role="alert"]').get_text().startswith("Stopped after")
    assert QueryRun.objects.get().error.startswith("Stopped after")


def test_values_are_escaped_and_nulls_marked(staff_client):
    make_listing(notes="<script>alert(1)</script>")
    response = get(staff_client, "SELECT notes, NULL AS empty_value FROM listings_listing")
    assert b"<script>alert(1)</script>" not in response.content
    cells = soup(response).select("div.sql-results td")
    assert cells[0].get_text() == "<script>alert(1)</script>"
    assert cells[1].select_one("span.sql-null").get_text() == "NULL"


def test_duplicate_column_names_both_render(staff_client):
    response = get(staff_client, "SELECT 1 AS a, 2 AS a")
    assert [th.get_text() for th in soup(response).select("div.sql-results th")] == ["a", "a"]
    assert result_rows(response) == [["1", "2"]]


def test_statement_with_no_rows(staff_client):
    page = soup(get(staff_client, "SELECT id FROM listings_listing"))
    assert "0 rows" in page.select_one("p.sql-summary").get_text()


def test_recent_lists_earlier_runs(staff_client):
    get(staff_client, "SELECT 42 AS answer")
    recent = soup(staff_client.get("/sql/")).find("summary", string="Recent").parent
    assert recent.find("a", string="SELECT 42 AS answer") is not None


def test_csv_has_every_row_and_utf8(staff_client, settings):
    settings.SQL_CONSOLE_MAX_ROWS = 1
    make_listing(address_key="a|1|97209", address="1 Café Row #1", price=2000)
    make_listing(address_key="b|2|97209", address="2 Main St #2", price=3000)
    response = get(staff_client, "SELECT address, price FROM listings_listing ORDER BY price", path="/sql/csv/")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert response["Content-Disposition"].startswith('attachment; filename="query-')
    assert list(csv.reader(io.StringIO(response.content.decode("utf-8")))) == [
        ["address", "price"], ["1 Café Row #1", "2000"], ["2 Main St #2", "3000"],
    ]


def test_csv_error_is_a_400_not_a_partial_file(staff_client, settings):
    settings.SQL_CONSOLE_TIMEOUT_SECONDS = 0.05
    response = get(staff_client, "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 100000000) SELECT x FROM c", path="/sql/csv/")
    assert response.status_code == 400
    assert response.content.decode().startswith("Query failed: Stopped after")


def test_csv_without_query_is_a_400(staff_client):
    assert staff_client.get("/sql/csv/").status_code == 400


def test_csv_link_carries_the_query(staff_client):
    page = soup(get(staff_client, "SELECT 1 AS one"))
    path, _, query = page.find("a", string="Download CSV")["href"].partition("?")
    assert (path, parse_qs(query)) == ("/sql/csv/", {"q": ["SELECT 1 AS one"]})


def test_phone_layout_lets_wide_results_scroll_inside_their_box():
    # A plain 1fr grid column grows to fit a wide table, so the whole page scrolled sideways on phones.
    from pathlib import Path

    css = Path("listings/templates/listings/base.html").read_text()
    phone = css[css.index("@media (max-width: 800px)"):]
    assert ".sql-layout { grid-template-columns:minmax(0, 1fr); }" in phone
