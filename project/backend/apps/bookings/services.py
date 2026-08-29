import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.bookings.exceptions import (
    StudentAlreadyHasActiveBookingException,
    NoSeatsAvailableException,
    ConcurrentBookingContentionException,
)
from apps.bookings.models import Booking
from apps.core.models import SystemSetting
from apps.notifications.models import Notification
from apps.payments.models import Payment
from apps.seats.models import Seat


def generate_booking_reference() -> str:
    """Generates a unique booking reference like BKG-YYYYMM-XXXX."""
    prefix = timezone.now().strftime("BKG-%Y%m")
    unique_suffix = uuid.uuid4().hex[:6].upper()
    return f"{prefix}-{unique_suffix}"


@transaction.atomic
def initiate_random_seat_booking(student) -> Booking:
    """
    Randomly allocates an available physical seat to the student.

    Places the seat into HELD status with a configurable hold expiration
    window and initializes Payment Attempt 1.
    """

    # 1. Clean up unpaid expired holds.
    process_expired_seat_holds()

    # 2. Prevent multiple active bookings for the same student.
    if Booking.objects.filter(
        student=student,
        status__in=Booking.ACTIVE_STATUSES,
        is_active=True,
    ).exists():
        raise StudentAlreadyHasActiveBookingException(
            "You already hold an active or pending seat allocation."
        )

    # 3. Random seat allocation with row-level locking.
    seat = (
        Seat.objects
        .select_for_update(skip_locked=True)
        .filter(
            status=Seat.Status.AVAILABLE,
            is_active=True,
        )
        .order_by("?")
        .first()
    )

    if not seat:
        if not Seat.objects.filter(
            status=Seat.Status.AVAILABLE,
            is_active=True,
        ).exists():
            raise NoSeatsAvailableException(
                "All 150 study seats are currently occupied."
            )

        raise ConcurrentBookingContentionException(
            "High server traffic. Please retry your booking request in a moment."
        )

    # 4. AVAILABLE -> HELD
    seat.status = Seat.Status.HELD
    seat.save(update_fields=["status", "updated_at"])

    # 5. Calculate configurable hold duration.
    hold_duration_setting = SystemSetting.get_setting(
        "SEAT_HOLD_DURATION_MINUTES",
        str(getattr(settings, "SEAT_HOLD_DURATION_MINUTES", 30)),
    )

    try:
        hold_duration_minutes = int(hold_duration_setting)

        if hold_duration_minutes <= 0:
            raise ValueError

    except (ValueError, TypeError):
        hold_duration_minutes = 30

    now = timezone.now()
    hold_expires_at = now + timedelta(minutes=hold_duration_minutes)

    # 6. Create booking.
    booking = Booking.objects.create(
        booking_reference=generate_booking_reference(),
        student=student,
        seat=seat,
        hold_created_at=now,
        hold_expires_at=hold_expires_at,
        membership_start=None,
        membership_expires_at=None,
        grace_until=None,
        status=Booking.Status.PENDING_PAYMENT,
        is_active=True,
    )

    # 7. Create Payment Attempt 1.
    Payment.objects.create(
        booking=booking,
        attempt_number=1,
        amount=Decimal("800.00"),
        payment_mode=Payment.Mode.MANUAL_UPI,
        status=Payment.Status.PENDING_VERIFICATION,
    )

    # 8. Audit log.
    AuditLog.log(
        action="SEAT_HELD",
        target_model="Booking",
        target_id=str(booking.id),
        actor=student,
        details={
            "seat_number": seat.number,
            "hold_expires_at": hold_expires_at.isoformat(),
        },
    )

    return booking


@transaction.atomic
def vacate_booking(booking_id: int, admin_user) -> Booking:
    """
    Manually vacates an active booking after the administrator has
    physically refunded the student.

    This function does NOT process a monetary refund.

    It:
    - locks the Booking first
    - locks the Seat second
    - marks the booking as CANCELLED
    - marks the booking inactive
    - releases the physical seat
    - records an audit log
    """

    # Lock Booking first.
    booking = (
        Booking.objects
        .select_for_update()
        .select_related("seat", "student")
        .get(id=booking_id)
    )

    # Only active bookings may be manually vacated.
    if not booking.is_active or booking.status not in Booking.ACTIVE_STATUSES:
        raise ValueError(
            "This booking is no longer active and cannot be vacated."
        )

    # Lock Seat second.
    seat = Seat.objects.select_for_update().get(id=booking.seat_id)

    # Booking -> CANCELLED / inactive.
    booking.status = Booking.Status.CANCELLED
    booking.is_active = False

    booking.save(
        update_fields=[
            "status",
            "is_active",
            "updated_at",
        ]
    )

    # Seat -> AVAILABLE.
    seat.status = Seat.Status.AVAILABLE
    seat.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    # Record administrative action.
    AuditLog.log(
        action="SEAT_VACATED",
        target_model="Booking",
        target_id=str(booking.id),
        actor=admin_user,
        details={
            "booking_reference": booking.booking_reference,
            "student_id": booking.student_id,
            "seat_id": seat.id,
            "seat_number": seat.number,
            "reason": "Manual seat vacation after physical refund.",
        },
    )

    return booking


