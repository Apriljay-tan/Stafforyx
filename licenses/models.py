from django.db import models
from django.utils import timezone
from companies.models import Company


class License(models.Model):
    PLAN_CHOICES = [
        ('trial', 'Trial'),
        ('monthly', 'Monthly'),
        ('annual', 'Annual'),
        ('lifetime', 'Lifetime'),
    ]
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('suspended', 'Suspended'),
        ('trial', 'Trial'),
    ]

    # Identifier from the signed payload (UUID). Null for admin-created records.
    license_id = models.CharField(max_length=36, unique=True, null=True, blank=True)

    # FK to a Company record (used by admin-created licenses only).
    company = models.ForeignKey(
        Company, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='licenses'
    )
    # Plain company name from the signed payload.
    company_name = models.CharField(max_length=255, blank=True)

    # Full signed key string — much longer than a manual key, so max_length=2000.
    license_key = models.CharField(max_length=2000, unique=True)

    client_name = models.CharField(max_length=255)
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default='trial')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='trial')
    valid_from = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    max_employees = models.PositiveIntegerField(default=50)
    machine_id = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.client_name} — {self.get_plan_display()} ({self.get_status_display()})"

    @property
    def is_lifetime(self):
        return self.plan == 'lifetime'

    @property
    def is_expired(self):
        if self.is_lifetime or not self.valid_until:
            return False
        return self.valid_until < timezone.now().date()

    @property
    def days_remaining(self):
        if self.is_lifetime or not self.valid_until:
            return None
        return (self.valid_until - timezone.now().date()).days

    @property
    def masked_key(self):
        """Return a safe partial view of the key for display — never expose the full key."""
        k = self.license_key or ''
        if len(k) <= 30:
            return k[:8] + '•••' if k else '—'
        return k[:20] + ' ••••••••••••••••••••••••••••• ' + k[-8:]

    @property
    def display_company(self):
        """Return the best available company name for display."""
        if self.company:
            return self.company.name
        return self.company_name or '—'
