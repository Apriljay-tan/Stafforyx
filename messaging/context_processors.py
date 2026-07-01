from .permissions import user_can_manage_chat
from .services import unread_count_for_user


def messaging_context(request):
    if not request.user.is_authenticated:
        return {}
    can_manage = user_can_manage_chat(request.user)
    if not can_manage:
        return {'can_manage_chat_user': False}
    return {
        'can_manage_chat_user': True,
        'messaging_unread_total': unread_count_for_user(request.user),
    }
