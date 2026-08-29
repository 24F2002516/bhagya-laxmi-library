from django.views.generic import TemplateView, View
from django.http import JsonResponse
from django.conf import settings
from django.db import connection
from django.utils import timezone


class HomeView(TemplateView):
    """
    Renders the public landing / home page for Bhagya Laxmi Library.
    """

    template_name = "pages/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["app_name"] = "Bhagya Laxmi Library"
        context["total_seats"] = settings.TOTAL_LIBRARY_SEATS
        context["seat_fee"] = settings.SEAT_MONTHLY_FEE
        context["now"] = timezone.now()
        return context


class HealthCheckView(View):
    """
    Returns system health status and database connectivity.
    """

    def get(self, request, *args, **kwargs):
        db_status = "unknown"
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                row = cursor.fetchone()
                if row and row[0] == 1:
                    db_status = "healthy"
                else:
                    db_status = "degraded"
        except Exception as exc:
            db_status = f"unhealthy: {str(exc)}"

        is_healthy = db_status == "healthy"
        status_code = 200 if is_healthy else 503

        data = {
            "status": "ok" if is_healthy else "error",
            "app": "Bhagya Laxmi Library",
            "environment": "production" if not settings.DEBUG else "development",
            "database": db_status,
            "total_seats": settings.TOTAL_LIBRARY_SEATS,
            "seat_monthly_fee": settings.SEAT_MONTHLY_FEE,
            "timestamp": timezone.now().isoformat(),
        }
        return JsonResponse(data, status=status_code)
