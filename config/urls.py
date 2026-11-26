from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accedi/", auth_views.LoginView.as_view(template_name="ws/login.html"), name="login"),
    path("esci/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("ws.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
