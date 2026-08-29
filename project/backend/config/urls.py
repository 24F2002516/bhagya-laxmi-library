"""
URL configuration for Bhagya Laxmi Library.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls", namespace="accounts")),
    path("portal/", include("apps.bookings.urls", namespace="portal")),
    path("admin/", include("apps.admin_portal.urls")),
    path("", include("apps.core.urls", namespace="core")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
