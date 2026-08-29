import hashlib
import secrets
from datetime import timedelta
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone
from apps.core.models import TimeStampedModel
from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    """
    Custom user model where email is the primary login credential.
    """

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Admin / Owner"
        STUDENT = "STUDENT", "Student / Member"

    email = models.EmailField(unique=True, db_index=True, max_length=255)
    phone_number = models.CharField(unique=True, db_index=True, max_length=15)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["phone_number"]

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["email"], name="unique_user_email"),
            models.UniqueConstraint(fields=["phone_number"], name="unique_user_phone"),
        ]

    def __str__(self):
        return f"{self.email} ({self.get_role_display()})"

    @property
    def is_admin_user(self) -> bool:
        return self.role == self.Role.ADMIN

    @property
    def is_student(self) -> bool:
        return self.role == self.Role.STUDENT


class StudentProfile(TimeStampedModel):
    """
    Personal profile, emergency details, and KYC information for a student member.
    """

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="student_profile"
    )
    full_name = models.CharField(max_length=150)
    document_type = models.CharField(
        max_length=64, blank=True, help_text="Configurable document type (e.g. Aadhaar, Student ID)"
    )
    document_number = models.CharField(max_length=64, blank=True)
    document_file = models.FileField(
        upload_to="kyc_documents/%Y/%m/", null=True, blank=True
    )
    photo = models.ImageField(
        upload_to="student_photos/%Y/%m/", null=True, blank=True
    )
    emergency_contact_name = models.CharField(max_length=100, blank=True)
    emergency_contact_phone = models.CharField(max_length=15, blank=True)
    address = models.TextField(blank=True)

    class Meta:
        verbose_name = "Student Profile"
        verbose_name_plural = "Student Profiles"
        ordering = ["full_name"]

    def __str__(self):
        return f"{self.full_name} ({self.user.phone_number})"


class EmailOTP(models.Model):
    """
    Secure 6-digit email OTP with 5-minute expiry, single-use invalidation,
    and a maximum of 3 failed verification attempts.
    Used exclusively for PASSWORD_CHANGE and PASSWORD_RESET.
    """

    class Purpose(models.TextChoices):
        PASSWORD_CHANGE = "PASSWORD_CHANGE", "Password Change"
        PASSWORD_RESET = "PASSWORD_RESET", "Password Reset"

    MAX_FAILED_ATTEMPTS = 3
    LIFESPAN_MINUTES = 5

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="email_otps")
    otp_hash = models.CharField(max_length=128)
    purpose = models.CharField(max_length=30, choices=Purpose.choices)
    expires_at = models.DateTimeField(db_index=True)
    is_used = models.BooleanField(default=False)
    attempts_count = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Email OTP"
        verbose_name_plural = "Email OTPs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["user", "purpose", "is_used", "expires_at"],
                name="idx_otp_lookup",
            )
        ]

    def __str__(self):
        return f"OTP for {self.user.email} [{self.purpose}]"

    @staticmethod
    def hash_code(raw_code: str) -> str:
        return hashlib.sha256(raw_code.strip().encode("utf-8")).hexdigest()

    @classmethod
    def create_otp(cls, user: User, purpose: str) -> tuple["EmailOTP", str]:
        """
        Generates a secure 6-digit code, hashes it, saves the record,
        and returns (instance, raw_code).
        """
        # Invalidate any existing unused OTPs for this user and purpose
        cls.objects.filter(user=user, purpose=purpose, is_used=False).update(is_used=True)

        raw_code = f"{secrets.randbelow(1_000_000):06d}"
        expires_at = timezone.now() + timedelta(minutes=cls.LIFESPAN_MINUTES)
        otp_instance = cls.objects.create(
            user=user,
            otp_hash=cls.hash_code(raw_code),
            purpose=purpose,
            expires_at=expires_at,
            is_used=False,
            attempts_count=0,
        )
        return otp_instance, raw_code

    def verify(self, raw_code: str) -> bool:
        """
        Verifies the given raw 6-digit code against this OTP record.
        Returns True on success and marks OTP as used.
        Returns False and increments attempts_count on failure.
        """
        if self.is_used or timezone.now() > self.expires_at or self.attempts_count >= self.MAX_FAILED_ATTEMPTS:
            return False

        if self.otp_hash == self.hash_code(raw_code):
            self.is_used = True
            self.save(update_fields=["is_used"])
            return True

        self.attempts_count += 1
        if self.attempts_count >= self.MAX_FAILED_ATTEMPTS:
            self.is_used = True  # Lock permanently
            self.save(update_fields=["attempts_count", "is_used"])
        else:
            self.save(update_fields=["attempts_count"])
        return False
