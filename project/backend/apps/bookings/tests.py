from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.bookings.exceptions import StudentAlreadyHasActiveBookingException
from apps.bookings.models import Booking
from apps.bookings.services import (
    initiate_random_seat_booking,
    process_expired_seat_holds,
    process_expired_grace_periods,
    process_renewal_reminders,
)
from apps.notifications.models import Notification
from apps.payments.models import Payment
from apps.seats.models import Seat


class BookingServiceAndModelTests(TestCase):
    def setUp(self):
        self.student1 = User.objects.create_user(
            email="student1@example.com",
            phone_number="9876543201",
            password="Password123!",
        )
        self.student2 = User.objects.create_user(
            email="student2@example.com",
            phone_number="9876543202",
            password="Password123!",
        )

    def test_random_seat_allocation_initiates_hold(self):
        booking = initiate_random_seat_booking(self.student1)

        self.assertEqual(booking.student, self.student1)
        self.assertEqual(booking.status, Booking.Status.PENDING_PAYMENT)
        self.assertIsNone(booking.membership_start)
        self.assertIsNone(booking.membership_expires_at)
        self.assertIsNone(booking.grace_until)
        self.assertGreater(
            booking.hold_expires_at,
            booking.hold_created_at,
        )

        # Physical seat transitioned to HELD
        seat = Seat.objects.get(id=booking.seat_id)
        self.assertEqual(seat.status, Seat.Status.HELD)

        # Payment Attempt 1 created
        payment = Payment.objects.get(booking=booking)
        self.assertEqual(payment.attempt_number, 1)
        self.assertEqual(
            payment.status,
            Payment.Status.PENDING_VERIFICATION,
        )
        self.assertEqual(payment.amount, 800.00)

    def test_booking_uses_configured_30_minute_hold_duration(self):
        booking = initiate_random_seat_booking(self.student1)

        duration = (
            booking.hold_expires_at - booking.hold_created_at
        ).total_seconds()

        self.assertEqual(duration, 30 * 60)

    def test_student_cannot_create_multiple_active_bookings(self):
        initiate_random_seat_booking(self.student1)

        # Service-level check blocks second booking
        with self.assertRaises(StudentAlreadyHasActiveBookingException):
            initiate_random_seat_booking(self.student1)

    def test_database_partial_unique_constraint_per_seat(self):
        booking1 = initiate_random_seat_booking(self.student1)

        # Attempt to bypass service and insert active booking on same seat
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Booking.objects.create(
                    booking_reference="BKG-DUPLICATE-SEAT",
                    student=self.student2,
                    seat=booking1.seat,
                    hold_created_at=timezone.now(),
                    hold_expires_at=timezone.now() + timedelta(minutes=30),
                    status=Booking.Status.PENDING_PAYMENT,
                )

    def test_database_partial_unique_constraint_per_student(self):
        initiate_random_seat_booking(self.student1)

        available_seat = Seat.objects.filter(
            status=Seat.Status.AVAILABLE
        ).first()

        # Attempt to bypass service and insert second active booking
        # for the same student
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Booking.objects.create(
                    booking_reference="BKG-DUPLICATE-STUDENT",
                    student=self.student1,
                    seat=available_seat,
                    hold_created_at=timezone.now(),
                    hold_expires_at=timezone.now() + timedelta(minutes=30),
                    status=Booking.Status.PENDING_PAYMENT,
                )

    def test_process_expired_seat_holds_releases_seat(self):
        booking = initiate_random_seat_booking(self.student1)
        seat = booking.seat

        # Fast-forward hold window to the past while respecting
        # hold_expires_at > hold_created_at
        booking.hold_created_at = timezone.now() - timedelta(minutes=40)
        booking.hold_expires_at = timezone.now() - timedelta(minutes=10)
        booking.save(
            update_fields=[
                "hold_created_at",
                "hold_expires_at",
            ]
        )

        released = process_expired_seat_holds()
        self.assertEqual(released, 1)

        booking.refresh_from_db()
        self.assertEqual(
            booking.status,
            Booking.Status.CANCELLED,
        )
        self.assertFalse(booking.is_active)

        seat.refresh_from_db()
        self.assertEqual(
            seat.status,
            Seat.Status.AVAILABLE,
        )

        payment = Payment.objects.get(booking=booking)
        self.assertEqual(
            payment.status,
            Payment.Status.REJECTED,
        )

    def test_process_expired_grace_period_releases_seat(self):
        booking = initiate_random_seat_booking(self.student1)
        seat = booking.seat

        # Simulate confirmed booking that expired and passed 48h grace
        now = timezone.now()

        booking.status = Booking.Status.GRACE_PERIOD
        booking.membership_start = now - timedelta(days=33)
        booking.membership_expires_at = now - timedelta(days=3)
        booking.grace_until = now - timedelta(hours=1)
        booking.save()

        seat.status = Seat.Status.BOOKED
        seat.save()

        released = process_expired_grace_periods()
        self.assertEqual(released, 1)

        booking.refresh_from_db()
        self.assertEqual(
            booking.status,
            Booking.Status.EXPIRED,
        )
        self.assertFalse(booking.is_active)

        seat.refresh_from_db()
        self.assertEqual(
            seat.status,
            Seat.Status.AVAILABLE,
        )

    def test_process_renewal_reminders_at_4d_and_3d(self):
        booking = initiate_random_seat_booking(self.student1)
        now = timezone.now()

        # Simulate confirmed booking expiring in 3.5 days
        # (Day T-4 window)
        booking.status = Booking.Status.CONFIRMED
        booking.membership_start = now - timedelta(days=26, hours=12)
        booking.membership_expires_at = now + timedelta(days=3, hours=12)
        booking.grace_until = (
            booking.membership_expires_at + timedelta(hours=48)
        )
        booking.save()

        # 1st run: 4-day reminder sent
        count = process_renewal_reminders()
        self.assertEqual(count, 1)

        booking.refresh_from_db()
        self.assertEqual(
            booking.status,
            Booking.Status.EXPIRING_SOON,
        )
        self.assertIsNotNone(
            booking.reminder_4d_sent_at
        )
        self.assertIsNone(
            booking.reminder_3d_sent_at
        )

        self.assertTrue(
            Notification.objects.filter(
                recipient=self.student1,
                notification_type=(
                    Notification.Type.RENEWAL_REMINDER_4D
                ),
            ).exists()
        )

        # Fast-forward to 2.5 days remaining
        # (Day T-3 window)
        booking.membership_expires_at = (
            now + timedelta(days=2, hours=12)
        )
        booking.save(
            update_fields=["membership_expires_at"]
        )

        # 2nd run: 3-day reminder sent
        count = process_renewal_reminders()
        self.assertEqual(count, 1)

        booking.refresh_from_db()
        self.assertIsNotNone(
            booking.reminder_3d_sent_at
        )

        self.assertTrue(
            Notification.objects.filter(
                recipient=self.student1,
                notification_type=(
                    Notification.Type.RENEWAL_REMINDER_3D
                ),
            ).exists()
        )

    def test_submitted_payment_proof_protects_seat_from_hold_expiry(self):
        booking = initiate_random_seat_booking(self.student1)
        seat = booking.seat
        payment = Payment.objects.get(booking=booking)

        # Student submits payment proof
        payment.utr_number = "SUBMITTED-UTR-1234"
        payment.submitted_at = timezone.now()
        payment.save()

        # Hold window passes into the past
        booking.hold_created_at = timezone.now() - timedelta(minutes=40)
        booking.hold_expires_at = timezone.now() - timedelta(minutes=10)
        booking.save(
            update_fields=[
                "hold_created_at",
                "hold_expires_at",
            ]
        )

        # Hold reaper must NOT release this seat because
        # payment proof was submitted
        released = process_expired_seat_holds()
        self.assertEqual(released, 0)

        booking.refresh_from_db()
        self.assertEqual(
            booking.status,
            Booking.Status.PENDING_PAYMENT,
        )
        self.assertTrue(booking.is_active)

        seat.refresh_from_db()
        self.assertEqual(
            seat.status,
            Seat.Status.HELD,
        )

    def test_authoritative_countdown_timer_properties(self):
        booking = initiate_random_seat_booking(self.student1)

        self.assertFalse(booking.is_hold_expired)
        self.assertGreater(
            booking.remaining_hold_seconds,
            0,
        )
        self.assertFalse(
            booking.has_submitted_payment_proof
        )

        payment = Payment.objects.get(booking=booking)
        payment.submitted_at = timezone.now()
        payment.save()

        self.assertTrue(
            booking.has_submitted_payment_proof
        )