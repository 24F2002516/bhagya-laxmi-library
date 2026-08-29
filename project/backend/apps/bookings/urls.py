from django.urls import path

from apps.bookings import views


app_name = "portal"


urlpatterns = [
    # Dashboard
    path(
        "",
        views.dashboard_view,
        name="dashboard",
    ),

    # Seat booking
    path(
        "book/",
        views.book_seat_view,
        name="book_seat",
    ),

    # Payment
    path(
        "payment/submit/<int:payment_id>/",
        views.submit_payment_view,
        name="submit_payment",
    ),

    # Receipt
    path(
        "receipt/<int:receipt_id>/download/",
        views.download_receipt_view,
        name="download_receipt",
    ),

    # Student profile
    path(
        "profile/",
        views.profile_view,
        name="profile",
    ),

    # Complaints
    path(
        "complaints/",
        views.complaints_view,
        name="complaints",
    ),

    # Feedback
    path(
        "feedback/",
        views.feedback_view,
        name="feedback",
    ),

    # History
    path(
        "history/",
        views.history_view,
        name="history",
    ),
]