from django.urls import path

from . import sql_views, views

urlpatterns = [
    path("", views.listing_list, name="listing_list"),
    path("listing/<int:pk>/", views.listing_detail, name="listing_detail"),
    path("listing/<int:pk>/tracking/", views.update_tracking, name="update_tracking"),
    path("listing/<int:pk>/status/", views.set_status, name="set_status"),
    path("listing/<int:pk>/refresh/", views.refresh_listing, name="refresh_listing"),
    path("listing/<int:pk>/history/add/", views.history_add, name="history_add"),
    path("listing/<int:pk>/history/<int:change_pk>/edit/", views.history_edit, name="history_edit"),
    path("listing/<int:pk>/history/<int:change_pk>/delete/", views.history_delete, name="history_delete"),
    path("feed/", views.feed_page, name="feed"),
    path("trends/", views.trends_page, name="trends"),
    path("trends/run/", views.trends_run, name="trends_run"),
    path("trends/priorities/", views.trends_priorities, name="trends_priorities"),
    path("trends/status/", views.trends_status, name="trends_status"),
    path("sources/", views.sources, name="sources"),
    path("sources/scrape/", views.scrape_now, name="scrape_now"),
    path("sql/", sql_views.sql_console_page, name="sql_console"),
    path("sql/csv/", sql_views.sql_csv, name="sql_csv"),
    path("sql/save/", sql_views.sql_save, name="sql_save"),
    path("sql/saved/<int:pk>/delete/", sql_views.sql_delete, name="sql_delete"),
]
