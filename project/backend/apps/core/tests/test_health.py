from django.test import TestCase, Client
from django.urls import reverse


class HealthCheckTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_health_check_returns_200_and_json(self):
        response = self.client.get(reverse("core:health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")

        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["app"], "Bhagya Laxmi Library")
        self.assertEqual(data["total_seats"], 150)
        self.assertEqual(data["seat_monthly_fee"], 800)
        self.assertEqual(data["database"], "healthy")
        self.assertIn("timestamp", data)
