from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm

class NearifySignupForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user

from django.contrib.auth.forms import AuthenticationForm




class EmailOrUsernameAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label="Email or Username",
        widget=forms.TextInput(attrs={"autofocus": True}),
    )