def process_expired_seat_holds() -> int:
    """
    Identifies and cancels unpaid expired seat holds.

    Expired holds are released only when the student has NOT submitted
    payment proof.
    """

    now = timezone.now()

    expired_booking_ids = list(
        Booking.objects
        .filter(
            status=Booking.Status.PENDING_PAYMENT,
            hold_expires_at__lt=now,
            is_active=True,
        )
        .exclude(payments__submitted_at__isnull=False)
        .values_list("id", flat=True)
    )

    released_count = 0

    for booking_id in expired_booking_ids:
        try:
            with transaction.atomic():
                booking = (
                    Booking.objects
                    .select_for_update()
                    .get(id=booking_id)
                )

                if (
                    booking.status != Booking.Status.PENDING_PAYMENT
                    or not booking.is_active
                    or not booking.hold_expires_at
                    or booking.hold_expires_at >= timezone.now()
                ):
                    continue

                if booking.payments.filter(
                    submitted_at__isnull=False
                ).exists():
                    continue

                seat = (
                    Seat.objects
                    .select_for_update()
                    .get(id=booking.seat_id)
                )

                booking.status = Booking.Status.CANCELLED
                booking.is_active = False

                booking.save(
                    update_fields=[
                        "status",
                        "is_active",
                        "updated_at",
                    ]
                )

                seat.status = Seat.Status.AVAILABLE

                seat.save(
                    update_fields=[
                        "status",
                        "updated_at",
                    ]
                )

                booking.payments.filter(
                    status=Payment.Status.PENDING_VERIFICATION
                ).update(
                    status=Payment.Status.REJECTED,
                    rejection_reason="Payment hold expired before payment proof was submitted.",
                    verified_at=timezone.now(),
                )

                AuditLog.log(
                    action="SEAT_HOLD_EXPIRED",
                    target_model="Booking",
                    target_id=str(booking.id),
                    actor=None,
                    details={
                        "seat_number": seat.number,
                        "hold_expires_at": booking.hold_expires_at.isoformat(),
                    },
                )

                released_count += 1

        except Booking.DoesNotExist:
            continue

        except Seat.DoesNotExist:
            continue

    return released_count


def process_expired_grace_periods() -> int:
    """
    Releases seats for memberships whose grace period has expired.
    """

    now = timezone.now()

    expired_booking_ids = list(
        Booking.objects
        .filter(
            status=Booking.Status.GRACE_PERIOD,
            grace_until__lt=now,
            is_active=True,
        )
        .values_list("id", flat=True)
    )

    released_count = 0

    for booking_id in expired_booking_ids:
        with transaction.atomic():
            booking = (
                Booking.objects
                .select_for_update()
                .get(id=booking_id)
            )

            if (
                booking.status != Booking.Status.GRACE_PERIOD
                or not booking.is_active
                or not booking.grace_until
                or booking.grace_until >= timezone.now()
            ):
                continue

            seat = (
                Seat.objects
                .select_for_update()
                .get(id=booking.seat_id)
            )

            booking.status = Booking.Status.EXPIRED
            booking.is_active = False

            booking.save(
                update_fields=[
                    "status",
                    "is_active",
                    "updated_at",
                ]
            )

            seat.status = Seat.Status.AVAILABLE

            seat.save(
                update_fields=[
                    "status",
                    "updated_at",
                ]
            )

            AuditLog.log(
                action="MEMBERSHIP_EXPIRED",
                target_model="Booking",
                target_id=str(booking.id),
                actor=None,
                details={
                    "seat_number": seat.number,
                    "grace_until": booking.grace_until.isoformat(),
                },
            )

            released_count += 1

    return released_count


def process_renewal_reminders() -> int:
    """
    Sends renewal reminders approximately 4 days and 3 days
    before membership expiration.
    """

    now = timezone.now()
    count = 0

    bookings = Booking.objects.filter(
        status__in=[
            Booking.Status.CONFIRMED,
            Booking.Status.EXPIRING_SOON,
        ],
        is_active=True,
        membership_expires_at__isnull=False,
    )

    for booking in bookings:
        remaining = booking.membership_expires_at - now
        remaining_days = remaining.total_seconds() / 86400

        # 4-day reminder window.
        if (
            3.0 <= remaining_days <= 4.0
            and booking.reminder_4d_sent_at is None
        ):
            Notification.objects.create(
                recipient=booking.student,
                notification_type=Notification.Type.RENEWAL_REMINDER_4D,
                title="Membership renewal reminder",
                message=(
                    "Your library membership expires in approximately "
                    "4 days. Please renew your membership to retain "
                    "your seat."
                ),
            )

            booking.reminder_4d_sent_at = now

            if booking.status == Booking.Status.CONFIRMED:
                booking.status = Booking.Status.EXPIRING_SOON

            booking.save(
                update_fields=[
                    "reminder_4d_sent_at",
                    "status",
                    "updated_at",
                ]
            )

            count += 1

        # 3-day reminder window.
        elif (
            2.0 <= remaining_days <= 3.0
            and booking.reminder_3d_sent_at is None
        ):
            Notification.objects.create(
                recipient=booking.student,
                notification_type=Notification.Type.RENEWAL_REMINDER_3D,
                title="Membership renewal reminder",
                message=(
                    "Your library membership expires in approximately "
                    "3 days. Please renew your membership to retain "
                    "your seat."
                ),
            )

            booking.reminder_3d_sent_at = now

            if booking.status == Booking.Status.CONFIRMED:
                booking.status = Booking.Status.EXPIRING_SOON

            booking.save(
                update_fields=[
                    "reminder_3d_sent_at",
                    "status",
                    "updated_at",
                ]
            )

            count += 1

    return count