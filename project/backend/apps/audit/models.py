from django.db import models


class AuditLog(models.Model):
    """
    Immutable system-wide audit trail for security, financial, and operational events.
    """

    actor = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_actions",
        help_text="User who initiated this action",
    )
    action = models.CharField(
        max_length=50,
        db_index=True,
        help_text="Action identifier (e.g. PAYMENT_VERIFIED, SEAT_HELD, SEAT_BOOKED)",
    )
    target_model = models.CharField(
        max_length=50, help_text="Target model name (e.g. Booking, Payment, Seat)"
    )
    target_id = models.CharField(
        max_length=50, help_text="Primary key or reference code of target entity"
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    details = models.JSONField(
        default=dict, help_text="Before/After diff or additional context"
    )
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"
        ordering = ["-timestamp"]

    def __str__(self):
        actor_name = self.actor.email if self.actor else "System"
        return (
            f"[{self.timestamp:%Y-%m-%d %H:%M:%S}] {actor_name} -> "
            f"{self.action} on {self.target_model} #{self.target_id}"
        )

    @classmethod
    def log(
        cls,
        action: str,
        target_model: str,
        target_id: str,
        actor=None,
        ip_address=None,
        details=None,
    ):
        """Helper to create an immutable audit log entry."""
        return cls.objects.create(
            action=action,
            target_model=target_model,
            target_id=str(target_id),
            actor=actor,
            ip_address=ip_address,
            details=details or {},
        )
