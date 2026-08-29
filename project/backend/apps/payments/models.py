from decimal import Decimal
from django.db import models
from django.db.models import Q
from apps.core.models import TimeStampedModel


class Payment(TimeStampedModel):
    """
    Tracks manual UPI payment attempts for a booking.
    Multiple attempts per booking are supported if an earlier attempt was rejected.
    The canonical student relationship is derived via booking.student.
    """

    class Mode(models.TextChoices):
        MANUAL_UPI = "MANUAL_UPI", "Manual UPI"

    class Status(models.TextChoices):
        PENDING_VERIFICATION = "PENDING_VERIFICATION", "Pending Verification"
        VERIFIED = "VERIFIED", "Verified"
        REJECTED = "REJECTED", "Rejected"

    booking = models.ForeignKey(
        "bookings.Booking",
        on_delete=models.PROTECT,
        related_name="payments",
        help_text="Canonical booking linked to this payment attempt",
    )
    attempt_number = models.PositiveSmallIntegerField(
        default=1, help_text="Sequential attempt number for this booking (1, 2, 3...)"
    )
    amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("800.00"),
        help_text="Fixed 30-day seat fee (₹800.00)",
    )
    payment_mode = models.CharField(
        max_length=20,
        choices=Mode.choices,
        default=Mode.MANUAL_UPI,
    )
    utr_number = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        db_index=True,
        help_text="Bank transaction reference (UTR) provided by student",
    )
    payment_screenshot = models.ImageField(
        upload_to="payment_proofs/%Y/%m/",
        null=True,
        blank=True,
        help_text="Optional payment screenshot uploaded by student",
    )
    submitted_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Timestamp when student submitted payment proof (UTR / screenshot)",
    )
    status = models.CharField(
        max_length=25,
        choices=Status.choices,
        default=Status.PENDING_VERIFICATION,
        db_index=True,
    )
    verified_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_payments",
        help_text="Admin user who verified or rejected this payment attempt",
    )
    verified_at = models.DateTimeField(
        null=True, blank=True, help_text="Timestamp of verification or rejection"
    )
    rejection_reason = models.TextField(
        blank=True, help_text="Reason provided by admin if payment was rejected"
    )

    class Meta:
        verbose_name = "Payment"
        verbose_name_plural = "Payments"
        ordering = ["booking", "attempt_number"]
        constraints = [
            # Invariant: Fixed fee must strictly be 800.00
            models.CheckConstraint(
                condition=Q(amount=Decimal("800.00")),
                name="fixed_fee_800_rupees",
            ),
            # Invariant: Attempt numbers must be unique per booking
            models.UniqueConstraint(
                fields=["booking", "attempt_number"],
                name="unique_attempt_per_booking",
            ),
            # Invariant: Only ONE pending payment attempt per booking at a time
            models.UniqueConstraint(
                fields=["booking"],
                condition=Q(status="PENDING_VERIFICATION"),
                name="unique_pending_payment_per_booking",
            ),
            # Invariant: Single conditional unique constraint for real non-null/non-empty UTRs
            models.UniqueConstraint(
                fields=["utr_number"],
                condition=Q(utr_number__isnull=False) & ~Q(utr_number=""),
                name="unique_non_null_utr_number",
            ),
        ]

    def __str__(self):
        return (
            f"Payment #{self.id} for Booking {self.booking.booking_reference} "
            f"(Attempt {self.attempt_number}) - {self.get_status_display()}"
        )

    @property
    def student(self):
        """Derives the student directly and canonically from the linked booking."""
        return self.booking.student

    @property
    def is_submitted(self) -> bool:
        """Indicates whether the student has submitted payment details."""
        return self.submitted_at is not None

    def clean(self):
        super().clean()
        if self.utr_number:
            self.utr_number = self.utr_number.strip().upper()


class ReceiptSequence(models.Model):
    """
    Database-level atomic sequence tracker for receipt numbering.
    Enforces concurrency safety via SELECT FOR UPDATE row locking.
    """

    year_month = models.CharField(
        max_length=6, primary_key=True, help_text="YYYYMM format (e.g. 202608)"
    )
    last_sequence_number = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Receipt Sequence"
        verbose_name_plural = "Receipt Sequences"

    def __str__(self):
        return f"Sequence {self.year_month}: {self.last_sequence_number}"


class Receipt(models.Model):
    """
    Official sequential receipt generated upon successful payment verification.
    Stores an immutable snapshot of all critical transaction parameters.
    """

    receipt_number = models.CharField(
        max_length=32, unique=True, db_index=True, help_text="Sequential receipt number (e.g. BLL-202608-0042)"
    )
    payment = models.OneToOneField(
        Payment,
        on_delete=models.PROTECT,
        related_name="receipt",
        help_text="The verified payment attempt this receipt is issued for",
    )
    student_name = models.CharField(max_length=150)
    student_phone = models.CharField(max_length=15)
    seat_number = models.PositiveSmallIntegerField()
    membership_start = models.DateTimeField()
    membership_expires_at = models.DateTimeField()
    amount_paid = models.DecimalField(max_digits=8, decimal_places=2)
    payment_mode = models.CharField(max_length=20, default="MANUAL_UPI")
    utr_reference = models.CharField(max_length=64, blank=True)
    issued_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True
    )
    issued_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Receipt"
        verbose_name_plural = "Receipts"
        ordering = ["-issued_at"]

    def __str__(self):
        return f"Receipt {self.receipt_number} (Seat #{self.seat_number} - ₹{self.amount_paid})"
