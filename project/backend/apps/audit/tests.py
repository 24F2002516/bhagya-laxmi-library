from django.test import TestCase
from apps.accounts.models import User
from apps.audit.models import AuditLog


class AuditLogModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="auditor@example.com",
            phone_number="9876543260",
            password="Password123!",
        )

    def test_audit_log_helper_and_fields(self):
        log = AuditLog.log(
            action="SEAT_HELD",
            target_model="Booking",
            target_id="101",
            actor=self.user,
            ip_address="192.168.1.50",
            details={"seat_number": 42},
        )
        self.assertEqual(log.action, "SEAT_HELD")
        self.assertEqual(log.target_model, "Booking")
        self.assertEqual(log.target_id, "101")
        self.assertEqual(log.actor, self.user)
        self.assertEqual(log.details["seat_number"], 42)
        self.assertIn("auditor@example.com -> SEAT_HELD on Booking #101", str(log))
