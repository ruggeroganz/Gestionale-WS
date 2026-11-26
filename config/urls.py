from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from ws.views import allegato

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accedi/", auth_views.LoginView.as_view(template_name="ws/login.html"), name="login"),
    path("esci/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "password/",
        auth_views.PasswordChangeView.as_view(template_name="ws/password.html", success_url="/password/fatto/"),
        name="password",
    ),
    path(
        "password/fatto/",
        auth_views.PasswordChangeDoneView.as_view(template_name="ws/password.html"),
        name="password_fatto",
    ),
    # allegati (artwork): serviti solo a utenti autenticati
    path("media/<path:percorso>", allegato, name="allegato"),
    path("", include("ws.urls")),
]
