import concurrent.futures
from django.db import connection, transaction
from django.test import TransactionTestCase, tag
from apps.accounts.models import User
from apps.bookings.models import Booking
from apps.bookings.services import initiate_random_seat_booking
from apps.payments.models import Payment
from apps.payments.services import verify_payment_and_activate_membership
from apps.seats.models import Seat


@tag("concurrency")
class PostgresSeatAllocationConcurrencyTests(TransactionTestCase):
    """
    Validates that simultaneous booking attempts under high concurrency
    never allocate the same physical seat to two different students.
    Uses PostgreSQL row-level locking (SELECT FOR UPDATE SKIP LOCKED).
    """

    def setUp(self):
        # Verify test is running on PostgreSQL
        engine = connection.settings_dict.get("ENGINE", "")
        if "postgresql" not in engine and "psycopg" not in engine:
            self.skipTest("Concurrency test requires PostgreSQL row-level locking backend.")

        # In TransactionTestCase, tables are truncated between test methods.
        # Ensure the 150 permanent library seats are initialized.
        if Seat.objects.count() < 150:
            seats = [
                Seat(number=i, status=Seat.Status.AVAILABLE, is_active=True, has_power_socket=True)
                for i in range(1, 151)
            ]
            Seat.objects.bulk_create(seats, ignore_conflicts=True)
        else:
            Seat.objects.all().update(status=Seat.Status.AVAILABLE)

        # Create 10 distinct student users
        self.students = [
            User.objects.create_user(
                email=f"concurrent_student_{i}@example.com",
                phone_number=f"98765430{i:02d}",
                password="Password123!",
            )
            for i in range(1, 11)
        ]
        self.admin = User.objects.create_superuser(
            email="concurrent_admin@example.com",
            phone_number="9876543999",
            password="AdminPassword123!",
        )

    def _attempt_booking(self, student_id):
        connection.close()
        try:
            student = User.objects.get(id=student_id)
            booking = initiate_random_seat_booking(student)
            return {"status": "SUCCESS", "seat_number": booking.seat.number, "booking_id": booking.id}
        except Exception as e:
            return {"status": "FAILED", "error": str(e)}
        finally:
            connection.close()

    def _attempt_verification(self, payment_id):
        connection.close()
        try:
            with transaction.atomic():
                admin = User.objects.get(id=self.admin.id)
                receipt = verify_payment_and_activate_membership(payment_id, admin)
                return {"status": "SUCCESS", "receipt_number": receipt.receipt_number}
        except Exception as e:
            return {"status": "FAILED", "error": str(e)}
        finally:
            connection.close()

    def test_simultaneous_concurrent_seat_allocations_are_strictly_disjoint(self):
        # 10 students simultaneously attempt random seat booking
        allocated_seats = []
        successful_bookings = 0

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(self._attempt_booking, student.id)
                for student in self.students
            ]
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                self.assertEqual(
                    result["status"],
                    "SUCCESS",
                    f"Booking attempt failed: {result.get('error')}",
                )
                successful_bookings += 1
                allocated_seats.append(result["seat_number"])

        # Invariant 1: All 10 bookings succeeded
        self.assertEqual(successful_bookings, len(self.students))

        # Invariant 2: CRITICAL - Every allocated physical seat is distinct
        self.assertEqual(
            len(allocated_seats),
            len(set(allocated_seats)),
            f"Collision detected! Allocated seats: {allocated_seats}",
        )

        # Invariant 3: In database, all 10 seats have physical status = HELD
        held_seats_count = Seat.objects.filter(number__in=allocated_seats, status=Seat.Status.HELD).count()
        self.assertEqual(held_seats_count, len(self.students))

        # Invariant 4: In database, all 10 bookings are PENDING_PAYMENT
        active_bookings_count = Booking.objects.filter(
            seat__number__in=allocated_seats,
            status=Booking.Status.PENDING_PAYMENT,
        ).count()
        self.assertEqual(active_bookings_count, len(self.students))

    def test_concurrent_payment_verifications_generate_collision_free_receipt_numbers(self):
        # Create 5 distinct bookings
        payment_ids = []
        for i in range(5):
            student = self.students[i]
            booking = initiate_random_seat_booking(student)
            payment = Payment.objects.get(booking=booking)
            payment.utr_number = f"UTR-CONCURRENT-{i}"
            payment.save()
            payment_ids.append(payment.id)

        # Concurrently verify all 5 payments across 5 worker threads
        receipt_numbers = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(self._attempt_verification, pid)
                for pid in payment_ids
            ]
            for future in concurrent.futures.as_completed(futures):
                res = future.result()
                self.assertEqual(res["status"], "SUCCESS", f"Verification failed: {res.get('error')}")
                receipt_numbers.append(res["receipt_number"])

        # All 5 receipt numbers must be strictly unique
        self.assertEqual(len(receipt_numbers), 5)
        self.assertEqual(
            len(receipt_numbers),
            len(set(receipt_numbers)),
            f"Receipt number collision detected! Numbers: {receipt_numbers}",
        )
