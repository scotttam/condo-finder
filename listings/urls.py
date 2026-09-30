from django.urls import path

from . import collab_views, sql_views, views

urlpatterns = [
    path("", views.listing_list, name="listing_list"),
    path("listing/<int:pk>/", views.listing_detail, name="listing_detail"),
    path("listing/<int:pk>/vote/", collab_views.vote, name="vote"),
    path("listing/<int:pk>/comments/", collab_views.comment_list, name="comment_list"),
    path("listing/<int:pk>/comments/add/", collab_views.comment_add, name="comment_add"),
    path("listing/<int:pk>/comments/<int:comment_pk>/edit/", collab_views.comment_edit, name="comment_edit"),
    path("listing/<int:pk>/comments/<int:comment_pk>/delete/", collab_views.comment_delete, name="comment_delete"),
    path("listing/<int:pk>/status/", views.set_status, name="set_status"),
    path("listing/<int:pk>/refresh/", views.refresh_listing, name="refresh_listing"),
    path("listing/<int:pk>/history/add/", views.history_add, name="history_add"),
    path("listing/<int:pk>/history/<int:change_pk>/edit/", views.history_edit, name="history_edit"),
    path("listing/<int:pk>/history/<int:change_pk>/delete/", views.history_delete, name="history_delete"),
    path("filters/defaults/", views.save_default_filters, name="save_default_filters"),
    path("feed/", views.feed_page, name="feed"),
    path("feed/badge/", views.feed_badge, name="feed_badge"),
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
