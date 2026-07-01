from django.conf import settings
from .permissions import user_can_manage_chat, user_can_use_employee_chat
from .services import unread_count_for_user


def messaging_context(request):
    if not request.user.is_authenticated:
        return {}
    can_manage = user_can_manage_chat(request.user)
    employee_chat = user_can_use_employee_chat(request.user)
    context = {
        'can_manage_chat_user': can_manage,
        'employee_chat_available': employee_chat,
        'messaging_poll_interval_ms': settings.MESSAGING_POLL_INTERVAL_MS,
    }
    if can_manage or employee_chat:
        context['messaging_unread_total'] = unread_count_for_user(request.user)
    return context
