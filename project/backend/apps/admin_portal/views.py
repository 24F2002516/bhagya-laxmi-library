from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.db.models import Q, Sum, Count, Avg
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from django.views.decorators.http import require_POST
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.accounts.forms import (
    AuthenticatedResetPasswordForm,
    ChangePasswordForm,
    ForgotPasswordForm,
    SetNewPasswordForm,
    VerifyOTPForm,
)
from apps.accounts.models import EmailOTP, User
from apps.accounts.services import send_otp_email
from apps.accounts.views import mask_email
from apps.bookings.models import Booking
from apps.bookings.services import vacate_booking
from apps.seats.models import Seat, SeatMaintenanceLog
from apps.complaints.models import Complaint, Feedback
from apps.payments.models import Payment
from apps.audit.models import AuditLog
from apps.core.models import SystemSetting
from apps.payments.exceptions import InvalidPaymentStateException
from apps.payments.services import (
    reject_payment_attempt,
    verify_payment_and_activate_membership,
)
from .decorators import admin_required


def admin_login_view(request):
    if request.user.is_authenticated and request.user.is_admin_user:
        return redirect("admin_portal:dashboard")

    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")

        if email != settings.ADMIN_EMAIL.strip().lower():
            messages.error(request, "Invalid email or password.")
            return render(request, "admin_portal/login.html")

        user = authenticate(
            request,
            username=email,
            password=password,
        )

        if user is None:
            messages.error(request, "Invalid email or password.")
            return render(request, "admin_portal/login.html")

        if not user.is_admin_user:
            messages.error(
                request,
                "You do not have permission to access the admin portal.",
            )
            return render(request, "admin_portal/login.html")

        if not user.is_active:
            messages.error(request, "This account is inactive.")
            return render(request, "admin_portal/login.html")

        login(request, user)
        return redirect("admin_portal:dashboard")

    return render(request, "admin_portal/login.html")


def admin_logout_view(request):
    logout(request)
    return redirect("admin_portal:login")


def admin_forgot_password_view(request):
    """
    Step 1 of the logged-out admin password reset flow: collects the admin
    email and dispatches a 6-digit OTP. Only the single admin account
    (role=ADMIN) can ever receive an OTP here; uses account-enumeration
    safe messaging either way, mirroring the student portal flow.
    """
    if request.user.is_authenticated and request.user.is_admin_user:
        return redirect("admin_portal:dashboard")

    if request.method == "POST":
        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"]
            user = User.objects.filter(
                email__iexact=email,
                role=User.Role.ADMIN,
                is_active=True,
            ).first()

            if user:
                otp_obj, raw_code, success = send_otp_email(user, EmailOTP.Purpose.PASSWORD_RESET)
                if success:
                    request.session["admin_reset_user_id"] = user.id
                    request.session["admin_reset_email"] = user.email
            else:
                request.session["admin_reset_email"] = email

            messages.info(
                request,
                f"If an admin account is associated with {email}, a 6-digit verification code has been sent.",
            )
            return redirect("admin_portal:verify_reset_otp")
    else:
        form = ForgotPasswordForm()

    return render(request, "admin_portal/forgot_password.html", {"form": form})


def admin_verify_reset_otp_view(request):
    """
    Step 2: Verifies the 6-digit OTP code for the logged-out admin password
    reset flow.
    """
    if request.user.is_authenticated and request.user.is_admin_user:
        return redirect("admin_portal:dashboard")

    user_id = request.session.get("admin_reset_user_id")
    email = request.session.get("admin_reset_email")

    if not email:
        messages.warning(request, "Please enter the admin email address first.")
        return redirect("admin_portal:forgot_password")

    if request.method == "POST":
        form = VerifyOTPForm(request.POST)
        if form.is_valid():
            otp_code = form.cleaned_data["otp_code"]

            if not user_id:
                form.add_error("otp_code", "Invalid or expired verification code.")
            else:
                user = User.objects.filter(id=user_id, role=User.Role.ADMIN, is_active=True).first()
                if not user:
                    form.add_error("otp_code", "Admin account not found.")
                else:
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
                        request.session["admin_reset_otp_verified"] = True
                        messages.success(request, "Verification code confirmed. Please set your new password.")
                        return redirect("admin_portal:set_new_password")
                    else:
                        form.add_error("otp_code", "Invalid, expired, or locked verification code.")
    else:
        form = VerifyOTPForm()

    return render(
        request,
        "admin_portal/verify_reset_otp.html",
        {"form": form, "email": email},
    )


