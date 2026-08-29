import re
from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from apps.accounts.models import StudentProfile, User

INPUT_CSS = (
    "form-input w-full px-4 py-2.5 rounded-lg border border-slate-300 "
    "focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500"
)
OTP_INPUT_CSS = (
    "form-input w-full text-center tracking-[0.5em] font-mono text-2xl px-4 py-3 "
    "rounded-lg border border-slate-300 focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500"
)


class StudentRegistrationForm(forms.Form):
    """
    Public student self-registration form.
    Creates User and StudentProfile atomically within transaction.atomic().
    """

    full_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Enter your full name",
                "class": INPUT_CSS,
                "autocomplete": "name",
            }
        ),
    )
    email = forms.EmailField(
        max_length=320,
        required=True,
        widget=forms.EmailInput(
            attrs={
                "placeholder": "student@example.com",
                "class": INPUT_CSS,
                "autocomplete": "email",
            }
        ),
    )
    phone_number = forms.CharField(
        max_length=15,
        required=True,
        widget=forms.TextInput(
            attrs={
                "placeholder": "10-digit mobile number",
                "class": INPUT_CSS,
                "autocomplete": "tel",
            }
        ),
    )
    address = forms.CharField(
        max_length=500,
        required=False,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Suratgarh address (Optional)",
                "class": INPUT_CSS,
                "autocomplete": "street-address",
            }
        ),
    )
    password = forms.CharField(
        required=True,
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Create a strong password",
                "class": INPUT_CSS,
                "autocomplete": "new-password",
            }
        ),
    )
    password_confirm = forms.CharField(
        required=True,
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Confirm your password",
                "class": INPUT_CSS,
                "autocomplete": "new-password",
            }
        ),
    )

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email address is already registered.")
        return email

    def clean_phone_number(self):
        phone = self.cleaned_data.get("phone_number", "").strip()
        digits_only = re.sub(r"\D", "", phone)
        if len(digits_only) < 10 or len(digits_only) > 15:
            raise ValidationError("Please enter a valid 10-digit mobile number.")
        if User.objects.filter(phone_number=digits_only).exists():
            raise ValidationError("An account with this phone number is already registered.")
        return digits_only

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        password_confirm = cleaned_data.get("password_confirm")

        if password and password_confirm:
            if password != password_confirm:
                self.add_error("password_confirm", "Passwords do not match.")
            else:
                try:
                    validate_password(password)
                except ValidationError as error:
                    self.add_error("password", error)

        return cleaned_data

    def save(self):
        """
        Atomically creates User and associated StudentProfile.
        """
        full_name = self.cleaned_data["full_name"].strip()
        email = self.cleaned_data["email"].strip().lower()
        phone_number = self.cleaned_data["phone_number"]
        address = self.cleaned_data.get("address", "").strip()
        password = self.cleaned_data["password"]

        with transaction.atomic():
            user = User.objects.create_user(
                email=email,
                phone_number=phone_number,
                password=password,
                role=User.Role.STUDENT,
                is_active=True,
                is_verified=False,
            )
            StudentProfile.objects.create(
                user=user,
                full_name=full_name,
                address=address,
            )
            return user


class StudentLoginForm(forms.Form):
    """
    Standard username (email) and password authentication form.
    """

    email = forms.EmailField(
        max_length=320,
        required=True,
        widget=forms.EmailInput(
            attrs={
                "placeholder": "student@example.com",
                "class": INPUT_CSS,
                "autocomplete": "email",
                "autofocus": "autofocus",
            }
        ),
    )
    password = forms.CharField(
        required=True,
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Enter your password",
                "class": INPUT_CSS,
                "autocomplete": "current-password",
            }
        ),
    )

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user_cache = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get("email", "").strip().lower()
        password = cleaned_data.get("password")

        if email and password:
            self.user_cache = authenticate(self.request, email=email, password=password)
            if self.user_cache is None:
                user = User.objects.filter(email__iexact=email).first()
                if user and user.check_password(password) and not user.is_active:
                    raise ValidationError("Your account is currently disabled. Please contact library administration.")
                raise ValidationError("Invalid email address or password. Please try again.")
            elif not self.user_cache.is_active:
                raise ValidationError("Your account is currently disabled. Please contact library administration.")

        return cleaned_data

    def get_user(self):
        return self.user_cache


class ForgotPasswordForm(forms.Form):
    """
    Step 1: Collect email for password reset OTP dispatch.
    """

    email = forms.EmailField(
        max_length=320,
        required=True,
        widget=forms.EmailInput(
            attrs={
                "placeholder": "Enter your registered email address",
                "class": INPUT_CSS,
                "autocomplete": "email",
                "autofocus": "autofocus",
            }
        ),
    )


class VerifyOTPForm(forms.Form):
    """
    Step 2: Collect 6-digit OTP code for password reset verification.
    """

    otp_code = forms.CharField(
        max_length=6,
        min_length=6,
        required=True,
        widget=forms.TextInput(
            attrs={
                "placeholder": "000000",
                "class": OTP_INPUT_CSS,
                "autocomplete": "one-time-code",
                "autofocus": "autofocus",
                "inputmode": "numeric",
                "pattern": "[0-9]*",
                "maxlength": "6",
            }
        ),
    )

    def clean_otp_code(self):
        code = self.cleaned_data.get("otp_code", "").strip()
        if not code.isdigit() or len(code) != 6:
            raise ValidationError("Please enter a valid 6-digit numeric OTP code.")
        return code


