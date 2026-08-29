from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import TestCase
from apps.accounts.models import User
from apps.seats.models import Seat, SeatMaintenanceLog


class SeatModelTests(TestCase):
    def test_exactly_150_seats_exist(self):
        self.assertEqual(Seat.objects.count(), 150)

    def test_seat_numbers_range_1_to_150(self):
        seat_numbers = set(Seat.objects.values_list("number", flat=True))
        expected_numbers = set(range(1, 151))
        self.assertEqual(seat_numbers, expected_numbers)

    def test_seat_number_immutability(self):
        seat_42 = Seat.objects.get(number=42)
        seat_42.number = 99
        with self.assertRaises(ValidationError) as ctx:
            seat_42.save()
        self.assertIn("Seat number is immutable", str(ctx.exception))

    def test_seat_deletion_prohibited(self):
        seat_1 = Seat.objects.get(number=1)
        with self.assertRaises(ValidationError) as ctx:
            seat_1.delete()
        self.assertIn("immutable and cannot be deleted", str(ctx.exception))

    def test_cannot_create_seat_beyond_150(self):
        # Database already has 150 seats, adding 151st is blocked
        new_seat = Seat(number=151, status=Seat.Status.AVAILABLE)
        with self.assertRaises(ValidationError):
            new_seat.save()

    def test_duplicate_seat_number_rejected(self):
        # Trying to save with duplicate number
        with transaction.atomic():
            with self.assertRaises(ValidationError):
                Seat(number=1, status=Seat.Status.AVAILABLE).save()

    def test_seat_maintenance_log_creation(self):
        user = User.objects.create_user(
            email="tech@example.com",
            phone_number="9876543233",
            password="Password123!",
        )
        seat = Seat.objects.get(number=10)
        log = SeatMaintenanceLog.objects.create(
            seat=seat,
            reported_by=user,
            issue_description="Power socket loose",
            status=SeatMaintenanceLog.MaintenanceStatus.IN_PROGRESS,
        )
        self.assertEqual(log.seat.number, 10)
        self.assertEqual(log.status, "IN_PROGRESS")
        self.assertIn("Maintenance on Seat #10", str(log))
