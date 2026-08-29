from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.core.files.storage import default_storage

from apps.accounts.models import StudentProfile
from apps.bookings.exceptions import (
    ConcurrentBookingContentionException,
    NoSeatsAvailableException,
    StudentAlreadyHasActiveBookingException,
)
from apps.bookings.forms import (
    ComplaintSubmissionForm,
    FeedbackSubmissionForm,
    PaymentProofSubmissionForm,
    StudentProfileForm,
)
from apps.bookings.models import Booking
from apps.bookings.services import initiate_random_seat_booking
from apps.complaints.models import Complaint, Feedback
from apps.core.models import SystemSetting
from apps.payments.exceptions import InvalidPaymentStateException
from apps.payments.models import Payment, Receipt
from apps.payments.services import submit_payment_proof
from apps.seats.models import Seat


@login_required
def dashboard_view(request):
    """
    Primary Student Dashboard.

    Displays:
    - current booking status
    - assigned seat number
    - membership dates
    - grace period status
    - live seat hold countdown
    - dynamically configured UPI ID
    - dynamically configured UPI QR code
    - UPI payment form
    """

    # ---------------------------------------------------------
    # 1. Fetch active booking
    # ---------------------------------------------------------

    active_booking = (
        Booking.objects
        .filter(
            student=request.user,
            is_active=True,
        )
        .select_related("seat")
        .prefetch_related("payments")
        .first()
    )

    # ---------------------------------------------------------
    # 2. Determine pending payment
    # ---------------------------------------------------------

    pending_payment = None
    payment_form = None

    if active_booking:
        pending_payment = (
            active_booking.payments
            .filter(
                status=Payment.Status.PENDING_VERIFICATION
            )
            .last()
        )

        if (
            pending_payment
            and not pending_payment.is_submitted
            and not active_booking.is_hold_expired
        ):
            payment_form = PaymentProofSubmissionForm()

    # ---------------------------------------------------------
    # 3. Seat availability
    # ---------------------------------------------------------

    available_seats_count = (
        Seat.objects
        .filter(
            status=Seat.Status.AVAILABLE,
            is_active=True,
        )
        .count()
    )

    # ---------------------------------------------------------
    # 4. Student profile
    # ---------------------------------------------------------

    profile, _ = StudentProfile.objects.get_or_create(
        user=request.user,
        defaults={
            "full_name": request.user.email,
        },
    )

    # ---------------------------------------------------------
    # 5. Dynamic payment configuration
    #
    # These values are controlled from:
    # Admin Dashboard -> Settings
    #
    # No UPI ID or QR image is hardcoded here.
    # ---------------------------------------------------------

    upi_vpa = SystemSetting.get_setting(
        "UPI_VPA",
        default="",
    ).strip()

    qr_image_path = SystemSetting.get_setting(
        "UPI_QR_IMAGE",
        default="",
    ).strip()

    upi_qr_url = ""

    if qr_image_path:
        try:
            upi_qr_url = default_storage.url(qr_image_path)
        except Exception:
            # If the configured file cannot be resolved,
            # simply don't display a broken QR image.
            upi_qr_url = ""

    # ---------------------------------------------------------
    # 6. Dashboard context
    # ---------------------------------------------------------

    context = {
        "student_profile": profile,
        "active_booking": active_booking,
        "pending_payment": pending_payment,
        "payment_form": payment_form,

        "available_seats_count": available_seats_count,

        "total_seats": getattr(
            settings,
            "TOTAL_LIBRARY_SEATS",
            150,
        ),

        "seat_fee": getattr(
            settings,
            "SEAT_MONTHLY_FEE",
            800,
        ),

        # Dynamic payment configuration
        "upi_vpa": upi_vpa,
        "upi_qr_url": upi_qr_url,
    }

    return render(
        request,
        "portal/dashboard.html",
        context,
    )


@login_required
@require_POST
def book_seat_view(request):
    """
    Initiates random seat allocation for the authenticated student.

    Delegates exclusively to the domain service layer.
    """

    try:
        fee = getattr(
            settings,
            "SEAT_MONTHLY_FEE",
            800,
        )

        booking = initiate_random_seat_booking(
            request.user
        )

        messages.success(
            request,
            f"Seat #{booking.seat.number} allocated! "
            f"Please complete your ₹{fee} UPI payment "
            "and submit your transaction UTR within "
            "30 minutes to confirm your seat.",
        )

    except StudentAlreadyHasActiveBookingException as e:
        messages.warning(
            request,
            str(e),
        )

    except NoSeatsAvailableException as e:
        messages.error(
            request,
            str(e),
        )

    except ConcurrentBookingContentionException as e:
        messages.info(
            request,
            str(e),
        )

    except Exception as e:
        messages.error(
            request,
            f"Unable to process booking: {e}",
        )

    return redirect(
        "portal:dashboard"
    )


