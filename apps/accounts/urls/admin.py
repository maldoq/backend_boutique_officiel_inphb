from django.urls import path

from apps.accounts.views.admin import ChangePasswordView, LoginView, LogoutView, MeView, RefreshView

urlpatterns = [
    path("auth/login/", LoginView.as_view(), name="admin-auth-login"),
    path("auth/refresh/", RefreshView.as_view(), name="admin-auth-refresh"),
    path("auth/logout/", LogoutView.as_view(), name="admin-auth-logout"),
    path("auth/me/", MeView.as_view(), name="admin-auth-me"),
    path("auth/change-password/", ChangePasswordView.as_view(), name="admin-auth-change-password"),
]
