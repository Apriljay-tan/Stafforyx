from django.db.models import Count

from .models import Notification
from .services import unread_notifications_for_user, user_can_see_admin_notifications


def notification_context(request):
    user = getattr(request, 'user', None)
    if (
        user is None
        or not user.is_authenticated
        or request.path.startswith('/portal/')
        or not user_can_see_admin_notifications(user)
    ):
        return {}

    unread = unread_notifications_for_user(user)
    grouped_counts = dict(
        unread
        .values('notification_type')
        .annotate(total=Count('id'))
        .values_list('notification_type', 'total')
    )
    latest = list(unread.select_related('company')[:10])

    leave_count = grouped_counts.get(Notification.TYPE_LEAVE_REQUEST, 0)
    overtime_count = grouped_counts.get(Notification.TYPE_OVERTIME_REQUEST, 0)
    ca_count = grouped_counts.get(Notification.TYPE_CASH_ADVANCE_REQUEST, 0)
    incident_count = grouped_counts.get(Notification.TYPE_INCIDENT_REPORT, 0)

    return {
        'show_admin_notifications': True,
        'notification_unread_total': sum(grouped_counts.values()),
        'unread_leave_count': leave_count,
        'unread_overtime_count': overtime_count,
        'unread_ca_count': ca_count,
        'unread_incident_count': incident_count,
        'latest_unread_notifications': latest,
    }
