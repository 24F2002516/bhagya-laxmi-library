from django.db import models
from django.db.models import F, Q
from django.utils import timezone
from apps.core.models import TimeStampedModel


class Booking(TimeStampedModel):
    """
    Represents a seat allocation lifecycle, separating the temporary seat hold window
    from the post-verification 30-calendar-day membership cycle and 48-hour grace period.
    """

    class Status(models.TextChoices):
        PENDING_PAYMENT = "PENDING_PAYMENT", "Pending Payment Verification"
        CONFIRMED = "CONFIRMED", "Confirmed (Active Membership)"
        EXPIRING_SOON = "EXPIRING_SOON", "Expiring Soon"
        GRACE_PERIOD = "GRACE_PERIOD", "Grace Period (48 Hours)"
        EXPIRED = "EXPIRED", "Expired"
        CANCELLED = "CANCELLED", "Cancelled"

    ACTIVE_STATUSES = [
        Status.PENDING_PAYMENT,
        Status.CONFIRMED,
        Status.EXPIRING_SOON,
        Status.GRACE_PERIOD,
    ]

    booking_reference = models.CharField(
        max_length=32, unique=True, db_index=True, help_text="Unique booking reference (e.g. BKG-202608-0142)"
    )
    student = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="bookings",
        help_text="Canonical student owner of this booking",
    )
    seat = models.ForeignKey(
        "seats.Seat",
        on_delete=models.PROTECT,
        related_name="bookings",
        help_text="Assigned study seat (1 to 150)",
    )
    hold_created_at = models.DateTimeField(
        default=timezone.now, help_text="Timestamp when temporary seat hold was initiated"
    )
    hold_expires_at = models.DateTimeField(
        db_index=True, help_text="Deadline by which payment must be verified before hold expires"
    )
    membership_start = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Timestamp when Admin verified payment and paid membership started",
    )
    membership_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Exact timestamp when 30-calendar-day membership expires",
    )
    grace_until = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Exact timestamp when 48-hour post-expiry grace period ends",
    )
    status = models.CharField(
        max_length=25,
        choices=Status.choices,
        default=Status.PENDING_PAYMENT,
        db_index=True,
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Quick boolean index to filter active vs archived bookings",
    )
    reminder_4d_sent_at = models.DateTimeField(
        null=True, blank=True, help_text="Timestamp when 4-day renewal reminder email was sent"
    )
    reminder_3d_sent_at = models.DateTimeField(
        null=True, blank=True, help_text="Timestamp when 3-day renewal reminder email was sent"
    )

    class Meta:
        verbose_name = "Booking"
        verbose_name_plural = "Bookings"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(hold_expires_at__gt=F("hold_created_at")),
                name="hold_expiry_after_hold_start",
            ),
            models.CheckConstraint(
                condition=Q(membership_expires_at__isnull=True)
                | Q(membership_expires_at__gt=F("membership_start")),
                name="membership_expiry_after_start",
            ),
            models.CheckConstraint(
                condition=Q(grace_until__isnull=True)
                | Q(grace_until__gt=F("membership_expires_at")),
                name="grace_until_after_membership_expiry",
            ),
            # Engine-level invariant: Strictly 1 active booking per seat
            models.UniqueConstraint(
                fields=["seat"],
                condition=Q(
                    status__in=[
                        "PENDING_PAYMENT",
                        "CONFIRMED",
                        "EXPIRING_SOON",
                        "GRACE_PERIOD",
                    ]
                ),
                name="unique_active_booking_per_seat",
            ),
            # Engine-level invariant: Strictly 1 active booking per student
            models.UniqueConstraint(
                fields=["student"],
                condition=Q(
                    status__in=[
                        "PENDING_PAYMENT",
                        "CONFIRMED",
                        "EXPIRING_SOON",
                        "GRACE_PERIOD",
                    ]
                ),
                name="unique_active_booking_per_student",
            ),
        ]

    def __str__(self):
        return f"Booking {self.booking_reference} (Seat #{self.seat.number} - {self.get_status_display()})"

    @property
    def is_confirmed(self) -> bool:
        return self.status in [self.Status.CONFIRMED, self.Status.EXPIRING_SOON]

    @property
    def in_grace_period(self) -> bool:
        return self.status == self.Status.GRACE_PERIOD

    @property
    def is_hold_expired(self) -> bool:
        """Determines if the authoritative server hold deadline has passed."""
        return timezone.now() >= self.hold_expires_at

    @property
    def remaining_hold_seconds(self) -> int:
        """
        Calculates remaining hold seconds authoritative for frontend countdown timers.
        Returns 0 if already expired.
        """
        remaining = int((self.hold_expires_at - timezone.now()).total_seconds())
        return max(0, remaining)

    @property
    def has_submitted_payment_proof(self) -> bool:
        """Checks if the student has submitted payment proof for this booking."""
        return self.payments.filter(submitted_at__isnull=False).exists()
