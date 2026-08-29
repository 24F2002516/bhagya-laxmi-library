from datetime import timedelta
from decimal import Decimal
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from apps.accounts.models import User, StudentProfile
from apps.bookings.services import initiate_random_seat_booking
from apps.payments.exceptions import InvalidPaymentStateException
from apps.payments.models import Payment
from apps.payments.services import (
    generate_sequential_receipt_number,
    submit_payment_proof,
    verify_payment_and_activate_membership,
    reject_payment_attempt,
)
from apps.seats.models import Seat


class PaymentServiceAndModelTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin@example.com",
            phone_number="9876543290",
            password="AdminPassword123!",
        )
        self.student = User.objects.create_user(
            email="student@example.com",
            phone_number="9876543291",
            password="Password123!",
        )
        StudentProfile.objects.create(
            user=self.student,
            full_name="Pooja Sharma",
            document_type="College ID",
            document_number="ENG-2024-001",
        )
        self.booking = initiate_random_seat_booking(self.student)
        self.payment = Payment.objects.get(booking=self.booking)

    def test_payment_derived_student_property(self):
        self.assertEqual(self.payment.student, self.student)

    def test_fixed_fee_800_check_constraint(self):
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Payment.objects.create(
                    booking=self.booking,
                    attempt_number=2,
                    amount=Decimal("500.00"),  # Invalid amount
                    payment_mode=Payment.Mode.MANUAL_UPI,
                )

    def test_attempt_number_unique_per_booking(self):
        # Attempt 1 already exists
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Payment.objects.create(
                    booking=self.booking,
                    attempt_number=1,  # Duplicate attempt number
                    amount=Decimal("800.00"),
                    payment_mode=Payment.Mode.MANUAL_UPI,
                )

    def test_single_pending_payment_per_booking_constraint(self):
        # Payment attempt 1 is already in PENDING_VERIFICATION
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Payment.objects.create(
                    booking=self.booking,
                    attempt_number=2,
                    amount=Decimal("800.00"),
                    payment_mode=Payment.Mode.MANUAL_UPI,
                    status=Payment.Status.PENDING_VERIFICATION,
                )

    def test_conditional_unique_utr_constraint(self):
        # 1. Multiple NULL/empty UTRs are allowed
        p1 = self.payment
        p1.utr_number = "123456789012"
        p1.save()

        # Reject p1 so we can create attempt 2
        reject_payment_attempt(p1.id, self.admin, "Blurry screenshot")

        # Creating attempt 2 with duplicate UTR fails
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Payment.objects.create(
                    booking=self.booking,
                    attempt_number=2,
                    amount=Decimal("800.00"),
                    payment_mode=Payment.Mode.MANUAL_UPI,
                    utr_number="123456789012",  # Duplicate UTR
                    status=Payment.Status.PENDING_VERIFICATION,
                )

    def test_submit_payment_proof_success(self):
        self.assertIsNone(self.payment.submitted_at)
        submitted_payment = submit_payment_proof(
            payment_id=self.payment.id,
            student=self.student,
            utr_number="123456789012",
        )
        self.assertEqual(submitted_payment.utr_number, "123456789012")
        self.assertIsNotNone(submitted_payment.submitted_at)
        self.assertTrue(submitted_payment.is_submitted)

    def test_submit_payment_proof_after_hold_expiry_rejected(self):
        # Shift hold into the past
        self.booking.hold_created_at = timezone.now() - timedelta(minutes=40)
        self.booking.hold_expires_at = timezone.now() - timedelta(minutes=10)
        self.booking.save(update_fields=["hold_created_at", "hold_expires_at"])

        with self.assertRaises(InvalidPaymentStateException) as ctx:
            submit_payment_proof(
                payment_id=self.payment.id,
                student=self.student,
                utr_number="123456789012",
            )
        self.assertIn("hold has expired", str(ctx.exception))

    def test_verify_payment_activates_membership_and_creates_receipt(self):
        self.payment.utr_number = "UPI-UTR-99887766"
        self.payment.submitted_at = timezone.now()
        self.payment.save()

        receipt = verify_payment_and_activate_membership(self.payment.id, self.admin)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.VERIFIED)
        self.assertEqual(self.payment.verified_by, self.admin)
        self.assertIsNotNone(self.payment.verified_at)

        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, "CONFIRMED")
        self.assertIsNotNone(self.booking.membership_start)
        self.assertIsNotNone(self.booking.membership_expires_at)
        self.assertIsNotNone(self.booking.grace_until)

        # Check exact 30-day and 48-hour calculation
        diff_days = (self.booking.membership_expires_at - self.booking.membership_start).days
        self.assertEqual(diff_days, 30)
        grace_hours = (self.booking.grace_until - self.booking.membership_expires_at).total_seconds() / 3600.0
        self.assertEqual(grace_hours, 48.0)

        # Seat is now BOOKED
        seat = Seat.objects.get(id=self.booking.seat_id)
        self.assertEqual(seat.status, Seat.Status.BOOKED)

        # Receipt verified
        self.assertEqual(receipt.payment, self.payment)
        self.assertEqual(receipt.student_name, "Pooja Sharma")
        self.assertEqual(receipt.student_phone, "9876543291")
        self.assertEqual(receipt.seat_number, seat.number)
        self.assertEqual(receipt.amount_paid, Decimal("800.00"))
        self.assertEqual(receipt.utr_reference, "UPI-UTR-99887766")
        self.assertTrue(receipt.receipt_number.startswith("BLL-"))

    def test_reject_payment_attempt_and_retry_flow(self):
        self.payment.utr_number = "INVALID-UTR"
        self.payment.save()

        rejected_payment = reject_payment_attempt(
            self.payment.id, self.admin, "UTR not credited in bank"
        )
        self.assertEqual(rejected_payment.status, Payment.Status.REJECTED)
        self.assertEqual(rejected_payment.rejection_reason, "UTR not credited in bank")

        # Booking is cancelled when no other pending attempt exists
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, "CANCELLED")

        # Seat released back to AVAILABLE
        seat = Seat.objects.get(id=self.booking.seat_id)
        self.assertEqual(seat.status, Seat.Status.AVAILABLE)

    def test_concurrent_receipt_numbering_sequential(self):
        with transaction.atomic():
            r1 = generate_sequential_receipt_number()
            r2 = generate_sequential_receipt_number()
            r3 = generate_sequential_receipt_number()

        self.assertNotEqual(r1, r2)
        self.assertNotEqual(r2, r3)
        prefix = timezone.now().strftime("BLL-%Y%m-")
        self.assertTrue(r1.startswith(prefix))
        self.assertTrue(r2.startswith(prefix))
        self.assertTrue(r3.startswith(prefix))
        seq1 = int(r1.split("-")[-1])
        seq2 = int(r2.split("-")[-1])
        seq3 = int(r3.split("-")[-1])
        self.assertEqual(seq2, seq1 + 1)
        self.assertEqual(seq3, seq2 + 1)
