from django.urls import path

from . import views

app_name = "marketdata"

urlpatterns = [
    path("stock-analysis/", views.StockAnalysisView.as_view(), name="stock_analysis"),
    path("watchlist/toggle/", views.WatchlistToggleView.as_view(), name="watchlist_toggle"),
    path("api/candles/<str:internal_id>/", views.CandleDataAPIView.as_view(), name="candle_api"),
]
