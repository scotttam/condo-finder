from django.contrib import admin

from .models import Comment, FeedEvent, Listing, ListingState, PriceChange, SearchPriorities, Source, SourceListing, SourceRun, TrendReport, Vote


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
    list_display = ("address", "price", "beds", "baths", "parking_spaces", "property_type", "is_active", "first_seen_at")
    list_filter = ("property_type", "city", "quadrant", "is_active")
    search_fields = ("address", "title", "neighborhood")
    inlines = [SourceListingInline, PriceChangeInline]


@admin.register(ListingState)
class ListingStateAdmin(admin.ModelAdmin):
    list_display = ("listing", "group", "status", "status_by", "status_at")
    list_filter = ("group", "status")


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("created_at", "listing", "group", "author", "body")
    list_filter = ("group",)
    search_fields = ("body", "listing__address")


@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ("listing", "group", "user", "value", "updated_at")
    list_filter = ("group",)


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("name", "platform", "is_enabled", "last_success_at", "last_count", "consecutive_failures")
    list_editable = ("is_enabled",)
    # key and platform are code-driven (the registry); status fields are written by the scraper.
    readonly_fields = ("key", "platform", "last_success_at", "last_count", "last_error", "last_error_at", "consecutive_failures")
    fields = ("name", "is_enabled", "key", "platform", "last_success_at", "last_count", "last_error", "last_error_at", "consecutive_failures")

    def has_add_permission(self, request):
        return False  # sources come from the registry in code


@admin.register(SourceRun)
class SourceRunAdmin(admin.ModelAdmin):
    list_display = ("source", "started_at", "ok", "count", "new_count")
    list_filter = ("source", "ok")


@admin.register(FeedEvent)
class FeedEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "kind", "listing", "summary", "source")
    list_filter = ("kind", "source")
    search_fields = ("summary", "listing__address")


@admin.register(TrendReport)
class TrendReportAdmin(admin.ModelAdmin):
    list_display = ("created_at", "group", "trigger", "status", "cost_usd", "summary")
    list_filter = ("group", "status", "trigger")

    def has_add_permission(self, request):
        return False  # reports come from the Trends page and the daily run


@admin.register(SearchPriorities)
class SearchPrioritiesAdmin(admin.ModelAdmin):
    list_display = ("group", "updated_at")
