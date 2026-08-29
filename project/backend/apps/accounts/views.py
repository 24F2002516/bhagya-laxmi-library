import logging
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.urls import reverse
from apps.accounts.forms import (
    AuthenticatedResetPasswordForm,
    ChangePasswordForm,
    ForgotPasswordForm,
    SetNewPasswordForm,
    StudentLoginForm,
    StudentRegistrationForm,
    VerifyOTPForm,
)
from apps.accounts.models import EmailOTP, User
from apps.accounts.oauth import (
    authenticate_or_create_google_student,
    build_google_auth_url,
    exchange_code_for_tokens,
    fetch_google_user_info,
    get_google_redirect_uri,
    is_google_oauth_configured,
)
from apps.accounts.services import send_otp_email

logger = logging.getLogger(__name__)


def mask_email(email: str) -> str:
    """
    Partially masks email for privacy display, e.g. 'rahul@example.com' -> 'r***l@example.com'.
    """
    if not email or "@" not in email:
        return email
    user_part, domain = email.split("@", 1)
    if len(user_part) <= 2:
        masked_user = user_part[0] + "*"
    else:
        masked_user = user_part[0] + "*" * (len(user_part) - 2) + user_part[-1]
    return f"{masked_user}@{domain}"


def register_view(request):
    """
    Public registration view for prospective library students.
    """
    if request.user.is_authenticated:
        return redirect("portal:dashboard")

    if request.method == "POST":
        form = StudentRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            messages.success(
                request,
                f"Welcome to Bhagya Laxmi Library, {user.student_profile.full_name}! "
                "Your account has been created successfully.",
            )
            return redirect("portal:dashboard")
    else:
        form = StudentRegistrationForm()

    return render(request, "accounts/register.html", {"form": form})