def admin_set_new_password_view(request):
    """
    Step 3: Lets the admin choose a new password after a verified OTP,
    for the logged-out password reset flow.
    """
    if request.user.is_authenticated and request.user.is_admin_user:
        return redirect("admin_portal:dashboard")

    user_id = request.session.get("admin_reset_user_id")
    otp_verified = request.session.get("admin_reset_otp_verified")

    if not user_id or not otp_verified:
        messages.error(request, "Unauthorized password reset attempt. Please verify your OTP code.")
        return redirect("admin_portal:forgot_password")

    user = User.objects.filter(id=user_id, role=User.Role.ADMIN, is_active=True).first()
    if not user:
        messages.error(request, "Admin account not found.")
        return redirect("admin_portal:forgot_password")

    if request.method == "POST":
        form = SetNewPasswordForm(request.POST)
        if form.is_valid():
            user.set_password(form.cleaned_data["new_password"])
            user.save(update_fields=["password", "updated_at"])

            request.session.pop("admin_reset_user_id", None)
            request.session.pop("admin_reset_email", None)
            request.session.pop("admin_reset_otp_verified", None)

            messages.success(request, "Your password has been reset successfully! Please log in.")
            return redirect("admin_portal:login")
    else:
        form = SetNewPasswordForm()

    return render(request, "admin_portal/set_new_password.html", {"form": form})


@admin_required
def admin_send_change_password_otp_view(request):
    """
    Dispatches a password-change OTP to the logged-in admin's registered email.
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
                "Unable to deliver OTP email. Please ensure SMTP configuration is set or contact IT support.",
            )
    return redirect("admin_portal:change_password")


@admin_required
def admin_change_password_view(request):
    """
    Allows an authenticated admin to change their password with mandatory email OTP verification.
    Also exposes the "forgot current password" modal (OTP-based reset) for admins locked out
    of their current password, mirroring the student portal flow.
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
                return redirect("admin_portal:dashboard")
    else:
        form = ChangePasswordForm(user=request.user)

    return render(
        request,
        "admin_portal/change_password.html",
        {
            "form": form,
            "reset_form": reset_form,
            "show_reset_modal": show_modal,
            "masked_email": mask_email(request.user.email),
        },
    )


