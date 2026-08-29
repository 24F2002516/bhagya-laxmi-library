from datetime import timedelta

from django.core.mail import EmailMessage
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.bookings.models import Booking
from apps.notifications.models import Notification
from apps.payments.exceptions import InvalidPaymentStateException
from apps.payments.models import Payment, Receipt, ReceiptSequence
from apps.payments.receipt_pdf import generate_receipt_pdf
from apps.seats.models import Seat


def generate_sequential_receipt_number() -> str:
    """
    Generates a concurrency-safe sequential receipt number
    in format BLL-YYYYMM-XXXX.
    """

    year_month = timezone.now().strftime("%Y%m")

    sequence_obj, _ = ReceiptSequence.objects.select_for_update().get_or_create(
        year_month=year_month,
        defaults={"last_sequence_number": 0},
    )

    sequence_obj.last_sequence_number += 1

    sequence_obj.save(
        update_fields=[
            "last_sequence_number",
            "updated_at",
        ]
    )

    return (
        f"BLL-{year_month}-"
        f"{sequence_obj.last_sequence_number:04d}"
    )


def send_receipt_email(receipt) -> None:
    """
    Generates the receipt PDF in memory and emails it to the student.

    The PDF is never stored on disk.
    """

    student = receipt.payment.booking.student

    pdf_bytes = generate_receipt_pdf(receipt)

    email = EmailMessage(
        subject=(
            f"Bhagya Laxmi Library - "
            f"Payment Receipt {receipt.receipt_number}"
        ),
        body=(
            f"Dear {receipt.student_name},\n\n"
            f"Your payment of ₹{receipt.amount_paid:.2f} "
            f"has been verified successfully.\n\n"
            f"Receipt Number: {receipt.receipt_number}\n"
            f"Seat Number: #{receipt.seat_number}\n"
            f"Membership Valid Until: "
            f"{receipt.membership_expires_at:%d %b %Y, %I:%M %p}\n\n"
            "Your official payment receipt is attached to this email.\n\n"
            "Regards,\n"
            "Bhagya Laxmi Library"
        ),
        from_email=None,
        to=[student.email],
    )

    email.attach(
        filename=f"{receipt.receipt_number}.pdf",
        content=pdf_bytes,
        mimetype="application/pdf",
    )

    try:
        email.send(fail_silently=False)
    except Exception as exc:
        # Email failure must never undo an already successful
        # payment verification and membership activation.
        print(
            f"Failed to send receipt email for "
            f"{receipt.receipt_number}: {exc}"
        )


@transaction.atomic
def submit_payment_proof(
    payment_id: int,
    student,
    utr_number: str,
    screenshot=None,
) -> Payment:
    """
    Student submits manual UPI payment proof.

    The payment must be submitted before the 30-minute
    seat hold expires.
    """

    payment = Payment.objects.select_for_update().get(
        id=payment_id
    )

    booking = Booking.objects.select_for_update().get(
        id=payment.booking_id
    )

    if booking.student_id != student.id:
        raise InvalidPaymentStateException(
            "You are not authorized to submit payment "
            "for this booking."
        )

    if payment.status != Payment.Status.PENDING_VERIFICATION:
        raise InvalidPaymentStateException(
            f"Payment #{payment.id} is in status "
            f"'{payment.status}', expected "
            "PENDING_VERIFICATION."
        )

    if booking.status != Booking.Status.PENDING_PAYMENT:
        raise InvalidPaymentStateException(
            f"Booking {booking.booking_reference} is in "
            f"status '{booking.status}', expected "
            "PENDING_PAYMENT."
        )

    now = timezone.now()

    if now >= booking.hold_expires_at:
        raise InvalidPaymentStateException(
            "The 30-minute seat hold has expired. "
            "Please initiate a new booking."
        )

    clean_utr = (
        utr_number.strip().upper()
        if utr_number
        else ""
    )

    if not clean_utr:
        raise InvalidPaymentStateException(
            "A valid UPI UTR (transaction reference) "
            "is required."
        )

    payment.utr_number = clean_utr

    if screenshot:
        payment.payment_screenshot = screenshot

    payment.submitted_at = now

    payment.save(
        update_fields=[
            "utr_number",
            "payment_screenshot",
            "submitted_at",
            "updated_at",
        ]
    )

    AuditLog.log(
        action="PAYMENT_PROOF_SUBMITTED",
        target_model="Payment",
        target_id=str(payment.id),
        actor=student,
        details={
            "utr_number": clean_utr,
            "has_screenshot": bool(screenshot),
            "submitted_at": now.isoformat(),
        },
    )

    return payment


