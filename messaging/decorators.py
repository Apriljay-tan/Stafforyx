from functools import wraps

from django.core.exceptions import PermissionDenied

from .permissions import user_can_manage_chat


def chat_manager_required(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not user_can_manage_chat(request.user):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return wrapped
