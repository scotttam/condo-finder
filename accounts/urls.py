from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .forms import EmailAuthenticationForm

urlpatterns = [
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="accounts/login.html",
            authentication_form=EmailAuthenticationForm,
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("group/", views.group_settings, name="group_settings"),
    path("group/rename/", views.rename_group, name="rename_group"),
    path("group/members/<int:user_id>/remove/", views.remove_member, name="remove_member"),
    path("group/leave/", views.leave_group, name="leave_group"),
    path("account/password/", views.PasswordChange.as_view(), name="password_change"),
]
