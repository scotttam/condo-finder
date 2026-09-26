import pytest


@pytest.mark.django_db
def test_admin_login_page_renders(client):
    response = client.get("/admin/login/")
    assert response.status_code == 200
