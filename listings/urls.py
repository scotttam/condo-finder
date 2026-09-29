from django.urls import path

from . import views

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
    path("sources/", views.sources, name="sources"),
    path("sources/scrape/", views.scrape_now, name="scrape_now"),
]