class SetNewPasswordForm(forms.Form):
    """
    Step 3: Collect new password after verified reset OTP.
    """

    new_password = forms.CharField(
        required=True,
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Enter your new password",
                "class": INPUT_CSS,
                "autocomplete": "new-password",
            }
        ),
    )
    new_password_confirm = forms.CharField(
        required=True,
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Confirm your new password",
                "class": INPUT_CSS,
                "autocomplete": "new-password",
            }
        ),
    )

    def clean(self):
        cleaned_data = super().clean()
        new_pw = cleaned_data.get("new_password")
        confirm_pw = cleaned_data.get("new_password_confirm")

        if new_pw and confirm_pw:
            if new_pw != confirm_pw:
                self.add_error("new_password_confirm", "Passwords do not match.")
            else:
                try:
                    validate_password(new_pw)
                except ValidationError as error:
                    self.add_error("new_password", error)

        return cleaned_data


class ChangePasswordForm(forms.Form):
    """
    Authenticated student password change form with mandatory email OTP.
    """

    current_password = forms.CharField(
        required=True,
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Enter your current password",
                "class": INPUT_CSS,
                "autocomplete": "current-password",
            }
        ),
    )
    otp_code = forms.CharField(
        max_length=6,
        min_length=6,
        required=True,
        widget=forms.TextInput(
            attrs={
                "placeholder": "6-digit OTP from email",
                "class": (
                    "form-input w-full font-mono text-center px-4 py-2.5 rounded-lg border "
                    "border-slate-300 focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500"
                ),
                "autocomplete": "one-time-code",
                "inputmode": "numeric",
                "maxlength": "6",
            }
        ),
    )
    new_password = forms.CharField(
        required=True,
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Enter your new password",
                "class": INPUT_CSS,
                "autocomplete": "new-password",
            }
        ),
    )
    new_password_confirm = forms.CharField(
        required=True,
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Confirm your new password",
                "class": INPUT_CSS,
                "autocomplete": "new-password",
            }
        ),
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        current_password = self.cleaned_data.get("current_password")
        if not self.user.check_password(current_password):
            raise ValidationError("Incorrect current password.")
        return current_password

    def clean_otp_code(self):
        code = self.cleaned_data.get("otp_code", "").strip()
        if not code.isdigit() or len(code) != 6:
            raise ValidationError("Please enter a valid 6-digit numeric OTP code.")
        return code

    def clean(self):
        cleaned_data = super().clean()
        new_pw = cleaned_data.get("new_password")
        confirm_pw = cleaned_data.get("new_password_confirm")

        if new_pw and confirm_pw:
            if new_pw != confirm_pw:
                self.add_error("new_password_confirm", "Passwords do not match.")
            else:
                try:
                    validate_password(new_pw, user=self.user)
                except ValidationError as error:
                    self.add_error("new_password", error)

        return cleaned_data


class AuthenticatedResetPasswordForm(forms.Form):
    """
    Form for authenticated student modal password reset using email OTP.
    """

    otp_code = forms.CharField(
        max_length=6,
        min_length=6,
        required=True,
        widget=forms.TextInput(
            attrs={
                "id": "id_reset_modal_otp",
                "placeholder": "000000",
                "class": (
                    "form-input w-full font-mono text-center tracking-widest text-lg px-4 py-2.5 rounded-lg border "
                    "border-slate-300 focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500"
                ),
                "autocomplete": "one-time-code",
                "inputmode": "numeric",
                "pattern": "[0-9]*",
                "maxlength": "6",
            }
        ),
    )
    new_password = forms.CharField(
        required=True,
        widget=forms.PasswordInput(
            attrs={
                "id": "id_reset_modal_new_password",
                "placeholder": "Enter your new password",
                "class": INPUT_CSS,
                "autocomplete": "new-password",
            }
        ),
    )
    new_password_confirm = forms.CharField(
        required=True,
        widget=forms.PasswordInput(
            attrs={
                "id": "id_reset_modal_new_password_confirm",
                "placeholder": "Confirm your new password",
                "class": INPUT_CSS,
                "autocomplete": "new-password",
            }
        ),
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_otp_code(self):
        code = self.cleaned_data.get("otp_code", "").strip()
        if not code.isdigit() or len(code) != 6:
            raise ValidationError("Please enter a valid 6-digit numeric OTP code.")
        return code

    def clean(self):
        cleaned_data = super().clean()
        new_pw = cleaned_data.get("new_password")
        confirm_pw = cleaned_data.get("new_password_confirm")

        if new_pw and confirm_pw:
            if new_pw != confirm_pw:
                self.add_error("new_password_confirm", "Passwords do not match.")
            else:
                try:
                    validate_password(new_pw, user=self.user)
                except ValidationError as error:
                    self.add_error("new_password", error)

        return cleaned_data
