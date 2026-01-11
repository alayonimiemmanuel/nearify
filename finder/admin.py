# finder/admin.py
from django.contrib import admin
from .models import FeaturedBusiness, BusinessClaim, Business




@admin.register(FeaturedBusiness)
class FeaturedBusinessAdmin(admin.ModelAdmin):
    # nice columns in the list page
    list_display = (
        "name", "category", "city", "state",
        "is_manual", "is_active", "plan",
        "owner", "featured_until", "created_at",
    )
    list_filter = ("is_manual", "is_active", "plan", "state")
    search_fields = ("name", "category", "location", "address", "city", "state", "zip_code", "phone", "url")
    ordering = ("-created_at",)

    # ✅ THIS is what controls what you can edit on the admin form
    fieldsets = (
        ("Core", {
            "fields": ("name", "category", "is_manual", "owner"),
        }),
        ("Address (used for Maps)", {
            "fields": ("address", "city", "state", "zip_code", "location"),
            "description": "Fill address/city/state/zip and Nearify will build Google Maps links automatically.",
        }),
        ("Contact", {
            "fields": ("phone", "url"),
        }),
        ("Images", {
            "fields": ("image", "image_url"),
        }),
        ("Hours / Availability", {
            "fields": ("open_time", "close_time", "is_on_holiday", "holiday_note", "holiday_until"),
        
        }),
        ("Promotion (paid only)", {
            "fields": ("plan", "is_active", "featured_from", "featured_until", "priority"),
        }),

        ("Stripe (auto)", {
            "fields": ("stripe_session_id", "stripe_customer_id", "stripe_subscription_id", "last_paid_amount"),
        }),
        ("Analytics", {
            "fields": ("views_count", "call_clicks", "website_clicks", "directions_clicks"),
        }),
    )
    

    readonly_fields = (
        "stripe_session_id", "stripe_customer_id", "stripe_subscription_id",
        "last_paid_amount",
        "views_count", "call_clicks", "website_clicks", "directions_clicks",
        "created_at",
    )


@admin.register(BusinessClaim)
class BusinessClaimAdmin(admin.ModelAdmin):
    list_display = ("business", "user", "email", "status", "attempts", "expires_at", "verified_at", "created_at")
    list_filter = ("status",)
    search_fields = ("email", "business__name", "user__username", "user__email")
    readonly_fields = ("code_hash", "created_at", "verified_at", "last_sent_at")

@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "city", "state", "is_claimed", "plan", "is_active")
    list_filter = ("state", "plan", "is_claimed", "is_active")
    search_fields = ("name", "category", "address", "city", "state", "zip_code", "phone", "osm_id")



