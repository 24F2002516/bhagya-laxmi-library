from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from apps.core.models import TimeStampedModel


class Seat(TimeStampedModel):
    """
    Represents physical study seats in Bhagya Laxmi Library.
    Inventory is strictly 150 fixed seats numbered 1 through 150.
    Status reflects physical inventory state only.
    """

    class Status(models.TextChoices):
        AVAILABLE = "AVAILABLE", "Available"
        HELD = "HELD", "Held (Payment Pending)"
        BOOKED = "BOOKED", "Booked (Active Membership)"
        MAINTENANCE = "MAINTENANCE", "Under Maintenance"

    number = models.PositiveSmallIntegerField(unique=True, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.AVAILABLE,
        db_index=True,
    )
    is_active = models.BooleanField(default=True)
    has_power_socket = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Seat"
        verbose_name_plural = "Seats"
        ordering = ["number"]
        constraints = [
            models.CheckConstraint(
                condition=Q(number__gte=1) & Q(number__lte=150),
                name="seat_number_strictly_1_to_150",
            ),
        ]

    def __str__(self):
        return f"Seat #{self.number} ({self.get_status_display()})"

    def clean(self):
        super().clean()
        if self.number < 1 or self.number > 150:
            raise ValidationError("Seat number must be between 1 and 150.")

    def save(self, *args, **kwargs):
        if self.pk:
            # Enforce immutability of physical seat number after creation
            original = Seat.objects.only("number").get(pk=self.pk)
            if original.number != self.number:
                raise ValidationError(
                    f"Seat number is immutable (attempted modification from #{original.number} to #{self.number})."
                )
        else:
            # Enforce maximum physical inventory limit of 150
            if Seat.objects.count() >= 150:
                raise ValidationError("Cannot create more than 150 physical library seats.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Physical library seats are immutable and cannot be deleted.")


class SeatMaintenanceLog(TimeStampedModel):
    """
    Log of maintenance tickets and repairs specific to physical study seats.
    """

    class MaintenanceStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        RESOLVED = "RESOLVED", "Resolved"

    seat = models.ForeignKey(
        Seat, on_delete=models.CASCADE, related_name="maintenance_logs"
    )
    reported_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True
    )
    issue_description = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=MaintenanceStatus.choices,
        default=MaintenanceStatus.PENDING,
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Seat Maintenance Log"
        verbose_name_plural = "Seat Maintenance Logs"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Maintenance on Seat #{self.seat.number} [{self.get_status_display()}]"
