from django.shortcuts import render, redirect
from .forms_auth import NearifySignupForm

from django.contrib.auth import login

def signup(request):
    if request.method == "POST":
        form = NearifySignupForm(request.POST)

        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("/finder/")
    else:
        form = NearifySignupForm()


    return render(request, "registration/signup.html", {"form": form})
