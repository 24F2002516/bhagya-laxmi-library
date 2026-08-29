from django.urls import path
from apps.accounts import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.register_view, name="register"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("forgot-password/", views.forgot_password_view, name="forgot_password"),
    path("verify-reset-otp/", views.verify_reset_otp_view, name="verify_reset_otp"),
    path("set-new-password/", views.set_new_password_view, name="set_new_password"),
    path("change-password/", views.change_password_view, name="change_password"),
    path("send-change-password-otp/", views.send_change_password_otp_view, name="send_change_password_otp"),
    path("authenticated-reset-password/", views.authenticated_reset_password_view, name="auth_reset_password"),
    path("google/login/", views.google_login_view, name="google_login"),
    path("google/callback/", views.google_callback_view, name="google_callback"),
]
