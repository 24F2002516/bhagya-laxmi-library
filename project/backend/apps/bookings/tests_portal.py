from datetime import timedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import StudentProfile, User
from apps.bookings.models import Booking
from apps.complaints.models import Complaint, Feedback
from apps.payments.models import Payment
from apps.seats.models import Seat


class StudentPortalAuthorizationTests(TestCase):
    def test_unauthenticated_dashboard_redirects_to_login(self):
        response = self.client.get(reverse("portal:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_unauthenticated_profile_redirects_to_login(self):
        response = self.client.get(reverse("portal:profile"))
        self.assertEqual(response.status_code, 302)

    def test_unauthenticated_complaints_redirects_to_login(self):
        response = self.client.get(reverse("portal:complaints"))
        self.assertEqual(response.status_code, 302)

    def test_unauthenticated_feedback_redirects_to_login(self):
        response = self.client.get(reverse("portal:feedback"))
        self.assertEqual(response.status_code, 302)

    def test_unauthenticated_history_redirects_to_login(self):
        response = self.client.get(reverse("portal:history"))
        self.assertEqual(response.status_code, 302)


class StudentPortalDashboardAndBookingTests(TestCase):
    def setUp(self):
        if Seat.objects.count() < 150:
            seats = [
                Seat(number=i, status=Seat.Status.AVAILABLE, is_active=True, has_power_socket=True)
                for i in range(1, 151)
            ]
            Seat.objects.bulk_create(seats, ignore_conflicts=True)

        self.student = User.objects.create_user(
            email="portal_student1@example.com",
            phone_number="9876511111",
            password="Password123!",
        )
        self.profile = StudentProfile.objects.create(
            user=self.student, full_name="Portal Student One", address="Suratgarh"
        )
        self.client.force_login(self.student)

    def test_dashboard_renders_for_student_without_booking(self):
        response = self.client.get(reverse("portal:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Welcome, Portal Student One")
        self.assertContains(response, "Book My Seat")
        self.assertContains(response, "None Allocated")

    def test_book_seat_view_allocates_seat_and_initiates_hold(self):
        response = self.client.post(reverse("portal:book_seat"))
        self.assertEqual(response.status_code, 302)

        # Invariant 1: Booking is created in PENDING_PAYMENT
        booking = Booking.objects.get(student=self.student, is_active=True)
        self.assertEqual(booking.status, Booking.Status.PENDING_PAYMENT)
        self.assertIsNotNone(booking.hold_expires_at)

        # Invariant 2: Physical seat is set to HELD
        self.assertEqual(booking.seat.status, Seat.Status.HELD)

        # Invariant 3: Payment attempt 1 is created
        payment = Payment.objects.get(booking=booking)
        self.assertEqual(payment.status, Payment.Status.PENDING_VERIFICATION)
        self.assertIsNone(payment.submitted_at)

        # Invariant 4: Dashboard displays allocated seat
        dash_resp = self.client.get(reverse("portal:dashboard"))
        self.assertEqual(dash_resp.status_code, 200)
        self.assertContains(dash_resp, f"Seat #{booking.seat.number}")
        self.assertContains(dash_resp, "Seat Allocation In Progress")
        self.assertContains(dash_resp, "Submit Payment Details")

    def test_student_cannot_book_multiple_active_seats(self):
        # First booking succeeds
        self.client.post(reverse("portal:book_seat"))
        self.assertEqual(Booking.objects.filter(student=self.student).count(), 1)

        # Second booking request is rejected with warning
        response = self.client.post(reverse("portal:book_seat"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Booking.objects.filter(student=self.student).count(), 1)


class StudentPortalPaymentSubmissionTests(TestCase):
    def setUp(self):
        if Seat.objects.count() < 150:
            seats = [
                Seat(number=i, status=Seat.Status.AVAILABLE, is_active=True, has_power_socket=True)
                for i in range(1, 151)
            ]
            Seat.objects.bulk_create(seats, ignore_conflicts=True)

        self.student1 = User.objects.create_user(
            email="payment_student1@example.com",
            phone_number="9876522221",
            password="Password123!",
        )
        StudentProfile.objects.create(user=self.student1, full_name="Student One")

        self.student2 = User.objects.create_user(
            email="payment_student2@example.com",
            phone_number="9876522222",
            password="Password123!",
        )
        StudentProfile.objects.create(user=self.student2, full_name="Student Two")

    def test_submit_payment_proof_view(self):
        self.client.force_login(self.student1)
        self.client.post(reverse("portal:book_seat"))
        booking = Booking.objects.get(student=self.student1)
        payment = Payment.objects.get(booking=booking)

        # Student 1 submits UTR
        response = self.client.post(
            reverse("portal:submit_payment", kwargs={"payment_id": payment.id}),
            {"utr_number": "UTR998877665544"},
        )
        self.assertEqual(response.status_code, 302)

        payment.refresh_from_db()
        self.assertEqual(payment.utr_number, "UTR998877665544")
        self.assertIsNotNone(payment.submitted_at)
        self.assertTrue(payment.is_submitted)

        # Dashboard shows submitted status and hides the submission form
        dash_resp = self.client.get(reverse("portal:dashboard"))
        self.assertEqual(dash_resp.status_code, 200)
        self.assertContains(dash_resp, "Payment Proof Submitted")
        self.assertContains(dash_resp, "UTR998877665544")
        self.assertNotContains(dash_resp, "Submit Payment Details")

    def test_student_cannot_submit_payment_for_another_students_booking(self):
        # Student 1 books seat
        self.client.force_login(self.student1)
        self.client.post(reverse("portal:book_seat"))
        booking1 = Booking.objects.get(student=self.student1)
        payment1 = Payment.objects.get(booking=booking1)

        # Student 2 logs in and tries to submit payment for Student 1's payment_id (IDOR attempt)
        self.client.force_login(self.student2)
        response = self.client.post(
            reverse("portal:submit_payment", kwargs={"payment_id": payment1.id}),
            {"utr_number": "MALICIOUS_UTR_123"},
        )
        # Must return 404
        self.assertEqual(response.status_code, 404)

    def test_expired_hold_renders_expired_panel_and_disables_payment_form(self):
        self.client.force_login(self.student1)
        self.client.post(reverse("portal:book_seat"))
        booking = Booking.objects.get(student=self.student1)

        # Force hold to be in the past without payment proof (maintaining hold_expires_at > hold_created_at constraint)
        booking.hold_created_at = timezone.now() - timedelta(minutes=35)
        booking.hold_expires_at = timezone.now() - timedelta(minutes=5)
        booking.save(update_fields=["hold_created_at", "hold_expires_at"])

        dash_resp = self.client.get(reverse("portal:dashboard"))
        self.assertEqual(dash_resp.status_code, 200)
        self.assertContains(dash_resp, "Your Seat Hold Has Expired")
        self.assertContains(dash_resp, "Book Another Seat")
        self.assertContains(dash_resp, "00:00")
        self.assertNotContains(dash_resp, "Submit Payment Details")

    def test_submit_payment_after_hold_expiry_is_rejected_by_backend(self):
        self.client.force_login(self.student1)
        self.client.post(reverse("portal:book_seat"))
        booking = Booking.objects.get(student=self.student1)
        payment = Payment.objects.get(booking=booking)

        # Expire hold
        booking.hold_created_at = timezone.now() - timedelta(minutes=35)
        booking.hold_expires_at = timezone.now() - timedelta(minutes=5)
        booking.save(update_fields=["hold_created_at", "hold_expires_at"])

        # Attempt to submit payment proof for expired hold
        response = self.client.post(
            reverse("portal:submit_payment", kwargs={"payment_id": payment.id}),
            {"utr_number": "LATE_UTR_123456"},
        )
        self.assertEqual(response.status_code, 302)

        payment.refresh_from_db()
        self.assertIsNone(payment.submitted_at)
        self.assertFalse(payment.is_submitted)

    def test_submitted_payment_proof_protects_hold_from_expired_ui(self):
        self.client.force_login(self.student1)
        self.client.post(reverse("portal:book_seat"))
        booking = Booking.objects.get(student=self.student1)
        payment = Payment.objects.get(booking=booking)

        # Submit valid payment proof before expiry
        self.client.post(
            reverse("portal:submit_payment", kwargs={"payment_id": payment.id}),
            {"utr_number": "VALID_UTR_123456"},
        )

        # Even after time passes past hold_expires_at, hold is protected
        booking.hold_created_at = timezone.now() - timedelta(minutes=35)
        booking.hold_expires_at = timezone.now() - timedelta(minutes=5)
        booking.save(update_fields=["hold_created_at", "hold_expires_at"])

        dash_resp = self.client.get(reverse("portal:dashboard"))
        self.assertEqual(dash_resp.status_code, 200)
        self.assertContains(dash_resp, "Payment Proof Submitted")
        self.assertContains(dash_resp, "UTR Submitted")
        self.assertContains(dash_resp, "Awaiting Admin Verification")
        self.assertNotContains(dash_resp, "id=\"hold-expired-panel\"")
        self.assertNotContains(dash_resp, "Submit Payment Details")

    def test_book_another_seat_after_hold_expiry_allocates_new_seat(self):
        self.client.force_login(self.student1)
        self.client.post(reverse("portal:book_seat"))
        booking1 = Booking.objects.get(student=self.student1, is_active=True)

        # Expire hold
        booking1.hold_created_at = timezone.now() - timedelta(minutes=35)
        booking1.hold_expires_at = timezone.now() - timedelta(minutes=5)
        booking1.save(update_fields=["hold_created_at", "hold_expires_at"])

        # Student clicks "Book Another Seat" (POST to portal:book_seat)
        response = self.client.post(reverse("portal:book_seat"))
        self.assertEqual(response.status_code, 302)

        # Inactive old booking was cancelled and freed
        booking1.refresh_from_db()
        self.assertEqual(booking1.status, Booking.Status.CANCELLED)
        self.assertFalse(booking1.is_active)

        # New active booking is present
        new_booking = Booking.objects.get(student=self.student1, is_active=True)
        self.assertNotEqual(new_booking.id, booking1.id)
        self.assertEqual(new_booking.status, Booking.Status.PENDING_PAYMENT)
        self.assertFalse(new_booking.is_hold_expired)


class StudentPortalProfileAndFeedbackTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            email="profile_student@example.com",
            phone_number="9876533331",
            password="Password123!",
        )
        self.profile = StudentProfile.objects.create(
            user=self.student,
            full_name="Initial Name",
            address="Initial Address",
        )
        self.client.force_login(self.student)

    def test_profile_update_successful(self):
        response = self.client.post(
            reverse("portal:profile"),
            {
                "full_name": "Updated Name",
                "phone_number": "9876533332",
                "address": "Updated Address in Suratgarh",
                "document_type": "Aadhaar Card",
                "document_number": "9999-8888-7777",
                "emergency_contact_name": "Father Name",
                "emergency_contact_phone": "9876533399",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.full_name, "Updated Name")
        self.assertEqual(self.profile.address, "Updated Address in Suratgarh")
        self.student.refresh_from_db()
        self.assertEqual(self.student.phone_number, "9876533332")

    def test_student_can_submit_complaint(self):
        response = self.client.post(
            reverse("portal:complaints"),
            {
                "category": "POWER_SOCKET",
                "title": "Socket loose at my desk",
                "description": "The laptop charger plug is slightly loose at desk.",
            },
        )
        self.assertEqual(response.status_code, 302)
        complaint = Complaint.objects.get(student=self.student)
        self.assertEqual(complaint.category, "POWER_SOCKET")
        self.assertEqual(complaint.title, "Socket loose at my desk")
        self.assertEqual(complaint.status, "OPEN")
        self.assertTrue(complaint.ticket_number.startswith("TKT-"))

    def test_student_can_submit_feedback(self):
        response = self.client.post(
            reverse("portal:feedback"),
            {
                "rating": 5,
                "category": "STUDY_ENVIRONMENT",
                "description": "Very quiet and peaceful environment for study.",
            },
        )
        self.assertEqual(response.status_code, 302)
        feedback = Feedback.objects.get(student=self.student)
        self.assertEqual(feedback.rating, 5)
        self.assertEqual(feedback.category, "STUDY_ENVIRONMENT")


class LandingPageTests(TestCase):
    def test_landing_page_renders_address_and_google_maps_link(self):
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bhagya Laxmi Library")
        self.assertContains(response, "Ward No. 3, Near Guru Tegh Bahadur Gurudwara")
        self.assertContains(response, "Bishnoi Mohalla")
        self.assertContains(response, "Suratgarh, Rajasthan – 335804")
        self.assertContains(response, "https://maps.app.goo.gl/97AWQim1UCMHrpTR9?g_st=aw")
        self.assertContains(response, "150 Fixed AC Seats")
        self.assertContains(response, "₹800 for 30 Days")