@admin_required
def admin_reset_password_view(request):
    """
    Allows an authenticated admin who forgot their current password to reset it via a
    6-digit email OTP directly inside the Change Password modal. On success the admin
    is logged out and redirected to the admin login screen with the new password.
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
                    "Unable to deliver OTP email. Please check your SMTP configuration or contact IT support.",
                )
            return redirect(f"{reverse('admin_portal:change_password')}?modal=open&otp_sent=1")

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
                    "admin_portal/change_password.html",
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
                return redirect("admin_portal:login")
        else:
            change_form = ChangePasswordForm(user=request.user)
            return render(
                request,
                "admin_portal/change_password.html",
                {
                    "form": change_form,
                    "reset_form": form,
                    "show_reset_modal": True,
                    "masked_email": mask_email(request.user.email),
                },
            )

    return redirect("admin_portal:change_password")


@admin_required
def admin_dashboard_view(request):
    active_membership_statuses = [
        Booking.Status.CONFIRMED,
        Booking.Status.EXPIRING_SOON,
        Booking.Status.GRACE_PERIOD,
    ]
    active_memberships = Booking.objects.filter(
        is_active=True, status__in=active_membership_statuses
    )
    pending_payments = Payment.objects.filter(
        status=Payment.Status.PENDING_VERIFICATION
    )
    recent_submissions = Payment.objects.filter(
        submitted_at__isnull=False
    ).select_related("booking").order_by("-submitted_at")[:3]
    recent_activity = [
        *(
            {
                "kind": "Registration",
                "label": student.email,
                "created_at": student.date_joined,
            }
            for student in User.objects.filter(
                role=User.Role.STUDENT
            ).order_by("-date_joined")[:3]
        ),
        *(
            {
                "kind": "Booking",
                "label": booking.booking_reference,
                "created_at": booking.created_at,
            }
            for booking in Booking.objects.order_by("-created_at")[:3]
        ),
        *(
            {
                "kind": "Payment",
                "label": payment.booking.booking_reference,
                "created_at": payment.submitted_at,
            }
            for payment in recent_submissions
        ),
        *(
            {
                "kind": "Complaint",
                "label": complaint.ticket_number,
                "created_at": complaint.created_at,
            }
            for complaint in Complaint.objects.order_by("-created_at")[:3]
        ),
    ]
    recent_activity.sort(key=lambda item: item["created_at"], reverse=True)
    stats = {
        "total_students": User.objects.filter(role=User.Role.STUDENT).count(),
        "active_members": active_memberships.values("student_id").distinct().count(),
        "pending_payments": pending_payments.count(),
        "available_seats": Seat.objects.filter(
            status=Seat.Status.AVAILABLE, is_active=True
        ).count(),
        "held_seats": Seat.objects.filter(
            status=Seat.Status.HELD, is_active=True
        ).count(),
        "occupied_seats": Seat.objects.filter(
            status=Seat.Status.BOOKED, is_active=True
        ).count(),
    }
    context = {
        "stats": stats,
        "stat_cards": [
            {"label": "Total Students", "value": stats["total_students"]},
            {"label": "Active Members", "value": stats["active_members"]},
            {"label": "Pending Payments", "value": stats["pending_payments"]},
            {"label": "Available Seats", "value": stats["available_seats"]},
            {"label": "Held Seats", "value": stats["held_seats"]},
            {"label": "Occupied Seats", "value": stats["occupied_seats"]},
        ],
        "recent_activity": recent_activity[:8],
        "unresolved_complaints": Complaint.objects.exclude(
            status__in=[Complaint.Status.RESOLVED, Complaint.Status.CLOSED]
        ).count(),
        "now": timezone.now(),
    }
    return render(request, "admin_portal/dashboard.html", context)


@admin_required
def admin_placeholder_view(request):
    section = request.resolver_match.url_name.replace("_", " ").title()
    return render(
        request,
        "admin_portal/placeholder.html",
        {"section": section},
    )


@admin_required
def admin_seats_view(request):
    seats = Seat.objects.all().order_by("number")

    status = request.GET.get("status", "ALL").strip()
    search = request.GET.get("q", "").strip()

    valid_statuses = {choice.value for choice in Seat.Status}

    if status not in valid_statuses and status != "ALL":
        status = "ALL"

    if status != "ALL":
        seats = seats.filter(status=status)

    if search:
        seats = seats.filter(number__icontains=search)

    active_bookings = Booking.objects.filter(
        seat_id__in=seats.values("id"),
        status__in=Booking.ACTIVE_STATUSES,
    ).select_related("student", "seat")

    booking_by_seat = {
        booking.seat_id: booking
        for booking in active_bookings
    }

    seat_rows = [
        {
            "seat": seat,
            "booking": booking_by_seat.get(seat.id),
        }
        for seat in seats
    ]

    counts = {
        "total": Seat.objects.filter(is_active=True).count(),
        "available": Seat.objects.filter(
            status=Seat.Status.AVAILABLE,
            is_active=True,
        ).count(),
        "held": Seat.objects.filter(
            status=Seat.Status.HELD,
            is_active=True,
        ).count(),
        "booked": Seat.objects.filter(
            status=Seat.Status.BOOKED,
            is_active=True,
        ).count(),
        "maintenance": Seat.objects.filter(
            status=Seat.Status.MAINTENANCE,
            is_active=True,
        ).count(),
    }

    return render(
        request,
        "admin_portal/seats/list.html",
        {
            "seat_rows": seat_rows,
            "counts": counts,
            "status": status,
            "search": search,
        },
    )


@admin_required
def admin_seat_detail_view(request, seat_id):
    seat = get_object_or_404(Seat, id=seat_id)

    active_booking = (
        Booking.objects.filter(
            seat=seat,
            status__in=Booking.ACTIVE_STATUSES,
        )
        .select_related("student", "student__student_profile")
        .order_by("-created_at")
        .first()
    )

    maintenance_logs = seat.maintenance_logs.select_related(
        "reported_by"
    ).order_by("-created_at")

    return render(
        request,
        "admin_portal/seats/detail.html",
        {
            "seat": seat,
            "booking": active_booking,
            "maintenance_logs": maintenance_logs,
            "now": timezone.now(),
        },
    )


@admin_required
@require_POST
def admin_seat_maintenance_view(request, seat_id, action):
    seat = get_object_or_404(Seat, id=seat_id)

    if action == "start":
        if seat.status != Seat.Status.AVAILABLE:
            messages.error(
                request,
                "Only an available seat can be placed under maintenance.",
            )
            return redirect(
                "admin_portal:seat_detail",
                seat_id=seat.id,
            )

        issue_description = request.POST.get(
            "issue_description",
            "",
        ).strip()

        if not issue_description:
            messages.error(
                request,
                "Please provide a maintenance reason.",
            )
            return redirect(
                "admin_portal:seat_detail",
                seat_id=seat.id,
            )

        SeatMaintenanceLog.objects.create(
            seat=seat,
            reported_by=request.user,
            issue_description=issue_description,
            status=SeatMaintenanceLog.MaintenanceStatus.IN_PROGRESS,
        )

        seat.status = Seat.Status.MAINTENANCE
        seat.save(update_fields=["status", "updated_at"])

        messages.success(
            request,
            f"Seat #{seat.number} is now under maintenance.",
        )

    elif action == "resolve":
        if seat.status != Seat.Status.MAINTENANCE:
            messages.error(
                request,
                "This seat is not currently under maintenance.",
            )
            return redirect(
                "admin_portal:seat_detail",
                seat_id=seat.id,
            )

        active_log = (
            seat.maintenance_logs.filter(
                status__in=[
                    SeatMaintenanceLog.MaintenanceStatus.PENDING,
                    SeatMaintenanceLog.MaintenanceStatus.IN_PROGRESS,
                ]
            )
            .order_by("-created_at")
            .first()
        )

        if active_log:
            active_log.status = SeatMaintenanceLog.MaintenanceStatus.RESOLVED
            active_log.resolved_at = timezone.now()
            active_log.save(
                update_fields=[
                    "status",
                    "resolved_at",
                    "updated_at",
                ]
            )

        seat.status = Seat.Status.AVAILABLE
        seat.save(update_fields=["status", "updated_at"])

        messages.success(
            request,
            f"Seat #{seat.number} is available again.",
        )

    else:
        raise Http404

    return redirect(
        "admin_portal:seat_detail",
        seat_id=seat.id,
    )

@admin_required
def admin_payment_list_view(request):
    payments = Payment.objects.select_related(
        "booking__student", "booking__seat", "booking__student__student_profile"
    )
    status = request.GET.get("status", "PENDING_VERIFICATION").strip()
    valid_statuses = {choice.value for choice in Payment.Status}
    if status not in valid_statuses and status != "ALL":
        status = "PENDING_VERIFICATION"
    if status != "ALL":
        payments = payments.filter(status=status)

    search = request.GET.get("q", "").strip()
    if search:
        payments = payments.filter(
            Q(booking__student__email__icontains=search)
            | Q(booking__student__student_profile__full_name__icontains=search)
        )
    utr = request.GET.get("utr", "").strip()
    if utr:
        payments = payments.filter(utr_number__icontains=utr)

    from django.core.paginator import Paginator

    page = Paginator(payments.order_by("-created_at"), 25).get_page(
        request.GET.get("page")
    )
    return render(
        request,
        "admin_portal/payments/list.html",
        {
            "page_obj": page,
            "status": status,
            "search": search,
            "utr": utr,
            "payment_statuses": Payment.Status,
        },
    )


@admin_required
def admin_payment_detail_view(request, payment_id):
    payment = get_object_or_404(
        Payment.objects.select_related(
            "booking__student", "booking__student__student_profile", "booking__seat"
        ),
        id=payment_id,
    )
    return render(
        request,
        "admin_portal/payments/detail.html",
        {"payment": payment},
    )


@admin_required
def admin_payment_screenshot_view(request, payment_id):
    payment = get_object_or_404(Payment, id=payment_id)
    if not payment.payment_screenshot:
        raise Http404
    return FileResponse(
        payment.payment_screenshot.open("rb"),
        content_type="image/*",
    )


@admin_required
@require_http_methods(["GET", "POST"])
def admin_payment_action_view(request, payment_id, action):
    payment = get_object_or_404(
        Payment.objects.select_related(
            "booking__student", "booking__student__student_profile", "booking__seat"
        ),
        id=payment_id,
    )
    if request.method == "GET":
        return render(
            request,
            "admin_portal/payments/confirm.html",
            {"payment": payment, "action": action},
        )

    try:
        if action == "approve":
            verify_payment_and_activate_membership(payment.id, request.user)
            messages.success(request, "Payment approved and membership activated.")
        elif action == "reject":
            reason = request.POST.get(
                "reason", "Payment rejected by administrator"
            ).strip()
            reject_payment_attempt(payment.id, request.user, reason)
            messages.success(request, "Payment rejected.")
        else:
            raise Http404
    except InvalidPaymentStateException as exc:
        messages.error(request, str(exc))
    return redirect("admin_portal:payment_detail", payment_id=payment.id)


# ============================================================
# STUDENT MANAGEMENT
# ============================================================

from django.core.paginator import Paginator
from django.db.models import Q


@admin_required
def admin_student_list_view(request):
    """
    Admin student management list.

    Supports:
    - Search by name, email, phone
    - Active/inactive filtering
    - Pagination
    """

    students = (
        User.objects
        .filter(role=User.Role.STUDENT)
        .select_related("student_profile")
        .order_by("-date_joined")
    )

    search = request.GET.get("q", "").strip()
    status = request.GET.get("status", "ALL").strip().upper()

    if search:
        students = students.filter(
            Q(email__icontains=search)
            | Q(phone_number__icontains=search)
            | Q(student_profile__full_name__icontains=search)
        )

    if status == "ACTIVE":
        students = students.filter(is_active=True)

    elif status == "INACTIVE":
        students = students.filter(is_active=False)

    paginator = Paginator(students, 25)

    page_obj = paginator.get_page(
        request.GET.get("page")
    )

    return render(
        request,
        "admin_portal/students/list.html",
        {
            "page_obj": page_obj,
            "search": search,
            "status": status,
        },
    )


@admin_required
def admin_student_detail_view(request, student_id):
    """
    Admin view of a student's complete account,
    membership, booking and payment history.
    """

    student = get_object_or_404(
        User.objects.select_related("student_profile"),
        id=student_id,
        role=User.Role.STUDENT,
    )

    bookings = (
        Booking.objects
        .filter(student=student)
        .select_related("seat")
        .order_by("-created_at")
    )

    payments = (
        Payment.objects
        .filter(booking__student=student)
        .select_related("booking", "booking__seat")
        .order_by("-created_at")
    )

    active_booking = (
        bookings
        .filter(
            status__in=[
                Booking.Status.PENDING_PAYMENT,
                Booking.Status.CONFIRMED,
                Booking.Status.EXPIRING_SOON,
                Booking.Status.GRACE_PERIOD,
            ]
        )
        .first()
    )

    return render(
        request,
        "admin_portal/students/detail.html",
        {
            "student": student,
            "profile": getattr(student, "student_profile", None),
            "bookings": bookings,
            "payments": payments,
            "active_booking": active_booking,
        },
    )


@admin_required
@require_POST
def admin_student_toggle_status_view(request, student_id):
    """
    Activate or deactivate a student account.
    """

    student = get_object_or_404(
        User,
        id=student_id,
        role=User.Role.STUDENT,
    )

    student.is_active = not student.is_active
    student.save(update_fields=["is_active"])

    if student.is_active:
        messages.success(
            request,
            f"{student.email} has been activated.",
        )
    else:
        messages.success(
            request,
            f"{student.email} has been deactivated.",
        )

    return redirect(
        "admin_portal:student_detail",
        student_id=student.id,
    )
    
@admin_required
def admin_booking_list_view(request):
    bookings = Booking.objects.select_related(
        "student",
        "student__student_profile",
        "seat",
    ).order_by("-created_at")

    status = request.GET.get("status", "ALL").strip()
    search = request.GET.get("q", "").strip()

    valid_statuses = {choice.value for choice in Booking.Status}

    if status not in valid_statuses and status != "ALL":
        status = "ALL"

    if status != "ALL":
        bookings = bookings.filter(status=status)

    if search:
        bookings = bookings.filter(
            Q(booking_reference__icontains=search)
            | Q(student__email__icontains=search)
            | Q(student__student_profile__full_name__icontains=search)
            | Q(seat__number__icontains=search)
        )

    all_bookings = Booking.objects.all()

    counts = {
        "total": all_bookings.count(),
        "active": all_bookings.filter(
            status__in=Booking.ACTIVE_STATUSES
        ).count(),
        "pending": all_bookings.filter(
            status=Booking.Status.PENDING_PAYMENT
        ).count(),
        "confirmed": all_bookings.filter(
            status__in=[
                Booking.Status.CONFIRMED,
                Booking.Status.EXPIRING_SOON,
                Booking.Status.GRACE_PERIOD,
            ]
        ).count(),
        "expired": all_bookings.filter(
            status=Booking.Status.EXPIRED
        ).count(),
        "cancelled": all_bookings.filter(
            status=Booking.Status.CANCELLED
        ).count(),
    }

    return render(
        request,
        "admin_portal/bookings/list.html",
        {
            "bookings": bookings,
            "counts": counts,
            "status": status,
            "search": search,
            "booking_statuses": Booking.Status,
        },
    )


@admin_required
def admin_booking_detail_view(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related(
            "student",
            "student__student_profile",
            "seat",
        ),
        id=booking_id,
    )

    payments = booking.payments.all().order_by("-created_at")

    can_vacate = (
        booking.is_active
        and booking.status in Booking.ACTIVE_STATUSES
    )

    return render(
        request,
        "admin_portal/bookings/detail.html",
        {
            "booking": booking,
            "payments": payments,
            "can_vacate": can_vacate,
        },
    )
    
    
    
    
@admin_required
@require_http_methods(["POST"])
def admin_booking_vacate_view(request, booking_id):
    """
    Manually vacates an active booking after the administrator
    has physically refunded the student.

    No monetary refund is processed by the application.
    """

    try:
        booking = vacate_booking(
            booking_id=booking_id,
            admin_user=request.user,
        )

    except Booking.DoesNotExist:
        messages.error(
            request,
            "Booking not found.",
        )

        return redirect(
            "admin_portal:bookings"
        )

    except ValueError as exc:
        messages.error(
            request,
            str(exc),
        )

        return redirect(
            "admin_portal:booking_detail",
            booking_id=booking_id,
        )

    messages.success(
        request,
        (
            f"Seat #{booking.seat.number} has been vacated successfully. "
            f"Booking {booking.booking_reference} is now cancelled."
        ),
    )

    return redirect(
        "admin_portal:booking_detail",
        booking_id=booking.id,
    )

    
@admin_required
def admin_complaint_list_view(request):
    complaints = (
        Complaint.objects
        .select_related(
            "student",
            "student__student_profile",
            "seat",
            "resolved_by",
        )
        .order_by("-created_at")
    )

    status = request.GET.get("status", "ALL").strip().upper()
    search = request.GET.get("q", "").strip()

    valid_statuses = {choice.value for choice in Complaint.Status}

    if status not in valid_statuses and status != "ALL":
        status = "ALL"

    if status != "ALL":
        complaints = complaints.filter(status=status)

    if search:
        complaints = complaints.filter(
            Q(ticket_number__icontains=search)
            | Q(title__icontains=search)
            | Q(student__email__icontains=search)
            | Q(
                student__student_profile__full_name__icontains=search
            )
        )

    all_complaints = Complaint.objects.all()

    counts = {
        "total": all_complaints.count(),
        "open": all_complaints.filter(
            status=Complaint.Status.OPEN
        ).count(),
        "in_progress": all_complaints.filter(
            status=Complaint.Status.IN_PROGRESS
        ).count(),
        "resolved": all_complaints.filter(
            status=Complaint.Status.RESOLVED
        ).count(),
        "closed": all_complaints.filter(
            status=Complaint.Status.CLOSED
        ).count(),
    }

    return render(
        request,
        "admin_portal/complaints/list.html",
        {
            "complaints": complaints,
            "counts": counts,
            "status": status,
            "complaint_statuses": Complaint.Status,
            "search": search,
        },
    )


@admin_required
def admin_complaint_detail_view(request, complaint_id):
    complaint = get_object_or_404(
        Complaint.objects.select_related(
            "student",
            "student__student_profile",
            "seat",
            "resolved_by",
        ),
        id=complaint_id,
    )

    return render(
        request,
        "admin_portal/complaints/detail.html",
        {
            "complaint": complaint,
            "complaint_statuses": Complaint.Status,
        },
    )


@admin_required
@require_POST
def admin_complaint_update_view(request, complaint_id):
    complaint = get_object_or_404(Complaint, id=complaint_id)

    status = request.POST.get("status", "").strip().upper()
    resolution_notes = request.POST.get("resolution_notes", "").strip()

    valid_statuses = {choice.value for choice in Complaint.Status}

    if status not in valid_statuses:
        messages.error(request, "Invalid complaint status.")
        return redirect(
            "admin_portal:complaint_detail",
            complaint_id=complaint.id,
        )

    complaint.status = status
    complaint.resolution_notes = resolution_notes

    if status in [
        Complaint.Status.RESOLVED,
        Complaint.Status.CLOSED,
    ]:
        complaint.resolved_by = request.user

        if not complaint.resolved_at:
            complaint.resolved_at = timezone.now()
    else:
        complaint.resolved_by = None
        complaint.resolved_at = None

    complaint.save(
        update_fields=[
            "status",
            "resolution_notes",
            "resolved_by",
            "resolved_at",
            "updated_at",
        ]
    )

    messages.success(
        request,
        f"Complaint {complaint.ticket_number} updated successfully.",
    )

    return redirect(
        "admin_portal:complaint_detail",
        complaint_id=complaint.id,
    )
    
# ============================================================
# FEEDBACK MANAGEMENT
# ============================================================

@admin_required
def admin_feedback_list_view(request):
    feedbacks = (
        Feedback.objects
        .select_related("student", "student__student_profile", "reviewed_by")
        .order_by("-created_at")
    )

    filter_value = request.GET.get("status", "ALL").strip().upper()
    search = request.GET.get("q", "").strip()

    if filter_value == "REVIEWED":
        feedbacks = feedbacks.filter(is_reviewed=True)
    elif filter_value == "UNREVIEWED":
        feedbacks = feedbacks.filter(is_reviewed=False)
    elif filter_value != "ALL":
        filter_value = "ALL"

    if search:
        feedbacks = feedbacks.filter(
            Q(student__email__icontains=search)
            | Q(student__student_profile__full_name__icontains=search)
            | Q(description__icontains=search)
            | Q(category__icontains=search)
        )

    all_feedback = Feedback.objects.all()

    counts = {
        "total": all_feedback.count(),
        "unreviewed": all_feedback.filter(is_reviewed=False).count(),
        "reviewed": all_feedback.filter(is_reviewed=True).count(),
    }

    return render(
        request,
        "admin_portal/feedback/list.html",
        {
            "feedbacks": feedbacks,
            "counts": counts,
            "status": filter_value,
            "search": search,
        },
    )


@admin_required
def admin_feedback_detail_view(request, feedback_id):
    feedback = get_object_or_404(
        Feedback.objects.select_related(
            "student",
            "student__student_profile",
            "reviewed_by",
        ),
        id=feedback_id,
    )

    return render(
        request,
        "admin_portal/feedback/detail.html",
        {
            "feedback": feedback,
        },
    )


@admin_required
@require_POST
def admin_feedback_update_view(request, feedback_id):
    feedback = get_object_or_404(Feedback, id=feedback_id)

    reviewed = request.POST.get("is_reviewed") == "1"
    admin_notes = request.POST.get("admin_notes", "").strip()

    feedback.is_reviewed = reviewed
    feedback.admin_notes = admin_notes

    if reviewed:
        feedback.reviewed_by = request.user

        if not feedback.reviewed_at:
            feedback.reviewed_at = timezone.now()
    else:
        feedback.reviewed_by = None
        feedback.reviewed_at = None

    feedback.save(
        update_fields=[
            "is_reviewed",
            "admin_notes",
            "reviewed_by",
            "reviewed_at",
            "updated_at",
        ]
    )

    messages.success(
        request,
        "Feedback updated successfully.",
    )

    return redirect(
        "admin_portal:feedback_detail",
        feedback_id=feedback.id,
    )
    
@admin_required
def admin_reports_view(request):
    """
    Admin reports and operational analytics.
    """

    today = timezone.localdate()

    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()

    # -----------------------------
    # BASE QUERYSETS
    # -----------------------------

    bookings = Booking.objects.all()
    payments = Payment.objects.all()
    complaints = Complaint.objects.all()
    feedback_qs = Feedback.objects.all()

    # -----------------------------
    # DATE FILTER
    # -----------------------------

    if date_from:
        bookings = bookings.filter(
            created_at__date__gte=date_from
        )

        payments = payments.filter(
            created_at__date__gte=date_from
        )

        complaints = complaints.filter(
            created_at__date__gte=date_from
        )

        feedback_qs = feedback_qs.filter(
            created_at__date__gte=date_from
        )

    if date_to:
        bookings = bookings.filter(
            created_at__date__lte=date_to
        )

        payments = payments.filter(
            created_at__date__lte=date_to
        )

        complaints = complaints.filter(
            created_at__date__lte=date_to
        )

        feedback_qs = feedback_qs.filter(
            created_at__date__lte=date_to
        )

    # -----------------------------
    # BASIC STATISTICS
    # -----------------------------

    total_students = User.objects.filter(
        role=User.Role.STUDENT
    ).count()

    active_members = Booking.objects.filter(
        is_active=True,
        status__in=Booking.ACTIVE_STATUSES,
    ).values(
        "student_id"
    ).distinct().count()

    total_bookings = bookings.count()

    # -----------------------------
    # PAYMENT STATISTICS
    # -----------------------------

    verified_payments = payments.filter(
        status=Payment.Status.VERIFIED
    )

    verified_revenue = (
        verified_payments.aggregate(
            total=Sum("amount")
        )["total"]
        or 0
    )

    pending_payments = payments.filter(
        status=Payment.Status.PENDING_VERIFICATION
    ).count()

    rejected_payments = payments.filter(
        status=Payment.Status.REJECTED
    ).count()

    # -----------------------------
    # BOOKING STATISTICS
    # -----------------------------

    booking_stats = {
        "pending": bookings.filter(
            status=Booking.Status.PENDING_PAYMENT
        ).count(),

        "confirmed": bookings.filter(
            status=Booking.Status.CONFIRMED
        ).count(),

        "expiring": bookings.filter(
            status=Booking.Status.EXPIRING_SOON
        ).count(),

        "grace": bookings.filter(
            status=Booking.Status.GRACE_PERIOD
        ).count(),

        "expired": bookings.filter(
            status=Booking.Status.EXPIRED
        ).count(),

        "cancelled": bookings.filter(
            status=Booking.Status.CANCELLED
        ).count(),
    }

    # -----------------------------
    # SEAT STATISTICS
    # -----------------------------

    total_seats = Seat.objects.filter(
        is_active=True
    ).count()

    available_seats = Seat.objects.filter(
        is_active=True,
        status=Seat.Status.AVAILABLE,
    ).count()

    held_seats = Seat.objects.filter(
        is_active=True,
        status=Seat.Status.HELD,
    ).count()

    occupied_seats = Seat.objects.filter(
        is_active=True,
        status=Seat.Status.BOOKED,
    ).count()

    maintenance_seats = Seat.objects.filter(
        is_active=True,
        status=Seat.Status.MAINTENANCE,
    ).count()

    if total_seats:
        utilization = round(
            (occupied_seats / total_seats) * 100,
            1,
        )
    else:
        utilization = 0

    # -----------------------------
    # COMPLAINT STATISTICS
    # -----------------------------

    complaint_stats = {
        "open": complaints.filter(
            status=Complaint.Status.OPEN
        ).count(),

        "in_progress": complaints.filter(
            status=Complaint.Status.IN_PROGRESS
        ).count(),

        "resolved": complaints.filter(
            status=Complaint.Status.RESOLVED
        ).count(),

        "closed": complaints.filter(
            status=Complaint.Status.CLOSED
        ).count(),
    }

    # -----------------------------
    # FEEDBACK STATISTICS
    # -----------------------------

    feedback_count = feedback_qs.count()

    average_rating = (
        feedback_qs.aggregate(
            average=Avg("rating")
        )["average"]
        or 0
    )

    reviewed_feedback = feedback_qs.filter(
        is_reviewed=True
    ).count()

    # -----------------------------
    # RENDER REPORT
    # -----------------------------

    return render(
        request,
        "admin_portal/reports.html",
        {
            "date_from": date_from,
            "date_to": date_to,
            "today": today,

            # Basic statistics
            "total_students": total_students,
            "active_members": active_members,
            "total_bookings": total_bookings,

            # Payments
            "verified_revenue": verified_revenue,
            "pending_payments": pending_payments,
            "rejected_payments": rejected_payments,

            # Bookings
            "booking_stats": booking_stats,

            # Seats
            "total_seats": total_seats,
            "available_seats": available_seats,
            "held_seats": held_seats,
            "occupied_seats": occupied_seats,
            "maintenance_seats": maintenance_seats,
            "utilization": utilization,

            # Complaints
            "complaint_stats": complaint_stats,

            # Feedback
            "feedback_count": feedback_count,
            "average_rating": average_rating,
            "reviewed_feedback": reviewed_feedback,
        },
    )
    
    
@admin_required
def admin_audit_log_list_view(request):
    """
    Display the system-wide immutable audit trail.
    """

    logs = (
        AuditLog.objects
        .select_related("actor")
        .order_by("-timestamp")
    )

    search = request.GET.get("q", "").strip()
    action = request.GET.get("action", "").strip()

    if search:
        logs = logs.filter(
            Q(action__icontains=search)
            | Q(target_model__icontains=search)
            | Q(target_id__icontains=search)
            | Q(actor__email__icontains=search)
        )

    if action:
        logs = logs.filter(action=action)

    actions = (
        AuditLog.objects
        .values_list("action", flat=True)
        .distinct()
        .order_by("action")
    )

    return render(
        request,
        "admin_portal/audit_logs/list.html",
        {
            "logs": logs,
            "search": search,
            "action": action,
            "actions": actions,
        },
    )
    
    
@admin_required
@require_http_methods(["GET", "POST"])
def admin_settings_view(request):
    """
    Admin system configuration page.

    Allows administrators to view and update runtime
    configuration stored in SystemSetting.

    UPI VPA is optional because students can pay
    directly by scanning the uploaded QR code.
    """

    setting_definitions = [
        {
            "key": "SEAT_HOLD_DURATION_MINUTES",
            "label": "Seat Hold Duration",
            "description": (
                "How long a selected seat remains temporarily held "
                "before the booking expires."
            ),
            "default": "30",
            "unit": "minutes",
        },
        {
            "key": "UPI_VPA",
            "label": "UPI VPA",
            "description": (
                "Optional UPI ID displayed to students for manual payment."
            ),
            "default": "",
            "unit": "",
        },
        {
            "key": "UPI_QR_IMAGE",
            "label": "UPI QR Code",
            "description": (
                "QR code displayed to students for manual UPI payment."
            ),
            "default": "",
            "unit": "",
        },
        {
            "key": "MAINTENANCE_BANNER",
            "label": "Maintenance Banner",
            "description": (
                "Optional message displayed to students when "
                "the library is under maintenance."
            ),
            "default": "",
            "unit": "",
        },
    ]

    if request.method == "POST":
        # -----------------------------
        # SEAT HOLD DURATION
        # -----------------------------

        hold_duration = request.POST.get(
            "SEAT_HOLD_DURATION_MINUTES",
            "",
        ).strip()

        try:
            duration = int(hold_duration)

            if duration <= 0:
                raise ValueError

        except (TypeError, ValueError):
            messages.error(
                request,
                "Seat hold duration must be a positive whole number.",
            )
            return redirect("admin_portal:settings")

        SystemSetting.objects.update_or_create(
            key="SEAT_HOLD_DURATION_MINUTES",
            defaults={
                "value": hold_duration,
                "description": (
                    "How long a selected seat remains temporarily "
                    "held before the booking expires."
                ),
            },
        )

        # -----------------------------
        # UPI VPA
        # -----------------------------

        # UPI VPA is OPTIONAL.
        # The QR code can be used independently.
        upi_vpa = request.POST.get(
            "UPI_VPA",
            "",
        ).strip()

        SystemSetting.objects.update_or_create(
            key="UPI_VPA",
            defaults={
                "value": upi_vpa,
                "description": (
                    "Optional UPI ID displayed to students "
                    "for manual payment."
                ),
            },
        )

        # -----------------------------
        # UPI QR CODE
        # -----------------------------

        qr_image = request.FILES.get("UPI_QR_IMAGE")

        if qr_image:
            allowed_types = {
                "image/jpeg",
                "image/png",
                "image/webp",
            }

            if qr_image.content_type not in allowed_types:
                messages.error(
                    request,
                    "QR code must be a PNG, JPG, or WebP image.",
                )
                return redirect("admin_portal:settings")

            # Limit QR image size to 5 MB.
            max_size = 5 * 1024 * 1024

            if qr_image.size > max_size:
                messages.error(
                    request,
                    "QR code image must be smaller than 5 MB.",
                )
                return redirect("admin_portal:settings")

            from django.core.files.storage import default_storage

            # Delete the previous QR image if one exists.
            old_qr_path = SystemSetting.get_setting(
                "UPI_QR_IMAGE",
                "",
            )

            if old_qr_path and default_storage.exists(old_qr_path):
                default_storage.delete(old_qr_path)

            file_path = default_storage.save(
                f"payment_qr/{qr_image.name}",
                qr_image,
            )

            SystemSetting.objects.update_or_create(
                key="UPI_QR_IMAGE",
                defaults={
                    "value": file_path,
                    "description": (
                        "QR code image displayed to students "
                        "for manual UPI payment."
                    ),
                },
            )

        # -----------------------------
        # MAINTENANCE BANNER
        # -----------------------------

        maintenance_banner = request.POST.get(
            "MAINTENANCE_BANNER",
            "",
        ).strip()

        SystemSetting.objects.update_or_create(
            key="MAINTENANCE_BANNER",
            defaults={
                "value": maintenance_banner,
                "description": (
                    "Optional message displayed to students when "
                    "the library is under maintenance."
                ),
            },
        )

        messages.success(
            request,
            "System settings updated successfully.",
        )

        return redirect("admin_portal:settings")

    # -----------------------------
    # GET SETTINGS
    # -----------------------------

    settings_data = []

    for setting in setting_definitions:
        current_value = SystemSetting.get_setting(
            setting["key"],
            default=setting["default"],
        )

        settings_data.append(
            {
                **setting,
                "value": current_value,
            }
        )

    qr_image_path = SystemSetting.get_setting(
        "UPI_QR_IMAGE",
        "",
    )

    qr_image_url = ""

    if qr_image_path:
        from django.core.files.storage import default_storage

        if default_storage.exists(qr_image_path):
            qr_image_url = default_storage.url(qr_image_path)

    return render(
        request,
        "admin_portal/settings/settings.html",
        {
            "settings": settings_data,
            "upi_qr_image": qr_image_url,
        },
    )