from django.contrib import admin

from .models import Candle, Instrument, InstrumentBrokerMapping


class InstrumentBrokerMappingInline(admin.TabularInline):
    model = InstrumentBrokerMapping
    extra = 0


@admin.register(Instrument)
class InstrumentAdmin(admin.ModelAdmin):
    list_display = ("internal_id", "symbol", "name", "exchange", "is_active")
    search_fields = ("internal_id", "symbol", "name")
    list_filter = ("exchange", "is_active")
    inlines = [InstrumentBrokerMappingInline]


@admin.register(Candle)
class CandleAdmin(admin.ModelAdmin):
    list_display = ("instrument", "timeframe", "timestamp", "close", "volume", "source")
    list_filter = ("timeframe", "source")
    search_fields = ("instrument__internal_id",)
    date_hierarchy = "timestamp"
