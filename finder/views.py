# finder/views.py
import os
import hashlib
from datetime import datetime, timedelta
from urllib.parse import quote_plus, urlparse
import requests
import stripe
from dotenv import load_dotenv

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_http_methods
from django.core.mail import send_mail
from django.views.decorators.http import require_GET


from .forms import ManualBusinessForm, EditBusinessForm
from .models import FeaturedBusiness, BusinessClaim
from .services.osm import geocode_location, overpass_search

 # for OSM claim flow

load_dotenv()

# -------------------------
# Stripe
# -------------------------
stripe.api_key = settings.STRIPE_SECRET_KEY

PRICE_MAP = {
    FeaturedBusiness.PLAN_FEATURED: os.getenv("STRIPE_PRICE_FEATURED"),
    FeaturedBusiness.PLAN_PREMIUM: os.getenv("STRIPE_PRICE_PREMIUM"),
    FeaturedBusiness.PLAN_TOP: os.getenv("STRIPE_PRICE_TOP"),
}

# -------------------------
# Small helpers
# -------------------------
def env_str(v) -> str:
    return (v or "").strip()

def _stars_for_rating(rating: float):
    rating = float(rating or 0)
    full = int(rating)
    half = 1 if (rating - full) >= 0.5 else 0
    empty = 5 - full - half
    return {"full": range(full), "half": bool(half), "empty": range(empty)}

def _build_display_location(*parts):
    cleaned = [str(p).strip() for p in parts if p and str(p).strip()]
    return ", ".join(cleaned) if cleaned else "Unknown location"

def _google_maps_url(address: str, city: str = "", state: str = "", zip_code: str = "") -> str:
    full = _build_display_location(address, city, state, zip_code)
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(full)}"

def _db_address_parts(db_biz: FeaturedBusiness):
    address = getattr(db_biz, "address", "") or ""
    city = getattr(db_biz, "city", "") or ""
    state = getattr(db_biz, "state", "") or ""
    zip_code = getattr(db_biz, "zip_code", "") or ""

    # fallback if only `location` is populated
    if (not city and not state) and getattr(db_biz, "location", ""):
        loc = db_biz.location or ""
        if "," in loc:
            a, b = loc.split(",", 1)
            city = city or a.strip()
            state = state or b.strip()
        else:
            city = city or loc.strip()

    return address, city, state, zip_code

def _is_open_now(open_time, close_time, now_time):
    if not open_time or not close_time:
        return False
    if open_time <= close_time:
        return open_time <= now_time <= close_time
    return now_time >= open_time or now_time <= close_time

def _business_available_now(biz: FeaturedBusiness, now_dt=None) -> bool:
    now_dt = now_dt or timezone.localtime()
    now_time = now_dt.time()

    # auto-clear expired holiday
    if biz.is_on_holiday and biz.holiday_until and biz.holiday_until <= timezone.now():
        biz.is_on_holiday = False
        biz.holiday_until = None
        biz.holiday_note = None
        biz.save(update_fields=["is_on_holiday", "holiday_until", "holiday_note"])

    if biz.is_on_holiday:
        return False
    
    return _is_open_now(biz.open_time, biz.close_time, now_time)

def _expire_promotions():
    qs = FeaturedBusiness.objects.filter(is_active=True).only("id", "featured_until", "is_active", "priority")
    for biz in qs:
        biz.deactivate_if_expired()

def _manual_to_payload(m: FeaturedBusiness):
    addr, city, state, zip_code = _db_address_parts(m)
    display_location = _build_display_location(addr, city, state, zip_code) or (m.location or "")
    maps_url = _google_maps_url(addr, city, state, zip_code)

    return {
        "db_id": m.id,
        "id": m.yelp_id or f"manual_{m.id}",
        "name": m.name,
        "address": addr,
        "city": city,
        "state": state,
        "zip_code": zip_code,
        "display_location": display_location,
        "maps_url": maps_url,
        "display_phone": m.phone or "",
        "url": m.url or "",
        "image_url": getattr(m, "image_url", "") or "",
        "rating": m.rating or 0,
        "review_count": m.review_count or 0,
        "featured": bool(m.is_active),
        "plan": m.plan,
        "featured_until": m.featured_until,
        "owner_id": m.owner_id,
        "open_time": m.open_time,
        "close_time": m.close_time,
        "is_on_holiday": m.is_on_holiday,
        "holiday_note": m.holiday_note,
        "holiday_until": m.holiday_until,
        "stars": _stars_for_rating(m.rating or 0),
        "source": "manual",
    }