def login_view(request):
    """
    Student login view using email and password credentials.
    """
    if request.user.is_authenticated:
        return redirect("portal:dashboard")

    redirect_to = request.POST.get("next", request.GET.get("next", ""))

    if request.method == "POST":
        form = StudentLoginForm(request=request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            messages.success(request, f"Welcome back, {user.email}!")

            # Secure redirect validation
            if redirect_to and url_has_allowed_host_and_scheme(
                url=redirect_to,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                return redirect(redirect_to)
            return redirect("portal:dashboard")
    else:
        form = StudentLoginForm(request=request)

    return render(
        request,
        "accounts/login.html",
        {
            "form": form,
            "next": redirect_to,
            "google_oauth_configured": is_google_oauth_configured(),
        },
    )


def logout_view(request):
    """
    Terminates user session and redirects to the landing page.
    """
    if request.user.is_authenticated:
        logout(request)
        messages.info(request, "You have been logged out successfully.")
    return redirect("core:home")


def forgot_password_view(request):
    """
    Step 1 of Password Reset: Collects email and dispatches a 6-digit OTP.
    Employs account-enumeration safe messaging.
    """
    if request.user.is_authenticated:
        return redirect("portal:dashboard")

    if request.method == "POST":
        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"]
            user = User.objects.filter(email__iexact=email, is_active=True).first()

            if user:
                otp_obj, raw_code, success = send_otp_email(user, EmailOTP.Purpose.PASSWORD_RESET)
                if success:
                    request.session["reset_user_id"] = user.id
                    request.session["reset_email"] = user.email
                else:
                    logger.error("Failed to send password reset OTP email for user %s", user.id)
            else:
                # Store email to render consistent next screen without revealing account existence
                request.session["reset_email"] = email

            messages.info(
                request,
                f"If an account is associated with {email}, a 6-digit verification code has been sent.",
            )
            return redirect("accounts:verify_reset_otp")
    else:
        form = ForgotPasswordForm()

    return render(request, "accounts/forgot_password.html", {"form": form})


def verify_reset_otp_view(request):
    """
    Step 2 of Password Reset: Verifies the 6-digit OTP code against the user's account.
    """
    if request.user.is_authenticated:
        return redirect("portal:dashboard")

    user_id = request.session.get("reset_user_id")
    email = request.session.get("reset_email")

    if not email:
        messages.warning(request, "Please enter your registered email address first.")
        return redirect("accounts:forgot_password")

    if request.method == "POST":
        form = VerifyOTPForm(request.POST)
        if form.is_valid():
            otp_code = form.cleaned_data["otp_code"]

            if not user_id:
                # Non-existent user simulation
                form.add_error("otp_code", "Invalid or expired verification code.")
            else:
                user = User.objects.filter(id=user_id, is_active=True).first()
                if not user:
                    form.add_error("otp_code", "User account not found.")
                else:
                    # Find latest unused OTP
                    otp_obj = (
                        EmailOTP.objects
                        .filter(
                            user=user,
                            purpose=EmailOTP.Purpose.PASSWORD_RESET,
                            is_used=False,
                            expires_at__gt=timezone.now(),
                        )
                        .order_by("-created_at")
                        .first()
                    )
                    if otp_obj and otp_obj.verify(otp_code):
                        request.session["reset_otp_verified"] = True
                        messages.success(request, "Verification code confirmed. Please set your new password.")
                        return redirect("accounts:set_new_password")
                    else:
                        form.add_error("otp_code", "Invalid, expired, or locked verification code.")
    else:
        form = VerifyOTPForm()

    return render(
        request,
        "accounts/verify_reset_otp.html",
        {"form": form, "email": email},
    )


def set_new_password_view(request):
    """
    Step 3 of Password Reset: Allows the user to choose a new password after successful OTP verification.
    """
    if request.user.is_authenticated:
        return redirect("portal:dashboard")

    user_id = request.session.get("reset_user_id")
    otp_verified = request.session.get("reset_otp_verified")

    if not user_id or not otp_verified:
        messages.error(request, "Unauthorized password reset attempt. Please verify your OTP code.")
        return redirect("accounts:forgot_password")

    user = User.objects.filter(id=user_id, is_active=True).first()
    if not user:
        messages.error(request, "User account not found.")
        return redirect("accounts:forgot_password")

    if request.method == "POST":
        form = SetNewPasswordForm(request.POST)
        if form.is_valid():
            user.set_password(form.cleaned_data["new_password"])
            user.save(update_fields=["password", "updated_at"])

            # Clean session variables
            request.session.pop("reset_user_id", None)
            request.session.pop("reset_email", None)
            request.session.pop("reset_otp_verified", None)

            messages.success(request, "Your password has been reset successfully! Please log in.")
            return redirect("accounts:login")
    else:
        form = SetNewPasswordForm()

    return render(request, "accounts/set_new_password.html", {"form": form})


@login_required
def send_change_password_otp_view(request):
    """
    Dispatches a password change OTP to the logged-in student.
    Can be called via HTMX or standard POST.
    """
    if request.method == "POST":
        otp_obj, raw_code, success = send_otp_email(request.user, EmailOTP.Purpose.PASSWORD_CHANGE)
        if success:
            messages.info(
                request,
                f"A 6-digit OTP code has been sent to your registered email ({request.user.email}).",
            )
        else:
            messages.error(
                request,
                "Unable to deliver OTP email. Please ensure SMTP configuration is set or contact administration.",
            )
    return redirect("accounts:change_password")


@login_required
def change_password_view(request):
    """
    Allows an authenticated student to change their password with mandatory email OTP verification.
    Also provides access to the in-page authenticated password reset modal if current password is forgotten.
    """
    show_modal = request.GET.get("modal") == "open"
    reset_form = AuthenticatedResetPasswordForm(user=request.user)

    if request.method == "POST":
        form = ChangePasswordForm(user=request.user, data=request.POST)
        if form.is_valid():
            otp_code = form.cleaned_data["otp_code"]
            otp_obj = (
                EmailOTP.objects
                .filter(
                    user=request.user,
                    purpose=EmailOTP.Purpose.PASSWORD_CHANGE,
                    is_used=False,
                    expires_at__gt=timezone.now(),
                )
                .order_by("-created_at")
                .first()
            )
            if not otp_obj or not otp_obj.verify(otp_code):
                form.add_error("otp_code", "Invalid, expired, or locked verification code.")
            else:
                request.user.set_password(form.cleaned_data["new_password"])
                request.user.save(update_fields=["password", "updated_at"])
                update_session_auth_hash(request, request.user)
                messages.success(request, "Your password has been changed successfully!")
                return redirect("portal:dashboard")
    else:
        form = ChangePasswordForm(user=request.user)

    return render(
        request,
        "accounts/change_password.html",
        {
            "form": form,
            "reset_form": reset_form,
            "show_reset_modal": show_modal,
            "masked_email": mask_email(request.user.email),
        },
    )


@login_required
def authenticated_reset_password_view(request):
    """
    Allows an authenticated student who forgot their current password
    to reset it via 6-digit email OTP directly inside the Change Password modal.
    On successful reset, logs the user out and redirects to login.
    """
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "send_otp":
            otp_obj, raw_code, success = send_otp_email(request.user, EmailOTP.Purpose.PASSWORD_RESET)
            if success:
                messages.info(
                    request,
                    f"A 6-digit password reset OTP code has been sent to your registered email ({request.user.email}).",
                )
            else:
                messages.error(
                    request,
                    "Unable to deliver OTP email. Please check your SMTP configuration or contact administration.",
                )
            return redirect(f"{reverse('accounts:change_password')}?modal=open&otp_sent=1")

        form = AuthenticatedResetPasswordForm(user=request.user, data=request.POST)
        if form.is_valid():
            otp_code = form.cleaned_data["otp_code"]
            otp_obj = (
                EmailOTP.objects
                .filter(
                    user=request.user,
                    purpose=EmailOTP.Purpose.PASSWORD_RESET,
                    is_used=False,
                    expires_at__gt=timezone.now(),
                )
                .order_by("-created_at")
                .first()
            )
            if not otp_obj or not otp_obj.verify(otp_code):
                form.add_error("otp_code", "Invalid, expired, or locked verification code.")
                change_form = ChangePasswordForm(user=request.user)
                return render(
                    request,
                    "accounts/change_password.html",
                    {
                        "form": change_form,
                        "reset_form": form,
                        "show_reset_modal": True,
                        "masked_email": mask_email(request.user.email),
                    },
                )
            else:
                request.user.set_password(form.cleaned_data["new_password"])
                request.user.save(update_fields=["password", "updated_at"])
                logout(request)
                messages.success(
                    request,
                    "Your password has been reset successfully! Please log in with your new password.",
                )
                return redirect("accounts:login")
        else:
            change_form = ChangePasswordForm(user=request.user)
            return render(
                request,
                "accounts/change_password.html",
                {
                    "form": change_form,
                    "reset_form": form,
                    "show_reset_modal": True,
                    "masked_email": mask_email(request.user.email),
                },
            )

    return redirect("accounts:change_password")


# Google OAuth 2.0 Views


def google_login_view(request):
    """
    Initiates Google OAuth 2.0 flow by redirecting student to Google consent screen.
    """
    if request.user.is_authenticated:
        return redirect("portal:dashboard")

    if not is_google_oauth_configured():
        messages.error(
            request,
            "Google Sign-In is not configured yet. "
            "Please configure GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env.",
        )
        return redirect("accounts:login")

    auth_url, state = build_google_auth_url(request)
    request.session["google_oauth_state"] = state
    return redirect(auth_url)


def google_callback_view(request):
    """
    Handles Google OAuth 2.0 redirect callback, validates state token,
    exchanges authorization code for user info, and authenticates the student.
    """
    if request.user.is_authenticated:
        return redirect("portal:dashboard")

    # Check for OAuth error from Google
    error = request.GET.get("error")
    if error:
        logger.warning("Google OAuth error received: %s", error)
        messages.error(request, f"Google Sign-In was cancelled or failed ({error}).")
        return redirect("accounts:login")

    # Validate state parameter against session (CSRF protection)
    state = request.GET.get("state")
    saved_state = request.session.pop("google_oauth_state", None)

    if not state or not saved_state or state != saved_state:
        logger.warning("Google OAuth state mismatch: received '%s', expected '%s'", state, saved_state)
        messages.error(request, "Authentication failed due to state mismatch. Please try again.")
        return redirect("accounts:login")

    code = request.GET.get("code")
    if not code:
        messages.error(request, "Invalid response from Google (missing authorization code).")
        return redirect("accounts:login")

    redirect_uri = get_google_redirect_uri(request)

    try:
        token_data = exchange_code_for_tokens(code, redirect_uri)
        access_token = token_data.get("access_token")
        if not access_token:
            messages.error(request, "Unable to obtain access token from Google.")
            return redirect("accounts:login")

        user_info = fetch_google_user_info(access_token)
        user, is_new, status_code = authenticate_or_create_google_student(user_info)

        if status_code == "inactive_account":
            messages.error(request, "Your account is currently disabled. Please contact library administration.")
            return redirect("accounts:login")

        if status_code == "unverified_email":
            messages.error(request, "Google email is not verified. Please verify your Google account first.")
            return redirect("accounts:login")

        if not user:
            messages.error(request, "Failed to authenticate with Google. Please try again.")
            return redirect("accounts:login")

        # Log in the authenticated student
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")

        if is_new:
            messages.success(
                request,
                f"Welcome to Bhagya Laxmi Library, {user.student_profile.full_name}! "
                "Your account was created via Google. Please complete your mobile number in your profile.",
            )
        else:
            messages.success(request, f"Welcome back, {user.email}! (Signed in with Google)")

        return redirect("portal:dashboard")

    except Exception as exc:
        logger.error("Error during Google OAuth callback processing: %s", exc)
        messages.error(request, "An error occurred while communicating with Google. Please try again.")
        return redirect("accounts:login")