@transaction.atomic
def verify_payment_and_activate_membership(
    payment_id: int,
    admin_user,
) -> Receipt:
    """
    Atomically verifies a manual UPI payment and activates
    the student's 30-day membership.

    Creates the official Receipt database record.

    After the database transaction successfully commits,
    a PDF receipt is generated in memory and emailed to
    the student. The PDF itself is never stored.
    """

    # ---------------------------------------------------------
    # 1. Lock Payment
    # ---------------------------------------------------------

    payment = Payment.objects.select_for_update().get(
        id=payment_id
    )

    # ---------------------------------------------------------
    # 2. Lock Booking
    # ---------------------------------------------------------

    booking = Booking.objects.select_for_update().get(
        id=payment.booking_id
    )

    # ---------------------------------------------------------
    # 3. Lock Seat
    # ---------------------------------------------------------

    seat = Seat.objects.select_for_update().get(
        id=booking.seat_id
    )

    # ---------------------------------------------------------
    # 4. Re-check state
    # ---------------------------------------------------------

    if payment.status != Payment.Status.PENDING_VERIFICATION:
        raise InvalidPaymentStateException(
            f"Payment #{payment.id} is in status "
            f"'{payment.status}', expected "
            "PENDING_VERIFICATION."
        )

    if booking.status != Booking.Status.PENDING_PAYMENT:
        raise InvalidPaymentStateException(
            f"Booking {booking.booking_reference} is in "
            f"status '{booking.status}', expected "
            "PENDING_PAYMENT."
        )

    now = timezone.now()

    # ---------------------------------------------------------
    # 5. Verify payment
    # ---------------------------------------------------------

    payment.status = Payment.Status.VERIFIED
    payment.verified_by = admin_user
    payment.verified_at = now

    payment.save(
        update_fields=[
            "status",
            "verified_by",
            "verified_at",
            "updated_at",
        ]
    )

    # ---------------------------------------------------------
    # 6. Activate membership
    # ---------------------------------------------------------

    membership_start = now

    membership_expires_at = (
        membership_start + timedelta(days=30)
    )

    grace_until = (
        membership_expires_at
        + timedelta(hours=48)
    )

    booking.membership_start = membership_start
    booking.membership_expires_at = membership_expires_at
    booking.grace_until = grace_until
    booking.status = Booking.Status.CONFIRMED

    booking.save(
        update_fields=[
            "membership_start",
            "membership_expires_at",
            "grace_until",
            "status",
            "updated_at",
        ]
    )

    # ---------------------------------------------------------
    # 7. Seat becomes BOOKED
    # ---------------------------------------------------------

    seat.status = Seat.Status.BOOKED

    seat.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    # ---------------------------------------------------------
    # 8. Create official Receipt DB record
    # ---------------------------------------------------------

    student_profile = getattr(
        booking.student,
        "student_profile",
        None,
    )

    student_name = (
        student_profile.full_name
        if student_profile
        else booking.student.email
    )

    receipt = Receipt.objects.create(
        receipt_number=generate_sequential_receipt_number(),
        payment=payment,
        student_name=student_name,
        student_phone=booking.student.phone_number,
        seat_number=seat.number,
        membership_start=membership_start,
        membership_expires_at=membership_expires_at,
        amount_paid=payment.amount,
        payment_mode=payment.payment_mode,
        utr_reference=payment.utr_number or "",
        issued_by=admin_user,
    )

    # ---------------------------------------------------------
    # 9. Existing notification
    # ---------------------------------------------------------

    Notification.objects.create(
        recipient=booking.student,
        notification_type=Notification.Type.PAYMENT_VERIFIED,
        channel=Notification.Channel.EMAIL,
        title="Payment Verified - Membership Activated!",
        message=(
            f"Your payment of ₹{payment.amount} "
            f"for Seat #{seat.number} has been verified. "
            f"Receipt #{receipt.receipt_number} issued. "
            f"Valid until "
            f"{membership_expires_at:%d %b %Y %H:%M}."
        ),
    )

    # ---------------------------------------------------------
    # 10. Audit
    # ---------------------------------------------------------

    AuditLog.log(
        action="PAYMENT_VERIFIED",
        target_model="Payment",
        target_id=str(payment.id),
        actor=admin_user,
        details={
            "receipt_number": receipt.receipt_number,
            "seat_number": seat.number,
            "student_id": booking.student_id,
            "amount": str(payment.amount),
        },
    )

    # ---------------------------------------------------------
    # 11. Send PDF AFTER successful DB commit
    # ---------------------------------------------------------

    transaction.on_commit(
        lambda: send_receipt_email(receipt)
    )

    return receipt


