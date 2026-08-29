import os

from celery import Celery


# Set default Django settings module
os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings.local",
)


app = Celery("bhagya_laxmi_library")


# Load configuration from Django settings.
# CELERY_* settings are automatically picked up.
app.config_from_object(
    "django.conf:settings",
    namespace="CELERY",
)


# Automatically discover tasks.py inside installed Django apps.
app.autodiscover_tasks()


# =========================================================
# CELERY BEAT SCHEDULE
# =========================================================
#
# These jobs run automatically in the background.
#
# 1. Expired unpaid seat holds:
#    Checked every 2 minutes.
#
# 2. Expired membership grace periods:
#    Checked every hour.
#
# 3. Renewal reminders:
#    Checked every day.
#
# =========================================================

app.conf.beat_schedule = {

    "check-expired-seat-holds-every-2-minutes": {
        "task": "apps.bookings.tasks.check_expired_seat_holds_task",
        "schedule": 120.0,
    },

    "check-expired-grace-periods-every-hour": {
        "task": "apps.bookings.tasks.check_expired_grace_periods_task",
        "schedule": 3600.0,
    },

    "check-renewal-reminders-daily": {
        "task": "apps.bookings.tasks.check_renewal_reminders_task",
        "schedule": 86400.0,
    },
}


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f"Request: {self.request!r}")