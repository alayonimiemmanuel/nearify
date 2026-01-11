"""
URL configuration for businessfinder project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from finder.auth_views import signup  # (or wherever your signup view is)
from django.contrib.auth import views as auth_views
from finder.forms_auth import EmailOrUsernameAuthenticationForm
from finder import views as finder_views



urlpatterns = [
    path("", RedirectView.as_view(url="/finder/", permanent=False)),  # ✅ ADD THIS

    path("admin/", admin.site.urls),

    path("", finder_views.landing, name="landing"),


    path("accounts/signup/", signup, name="signup"),
    path(
    "accounts/login/",
    auth_views.LoginView.as_view(authentication_form=EmailOrUsernameAuthenticationForm),
    name="login",
),

    path("accounts/", include("django.contrib.auth.urls")),

    path("finder/", include("finder.urls")),
]




from django.conf import settings
from django.conf.urls.static import static

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
