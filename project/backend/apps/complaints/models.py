from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q
from apps.core.models import TimeStampedModel


class Complaint(TimeStampedModel):
    """
    Desk and facility complaint tickets submitted by students.
    """

    class Category(models.TextChoices):
        AC_COOLING = "AC_COOLING", "AC / Cooling & Temperature"
        CHAIR_DESK = "CHAIR_DESK", "Chair / Desk Furniture"
        POWER_SOCKET = "POWER_SOCKET", "Power Socket / Electrical"
        LIGHTING = "LIGHTING", "Lighting"
        WIFI_INTERNET = "WIFI_INTERNET", "WiFi / Internet"
        NOISE = "NOISE", "Noise / Discipline"
        CLEANLINESS = "CLEANLINESS", "Cleanliness & Hygiene"
        OTHER = "OTHER", "Other Issue"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        RESOLVED = "RESOLVED", "Resolved"
        CLOSED = "CLOSED", "Closed"

    ticket_number = models.CharField(
        max_length=32, unique=True, db_index=True, help_text="Unique ticket identifier (e.g. TKT-202608-0012)"
    )
    student = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="complaints"
    )
    seat = models.ForeignKey(
        "seats.Seat",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="complaints",
        help_text="Associated study seat (optional if complaint is for general amenities)",
    )
    category = models.CharField(
        max_length=30, choices=Category.choices, default=Category.OTHER
    )
    title = models.CharField(max_length=200)
    description = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )
    resolution_notes = models.TextField(
        blank=True, help_text="Notes recorded by admin upon investigating/resolving"
    )
    resolved_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_complaints",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Complaint"
        verbose_name_plural = "Complaints"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Ticket {self.ticket_number} [{self.get_category_display()}] - {self.get_status_display()}"


class Feedback(TimeStampedModel):
    """
    General feedback submitted by students regarding library amenities and services.
    Separate from specific desk/maintenance complaints.
    """

    class Category(models.TextChoices):
        GENERAL = "GENERAL", "General Experience"
        STUDY_ENVIRONMENT = "STUDY_ENVIRONMENT", "Study Environment & Silence"
        AIR_CONDITIONING = "AIR_CONDITIONING", "AC & Temperature"
        CLEANLINESS = "CLEANLINESS", "Cleanliness & Hygiene"
        WIFI_FACILITY = "WIFI_FACILITY", "WiFi & Digital Facilities"
        STAFF_SUPPORT = "STAFF_SUPPORT", "Staff & Management Support"
        OTHER = "OTHER", "Other"

    student = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="feedbacks"
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Rating from 1 (poor) to 5 (excellent)",
    )
    category = models.CharField(
        max_length=50, choices=Category.choices, default=Category.GENERAL
    )
    description = models.TextField(help_text="Detailed feedback or suggestions")
    is_reviewed = models.BooleanField(
        default=False, db_index=True, help_text="Flag indicating if admin has reviewed this feedback"
    )
    admin_notes = models.TextField(blank=True, help_text="Internal notes by admin")
    reviewed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_feedbacks",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Feedback"
        verbose_name_plural = "Feedbacks"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(rating__gte=1) & Q(rating__lte=5),
                name="feedback_rating_between_1_and_5",
            ),
        ]

    def __str__(self):
        return f"Feedback from {self.student.email} [{self.rating}/5 - {self.get_category_display()}]"
