from django.db import IntegrityError, transaction
from django.test import TestCase
from apps.accounts.models import User
from apps.complaints.models import Complaint, Feedback
from apps.seats.models import Seat


class ComplaintAndFeedbackTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin@example.com",
            phone_number="9876543280",
            password="AdminPassword123!",
        )
        self.student = User.objects.create_user(
            email="student@example.com",
            phone_number="9876543281",
            password="Password123!",
        )

    def test_complaint_lifecycle(self):
        seat = Seat.objects.get(number=15)
        complaint = Complaint.objects.create(
            ticket_number="TKT-202608-0001",
            student=self.student,
            seat=seat,
            category=Complaint.Category.AC_COOLING,
            title="AC airflow too cold near desk 15",
            description="Please adjust the swing vane or increase temperature slightly.",
        )
        self.assertEqual(complaint.status, Complaint.Status.OPEN)
        self.assertEqual(complaint.category, "AC_COOLING")
        self.assertEqual(str(complaint), "Ticket TKT-202608-0001 [AC / Cooling & Temperature] - Open")

        # Resolve complaint
        complaint.status = Complaint.Status.RESOLVED
        complaint.resolution_notes = "Vane adjusted upwards."
        complaint.resolved_by = self.admin
        complaint.save()

        complaint.refresh_from_db()
        self.assertEqual(complaint.status, Complaint.Status.RESOLVED)
        self.assertEqual(complaint.resolved_by, self.admin)

    def test_feedback_creation_and_rating_validation(self):
        feedback = Feedback.objects.create(
            student=self.student,
            rating=5,
            category=Feedback.Category.STUDY_ENVIRONMENT,
            description="The reading hall atmosphere is very quiet and conducive for UPSC prep.",
        )
        self.assertEqual(feedback.rating, 5)
        self.assertFalse(feedback.is_reviewed)
        self.assertIn("5/5", str(feedback))

        # Admin reviews feedback
        feedback.is_reviewed = True
        feedback.admin_notes = "Thanked student during daily rounds."
        feedback.reviewed_by = self.admin
        feedback.save()

        feedback.refresh_from_db()
        self.assertTrue(feedback.is_reviewed)
        self.assertEqual(feedback.reviewed_by, self.admin)

    def test_feedback_rating_boundary_constraints(self):
        # Rating = 0 (below 1) must fail check constraint
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Feedback.objects.create(
                    student=self.student,
                    rating=0,
                    category=Feedback.Category.GENERAL,
                    description="Rating 0 test",
                )

        # Rating = 6 (above 5) must fail check constraint
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Feedback.objects.create(
                    student=self.student,
                    rating=6,
                    category=Feedback.Category.GENERAL,
                    description="Rating 6 test",
                )
