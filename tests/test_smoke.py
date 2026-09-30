import pytest


@pytest.mark.django_db
def test_admin_login_page_renders(anon_client):
    response = anon_client.get("/admin/login/")
    assert response.status_code == 200
