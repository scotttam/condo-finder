from django.contrib import admin

from .models import Profile, SearchGroup


class ProfileInline(admin.TabularInline):
    model = Profile
    extra = 0
    fields = ("user", "display_name", "joined_at")
    readonly_fields = ("user", "joined_at")


@admin.register(SearchGroup)
class SearchGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    inlines = [ProfileInline]


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("display_name", "user", "group", "joined_at")
    list_filter = ("group",)
