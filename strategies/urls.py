from django.urls import path

from . import views

app_name = "strategies"

urlpatterns = [
    path("", views.StrategyListView.as_view(), name="list"),
    path("new/", views.StrategyFormView.as_view(), name="create"),
    path("<int:strategy_id>/", views.StrategyDetailView.as_view(), name="detail"),
    path("<int:strategy_id>/edit/", views.StrategyFormView.as_view(), name="edit"),
    path("<int:strategy_id>/duplicate/", views.StrategyDuplicateView.as_view(), name="duplicate"),
    path("<int:strategy_id>/status/<str:new_status>/", views.StrategyStatusView.as_view(), name="set_status"),
    path("<int:strategy_id>/preview/", views.StrategyPreviewAPIView.as_view(), name="preview_api"),
]
