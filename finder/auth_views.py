# finder/auth_views.py
from django.conf import settings
from django.contrib.auth import login
from django.shortcuts import redirect, render

from .forms import SignUpForm  # keep your existing import if different


def signup(request):
    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()

            # ✅ FIX: tell Django which backend to use (because you have multiple)
            backend = settings.AUTHENTICATION_BACKENDS[0]
            login(request, user, backend=backend)

            return redirect("login")  # or redirect("finder_home") / whatever you use
    else:
        form = SignUpForm()

    return render(request, "registration/signup.html", {"form": form})
