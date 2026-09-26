from django.urls import path

from . import views

urlpatterns = [
    path("", views.listing_list, name="listing_list"),
    path("listing/<int:pk>/", views.listing_detail, name="listing_detail"),
    path("listing/<int:pk>/tracking/", views.update_tracking, name="update_tracking"),
    path("listing/<int:pk>/status/", views.set_status, name="set_status"),
    path("sources/", views.sources, name="sources"),
    path("sources/scrape/", views.scrape_now, name="scrape_now"),
]
