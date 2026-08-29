from django.test import TestCase, Client
from django.urls import reverse


class HomeViewTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_home_page_renders_successfully(self):
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/home.html")
        self.assertTemplateUsed(response, "base.html")
        self.assertContains(response, "Bhagya Laxmi Library")
        self.assertContains(response, "150")
        self.assertContains(response, "800")
        self.assertContains(response, "htmx.min.js")
        self.assertContains(response, "output.css")
