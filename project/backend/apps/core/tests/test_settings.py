from django.test import TestCase
from apps.core.models import SystemSetting


class SystemSettingTests(TestCase):
    def test_get_setting_fallback_and_override(self):
        # Fallback when key does not exist
        value = SystemSetting.get_setting("NON_EXISTENT_KEY", default="default_val")
        self.assertEqual(value, "default_val")

        # Create setting
        SystemSetting.objects.create(
            key="SEAT_HOLD_DURATION_MINUTES",
            value="45",
            description="Temporary hold duration in minutes",
        )
        fetched = SystemSetting.get_setting("SEAT_HOLD_DURATION_MINUTES")
        self.assertEqual(fetched, "45")
