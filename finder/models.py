# finder/models.py
import uuid
import hashlib
import random
from datetime import timedelta, time
from urllib.parse import urlparse

from django.conf import settings
from django.db import models
from django.utils import timezone


class FeaturedBusiness(models.Model):
    # -------------------------
    # Plans
    # -------------------------
    PLAN_FEATURED = "featured"
    PLAN_PREMIUM = "premium"
    PLAN_TOP = "top"

    PLAN_CHOICES = [
        (PLAN_FEATURED, "Featured"),
        (PLAN_PREMIUM, "Premium"),
        (PLAN_TOP, "Top Slot"),
    ]

    # -------------------------
    # Ownership (Claimed owner)
    # -------------------------
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_featured_businesses",
    )

    # -------------------------
    # Core business info
    # -------------------------
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=100, blank=True, default="")

    # Display/search compatibility
    location = models.CharField(max_length=255, blank=True, default="")  # e.g. "Brownsburg, IN"

    # Structured address (maps)
    address = models.CharField(max_length=255, blank=True, default="")
    city = models.CharField(max_length=120, blank=True, default="")
    state = models.CharField(max_length=120, blank=True, default="")
    zip_code = models.CharField(max_length=20, blank=True, default="")

    # Source flags
    is_manual = models.BooleanField(default=False)

    # Yelp / external fields
    yelp_id = models.CharField(max_length=255, blank=True, null=True, unique=True)
    url = models.URLField(blank=True, null=True)
    phone = models.CharField(max_length=50, blank=True, null=True)

    # Images
    image = models.ImageField(upload_to="business_images/", blank=True, null=True)
    image_url = models.URLField(blank=True, null=True)

    # Reviews
    rating = models.FloatField(blank=True, null=True)
    review_count = models.IntegerField(blank=True, null=True)

    # -------------------------
    # Hours / availability
    # -------------------------
    open_time = models.TimeField(default=time(9, 0))
    close_time = models.TimeField(default=time(17, 0))

    # Holiday / temporary closure
    is_on_holiday = models.BooleanField(default=False)
    holiday_note = models.CharField(max_length=120, blank=True, null=True)
    holiday_until = models.DateTimeField(blank=True, null=True)

    # -------------------------
    # Promotion / subscription
    # -------------------------
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default=PLAN_FEATURED)
    is_active = models.BooleanField(default=False)
    featured_from = models.DateTimeField(blank=True, null=True)
    featured_until = models.DateTimeField(blank=True, null=True)
    priority = models.IntegerField(default=0)

    # Stripe tracking
    stripe_session_id = models.CharField(max_length=255, blank=True, null=True)
    stripe_customer_id = models.CharField(max_length=255, blank=True, null=True)
    stripe_subscription_id = models.CharField(max_length=255, blank=True, null=True)
    last_paid_amount = models.IntegerField(default=0)

    # -------------------------
    # Analytics
    # -------------------------
    views_count = models.PositiveIntegerField(default=0)
    call_clicks = models.PositiveIntegerField(default=0)
    website_clicks = models.PositiveIntegerField(default=0)
    directions_clicks = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["category"]),
            models.Index(fields=["location"]),
            models.Index(fields=["is_active", "priority"]),
        ]
        ordering = ["-created_at"]

    # -------------------------
    # Promotion helpers
    # -------------------------
    def set_priority_by_plan(self):
        if self.plan == self.PLAN_TOP:
            self.priority = 300
        elif self.plan == self.PLAN_PREMIUM:
            self.priority = 200
        else:
            self.priority = 100

    def is_promoted_now(self) -> bool:
        if not self.is_active:
            return False

        now = timezone.now()

        if self.featured_from and now < self.featured_from:
            return False

        if self.featured_until and now > self.featured_until:
            return False

        return True


    def deactivate_if_expired(self):
        now = timezone.now()
        if self.featured_until and self.featured_until < now:
            self.is_active = False
            self.priority = 0
            self.save(update_fields=["is_active", "priority"])


    # -------------------------
    # Availability helpers
    # -------------------------
    def is_open_now(self, now_dt=None) -> bool:
        now_dt = now_dt or timezone.localtime()
        now_time = now_dt.time()

        # auto-clear holiday if expired
        if self.is_on_holiday and self.holiday_until and self.holiday_until <= timezone.now():
            self.is_on_holiday = False
            self.holiday_until = None
            self.holiday_note = None
            self.save(update_fields=["is_on_holiday", "holiday_until", "holiday_note"])

        if self.is_on_holiday:
            return False

        ot, ct = self.open_time, self.close_time
        if not ot or not ct:
            return False

        # Normal same-day
        if ot <= ct:
            return ot <= now_time <= ct

        # Overnight (e.g. 8pm - 2am)
        return now_time >= ot or now_time <= ct

    # -------------------------
    # Map helpers
    # -------------------------
    def full_address(self) -> str:
        parts = [self.address, self.city, self.state, self.zip_code]
        return ", ".join([p.strip() for p in parts if p and p.strip()])

    def website_domain(self) -> str:
        """Return domain without www."""
        if not self.url:
            return ""
        try:
            host = urlparse(self.url).netloc.lower()
            return host.replace("www.", "")
        except Exception:
            return ""

    def __str__(self):
        return f"{self.name} ({self.location})"


