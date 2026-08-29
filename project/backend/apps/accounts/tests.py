from datetime import timedelta
from unittest.mock import patch
from django.core import mail
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import EmailOTP, StudentProfile, User
from apps.accounts.oauth import authenticate_or_create_google_student
from apps.accounts.services import send_otp_email


class AccountsModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="student@example.com",
            phone_number="9876543210",
            password="StrongPassword123!",
        )

    def test_create_student_user(self):
        self.assertEqual(self.user.email, "student@example.com")
        self.assertEqual(self.user.phone_number, "9876543210")
        self.assertEqual(self.user.role, User.Role.STUDENT)
        self.assertTrue(self.user.is_active)
        self.assertFalse(self.user.is_staff)
        self.assertTrue(self.user.is_student)
        self.assertFalse(self.user.is_admin_user)

    def test_create_superuser(self):
        admin = User.objects.create_superuser(
            email="admin@example.com",
            phone_number="9876543211",
            password="AdminPassword123!",
        )
        self.assertEqual(admin.role, User.Role.ADMIN)
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)
        self.assertTrue(admin.is_admin_user)
        self.assertFalse(admin.is_student)

    def test_unique_email_and_phone_constraints(self):
        # Duplicate email
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                User.objects.create_user(
                    email="student@example.com",
                    phone_number="9876543212",
                    password="Pass!",
                )

        # Duplicate phone number
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                User.objects.create_user(
                    email="other@example.com",
                    phone_number="9876543210",
                    password="Pass!",
                )

    def test_student_profile_creation(self):
        profile = StudentProfile.objects.create(
            user=self.user,
            full_name="Rahul Sharma",
            document_type="Aadhaar Card",
            document_number="1234-5678-9012",
            emergency_contact_name="Suresh Sharma",
            emergency_contact_phone="9876543299",
            address="Jaipur, Rajasthan",
        )
        self.assertEqual(self.user.student_profile.full_name, "Rahul Sharma")
        self.assertEqual(profile.document_type, "Aadhaar Card")
        self.assertEqual(str(profile), "Rahul Sharma (9876543210)")


class EmailOTPTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="otpuser@example.com",
            phone_number="9876543222",
            password="Password123!",
        )

    def test_otp_generation_and_successful_verification(self):
        otp_instance, raw_code = EmailOTP.create_otp(
            user=self.user, purpose=EmailOTP.Purpose.PASSWORD_RESET
        )
        self.assertEqual(len(raw_code), 6)
        self.assertTrue(raw_code.isdigit())
        self.assertFalse(otp_instance.is_used)
        self.assertEqual(otp_instance.attempts_count, 0)
        self.assertGreater(otp_instance.expires_at, timezone.now())

        # Verify correct code
        verified = otp_instance.verify(raw_code)
        self.assertTrue(verified)
        self.assertTrue(otp_instance.is_used)

        # Re-verification must fail (single use)
        self.assertFalse(otp_instance.verify(raw_code))

    def test_otp_failed_attempts_lockout(self):
        otp_instance, raw_code = EmailOTP.create_otp(
            user=self.user, purpose=EmailOTP.Purpose.PASSWORD_CHANGE
        )
        wrong_code = "000000" if raw_code != "000000" else "111111"

        # Attempt 1 failed
        self.assertFalse(otp_instance.verify(wrong_code))
        self.assertEqual(otp_instance.attempts_count, 1)
        self.assertFalse(otp_instance.is_used)

        # Attempt 2 failed
        self.assertFalse(otp_instance.verify(wrong_code))
        self.assertEqual(otp_instance.attempts_count, 2)
        self.assertFalse(otp_instance.is_used)

        # Attempt 3 failed (max limit reached -> locked permanently)
        self.assertFalse(otp_instance.verify(wrong_code))
        self.assertEqual(otp_instance.attempts_count, 3)
        self.assertTrue(otp_instance.is_used)

        # Subsequent correct code attempt fails because OTP is locked
        self.assertFalse(otp_instance.verify(raw_code))

    def test_expired_otp_fails(self):
        otp_instance, raw_code = EmailOTP.create_otp(
            user=self.user, purpose=EmailOTP.Purpose.PASSWORD_RESET
        )
        # Manually set expiration in past
        otp_instance.expires_at = timezone.now() - timedelta(minutes=1)
        otp_instance.save(update_fields=["expires_at"])

        self.assertFalse(otp_instance.verify(raw_code))


class EmailServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="service_test@example.com",
            phone_number="9876543290",
            password="Password123!",
        )

    def test_send_otp_email_success(self):
        mail.outbox.clear()
        otp_obj, raw_code, success = send_otp_email(self.user, EmailOTP.Purpose.PASSWORD_RESET)
        self.assertTrue(success)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Bhagya Laxmi Library", mail.outbox[0].subject)
        self.assertIn(raw_code, mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].to, [self.user.email])

    @patch("apps.accounts.services.send_mail", side_effect=Exception("SMTP Connection Error"))
    def test_send_otp_email_failure_handled_gracefully(self, mock_send_mail):
        otp_obj, raw_code, success = send_otp_email(self.user, EmailOTP.Purpose.PASSWORD_CHANGE)
        self.assertFalse(success)
        self.assertIsNotNone(otp_obj)


class StudentRegistrationTests(TestCase):
    def test_successful_registration(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "full_name": "Pooja Verma",
                "email": "pooja@example.com",
                "phone_number": "9876500001",
                "address": "Ward No. 3, Suratgarh",
                "password": "SecurePassword123!",
                "password_confirm": "SecurePassword123!",
            },
        )
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email="pooja@example.com")
        self.assertEqual(user.phone_number, "9876500001")
        self.assertEqual(user.student_profile.full_name, "Pooja Verma")
        self.assertEqual(user.student_profile.address, "Ward No. 3, Suratgarh")
        self.assertEqual(user.role, User.Role.STUDENT)

    def test_duplicate_email_registration_fails(self):
        User.objects.create_user(
            email="existing@example.com",
            phone_number="9876500002",
            password="Password123!",
        )
        response = self.client.post(
            reverse("accounts:register"),
            {
                "full_name": "Duplicate User",
                "email": "existing@example.com",
                "phone_number": "9876500003",
                "password": "SecurePassword123!",
                "password_confirm": "SecurePassword123!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "email",
            "An account with this email address is already registered.",
        )

    def test_duplicate_phone_registration_fails(self):
        User.objects.create_user(
            email="user1@example.com",
            phone_number="9876500004",
            password="Password123!",
        )
        response = self.client.post(
            reverse("accounts:register"),
            {
                "full_name": "Duplicate Phone User",
                "email": "user2@example.com",
                "phone_number": "9876500004",
                "password": "SecurePassword123!",
                "password_confirm": "SecurePassword123!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "phone_number",
            "An account with this phone number is already registered.",
        )

    def test_password_mismatch_fails(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "full_name": "Mismatch User",
                "email": "mismatch@example.com",
                "phone_number": "9876500005",
                "password": "SecurePassword123!",
                "password_confirm": "DifferentPassword123!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "password_confirm",
            "Passwords do not match.",
        )


class StudentLoginLogoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="login_student@example.com",
            phone_number="9876500010",
            password="CorrectPassword123!",
        )
        StudentProfile.objects.create(user=self.user, full_name="Login Student")

    def test_successful_login(self):
        response = self.client.post(
            reverse("accounts:login"),
            {
                "email": "login_student@example.com",
                "password": "CorrectPassword123!",
            },
        )
        self.assertEqual(response.status_code, 302)

    def test_case_insensitive_email_login(self):
        response = self.client.post(
            reverse("accounts:login"),
            {
                "email": "LOGIN_STUDENT@EXAMPLE.COM",
                "password": "CorrectPassword123!",
            },
        )
        self.assertEqual(response.status_code, 302)

    def test_incorrect_password_fails(self):
        response = self.client.post(
            reverse("accounts:login"),
            {
                "email": "login_student@example.com",
                "password": "WrongPassword!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid email address or password")

    def test_inactive_account_fails(self):
        self.user.is_active = False
        self.user.save()

        response = self.client.post(
            reverse("accounts:login"),
            {
                "email": "login_student@example.com",
                "password": "CorrectPassword123!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your account is currently disabled")

    def test_logout(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:logout"))
        self.assertEqual(response.status_code, 302)


class ForgotPasswordAndResetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="reset_student@example.com",
            phone_number="9876500020",
            password="OldPassword123!",
        )
        StudentProfile.objects.create(user=self.user, full_name="Reset Student")

    def test_forgot_password_flow(self):
        # 1. Request OTP
        mail.outbox.clear()
        response = self.client.post(
            reverse("accounts:forgot_password"),
            {"email": "reset_student@example.com"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Your Password Reset OTP", mail.outbox[0].subject)

        # Retrieve generated raw code from latest OTP
        otp_record = EmailOTP.objects.filter(
            user=self.user, purpose=EmailOTP.Purpose.PASSWORD_RESET
        ).first()
        self.assertIsNotNone(otp_record)

        # 2. Verify wrong OTP code fails
        verify_fail_resp = self.client.post(
            reverse("accounts:verify_reset_otp"),
            {"otp_code": "000000"},
        )
        self.assertEqual(verify_fail_resp.status_code, 200)

        # 2b. Re-fetch code and test valid OTP
        otp_rec, raw_code = EmailOTP.create_otp(self.user, EmailOTP.Purpose.PASSWORD_RESET)
        verify_succ_resp = self.client.post(
            reverse("accounts:verify_reset_otp"),
            {"otp_code": raw_code},
        )
        self.assertEqual(verify_succ_resp.status_code, 302)

        # 3. Set new password
        set_pw_resp = self.client.post(
            reverse("accounts:set_new_password"),
            {
                "new_password": "BrandNewPassword123!",
                "new_password_confirm": "BrandNewPassword123!",
            },
        )
        self.assertEqual(set_pw_resp.status_code, 302)

        # 4. Authenticate with new password
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("BrandNewPassword123!"))


class ChangePasswordTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="change_student@example.com",
            phone_number="9876500030",
            password="CurrentPassword123!",
        )
        StudentProfile.objects.create(user=self.user, full_name="Change Student")

    def test_change_password_requires_login(self):
        response = self.client.get(reverse("accounts:change_password"))
        self.assertEqual(response.status_code, 302)

    def test_send_change_password_otp_and_change_password(self):
        self.client.force_login(self.user)
        mail.outbox.clear()

        # Step 1: Send OTP
        send_resp = self.client.post(reverse("accounts:send_change_password_otp"))
        self.assertEqual(send_resp.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)

        # Step 2: Create valid OTP & verify change
        otp_rec, raw_code = EmailOTP.create_otp(self.user, EmailOTP.Purpose.PASSWORD_CHANGE)
        change_resp = self.client.post(
            reverse("accounts:change_password"),
            {
                "current_password": "CurrentPassword123!",
                "otp_code": raw_code,
                "new_password": "UpdatedPassword123!",
                "new_password_confirm": "UpdatedPassword123!",
            },
        )
        self.assertEqual(change_resp.status_code, 302)

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("UpdatedPassword123!"))


class UIPasswordToggleAndNavbarTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="navbar_user@example.com",
            phone_number="9876500040",
            password="Password123!",
        )
        StudentProfile.objects.create(user=self.user, full_name="Navbar User")

    def test_password_show_hide_toggle_present_on_login(self):
        response = self.client.get(reverse("accounts:login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-password-toggle")
        self.assertContains(response, "eye-open-icon")
        self.assertContains(response, "Continue with Google")

    def test_password_show_hide_toggle_present_on_register(self):
        response = self.client.get(reverse("accounts:register"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-password-toggle")

    def test_forgot_password_modal_trigger_present_on_change_password_page(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:change_password"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "open-reset-modal-btn")
        self.assertContains(response, "Forgot your password?")
        self.assertContains(response, "reset-password-modal")
        self.assertContains(response, "Reset Your Password")
        self.assertContains(response, "data-password-toggle")

    def test_student_navbar_routes_to_portal_for_authenticated_student(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("portal:dashboard"))
        self.assertEqual(response.status_code, 200)
        # Brand routes to portal for student
        self.assertContains(response, reverse("portal:dashboard"))
        self.assertContains(response, "Portal")

    def test_anonymous_navbar_routes_to_home_for_unauthenticated_user(self):
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("accounts:login"))
        self.assertContains(response, reverse("accounts:register"))


class AuthenticatedModalPasswordResetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="modal_student@example.com",
            phone_number="9876500045",
            password="OldSecretPassword123!",
        )
        StudentProfile.objects.create(user=self.user, full_name="Modal Student")

    def test_auth_reset_requires_login(self):
        response = self.client.post(reverse("accounts:auth_reset_password"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_send_auth_reset_otp_dispatches_email_to_authenticated_student(self):
        self.client.force_login(self.user)
        mail.outbox.clear()

        response = self.client.post(
            reverse("accounts:auth_reset_password"),
            {"action": "send_otp"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("modal=open", response.url)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Password Reset OTP", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, [self.user.email])

        # OTP record created in database with Purpose.PASSWORD_RESET
        otp_obj = EmailOTP.objects.filter(
            user=self.user, purpose=EmailOTP.Purpose.PASSWORD_RESET, is_used=False
        ).first()
        self.assertIsNotNone(otp_obj)

    def test_auth_reset_password_success(self):
        self.client.force_login(self.user)
        otp_obj, raw_code = EmailOTP.create_otp(self.user, EmailOTP.Purpose.PASSWORD_RESET)

        response = self.client.post(
            reverse("accounts:auth_reset_password"),
            {
                "otp_code": raw_code,
                "new_password": "NewResetPassword123!",
                "new_password_confirm": "NewResetPassword123!",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("accounts:login"))

        # Check password updated
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewResetPassword123!"))

        # Check session logged out
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_auth_reset_password_invalid_otp_rejected(self):
        self.client.force_login(self.user)
        otp_obj, raw_code = EmailOTP.create_otp(self.user, EmailOTP.Purpose.PASSWORD_RESET)
        wrong_code = "000000" if raw_code != "000000" else "111111"

        response = self.client.post(
            reverse("accounts:auth_reset_password"),
            {
                "otp_code": wrong_code,
                "new_password": "NewResetPassword123!",
                "new_password_confirm": "NewResetPassword123!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid, expired, or locked verification code.")
        self.assertTrue(response.context["show_reset_modal"])

        # Password must remain unchanged
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("OldSecretPassword123!"))

    def test_auth_reset_password_expired_otp_rejected(self):
        self.client.force_login(self.user)
        otp_obj, raw_code = EmailOTP.create_otp(self.user, EmailOTP.Purpose.PASSWORD_RESET)
        otp_obj.expires_at = timezone.now() - timedelta(minutes=1)
        otp_obj.save(update_fields=["expires_at"])

        response = self.client.post(
            reverse("accounts:auth_reset_password"),
            {
                "otp_code": raw_code,
                "new_password": "NewResetPassword123!",
                "new_password_confirm": "NewResetPassword123!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid, expired, or locked verification code.")

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("OldSecretPassword123!"))

    def test_auth_reset_password_mismatch_rejected(self):
        self.client.force_login(self.user)
        otp_obj, raw_code = EmailOTP.create_otp(self.user, EmailOTP.Purpose.PASSWORD_RESET)

        response = self.client.post(
            reverse("accounts:auth_reset_password"),
            {
                "otp_code": raw_code,
                "new_password": "NewResetPassword123!",
                "new_password_confirm": "DifferentPassword123!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Passwords do not match.")

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("OldSecretPassword123!"))


class GoogleOAuthTests(TestCase):
    def setUp(self):
        self.existing_user = User.objects.create_user(
            email="existing_google@example.com",
            phone_number="9876500050",
            password="Password123!",
        )
        StudentProfile.objects.create(user=self.existing_user, full_name="Google Student")

    def test_google_login_not_configured_shows_error(self):
        with override_settings(GOOGLE_CLIENT_ID="", GOOGLE_CLIENT_SECRET=""):
            response = self.client.get(reverse("accounts:google_login"))
            self.assertEqual(response.status_code, 302)
            self.assertRedirects(response, reverse("accounts:login"))

    def test_google_login_redirects_to_google_with_state(self):
        with override_settings(GOOGLE_CLIENT_ID="mock-client-id", GOOGLE_CLIENT_SECRET="mock-secret"):
            response = self.client.get(reverse("accounts:google_login"))
            self.assertEqual(response.status_code, 302)
            self.assertIn("accounts.google.com/o/oauth2/v2/auth", response.url)
            self.assertIn("mock-client-id", response.url)
            self.assertIn("state=", response.url)
            self.assertIn("google_oauth_state", self.client.session)

    def test_google_callback_state_mismatch_fails(self):
        session = self.client.session
        session["google_oauth_state"] = "valid_state_123"
        session.save()

        response = self.client.get(reverse("accounts:google_callback") + "?state=invalid_state&code=test_code")
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("accounts:login"))

    def test_google_linking_with_existing_active_account(self):
        user_info = {
            "email": "existing_google@example.com",
            "email_verified": True,
            "name": "Google Student",
        }
        user, is_new, status_code = authenticate_or_create_google_student(user_info)
        self.assertEqual(status_code, "success_existing")
        self.assertFalse(is_new)
        self.assertEqual(user.id, self.existing_user.id)

    def test_google_linking_with_inactive_account_rejected(self):
        self.existing_user.is_active = False
        self.existing_user.save()

        user_info = {
            "email": "existing_google@example.com",
            "email_verified": True,
            "name": "Google Student",
        }
        user, is_new, status_code = authenticate_or_create_google_student(user_info)
        self.assertEqual(status_code, "inactive_account")
        self.assertFalse(is_new)

    def test_google_unverified_email_rejected(self):
        user_info = {
            "email": "unverified@example.com",
            "email_verified": False,
            "name": "Unverified User",
        }
        user, is_new, status_code = authenticate_or_create_google_student(user_info)
        self.assertEqual(status_code, "unverified_email")
        self.assertIsNone(user)

    def test_google_new_student_account_created(self):
        user_info = {
            "email": "new_google_student@example.com",
            "email_verified": True,
            "name": "New Google Student",
        }
        user, is_new, status_code = authenticate_or_create_google_student(user_info)
        self.assertEqual(status_code, "success_new")
        self.assertTrue(is_new)
        self.assertIsNotNone(user)
        self.assertEqual(user.email, "new_google_student@example.com")
        self.assertEqual(user.role, User.Role.STUDENT)
        self.assertEqual(user.student_profile.full_name, "New Google Student")

    @patch("apps.accounts.views.exchange_code_for_tokens", return_value={"access_token": "mock-token"})
    @patch("apps.accounts.views.fetch_google_user_info", return_value={
        "email": "callback_test@example.com",
        "email_verified": True,
        "name": "Callback User",
    })
    def test_google_callback_success_flow(self, mock_fetch, mock_exchange):
        session = self.client.session
        session["google_oauth_state"] = "matching_state_xyz"
        session.save()

        response = self.client.get(
            reverse("accounts:google_callback") + "?state=matching_state_xyz&code=valid_google_code"
        )
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("portal:dashboard"))

        created_user = User.objects.filter(email="callback_test@example.com").first()
        self.assertIsNotNone(created_user)
        self.assertEqual(created_user.student_profile.full_name, "Callback User")
