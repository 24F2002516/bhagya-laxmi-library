from django.urls import path
from .views import HomeView, HealthCheckView

app_name = "core"

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("health/", HealthCheckView.as_view(), name="health"),
]
