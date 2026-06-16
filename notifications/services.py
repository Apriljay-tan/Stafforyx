from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from accounts.company_access import get_accessible_companies
from accounts.access import is_employee_only_user

from .models import Notification


REQUEST_NOTIFICATION_ROLES = {
    Notification.TYPE_LEAVE_REQUEST: {'owner', 'company_admin', 'hr_admin'},
    Notification.TYPE_OVERTIME_REQUEST: {
        'owner',
        'company_admin',
        'hr_admin',
        'attendance_officer',
    },
    Notification.TYPE_CASH_ADVANCE_REQUEST: {
        'owner',
        'company_admin',
        'hr_admin',
        'payroll_officer',
    },
    Notification.TYPE_INCIDENT_REPORT: {
        'owner',
        'company_admin',
        'hr_admin',
        'attendance_officer',
    },
}


def authorized_recipients_for(notification_type, company):
    roles = REQUEST_NOTIFICATION_ROLES.get(notification_type, set())
    scoped_access = Q(
        company_accesses__company=company,
        company_accesses__is_active=True,
        company_accesses__role__in=roles,
    )
    super_admin = Q(is_superuser=True) | Q(
        stafforyx_profile__role='super_admin',
        stafforyx_profile__is_active_stafforyx=True,
    )
    return User.objects.filter(is_active=True).filter(
        scoped_access | super_admin
    ).distinct()


def user_can_see_admin_notifications(user):
    if not user.is_authenticated or is_employee_only_user(user):
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, 'stafforyx_profile', None)
    if profile is None or not profile.is_active_stafforyx:
        return False
    if profile.role == 'super_admin':
        return True
    if any((
        profile.can_manage_leaves,
        profile.can_manage_employees,
        profile.can_manage_attendance,
        profile.can_manage_payroll,
        profile.can_manage_documents,
        profile.can_manage_announcements,
        profile.can_view_reports,
    )):
        return True
    return user.company_accesses.filter(
        is_active=True,
        role__in={
            'owner',
            'company_admin',
            'hr_admin',
            'payroll_officer',
            'attendance_officer',
        },
    ).exists()


def create_request_notifications(
    request_obj,
    notification_type,
    title,
    message,
    target_url,
):
    company = request_obj.company
    content_type = ContentType.objects.get_for_model(request_obj, for_concrete_model=False)
    created = []

    for recipient in authorized_recipients_for(notification_type, company):
        notification, was_created = Notification.objects.get_or_create(
            recipient=recipient,
            notification_type=notification_type,
            content_type=content_type,
            object_id=request_obj.pk,
            defaults={
                'company': company,
                'title': title,
                'message': message,
                'target_url': target_url,
            },
        )
        if was_created:
            created.append(notification)

    return created


def notifications_visible_to_user(user):
    if not user.is_authenticated:
        return Notification.objects.none()

    queryset = Notification.objects.filter(recipient=user)
    if user.is_superuser:
        return queryset

    profile = getattr(user, 'stafforyx_profile', None)
    if profile and profile.role == 'super_admin':
        return queryset

    return queryset.filter(company__in=get_accessible_companies(user))


def unread_notifications_for_user(user):
    return notifications_visible_to_user(user).filter(is_read=False)


def mark_notifications_read(user, notification_type=None, content_object=None):
    queryset = unread_notifications_for_user(user)
    if notification_type:
        queryset = queryset.filter(notification_type=notification_type)
    if content_object is not None:
        queryset = queryset.filter(
            content_type=ContentType.objects.get_for_model(
                content_object,
                for_concrete_model=False,
            ),
            object_id=content_object.pk,
        )
    now = timezone.now()
    return queryset.update(is_read=True, read_at=now)


def mark_all_notifications_read(user):
    return mark_notifications_read(user)


def delete_notifications_for_objects(model, object_ids):
    ids = [int(object_id) for object_id in object_ids if str(object_id).isdigit()]
    if not ids:
        return (0, {})
    content_type = ContentType.objects.get_for_model(model, for_concrete_model=False)
    return Notification.objects.filter(
        content_type=content_type,
        object_id__in=ids,
    ).delete()


def request_notification_target_url(request_obj):
    if request_obj.__class__.__name__ == 'LeaveRequest':
        return reverse('leaves:leave_request_edit', args=[request_obj.pk])
    if request_obj.__class__.__name__ == 'OvertimeRequest':
        return reverse('overtime:manage_overtime_detail', args=[request_obj.pk])
    if request_obj.__class__.__name__ == 'CashAdvanceRequest':
        return reverse('cash_advance:manage_ca_detail', args=[request_obj.pk])
    if request_obj.__class__.__name__ == 'IncidentReport':
        return reverse('incident_reports:detail', args=[request_obj.pk])
    return ''
