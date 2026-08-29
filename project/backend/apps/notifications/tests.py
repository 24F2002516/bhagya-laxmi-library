from django.test import TestCase
from apps.accounts.models import User
from apps.notifications.models import Notification


class NotificationModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="notif@example.com",
            phone_number="9876543270",
            password="Password123!",
        )

    def test_notification_channels_email_and_in_app_only(self):
        notif = Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.Type.BOOKING_CONFIRMED,
            channel=Notification.Channel.EMAIL,
            title="Booking Confirmed",
            message="Your seat allocation is confirmed.",
        )
        self.assertEqual(notif.channel, "EMAIL")
        self.assertFalse(notif.is_read)
        self.assertIn("Booking Confirmed to notif@example.com", str(notif))

        notif.is_read = True
        notif.save()
        notif.refresh_from_db()
        self.assertTrue(notif.is_read)
