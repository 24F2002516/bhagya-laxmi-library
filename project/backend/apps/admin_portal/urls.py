from django.urls import path

from . import views


app_name = "admin_portal"


urlpatterns = [
    # Authentication
    path(
        "login/",
        views.admin_login_view,
        name="login",
    ),
    path(
        "logout/",
        views.admin_logout_view,
        name="logout",
    ),
    path(
        "change-password/",
        views.admin_change_password_view,
        name="change_password",
    ),
    path(
        "send-change-password-otp/",
        views.admin_send_change_password_otp_view,
        name="send_change_password_otp",
    ),
    path(
        "reset-password/",
        views.admin_reset_password_view,
        name="reset_password",
    ),

    # Dashboard
    path(
        "",
        views.admin_dashboard_view,
        name="dashboard",
    ),

    # Payments
    path(
        "payments/",
        views.admin_payment_list_view,
        name="payments",
    ),
    path(
        "payments/<int:payment_id>/",
        views.admin_payment_detail_view,
        name="payment_detail",
    ),
    path(
        "payments/<int:payment_id>/screenshot/",
        views.admin_payment_screenshot_view,
        name="payment_screenshot",
    ),
    path(
        "payments/<int:payment_id>/approve/",
        views.admin_payment_action_view,
        {"action": "approve"},
        name="payment_approve",
    ),
    path(
        "payments/<int:payment_id>/reject/",
        views.admin_payment_action_view,
        {"action": "reject"},
        name="payment_reject",
    ),

    # Seats
    path(
        "seats/",
        views.admin_seats_view,
        name="seats",
    ),
    path(
        "seats/<int:seat_id>/",
        views.admin_seat_detail_view,
        name="seat_detail",
    ),
    path(
        "seats/<int:seat_id>/maintenance/",
        views.admin_seat_maintenance_view,
        {"action": "start"},
        name="seat_maintenance",
    ),
    path(
        "seats/<int:seat_id>/maintenance/resolve/",
        views.admin_seat_maintenance_view,
        {"action": "resolve"},
        name="seat_maintenance_resolve",
    ),

    # Students
    path(
        "students/",
        views.admin_student_list_view,
        name="students",
    ),
    path(
        "students/<int:student_id>/",
        views.admin_student_detail_view,
        name="student_detail",
    ),
    path(
        "students/<int:student_id>/toggle-status/",
        views.admin_student_toggle_status_view,
        name="student_toggle_status",
    ),

    # Bookings
    path(
        "bookings/",
        views.admin_booking_list_view,
        name="bookings",
    ),
    path(
        "bookings/<int:booking_id>/",
        views.admin_booking_detail_view,
        name="booking_detail",
    ),
    path(
        "bookings/<int:booking_id>/vacate/",
        views.admin_booking_vacate_view,
        name="booking_vacate",
    ),

    # Complaints
    path(
        "complaints/",
        views.admin_complaint_list_view,
        name="complaints",
    ),
    path(
        "complaints/<int:complaint_id>/",
        views.admin_complaint_detail_view,
        name="complaint_detail",
    ),
    path(
        "complaints/<int:complaint_id>/update/",
        views.admin_complaint_update_view,
        name="complaint_update",
    ),

    # Feedback
    path(
        "feedback/",
        views.admin_feedback_list_view,
        name="feedback",
    ),
    path(
        "feedback/<int:feedback_id>/",
        views.admin_feedback_detail_view,
        name="feedback_detail",
    ),
    path(
        "feedback/<int:feedback_id>/update/",
        views.admin_feedback_update_view,
        name="feedback_update",
    ),

    # Reports
    path(
        "reports/",
        views.admin_reports_view,
        name="reports",
    ),

    # Audit Logs
    path(
        "audit-logs/",
        views.admin_audit_log_list_view,
        name="audit_logs",
    ),

    # Settings
    path(
        "settings/",
        views.admin_settings_view,
        name="settings",
    ),
]