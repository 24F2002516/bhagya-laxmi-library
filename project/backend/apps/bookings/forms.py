import re
from django import forms
from django.core.exceptions import ValidationError
from apps.accounts.models import StudentProfile, User
from apps.complaints.models import Complaint, Feedback
from apps.payments.models import Payment

INPUT_CSS = (
    "form-input w-full px-4 py-2.5 rounded-lg border border-slate-300 "
    "focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500"
)
FILE_INPUT_CSS = (
    "block w-full text-sm text-slate-500 file:mr-4 file:py-2 file:px-4 file:rounded-lg "
    "file:border-0 file:text-xs file:font-semibold file:bg-emerald-50 file:text-emerald-700 "
    "hover:file:bg-emerald-100"
)


class StudentProfileForm(forms.ModelForm):
    """
    Form for students to update their profile and contact information safely.
    Administrative fields (role, email, is_active) cannot be edited.
    """

    phone_number = forms.CharField(
        max_length=15,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": INPUT_CSS,
                "autocomplete": "tel",
            }
        ),
    )

    class Meta:
        model = StudentProfile
        fields = [
            "full_name",
            "document_type",
            "document_number",
            "emergency_contact_name",
            "emergency_contact_phone",
            "address",
            "photo",
        ]
        widgets = {
            "full_name": forms.TextInput(attrs={"class": INPUT_CSS}),
            "document_type": forms.TextInput(
                attrs={
                    "placeholder": "e.g. Aadhaar Card, College ID",
                    "class": INPUT_CSS,
                }
            ),
            "document_number": forms.TextInput(attrs={"class": INPUT_CSS}),
            "emergency_contact_name": forms.TextInput(attrs={"class": INPUT_CSS}),
            "emergency_contact_phone": forms.TextInput(attrs={"class": INPUT_CSS}),
            "address": forms.Textarea(
                attrs={
                    "rows": 2,
                    "class": INPUT_CSS,
                }
            ),
            "photo": forms.FileInput(attrs={"class": FILE_INPUT_CSS}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.user_id:
            self.fields["phone_number"].initial = self.instance.user.phone_number

    def clean_phone_number(self):
        phone = self.cleaned_data.get("phone_number", "").strip()
        digits_only = re.sub(r"\D", "", phone)
        if len(digits_only) < 10 or len(digits_only) > 15:
            raise ValidationError("Please enter a valid 10-digit mobile number.")
        existing = User.objects.filter(phone_number=digits_only).exclude(id=self.instance.user_id)
        if existing.exists():
            raise ValidationError("This phone number is already registered to another user.")
        return digits_only

    def save(self, commit=True):
        profile = super().save(commit=False)
        phone = self.cleaned_data.get("phone_number")
        if phone and profile.user.phone_number != phone:
            profile.user.phone_number = phone
            profile.user.save(update_fields=["phone_number", "updated_at"])
        if commit:
            profile.save()
        return profile


class PaymentProofSubmissionForm(forms.Form):
    """
    Form for student to submit manual UPI transaction reference and proof screenshot.
    """

    utr_number = forms.CharField(
        max_length=64,
        required=True,
        label="UPI Transaction Reference (UTR / Txn ID)",
        widget=forms.TextInput(
            attrs={
                "placeholder": "e.g. 123456789012 or UPI Ref ID",
                "class": (
                    "form-input w-full font-mono uppercase tracking-wider px-4 py-2.5 rounded-lg "
                    "border border-slate-300 focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500"
                ),
                "autocomplete": "off",
            }
        ),
    )
    payment_screenshot = forms.ImageField(
        required=False,
        label="Payment Screenshot (Optional)",
        widget=forms.FileInput(
            attrs={
                "class": FILE_INPUT_CSS,
                "accept": "image/*",
            }
        ),
    )

    def clean_utr_number(self):
        utr = self.cleaned_data.get("utr_number", "").strip().upper()
        if not utr:
            raise ValidationError("A valid UPI UTR (transaction reference) is required.")
        # Check if already verified on another payment
        if Payment.objects.filter(utr_number=utr, status=Payment.Status.VERIFIED).exists():
            raise ValidationError("This UTR number has already been verified for another transaction.")
        return utr


class ComplaintSubmissionForm(forms.ModelForm):
    """
    Form for student to lodge a facility or desk issue complaint.
    """

    class Meta:
        model = Complaint
        fields = ["category", "title", "description"]
        widgets = {
            "category": forms.Select(attrs={"class": INPUT_CSS}),
            "title": forms.TextInput(
                attrs={
                    "placeholder": "Brief summary of the issue",
                    "class": INPUT_CSS,
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Provide details regarding the issue (e.g. AC cooling, light, power socket)...",
                    "class": INPUT_CSS,
                }
            ),
        }


class FeedbackSubmissionForm(forms.ModelForm):
    """
    Form for student to submit library feedback and rating (1 to 5 stars).
    """

    class Meta:
        model = Feedback
        fields = ["rating", "category", "description"]
        widgets = {
            "rating": forms.Select(
                choices=[
                    (5, "5 - Excellent (⭐⭐⭐⭐⭐)"),
                    (4, "4 - Very Good (⭐⭐⭐⭐)"),
                    (3, "3 - Good (⭐⭐⭐)"),
                    (2, "2 - Fair (⭐⭐)"),
                    (1, "1 - Needs Improvement (⭐)"),
                ],
                attrs={"class": INPUT_CSS},
            ),
            "category": forms.Select(attrs={"class": INPUT_CSS}),
            "description": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Share your thoughts on study atmosphere, facilities, or suggestions...",
                    "class": INPUT_CSS,
                }
            ),
        }
