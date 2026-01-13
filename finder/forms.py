# finder/forms.py
from django import forms
from .models import FeaturedBusiness
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User


class ManualBusinessForm(forms.ModelForm):
    class Meta:
        model = FeaturedBusiness
        fields = [
            "name",
            "category",

            # ✅ New location fields
            "address",
            "city",
            "state",
            "zip_code",

            "phone",
            "url",

            # image (either upload or URL)
            "image",
            "image_url",

            "open_time",
            "close_time",
        ]

        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Business name"}),
            "category": forms.TextInput(attrs={"placeholder": "Category (e.g. Fitness, Salon)"}),

            # ✅ Better location inputs
            "address": forms.TextInput(attrs={"placeholder": "Street address (e.g. 123 Main St)"}),
            "city": forms.TextInput(attrs={"placeholder": "City (e.g. Brownsburg)"}),
            "state": forms.TextInput(attrs={"placeholder": "State (e.g. IN)"}),
            "zip_code": forms.TextInput(attrs={"placeholder": "Zip code (optional)"}),

            "phone": forms.TextInput(attrs={"placeholder": "Phone (optional)"}),
            "url": forms.URLInput(attrs={"placeholder": "Website link (optional)"}),

            "image_url": forms.URLInput(attrs={"placeholder": "Image URL (optional)"}),

            "open_time": forms.TimeInput(attrs={"type": "time"}),
            "close_time": forms.TimeInput(attrs={"type": "time"}),
        }


class EditBusinessForm(forms.ModelForm):
    # ✅ Fix datetime-local parsing (browser submits: "YYYY-MM-DDTHH:MM")
    holiday_until = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
        input_formats=["%Y-%m-%dT%H:%M"],
    )

    class Meta:
        model = FeaturedBusiness
        fields = [
            "name",
            "category",

            # ✅ New location fields
            "address",
            "city",
            "state",
            "zip_code",

            "phone",
            "url",

            # image (either upload or URL)
            "image",
            "image_url",

            "open_time",
            "close_time",

            # holiday controls
            "is_on_holiday",
            "holiday_note",
            "holiday_until",
        ]

        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Business name"}),
            "category": forms.TextInput(attrs={"placeholder": "Category (e.g. Fitness, Salon)"}),

            "address": forms.TextInput(attrs={"placeholder": "Street address (e.g. 123 Main St)"}),
            "city": forms.TextInput(attrs={"placeholder": "City (e.g. Brownsburg)"}),
            "state": forms.TextInput(attrs={"placeholder": "State (e.g. IN)"}),
            "zip_code": forms.TextInput(attrs={"placeholder": "Zip code (optional)"}),

            "phone": forms.TextInput(attrs={"placeholder": "Phone (optional)"}),
            "url": forms.URLInput(attrs={"placeholder": "Website link (optional)"}),

            "image_url": forms.URLInput(attrs={"placeholder": "Image URL (optional)"}),

            "open_time": forms.TimeInput(attrs={"type": "time"}),
            "close_time": forms.TimeInput(attrs={"type": "time"}),

            "holiday_note": forms.TextInput(attrs={"placeholder": "Holiday note (optional)"}),
        }








class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")