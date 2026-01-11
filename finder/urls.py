# finder/urls.py
from django.urls import path
from . import views

urlpatterns = [
    # --------------------
    # Main app
    # --------------------
    path("", views.search_business, name="search_business"),
    path("claim/osm/start/", views.claim_osm_start, name="claim_osm_start"),


    path("add/", views.add_business, name="add_business"),

    # --------------------
    # Business pages
    # --------------------
    path("business/<int:business_id>/", views.business_detail, name="business_detail"),
    path("claim/<int:business_id>/start/", views.claim_request, name="claim_request"),
    path("claim/verify/<uuid:claim_id>/", views.claim_verify, name="claim_verify"),
    path("business/<int:business_id>/toggle-holiday/", views.toggle_holiday, name="toggle_holiday"),

    # --------------------
    # Dashboard / owner tools
    # --------------------
    path("dashboard/", views.dashboard, name="dashboard"),
    path("business/<int:business_id>/edit/", views.edit_business, name="edit_business"),

    # --------------------
    # Public pages (legal + trust)
    # --------------------
    path("about/", views.about, name="about"),
    path("privacy/", views.privacy, name="privacy"),
    path("terms/", views.terms, name="terms"),
    path("refunds/", views.refunds, name="refunds"),
    path("contact/", views.contact, name="contact"),

    # --------------------
    # Analytics
    # --------------------
    path("business/<int:business_id>/track/view/", views.track_view, name="track_view"),
    path("business/<int:business_id>/track/call/", views.track_call, name="track_call"),
    path("business/<int:business_id>/track/web/", views.track_web, name="track_web"),
    path("business/<int:business_id>/track/dir/", views.track_dir, name="track_dir"),
    path("osm/import/", views.import_osm_business, name="import_osm_business"),
    

    # --------------------
    # Stripe
    # --------------------
    path(
        "stripe/create-checkout-session/<int:business_id>/<str:plan>/",
        views.create_checkout_session,
        name="create_checkout_session",
    ),
    path("stripe/webhook/", views.stripe_webhook, name="stripe_webhook"),
]
