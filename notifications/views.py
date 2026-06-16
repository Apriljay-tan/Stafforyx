from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.timesince import timesince
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from accounts.company_access import get_accessible_companies

from .models import Notification
from .services import (
    mark_all_notifications_read,
    notifications_visible_to_user,
    unread_notifications_for_user,
    user_can_see_admin_notifications,
)


def _require_notification_access(user):
    if not user_can_see_admin_notifications(user):
        raise PermissionDenied


@require_GET
@login_required
def unread_api(request):
    _require_notification_access(request.user)

    unread = unread_notifications_for_user(request.user)
    grouped_counts = dict(
        unread
        .values('notification_type')
        .annotate(total=Count('id'))
        .values_list('notification_type', 'total')
    )
    latest = unread.select_related('company')[:10]

    return JsonResponse({
        'total_unread': sum(grouped_counts.values()),
        'leave_count': grouped_counts.get(Notification.TYPE_LEAVE_REQUEST, 0),
        'overtime_count': grouped_counts.get(Notification.TYPE_OVERTIME_REQUEST, 0),
        'cash_advance_count': grouped_counts.get(Notification.TYPE_CASH_ADVANCE_REQUEST, 0),
        'latest': [
            {
                'id': notification.pk,
                'title': notification.title,
                'message': notification.message,
                'url': reverse('notifications:open', args=[notification.pk]),
                'created_display': f'{timesince(notification.created_at)} ago',
                'type': notification.notification_type,
            }
            for notification in latest
        ],
    })


@login_required
def notification_list(request):
    _require_notification_access(request.user)

    notifications = (
        notifications_visible_to_user(request.user)
        .select_related('company', 'content_type')
        .order_by('-created_at')
    )
    notification_type = request.GET.get('type', '')
    status = request.GET.get('status', '')
    company_id = request.GET.get('company', '')

    if notification_type:
        notifications = notifications.filter(notification_type=notification_type)
    if status == 'unread':
        notifications = notifications.filter(is_read=False)
    elif status == 'read':
        notifications = notifications.filter(is_read=True)
    if company_id:
        notifications = notifications.filter(company_id=company_id)

    return render(request, 'notifications/notification_list.html', {
        'notifications': notifications,
        'notification_type_filter': notification_type,
        'status_filter': status,
        'company_filter': company_id,
        'notification_type_choices': Notification.NOTIFICATION_TYPE_CHOICES,
        'filter_companies': get_accessible_companies(request.user).order_by('name'),
    })


@login_required
def open_notification(request, pk):
    _require_notification_access(request.user)

    notification = get_object_or_404(
        notifications_visible_to_user(request.user),
        pk=pk,
    )
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save(update_fields=['is_read', 'read_at'])

    target_url = notification.target_url or reverse('notifications:list')
    if not url_has_allowed_host_and_scheme(
        target_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        target_url = reverse('notifications:list')
    return redirect(target_url)


@require_POST
@login_required
def mark_all_read(request):
    _require_notification_access(request.user)
    updated = mark_all_notifications_read(request.user)
    if updated:
        messages.success(request, f'Marked {updated} notification(s) as read.')
    else:
        messages.info(request, 'No unread notifications to mark as read.')
    return redirect('notifications:list')
