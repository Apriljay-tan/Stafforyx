from django.db import models


class Company(models.Model):
    STATUS_CHOICES = [
        ('trial', 'Trial'),
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('suspended', 'Suspended'),
    ]
    PLAN_CHOICES = [
        ('free', 'Free'),
        ('starter', 'Starter'),
        ('professional', 'Professional'),
        ('enterprise', 'Enterprise'),
    ]

    name = models.CharField(max_length=255)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
    logo = models.ImageField(upload_to='companies/logos/', blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='trial')
    subscription_plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default='free')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'Companies'
        ordering = ['name']

    def __str__(self):
        return self.name
