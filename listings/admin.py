from django.contrib import admin

from .models import Listing, PriceChange, Source, SourceListing, SourceRun


class SourceListingInline(admin.TabularInline):
    model = SourceListing
    extra = 0
    readonly_fields = ("source", "external_id", "url", "is_active", "missed_runs", "first_seen_at", "last_seen_at")

    def has_add_permission(self, request, obj=None):
        return False  # created by scrapers; every field is read-only, so an added row would save nothing


class PriceChangeInline(admin.TabularInline):
    # Editable so history can be corrected or added by hand. With every field read-only,
    # "Add another" rows had no inputs and were silently discarded on save.
    model = PriceChange
    extra = 0
    fields = ("seen_at", "price", "event", "source")


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ("address", "price", "beds", "baths", "parking_spaces", "property_type", "status", "is_active", "first_seen_at")
    list_filter = ("status", "property_type", "city", "quadrant", "is_active")
    search_fields = ("address", "title", "neighborhood")
    inlines = [SourceListingInline, PriceChangeInline]


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("name", "platform", "last_success_at", "last_count", "consecutive_failures")


@admin.register(SourceRun)
class SourceRunAdmin(admin.ModelAdmin):
    list_display = ("source", "started_at", "ok", "count", "new_count")
    list_filter = ("source", "ok")