def _osm_to_payload(item: dict):
    name = item.get("name") or "Unknown business"
    address = item.get("address") or ""
    city = item.get("city") or ""
    state = item.get("state") or ""
    zip_code = item.get("zip_code") or ""

    display_location = _build_display_location(address, city, state, zip_code)
    maps_url = _google_maps_url(address, city, state, zip_code)

    url = item.get("url") or ""
    phone = item.get("phone") or item.get("display_phone") or ""

    osm_id = item.get("osm_id") or item.get("id") or ""
    external_key = f"osm:{osm_id}" if osm_id else ""

    # ✅ if this OSM place is already imported into DB, attach it
    db = None
    if external_key:
        db = FeaturedBusiness.objects.filter(yelp_id=external_key).first()

    payload = {
        "db_id": db.id if db else None,
        "id": osm_id or hashlib.md5(f"{name}{display_location}".encode()).hexdigest(),
        "osm_id": osm_id,
        "external_key": external_key,

        "name": name,
        "address": address,
        "city": city,
        "state": state,
        "zip_code": zip_code,
        "display_location": display_location,
        "maps_url": maps_url,

        "display_phone": phone,
        "url": url,

        "image_url": item.get("image_url") or "",
        "rating": 0,
        "review_count": 0,

        # default “not promoted”
        "featured": bool(db.is_active) if db else False,
        "plan": db.plan if db else FeaturedBusiness.PLAN_FEATURED,
        "featured_until": db.featured_until if db else None,
        "owner_id": db.owner_id if db else None,
        "is_active": bool(db.is_active) if db else False,

        "stars": _stars_for_rating(0),
        "source": "osm",
    }
    return payload

# -------------------------
# Public pages
# -------------------------
def landing(request): return render(request, "finder/landing.html")
def about(request): return render(request, "finder/about.html")
def privacy(request): return render(request, "finder/privacy.html")
def terms(request): return render(request, "finder/terms.html")
def refunds(request): return render(request, "finder/refunds.html")
def contact(request): return render(request, "finder/contact.html")

# -------------------------
# Search
# -------------------------

from django.db.models import Q
from django.utils import timezone
import requests

@require_http_methods(["GET", "POST"])
def search_business(request):
    error = None
    businesses = []
    featured = []

    _expire_promotions()

    # -------------------------
    # Read inputs (POST or GET)
    # -------------------------
    if request.method == "POST":
        term = env_str(request.POST.get("term"))
        location = env_str(request.POST.get("location"))
        request.session["last_term"] = term
        request.session["last_location"] = location
    else:
        term = env_str(request.GET.get("term"))
        location = env_str(request.GET.get("location"))

    # -------------------------
    # Run search
    # -------------------------
    if term and location:
        # 1) Manual businesses first (your DB)
        manual_qs = (
            FeaturedBusiness.objects.filter(is_manual=True)
            .filter(Q(category__icontains=term) | Q(name__icontains=term))
            .filter(
                Q(location__icontains=location)
                | Q(address__icontains=location)
                | Q(city__icontains=location)
                | Q(state__icontains=location)
            )
        )

        manual_payloads = []
        for m in manual_qs:
            p = _manual_to_payload(m)

            # fields your template uses (upgrade/claim UI)
            p["db_id"] = m.id
            p["owner_id"] = m.owner_id
            p["is_active"] = bool(m.is_active)
            p["featured"] = bool(m.is_active)
            p["plan"] = m.plan
            p["is_on_holiday"] = bool(m.is_on_holiday)

            manual_payloads.append(p)

        # 2) OSM (Overpass)
        osm_payloads = []

        # ✅ your geocoder now returns 4 values ALWAYS
        lat, lon, geo_display, geo_err = geocode_location(location)

        if geo_err:
            error = f"Location error: {geo_err}"
        elif lat is None or lon is None:
            error = "Could not understand that location. Try: 'NYC, NY' or 'Los Angeles, CA'."
        else:
            try:
                # Try #1 (fast)
                osm_results = overpass_search(term, lat, lon, radius_m=8000, limit=40)

                # ✅ OPTIONAL: Try #2 (bigger radius) if nothing found
                if not osm_results:
                    osm_results = overpass_search(term, lat, lon, radius_m=20000, limit=60)

                osm_payloads = []
                for x in (osm_results or []):
                    p = _osm_to_payload(x)
                    p["osm_id"] = x.get("osm_id") or x.get("id")  # ensure present
                    p["category"] = term  # helps save category when importing into DB
                    osm_payloads.append(p)


            except requests.exceptions.ReadTimeout:
                error = "OSM is busy (timeout). Try again in a few seconds."
            except Exception as e:
                error = f"OSM search error: {e}"

        # Combine results (manual first)
        businesses = manual_payloads + osm_payloads

        if not businesses and not error:
            error = "No results. Try: 'gas station', 'pizza', 'salon' and a clearer location like 'NYC, NY'."

        # 3) Featured list (your DB promos)
        featured_qs = (
            FeaturedBusiness.objects.filter(is_active=True)
            .filter(Q(name__icontains=term) | Q(category__icontains=term))
            .filter(Q(location__icontains=location) | Q(city__icontains=location) | Q(state__icontains=location))
            .order_by("-priority", "-featured_until")
        )

        now = timezone.now()
        featured_list = []
        for biz in featured_qs[:50]:
            # only show if promo window is valid AND business is open (your function)
            if biz.is_promoted_now() and _business_available_now(biz):
                featured_list.append(biz)
        featured = featured_list[:5]

    elif request.method == "POST":
        error = "Please provide both business type and location."

    return render(
        request,
        "finder/search.html",
        {
            "businesses": businesses,
            "error": error,
            "featured": featured,
            "STRIPE_PUBLISHABLE_KEY": settings.STRIPE_PUBLISHABLE_KEY,
        },
    )










