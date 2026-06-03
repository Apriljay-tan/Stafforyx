"""
Supplies the Employee Portal notification bell with recent announcements and an
unread count. Only does work on /portal/ pages for a logged-in employee.
"""
from django.db.models import Q

from announcements.models import Announcement, AnnouncementSeen


def _portal_employee(request):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return None
    # 1. Employee.user OneToOne
    try:
        emp = user.employee_profile
        if emp is not None:
            return emp
    except Exception:
        pass
    # 2. UserProfile.employee FK
    try:
        profile = user.stafforyx_profile
        if profile.employee_id:
            return profile.employee
    except Exception:
        pass
    return None


def _employee_announcements(employee):
    qs = Announcement.objects.filter(company=employee.company, is_active=True)
    if employee.department_id:
        qs = qs.filter(Q(target_department__isnull=True) | Q(target_department=employee.department))
    else:
        qs = qs.filter(target_department__isnull=True)
    return qs.order_by('-created_at')


def portal_notifications(request):
    if not request.path.startswith('/portal/'):
        return {}
    employee = _portal_employee(request)
    if employee is None:
        return {}

    qs = _employee_announcements(employee)
    items = list(qs[:8])

    seen = AnnouncementSeen.objects.filter(employee=employee).first()
    last_seen = seen.last_seen_at if seen else None
    unread = qs.filter(created_at__gt=last_seen).count() if last_seen else qs.count()

    return {
        'portal_notif_items': items,
        'portal_notif_unread': unread,
    }
