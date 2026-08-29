from celery import shared_task
from apps.bookings.services import (
    process_expired_seat_holds,
    process_expired_grace_periods,
    process_renewal_reminders,
)


@shared_task(name="apps.bookings.tasks.check_expired_seat_holds_task")
def check_expired_seat_holds_task():
    """
    Background job scanning for unpaid expired seat holds and releasing seats to AVAILABLE.
    Intended to be scheduled every 1 to 5 minutes.
    """
    return process_expired_seat_holds()


@shared_task(name="apps.bookings.tasks.check_expired_grace_periods_task")
def check_expired_grace_periods_task():
    """
    Background job scanning for expired 48-hour grace periods and releasing unrenewed seats to AVAILABLE.
    Intended to be scheduled daily at midnight.
    """
    return process_expired_grace_periods()


@shared_task(name="apps.bookings.tasks.check_renewal_reminders_task")
def check_renewal_reminders_task():
    """
    Background job scanning for upcoming expirations (at 4 days and 3 days before expiry)
    and dispatching renewal reminder emails.
    Intended to be scheduled daily.
    """
    return process_renewal_reminders()
