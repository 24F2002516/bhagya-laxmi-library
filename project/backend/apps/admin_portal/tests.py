from datetime import timedelta

from django.test import TestCase
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch

from apps.accounts.models import StudentProfile, User
from apps.bookings.models import Booking
from apps.bookings.services import initiate_random_seat_booking
from apps.payments.models import Payment
from apps.payments.services import verify_payment_and_activate_membership
from apps.seats.models import Seat


class AdminPortalTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="owner@example.com",
            phone_number="9876500000",
            password="AdminPassword123!",
        )
        self.student = User.objects.create_user(
            email="student@example.com",
            phone_number="9876500001",
            password="StudentPassword123!",
        )
        StudentProfile.objects.create(
            user=self.student, full_name="Library Student", address="Jaipur"
        )

    def test_admin_login_succeeds_and_redirects_to_dashboard(self):
        response = self.client.post(
            reverse("admin_portal:login"),
            {"email": self.admin.email, "password": "AdminPassword123!"},
        )
        self.assertRedirects(response, reverse("admin_portal:dashboard"))

    def test_student_cannot_access_custom_admin(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("admin_portal:dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_redirects_to_admin_login(self):
        response = self.client.get(reverse("admin_portal:dashboard"))
        self.assertRedirects(response, reverse("admin_portal:login"))

    def test_admin_can_access_dashboard(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin_portal:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dashboard")

    def test_dashboard_displays_student_and_payment_counts(self):
        initiate_random_seat_booking(self.student)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin_portal:dashboard"))
        self.assertContains(response, "Total Students")
        self.assertContains(response, ">1<")
        self.assertContains(response, "Pending Payments")
        self.assertContains(response, ">1<")

    def test_dashboard_displays_seat_statistics(self):
        booking = initiate_random_seat_booking(self.student)
        occupied_seat = Seat.objects.exclude(pk=booking.seat_id).first()
        occupied_seat.status = Seat.Status.BOOKED
        occupied_seat.save(update_fields=["status", "updated_at"])
        Booking.objects.create(
            booking_reference="BKG-TEST-OCCUPIED",
            student=User.objects.create_user(
                email="member@example.com", phone_number="9876500002"
            ),
            seat=occupied_seat,
            hold_created_at=timezone.now() - timedelta(days=1),
            hold_expires_at=timezone.now() + timedelta(days=1),
            membership_start=timezone.now() - timedelta(days=1),
            membership_expires_at=timezone.now() + timedelta(days=29),
            status=Booking.Status.CONFIRMED,
            is_active=True,
        )
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin_portal:dashboard"))
        self.assertEqual(response.context["stats"]["held_seats"], 1)
        self.assertEqual(response.context["stats"]["occupied_seats"], 1)
        self.assertEqual(response.context["stats"]["available_seats"], 148)
        self.assertEqual(response.context["stats"]["active_members"], 1)

    def test_technical_admin_remains_available_and_requires_staff(self):
        student_response = self.client.get("/django-admin/")
        self.assertEqual(student_response.status_code, 302)
        self.assertIn("/django-admin/login/", student_response.url)

        self.client.force_login(self.admin)
        admin_response = self.client.get("/django-admin/")
        self.assertEqual(admin_response.status_code, 200)


class AdminPaymentTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="payments-owner@example.com",
            phone_number="9876500100",
            password="AdminPassword123!",
        )
        self.student = User.objects.create_user(
            email="payments-student@example.com",
            phone_number="9876500101",
            password="StudentPassword123!",
        )
        StudentProfile.objects.create(
            user=self.student, full_name="Payment Student", address="Jaipur"
        )
        self.booking = initiate_random_seat_booking(self.student)
        self.payment = Payment.objects.get(booking=self.booking)
        self.payment.utr_number = "UTR-123456"
        self.payment.submitted_at = timezone.now()
        self.payment.save(update_fields=["utr_number", "submitted_at"])

    def login_admin(self):
        self.client.force_login(self.admin)

    def test_payment_list_authentication_and_filters(self):
        response = self.client.get(reverse("admin_portal:payments"))
        self.assertRedirects(response, reverse("admin_portal:login"))
        self.client.force_login(self.student)
        self.assertEqual(
            self.client.get(reverse("admin_portal:payments")).status_code, 403
        )
        self.login_admin()
        response = self.client.get(
            reverse("admin_portal:payments"), {"utr": "123456"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Payment Student")
        self.assertContains(response, "UTR-123456")

    def test_admin_can_view_detail_and_student_cannot_access_payment(self):
        self.login_admin()
        response = self.client.get(
            reverse("admin_portal:payment_detail", args=[self.payment.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Payment Student")
        self.assertContains(response, "No payment screenshot provided.")
        self.client.force_login(self.student)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.client.get(
                reverse("admin_portal:payment_detail", args=[self.payment.id])
            ).status_code,
            403,
        )

    def test_approval_calls_service_and_real_approval_finishes_payment(self):
        self.login_admin()
        action_url = reverse(
            "admin_portal:payment_approve", args=[self.payment.id]
        )
        with patch(
            "apps.admin_portal.views.verify_payment_and_activate_membership"
        ) as verify:
            response = self.client.post(action_url)
        self.assertRedirects(
            response,
            reverse("admin_portal:payment_detail", args=[self.payment.id]),
        )
        verify.assert_called_once_with(self.payment.id, self.admin)

        verify_payment_and_activate_membership(self.payment.id, self.admin)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.VERIFIED)
        second_response = self.client.post(action_url)
        self.assertRedirects(
            second_response,
            reverse("admin_portal:payment_detail", args=[self.payment.id]),
        )

    def test_rejection_calls_service_and_finalized_payment_cannot_be_rejected(
        self,
    ):
        self.login_admin()
        action_url = reverse(
            "admin_portal:payment_reject", args=[self.payment.id]
        )
        with patch("apps.admin_portal.views.reject_payment_attempt") as reject:
            response = self.client.post(
                action_url, {"reason": "UTR not credited"}
            )
        self.assertRedirects(
            response,
            reverse("admin_portal:payment_detail", args=[self.payment.id]),
        )
        reject.assert_called_once_with(
            self.payment.id, self.admin, "UTR not credited"
        )
        self.payment.refresh_from_db()
        self.payment.status = Payment.Status.REJECTED
        self.payment.save(update_fields=["status"])
        second_response = self.client.post(action_url, {"reason": "Again"})
        self.assertRedirects(
            second_response,
            reverse("admin_portal:payment_detail", args=[self.payment.id]),
        )

    def test_students_cannot_take_actions_and_get_never_mutates(self):
        action_urls = [
            reverse("admin_portal:payment_approve", args=[self.payment.id]),
            reverse("admin_portal:payment_reject", args=[self.payment.id]),
        ]
        self.client.force_login(self.student)
        for action_url in action_urls:
            self.assertEqual(self.client.post(action_url).status_code, 403)
        self.login_admin()
        for action_url in action_urls:
            self.assertEqual(self.client.get(action_url).status_code, 200)
        self.payment.refresh_from_db()
        self.assertEqual(
            self.payment.status, Payment.Status.PENDING_VERIFICATION
        )

    def test_csrf_is_required_for_payment_actions(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        response = csrf_client.post(
            reverse("admin_portal:payment_approve", args=[self.payment.id])
        )
        self.assertEqual(response.status_code, 403)

    def test_dashboard_pending_count_is_reflected(self):
        self.login_admin()
        response = self.client.get(reverse("admin_portal:dashboard"))
        self.assertEqual(response.context["stats"]["pending_payments"], 1)
        self.assertContains(response, "Review Pending Payments")
