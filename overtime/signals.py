"""
Auto-create a pending OvertimeRequest when overtime is detected for an employee
whose policy is `management_review`, so HR sees it in the review queue.

Registered in OvertimeConfig.ready(). Idempotent via the (employee, date) unique
constraint; never overrides an already-reviewed request.
"""

from decimal import Decimal, ROUND_HALF_UP

from django.db.models.signals import post_save
from django.dispatch import receiver

from attendance.models import AttendanceRecord

_Q2 = Decimal('0.01')


@receiver(post_save, sender=AttendanceRecord, dispatch_uid='overtime_auto_create')
def auto_create_management_review_overtime(sender, instance, **kwargs):
    employee = instance.employee
    if getattr(employee, 'overtime_policy', None) != 'management_review':
        return

    detected = instance.overtime_minutes or 0
    if detected <= 0:
        return

    from .models import OvertimeRequest

    hours = (Decimal(detected) / Decimal(60)).quantize(_Q2, rounding=ROUND_HALF_UP)
    obj, created = OvertimeRequest.objects.get_or_create(
        employee=employee,
        date=instance.date,
        defaults=dict(
            company=instance.company,
            requested_hours=hours,
            reason='Auto-detected overtime',
            status='pending',
            source='detected',
        ),
    )
    # Keep a still-pending detected row in sync with recomputed attendance.
    if (
        not created
        and obj.status == 'pending'
        and obj.source == 'detected'
        and obj.requested_hours != hours
    ):
        obj.requested_hours = hours
        obj.save(update_fields=['requested_hours', 'updated_at'])