@transaction.atomic
def reject_payment_attempt(
    payment_id: int,
    admin_user,
    reason: str,
) -> Payment:
    """
    Atomically rejects a payment attempt.

    If there are no other pending attempts, the booking
    is cancelled and the physical seat is released.
    """

    payment = Payment.objects.select_for_update().get(
        id=payment_id
    )

    booking = Booking.objects.select_for_update().get(
        id=payment.booking_id
    )

    seat = Seat.objects.select_for_update().get(
        id=booking.seat_id
    )

    if payment.status != Payment.Status.PENDING_VERIFICATION:
        raise InvalidPaymentStateException(
            f"Payment #{payment.id} is in status "
            f"'{payment.status}', expected "
            "PENDING_VERIFICATION."
        )

    now = timezone.now()

    payment.status = Payment.Status.REJECTED
    payment.rejection_reason = reason
    payment.verified_by = admin_user
    payment.verified_at = now

    payment.save(
        update_fields=[
            "status",
            "rejection_reason",
            "verified_by",
            "verified_at",
            "updated_at",
        ]
    )

    has_other_pending = (
        Payment.objects
        .filter(
            booking=booking,
            status=Payment.Status.PENDING_VERIFICATION,
        )
        .exclude(id=payment.id)
        .exists()
    )

    if not has_other_pending:
        booking.status = Booking.Status.CANCELLED
        booking.is_active = False

        booking.save(
            update_fields=[
                "status",
                "is_active",
                "updated_at",
            ]
        )

        seat.status = Seat.Status.AVAILABLE

        seat.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )

        AuditLog.log(
            action="BOOKING_CANCELLED",
            target_model="Booking",
            target_id=str(booking.id),
            actor=admin_user,
            details={
                "reason": reason,
                "seat_number": seat.number,
            },
        )

    Notification.objects.create(
        recipient=booking.student,
        notification_type=Notification.Type.PAYMENT_REJECTED,
        channel=Notification.Channel.EMAIL,
        title="Payment Attempt Rejected",
        message=(
            f"Your payment attempt for Seat #{seat.number} "
            f"was rejected. Reason: {reason}"
        ),
    )

    AuditLog.log(
        action="PAYMENT_REJECTED",
        target_model="Payment",
        target_id=str(payment.id),
        actor=admin_user,
        details={
            "reason": reason,
            "attempt_number": payment.attempt_number,
        },
    )

    return payment