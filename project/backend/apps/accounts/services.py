import logging
from django.conf import settings
from django.core.mail import send_mail
from apps.accounts.models import EmailOTP, User

logger = logging.getLogger(__name__)


def send_otp_email(user: User, purpose: str) -> tuple[EmailOTP, str, bool]:
    """
    Generates a secure 6-digit OTP, stores its SHA-256 hash in the database,
    and sends the raw code to the user's registered email address.
    Returns (otp_instance, raw_code, success).
    """
    otp_instance, raw_code = EmailOTP.create_otp(user, purpose)

    purpose_labels = {
        EmailOTP.Purpose.PASSWORD_RESET: "Password Reset",
        EmailOTP.Purpose.PASSWORD_CHANGE: "Password Change",
    }
    label = purpose_labels.get(purpose, "Verification")

    subject = f"Bhagya Laxmi Library — Your {label} OTP: {raw_code}"
    message = (
        f"Hello,\n\n"
        f"Your One-Time Password (OTP) for {label} is: {raw_code}\n\n"
        f"This OTP is valid for {EmailOTP.LIFESPAN_MINUTES} minutes and can only be used once.\n"
        f"If you did not request this OTP, please ignore this email or contact library administration.\n\n"
        f"Regards,\n"
        f"Bhagya Laxmi Library & PG\n"
        f"Ward No. 3, near Guru Tegh Bahadur Gurudwara, Bishnoi Mohalla,\n"
        f"Suratgarh, Rajasthan – 335804"
    )

    try:
        from_email = getattr(
            settings, "DEFAULT_FROM_EMAIL", "Bhagya Laxmi Library <noreply@bhagyalaxmilibrary.com>"
        )
        send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=[user.email],
            fail_silently=False,
        )
        return otp_instance, raw_code, True
    except Exception as exc:
        logger.error(
            "Failed to send %s OTP email to user %s: %s",
            purpose,
            user.id,
            type(exc).__name__,
        )
        return otp_instance, raw_code, False