class BusinessClaim(models.Model):
    """
    OTP claim verification (email → code → ownership set).
    Recommended flow:
      - create claim (pending)
      - email code
      - verify code
      - mark verified + transfer ownership
    """

    STATUS_PENDING = "pending"
    STATUS_VERIFIED = "verified"
    STATUS_EXPIRED = "expired"
    STATUS_BLOCKED = "blocked"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_VERIFIED, "Verified"),
        (STATUS_EXPIRED, "Expired"),
        (STATUS_BLOCKED, "Blocked"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    business = models.ForeignKey(
        FeaturedBusiness,
        on_delete=models.CASCADE,
        related_name="claim_requests",
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    email = models.EmailField()
    code_hash = models.CharField(max_length=128)

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)

    expires_at = models.DateTimeField()
    attempts = models.PositiveIntegerField(default=0)

    # anti-spam
    last_sent_at = models.DateTimeField(null=True, blank=True)

    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["business", "user"]),
            models.Index(fields=["email"]),
            models.Index(fields=["status"]),
        ]

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_verified(self):
        return self.status == self.STATUS_VERIFIED and self.verified_at is not None

    # -------------------------
    # helpers
    # -------------------------
    @staticmethod
    def generate_code() -> str:
        return f"{random.randint(100000, 999999)}"

    @staticmethod
    def hash_code(code: str) -> str:
        return hashlib.sha256(code.encode()).hexdigest()

    def can_send_again(self, cooldown_seconds=60) -> bool:
        if not self.last_sent_at:
            return True
        return (timezone.now() - self.last_sent_at).total_seconds() >= cooldown_seconds

    @classmethod
    def create_claim(cls, business, user, email, minutes=10):
        """
        Creates a NEW claim request. (You can optionally expire previous ones in the view)
        Returns: (claim, plain_code)
        """
        code = cls.generate_code()
        claim = cls.objects.create(
            business=business,
            user=user,
            email=email,
            code_hash=cls.hash_code(code),
            expires_at=timezone.now() + timedelta(minutes=minutes),
            last_sent_at=timezone.now(),
            status=cls.STATUS_PENDING,
        )
        return claim, code

    def verify(self, code: str, max_attempts=5) -> bool:
        """
        Verify OTP. Updates status.
        Does NOT automatically transfer ownership — do that in your view after verify() returns True.
        """
        if self.is_verified:
            return True

        if self.is_expired:
            self.status = self.STATUS_EXPIRED
            self.save(update_fields=["status"])
            return False

        if self.attempts >= max_attempts:
            self.status = self.STATUS_BLOCKED
            self.save(update_fields=["status"])
            return False

        self.attempts += 1

        if self.hash_code(code) == self.code_hash:
            self.status = self.STATUS_VERIFIED
            self.verified_at = timezone.now()
            self.save(update_fields=["attempts", "status", "verified_at"])
            return True

        self.save(update_fields=["attempts"])
        return False
    




class Business(models.Model):
    PLAN_CHOICES = [
        ("free", "Free"),
        ("featured", "Featured"),
        ("premium", "Premium"),
        ("top", "Top Slot"),
    ]

    # Core listing info
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=120, blank=True, default="")
    description = models.TextField(blank=True, default="")

    address = models.CharField(max_length=255, blank=True, default="")
    city = models.CharField(max_length=100, blank=True, default="")
    state = models.CharField(max_length=100, blank=True, default="")
    zip_code = models.CharField(max_length=20, blank=True, default="")

    phone = models.CharField(max_length=50, blank=True, default="")
    url = models.URLField(blank=True, default="")

    # Map / OSM helpers (optional but useful)
    osm_id = models.CharField(max_length=60, blank=True, default="", db_index=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    maps_url = models.URLField(blank=True, default="")

    # Claim + monetization
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="owned_businesses"
    )
    is_claimed = models.BooleanField(default=False)

    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default="free")
    is_active = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