@login_required
@require_POST
def submit_payment_view(
    request,
    payment_id: int,
):
    """
    Processes manual UPI payment proof submission.

    Accepts:
    - UTR / transaction reference
    - optional payment screenshot

    Delegates payment processing to the domain service.
    """

    payment = get_object_or_404(
        Payment,
        id=payment_id,
        booking__student=request.user,
    )

    form = PaymentProofSubmissionForm(
        request.POST,
        request.FILES,
    )

    if form.is_valid():
        try:
            submit_payment_proof(
                payment_id=payment.id,
                student=request.user,
                utr_number=form.cleaned_data[
                    "utr_number"
                ],
                screenshot=form.cleaned_data.get(
                    "payment_screenshot"
                ),
            )

            messages.success(
                request,
                "Payment proof submitted successfully! "
                "Your seat remains held while the "
                "library administrator verifies your transaction.",
            )

        except InvalidPaymentStateException as e:
            messages.error(
                request,
                str(e),
            )

        except Exception as e:
            messages.error(
                request,
                f"Payment submission error: {e}",
            )

    else:
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(
                    request,
                    f"{error}",
                )

    return redirect(
        "portal:dashboard"
    )


@login_required
def profile_view(request):
    """
    Student profile management view.

    Allows editing contact details and personal profile safely.
    """

    profile, _ = StudentProfile.objects.get_or_create(
        user=request.user,
        defaults={
            "full_name": request.user.email,
        },
    )

    if request.method == "POST":
        form = StudentProfileForm(
            request.POST,
            request.FILES,
            instance=profile,
        )

        if form.is_valid():
            form.save()

            messages.success(
                request,
                "Your profile has been updated successfully.",
            )

            return redirect(
                "portal:profile"
            )

    else:
        form = StudentProfileForm(
            instance=profile
        )

    return render(
        request,
        "portal/profile.html",
        {
            "form": form,
            "profile": profile,
        },
    )


@login_required
def complaints_view(request):
    """
    Complaint ticketing view for lodging and
    tracking desk/facility issues.
    """

    import uuid
    from django.utils import timezone

    complaints = (
        Complaint.objects
        .filter(
            student=request.user
        )
        .order_by("-created_at")
    )

    if request.method == "POST":
        form = ComplaintSubmissionForm(
            request.POST
        )

        if form.is_valid():
            complaint = form.save(
                commit=False
            )

            complaint.student = request.user

            if not complaint.ticket_number:
                complaint.ticket_number = (
                    f"TKT-"
                    f"{timezone.now().strftime('%Y%m')}-"
                    f"{uuid.uuid4().hex[:6].upper()}"
                )

            # Attach active seat if student currently holds one
            active_booking = (
                Booking.objects
                .filter(
                    student=request.user,
                    is_active=True,
                )
                .first()
            )

            if active_booking:
                complaint.seat = (
                    active_booking.seat
                )

            complaint.save()

            messages.success(
                request,
                f"Complaint #{complaint.ticket_number} "
                "submitted. The librarian has been notified.",
            )

            return redirect(
                "portal:complaints"
            )

    else:
        form = ComplaintSubmissionForm()

    return render(
        request,
        "portal/complaints.html",
        {
            "form": form,
            "complaints": complaints,
        },
    )


@login_required
def feedback_view(request):
    """
    Student feedback view for submitting
    reviews and ratings (1 to 5 stars).
    """

    feedbacks = (
        Feedback.objects
        .filter(
            student=request.user
        )
        .order_by("-created_at")
    )

    if request.method == "POST":
        form = FeedbackSubmissionForm(
            request.POST
        )

        if form.is_valid():
            feedback = form.save(
                commit=False
            )

            feedback.student = request.user
            feedback.save()

            messages.success(
                request,
                "Thank you for your valuable feedback!",
            )

            return redirect(
                "portal:feedback"
            )

    else:
        form = FeedbackSubmissionForm()

    return render(
        request,
        "portal/feedback.html",
        {
            "form": form,
            "feedbacks": feedbacks,
        },
    )


@login_required
def history_view(request):
    """
    View displaying past booking allocations,
    payment attempts, and official receipts.
    """

    bookings = (
        Booking.objects
        .filter(
            student=request.user
        )
        .select_related("seat")
        .prefetch_related(
            "payments__receipt"
        )
        .order_by("-created_at")
    )

    receipts = (
        Receipt.objects
        .filter(
            payment__booking__student=request.user
        )
        .select_related(
            "payment__booking__seat"
        )
        .order_by("-issued_at")
    )

    return render(
        request,
        "portal/history.html",
        {
            "bookings": bookings,
            "receipts": receipts,
        },
    )
    
@login_required
def download_receipt_view(
    request,
    receipt_id: int,
):
    """
    Dynamically generates and downloads an official receipt PDF.

    Security:
    A student can only download a receipt belonging to
    their own booking.

    The PDF is generated entirely in memory and is never
    stored on disk.
    """

    receipt = get_object_or_404(
        Receipt.objects.select_related(
            "payment__booking__student",
        ),
        id=receipt_id,
        payment__booking__student=request.user,
    )

    from apps.payments.receipt_pdf import generate_receipt_pdf

    pdf_bytes = generate_receipt_pdf(receipt)

    response = HttpResponse(
        pdf_bytes,
        content_type="application/pdf",
    )

    response[
        "Content-Disposition"
    ] = (
        "attachment; "
        f'filename="{receipt.receipt_number}.pdf"'
    )

    return response