@require_GET
@login_required
def import_osm_business(request):
    """
    Import an OSM result into your DB so it can be claimed/upgraded later.
    We DO NOT set owner automatically (prevents stealing).
    We store OSM id in yelp_id as: "osm:<osm_id>" to avoid new migrations.
    """
    osm_id = env_str(request.GET.get("osm_id"))
    if not osm_id:
        messages.error(request, "Missing OSM id.")
        return redirect("search_business")

    external_key = f"osm:{osm_id}"

    name = env_str(request.GET.get("name"))
    address = env_str(request.GET.get("address"))
    city = env_str(request.GET.get("city"))
    state = env_str(request.GET.get("state"))
    zip_code = env_str(request.GET.get("zip_code"))
    phone = env_str(request.GET.get("phone"))
    url = env_str(request.GET.get("url"))
    category = env_str(request.GET.get("category"))  # optional (we can set it to search term)

    # if already exists, just go to details
    existing = FeaturedBusiness.objects.filter(yelp_id=external_key).first()
    if existing:
        return redirect("business_detail", business_id=existing.id)

    # Create as “manual/imported” so it behaves like your DB businesses
    biz = FeaturedBusiness.objects.create(
        name=name or "Imported business",
        category=category,
        location=_build_display_location(city, state) if (city or state) else "",
        address=address,
        city=city,
        state=state,
        zip_code=zip_code,
        phone=phone or None,
        url=url or None,

        is_manual=True,           # treat as DB business
        yelp_id=external_key,     # reuse field as external id
        is_active=False,
        plan=FeaturedBusiness.PLAN_FEATURED,
        priority=0,
    )

    messages.success(request, "Business imported. You can now claim it (add website if missing) and promote it.")
    return redirect("business_detail", business_id=biz.id)

        # 3) featured list (from your DB)

# -------------------------
# Business CRUD
# -------------------------
@login_required
def add_business(request):
    if request.method == "POST":
        form = ManualBusinessForm(request.POST, request.FILES)
        if form.is_valid():
            biz = form.save(commit=False)
            biz.owner = request.user
            biz.is_active = False
            biz.priority = 0
            biz.plan = FeaturedBusiness.PLAN_FEATURED
            biz.is_manual = True
            biz.yelp_id = None
            biz.save()
            return redirect("search_business")
    else:
        form = ManualBusinessForm()
    return render(request, "finder/add_business.html", {"form": form})

def business_detail(request, business_id):
    biz = get_object_or_404(FeaturedBusiness, id=business_id)

    if hasattr(biz, "views_count"):
        FeaturedBusiness.objects.filter(id=biz.id).update(views_count=F("views_count") + 1)
        biz.refresh_from_db()

    addr, city, state, zip_code = _db_address_parts(biz)
    maps_url = _google_maps_url(addr, city, state, zip_code)

    return render(request, "finder/business_detail.html", {
        "biz": biz,
        "stars": _stars_for_rating(biz.rating or 0),
        "maps_url": maps_url,
    })

