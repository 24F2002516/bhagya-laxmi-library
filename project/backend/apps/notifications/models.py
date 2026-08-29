from django.db import models


class Notification(models.Model):
    """
    Log and delivery status of automated notifications (Email and In-App only).
    """

    class Type(models.TextChoices):
        RENEWAL_REMINDER_4D = "RENEWAL_REMINDER_4D", "Renewal Reminder (4 Days Before Expiry)"
        RENEWAL_REMINDER_3D = "RENEWAL_REMINDER_3D", "Renewal Reminder (3 Days Before Expiry)"
        GRACE_WARNING = "GRACE_WARNING", "Grace Period Warning"
        PAYMENT_VERIFIED = "PAYMENT_VERIFIED", "Payment Verified & Membership Activated"
        PAYMENT_REJECTED = "PAYMENT_REJECTED", "Payment Rejected"
        BOOKING_CONFIRMED = "BOOKING_CONFIRMED", "Seat Booking Confirmed"
        SEAT_RELEASED = "SEAT_RELEASED", "Seat Auto-Released"
        COMPLAINT_UPDATE = "COMPLAINT_UPDATE", "Complaint Status Update"

    class Channel(models.TextChoices):
        EMAIL = "EMAIL", "Email"
        IN_APP = "IN_APP", "In-App Notification"

    recipient = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="notifications"
    )
    notification_type = models.CharField(max_length=40, choices=Type.choices)
    channel = models.CharField(max_length=20, choices=Channel.choices, default=Channel.EMAIL)
    title = models.CharField(max_length=255)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.get_channel_display()}] {self.title} to {self.recipient.email}"
