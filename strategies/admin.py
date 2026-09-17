from django.contrib import admin

from .models import Strategy, StrategyVersion


class StrategyVersionInline(admin.TabularInline):
    model = StrategyVersion
    extra = 0
    readonly_fields = ["version_number", "is_locked", "created_at"]


@admin.register(Strategy)
class StrategyAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "status", "created_at"]
    list_filter = ["category", "status"]
    search_fields = ["name"]
    inlines = [StrategyVersionInline]


@admin.register(StrategyVersion)
class StrategyVersionAdmin(admin.ModelAdmin):
    list_display = ["strategy", "version_number", "is_locked", "created_at"]
    list_filter = ["is_locked"]