@login_required
def dashboard(request):
    my_businesses = FeaturedBusiness.objects.filter(owner=request.user).order_by("-created_at")
    now = timezone.now()
    return render(request, "finder/dashboard.html", {"my_businesses": my_businesses, "now": now})

@login_required
def edit_business(request, business_id):
    biz = get_object_or_404(FeaturedBusiness, id=business_id, owner=request.user)
    if request.method == "POST":
        form = EditBusinessForm(request.POST, request.FILES, instance=biz)
        if form.is_valid():
            form.save()
            return redirect("dashboard")
    else:
        form = EditBusinessForm(instance=biz)
    return render(request, "finder/edit_business.html", {"form": form, "biz": biz})

@login_required
@require_POST
def toggle_holiday(request, business_id):
    biz = get_object_or_404(FeaturedBusiness, id=business_id, owner=request.user)
    action = (request.POST.get("action") or "").lower().strip()

    if action == "on":
        biz.is_on_holiday = True
        biz.holiday_note = (request.POST.get("note") or "On holiday").strip()[:120]
        biz.holiday_until = None

        until_raw = (request.POST.get("holiday_until") or "").strip()
        if until_raw:
            try:
                biz.holiday_until = timezone.make_aware(datetime.fromisoformat(until_raw))
            except Exception:
                pass

    elif action == "off":
        biz.is_on_holiday = False
        biz.holiday_note = None
        biz.holiday_until = None
    else:
        return JsonResponse({"error": "Invalid action"}, status=400)

    biz.save(update_fields=["is_on_holiday", "holiday_note", "holiday_until"])
    return redirect(request.META.get("HTTP_REFERER", "/finder/dashboard/"))

# -------------------------
# Claim flow (OTP email)
# -------------------------
def _domain_from_url(url: str) -> str:
    if not url:
        return ""
    try:
        host = urlparse(url).netloc.lower()
        return host.replace("www.", "")
    except Exception:
        return ""

def _gen_code() -> str:
    import random
    return f"{random.randint(100000, 999999)}"

def _hash_code(code: str) -> str:
    import hashlib
    return hashlib.sha256(code.encode()).hexdigest()






@login_required
@require_POST
def claim_osm_start(request):
    """
    Takes an OSM result from the search page (POST),
    creates/gets a DB Business row, then redirects to your existing claim flow.
    """

    osm_id = (request.POST.get("osm_id") or "").strip()
    name = (request.POST.get("name") or "").strip()

    address = (request.POST.get("address") or "").strip()
    city = (request.POST.get("city") or "").strip()
    state = (request.POST.get("state") or "").strip()
    zip_code = (request.POST.get("zip_code") or "").strip()

    phone = (request.POST.get("phone") or "").strip()
    url = (request.POST.get("url") or "").strip()
    category = (request.POST.get("category") or "").strip()

    # Safety: must have at least name + osm_id (or name alone)
    if not name:
        return redirect("finder")  # change to your search page url name if different

    # ✅ Create/get the business in your DB
    # IMPORTANT: adapt fields to YOUR model fields
    biz, created = FeaturedBusiness.objects.get_or_create(
        osm_id=osm_id,              # if your model doesn't have osm_id, remove this line
        defaults={
            "name": name,
            "address": address,
            "city": city,
            "state": state,
            "zip_code": zip_code,
            "phone": phone,
            "url": url,
            "category": category,
        }
    )

    # If it already exists, update missing fields (optional but helpful)
    changed = False
    for field, value in {
        "name": name,
        "address": address,
        "city": city,
        "state": state,
        "zip_code": zip_code,
        "phone": phone,
        "url": url,
        "category": category,
    }.items():
        if hasattr(biz, field) and value and not getattr(biz, field):
            setattr(biz, field, value)
            changed = True
    if changed:
        biz.save()

    # ✅ Send them into your existing "claim" flow for DB businesses
    # If your claim url name is different, change it here:
    return redirect("claim_request", biz.id)



