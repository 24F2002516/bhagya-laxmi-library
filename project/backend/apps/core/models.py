from django.db import models


class TimeStampedModel(models.Model):
    """
    An abstract base class model that provides self-updating
    ``created_at`` and ``updated_at`` fields.
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SystemSetting(models.Model):
    """
    Key-value store for runtime dynamic configuration
    (e.g., SEAT_HOLD_DURATION_MINUTES, UPI_VPA, UPI_QR_IMAGE, MAINTENANCE_BANNER).
    """

    key = models.CharField(max_length=64, primary_key=True)
    value = models.TextField()
    description = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "System Setting"
        verbose_name_plural = "System Settings"
        ordering = ["key"]

    def __str__(self):
        return f"{self.key}: {self.value}"

    @classmethod
    def get_setting(cls, key: str, default: str = "") -> str:
        """Helper to fetch a setting value by key with a fallback default."""
        try:
            return cls.objects.get(key=key).value
        except cls.DoesNotExist:
            return default
