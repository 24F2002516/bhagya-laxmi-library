import json
import logging
import secrets
import urllib.parse
import urllib.request
from django.conf import settings
from django.db import transaction
from apps.accounts.models import StudentProfile, User

logger = logging.getLogger(__name__)

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v3/userinfo"


def is_google_oauth_configured() -> bool:
    """
    Checks whether Google OAuth client ID and client secret are configured.
    """
    client_id = getattr(settings, "GOOGLE_CLIENT_ID", "")
    client_secret = getattr(settings, "GOOGLE_CLIENT_SECRET", "")
    return bool(client_id and client_secret)


def get_google_redirect_uri(request) -> str:
    """
    Constructs the absolute Google OAuth callback URL.
    """
    configured_uri = getattr(settings, "GOOGLE_REDIRECT_URI", "")
    if configured_uri:
        return configured_uri
    return request.build_absolute_uri("/accounts/google/callback/")


def build_google_auth_url(request) -> tuple[str, str]:
    """
    Generates a secure state token and returns (authorization_url, state).
    """
    client_id = getattr(settings, "GOOGLE_CLIENT_ID", "")
    redirect_uri = get_google_redirect_uri(request)
    state = secrets.token_urlsafe(32)

    params = {
        "client_id": client_id,
        "response_type": "code",
        "scope": "openid email profile",
        "redirect_uri": redirect_uri,
        "state": state,
        "prompt": "select_account",
        "access_type": "online",
    }
    auth_url = f"{GOOGLE_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"
    return auth_url, state


def exchange_code_for_tokens(code: str, redirect_uri: str) -> dict:
    """
    Exchanges the authorization code for Google access and ID tokens.
    """
    client_id = getattr(settings, "GOOGLE_CLIENT_ID", "")
    client_secret = getattr(settings, "GOOGLE_CLIENT_SECRET", "")

    payload = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode("utf-8")

    req = urllib.request.Request(
        GOOGLE_TOKEN_ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_google_user_info(access_token: str) -> dict:
    """
    Fetches verified profile info from Google UserInfo endpoint.
    """
    req = urllib.request.Request(
        GOOGLE_USERINFO_ENDPOINT,
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _generate_unique_phone_placeholder() -> str:
    """
    Generates a unique 10-digit placeholder starting with '00' for students
    who register via Google OAuth before setting their phone number.
    """
    for _ in range(20):
        candidate = f"00{secrets.randbelow(100_000_000):08d}"
        if not User.objects.filter(phone_number=candidate).exists():
            return candidate
    return f"00{secrets.token_hex(4)}"[:15]


def authenticate_or_create_google_student(user_info: dict) -> tuple[User | None, bool, str]:
    """
    Safely authenticates an existing student or registers a new student from Google user info.
    Returns (user, is_new_account, status_code).
    Status codes: 'success_existing', 'success_new', 'unverified_email', 'inactive_account', 'invalid_payload'.
    """
    email = user_info.get("email", "").strip().lower()
    email_verified = user_info.get("email_verified", False)
    name = user_info.get("name", "").strip() or email.split("@")[0]

    if not email:
        return None, False, "invalid_payload"

    # Strictly require verified email from Google to prevent unsafe account takeovers
    if not email_verified:
        logger.warning("Rejected Google OAuth login: email %s is not verified by Google", email)
        return None, False, "unverified_email"

    # Check if user already exists
    existing_user = User.objects.filter(email__iexact=email).first()
    if existing_user:
        if not existing_user.is_active:
            return existing_user, False, "inactive_account"

        # Ensure student profile exists
        if not hasattr(existing_user, "student_profile"):
            StudentProfile.objects.get_or_create(
                user=existing_user,
                defaults={"full_name": name},
            )
        return existing_user, False, "success_existing"

    # Create new student account atomically
    with transaction.atomic():
        temp_phone = _generate_unique_phone_placeholder()
        new_user = User.objects.create_user(
            email=email,
            phone_number=temp_phone,
            role=User.Role.STUDENT,
            is_active=True,
            is_verified=True,
        )
        StudentProfile.objects.create(
            user=new_user,
            full_name=name,
        )
        return new_user, True, "success_new"