@login_required
@require_http_methods(["GET", "POST"])
def claim_request(request, business_id):
    biz = get_object_or_404(FeaturedBusiness, id=business_id)

    if biz.owner and biz.owner != request.user:
        messages.error(request, "This business is already claimed.")
        return redirect("search_business")

    website_domain = _domain_from_url(biz.url)

    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()

        if not website_domain:
            messages.error(
                request,
                "This business has no website domain to verify. Please contact support for manual review."
            )
            return redirect("business_detail", business_id=biz.id)

        if "@" not in email:
            messages.error(request, "Enter a valid email address.")
            return redirect(request.path)

        email_domain = email.split("@")[-1].replace("www.", "")
        if email_domain != website_domain:
            messages.error(request, f"Email must be on the business domain: @{website_domain}")
            return redirect(request.path)

        # cleanup old expired unverified claims for this user+business
        BusinessClaim.objects.filter(
            business=biz,
            user=request.user,
            verified_at__isnull=True,
            expires_at__lt=timezone.now(),
        ).delete()

        code = _gen_code()
        claim = BusinessClaim.objects.create(
            business=biz,
            user=request.user,
            email=email,
            code_hash=_hash_code(code),
            expires_at=timezone.now() + timedelta(minutes=10),
        )

        send_mail(
            subject="Nearify business claim verification code",
            message=(
                f"Your verification code is: {code}\n\n"
                "This code expires in 10 minutes.\n"
                "If you did not request this, you can ignore this email."
            ),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[email],
            fail_silently=False,
        )

        return redirect("claim_verify", claim_id=claim.id)

    return render(request, "finder/claim_request.html", {"biz": biz, "website_domain": website_domain})

@login_required
@require_http_methods(["GET", "POST"])
def claim_verify(request, claim_id):
    claim = get_object_or_404(BusinessClaim, id=claim_id, user=request.user)
    biz = claim.business

    if claim.verified_at is not None:
        return redirect("dashboard")

    if claim.expires_at and timezone.now() > claim.expires_at:
        messages.error(request, "Code expired. Please request a new one.")
        return redirect("claim_request", business_id=biz.id)

    if request.method == "POST":
        code = (request.POST.get("code") or "").strip()

        claim.attempts += 1
        claim.save(update_fields=["attempts"])

        if claim.attempts > 8:
            messages.error(request, "Too many attempts. Request a new code.")
            return redirect("claim_request", business_id=biz.id)

        if _hash_code(code) != claim.code_hash:
            messages.error(request, "Invalid code.")
            return redirect(request.path)

        claim.verified_at = timezone.now()
        claim.save(update_fields=["verified_at"])

        # assign owner
        if not biz.owner:
            biz.owner = request.user
            biz.save(update_fields=["owner"])

        messages.success(request, "Business claimed successfully! You can now upgrade it.")
        return redirect("dashboard")

    return render(request, "finder/claim_verify.html", {"claim": claim, "biz": biz})







@require_POST
def claim_osm_start(request):
    """
    Converts an OSM search result into a DB listing (unclaimed + not active),
    then redirects into the normal claim OTP flow.
    """

    osm_id = env_str(request.POST.get("osm_id"))
    name = env_str(request.POST.get("name"))
    address = env_str(request.POST.get("address"))
    city = env_str(request.POST.get("city"))
    state = env_str(request.POST.get("state"))
    zip_code = env_str(request.POST.get("zip_code"))
    phone = env_str(request.POST.get("phone"))
    url = env_str(request.POST.get("url"))
    category = env_str(request.POST.get("category"))  # optional

    if not osm_id or not name:
        messages.error(request, "Missing business data. Please search again.")
        return redirect("search_business")

    # location string like "Brownsburg, IN"
    location = ", ".join([x for x in [city, state] if x])

    # Use yelp_id field to store OSM id to avoid adding a new DB column
    # (yelp_id is unique, so it works well as external_id)
    biz, created = FeaturedBusiness.objects.get_or_create(
        yelp_id=osm_id,
        defaults={
            "name": name,
            "category": category,
            "is_manual": False,      # important: this is NOT user-added manually
            "owner": None,
            "is_active": False,
            "priority": 0,
            "plan": FeaturedBusiness.PLAN_FEATURED,
            "location": location,
            "address": address,
            "city": city,
            "state": state,
            "zip_code": zip_code,
            "phone": phone or None,
            "url": url or None,
        },
    )

    # Update missing fields if the record already existed
    changed = False
    for field, value in [
        ("name", name),
        ("category", category),
        ("location", location),
        ("address", address),
        ("city", city),
        ("state", state),
        ("zip_code", zip_code),
        ("phone", phone or None),
        ("url", url or None),
    ]:
        if value and getattr(biz, field) != value:
            setattr(biz, field, value)
            changed = True

    if changed:
        biz.save()

    return redirect("claim_request", business_id=biz.id)


# -------------------------
# Stripe
# -------------------------
@login_required
def create_checkout_session(request, business_id, plan):
    business = get_object_or_404(FeaturedBusiness, id=business_id)

    if business.owner != request.user:
        return JsonResponse({"error": "Claim this business before promoting."}, status=403)

    plan = (plan or "").lower().strip()
    if plan not in PRICE_MAP:
        return JsonResponse({"error": "Invalid plan."}, status=400)

    price_id = PRICE_MAP.get(plan)
    if not price_id:
        return JsonResponse({"error": "Missing Stripe price id for this plan (check .env)."}, status=400)

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            metadata={"business_id": str(business.id), "plan": plan, "user_id": str(request.user.id)},
            success_url=request.build_absolute_uri("/finder/?sub=success"),
            cancel_url=request.build_absolute_uri("/finder/?sub=cancel"),
        )
        return JsonResponse({"id": session.id})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

# -------------------------
# Analytics
# -------------------------
@require_POST
def track_view(request, business_id):
    if not hasattr(FeaturedBusiness, "views_count"):
        return JsonResponse({"ok": False, "error": "Analytics not enabled"}, status=400)
    FeaturedBusiness.objects.filter(id=business_id).update(views_count=F("views_count") + 1)
    return JsonResponse({"ok": True})

@require_POST
def track_call(request, business_id):
    if not hasattr(FeaturedBusiness, "call_clicks"):
        return JsonResponse({"ok": False, "error": "Analytics not enabled"}, status=400)
    FeaturedBusiness.objects.filter(id=business_id).update(call_clicks=F("call_clicks") + 1)
    return JsonResponse({"ok": True})

@require_POST
def track_web(request, business_id):
    if not hasattr(FeaturedBusiness, "website_clicks"):
        return JsonResponse({"ok": False, "error": "Analytics not enabled"}, status=400)
    FeaturedBusiness.objects.filter(id=business_id).update(website_clicks=F("website_clicks") + 1)
    return JsonResponse({"ok": True})

@require_POST
def track_dir(request, business_id):
    if not hasattr(FeaturedBusiness, "directions_clicks"):
        return JsonResponse({"ok": False, "error": "Analytics not enabled"}, status=400)
    FeaturedBusiness.objects.filter(id=business_id).update(directions_clicks=F("directions_clicks") + 1)
    return JsonResponse({"ok": True})

# -------------------------
# Stripe webhook
# -------------------------
@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    endpoint_secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "")

    if not endpoint_secret:
        return JsonResponse({"error": "STRIPE_WEBHOOK_SECRET missing in settings.py/.env"}, status=500)

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)

    event_type = event["type"]
    obj = event["data"]["object"]

    def apply_subscription_to_business(biz: FeaturedBusiness, subscription_id: str, plan: str, amount_cents: int = 0):
        sub = stripe.Subscription.retrieve(subscription_id)
        period_end = sub.get("current_period_end")
        biz.featured_from = timezone.now()

        if period_end:
            biz.featured_until = datetime.fromtimestamp(period_end, tz=timezone.utc)

        biz.plan = plan
        biz.stripe_subscription_id = subscription_id
        biz.is_active = True
        biz.set_priority_by_plan()
        biz.last_paid_amount = amount_cents
        biz.save()

    if event_type == "checkout.session.completed":
        metadata = obj.get("metadata") or {}
        business_id = metadata.get("business_id")
        plan = (metadata.get("plan") or FeaturedBusiness.PLAN_FEATURED).lower().strip()

        customer_id = obj.get("customer")
        subscription_id = obj.get("subscription")

        if business_id and subscription_id:
            biz = FeaturedBusiness.objects.filter(id=business_id).first()
            if biz:
                biz.stripe_customer_id = customer_id
                apply_subscription_to_business(biz, subscription_id, plan)

    elif event_type == "invoice.paid":
        if obj.get("billing_reason") not in ("subscription_cycle", "subscription_create"):
            return JsonResponse({"status": "ignored"})

        subscription_id = obj.get("subscription")
        amount_paid = int(obj.get("amount_paid") or 0)

        if subscription_id:
            biz = FeaturedBusiness.objects.filter(stripe_subscription_id=subscription_id).first()
            if biz:
                apply_subscription_to_business(biz, subscription_id, biz.plan, amount_paid)

    elif event_type == "customer.subscription.deleted":
        subscription_id = obj.get("id")
        biz = FeaturedBusiness.objects.filter(stripe_subscription_id=subscription_id).first()
        if biz:
            biz.is_active = False
            biz.priority = 0
            biz.save(update_fields=["is_active", "priority"])

    return JsonResponse({"status": "ok"})
