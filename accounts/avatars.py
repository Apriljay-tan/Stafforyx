from __future__ import annotations

from django.contrib.auth.models import User

from employees.models import Employee
from messaging.constants import TYPE_ADMIN_SUPPORT, TYPE_DIRECT, TYPE_GROUP
from messaging.permissions import (
    get_portal_employee,
    get_support_display_name,
    user_can_manage_chat,
    user_can_use_employee_chat,
)


def initials_for_employee(employee) -> str:
    if employee is None:
        return '?'
    first = (employee.first_name or '').strip()
    last = (employee.last_name or '').strip()
    if first and last:
        return f'{first[0]}{last[0]}'.upper()
    if first:
        return first[0].upper()
    if last:
        return last[0].upper()
    return '?'


def initials_for_user(user: User) -> str:
    if user is None or not user.is_authenticated:
        return '?'
    first = (user.first_name or '').strip()
    last = (user.last_name or '').strip()
    if first and last:
        return f'{first[0]}{last[0]}'.upper()
    if first:
        return first[0].upper()
    full = user.get_full_name().strip()
    if full:
        return full[0].upper()
    username = (user.username or '').strip()
    if username:
        return username[0].upper()
    email = (user.email or '').strip()
    if email:
        return email[0].upper()
    return '?'


def initials_for_support(company) -> str:
    name = get_support_display_name(company).strip()
    if not name:
        return 'HR'
    parts = [part for part in name.split() if part]
    if len(parts) >= 2 and parts[-1].lower() == 'support':
        first = parts[0]
        if len(first) >= 2:
            return first[:2].upper()
        return f'{first[0]}{parts[1][0]}'.upper()
    if len(parts) >= 2:
        return f'{parts[0][0]}{parts[1][0]}'.upper()
    if len(name) >= 2:
        return name[:2].upper()
    return name[0].upper()


def photo_url_for_employee(employee) -> str | None:
    if employee is None:
        return None
    photo = getattr(employee, 'photo', None)
    if photo and photo.name:
        return photo.url
    return None


def photo_url_for_user_profile(user: User) -> str | None:
    if user is None or not user.is_authenticated:
        return None
    profile = getattr(user, 'stafforyx_profile', None)
    if profile is None:
        return None
    photo = getattr(profile, 'profile_photo', None)
    if photo and photo.name:
        return photo.url
    return None


def avatar_dict(*, image_url=None, initials='?', variant='user') -> dict:
    return {
        'image_url': image_url,
        'initials': initials,
        'variant': variant,
    }


def avatar_for_employee(employee) -> dict:
    return avatar_dict(
        image_url=photo_url_for_employee(employee),
        initials=initials_for_employee(employee),
        variant='employee',
    )


def avatar_for_user_profile(user: User) -> dict:
    return avatar_dict(
        image_url=photo_url_for_user_profile(user),
        initials=initials_for_user(user),
        variant='user',
    )


def avatar_for_support(company) -> dict:
    return avatar_dict(
        image_url=None,
        initials=initials_for_support(company),
        variant='support',
    )


def avatar_for_group(conversation) -> dict:
    if conversation.group_avatar and conversation.group_avatar.name:
        return avatar_dict(
            image_url=conversation.group_avatar.url,
            initials=conversation.get_group_avatar_initial(),
            variant='group',
        )
    title = (conversation.title or '').strip()
    initial = conversation.get_group_avatar_initial() if title else 'G'
    return avatar_dict(image_url=None, initials=initial, variant='group')


def _other_participant_user(conversation, viewer_user: User):
    participant = (
        conversation.participants.filter(left_at__isnull=True)
        .exclude(user=viewer_user)
        .select_related('user', 'employee')
        .first()
    )
    return participant.user if participant else None


def _employee_participant(conversation):
    participant = (
        conversation.participants.filter(left_at__isnull=True, employee__isnull=False)
        .select_related('employee')
        .first()
    )
    return participant.employee if participant else None


def avatar_for_user_as_viewer(user: User, viewer_user: User, *, conversation=None) -> dict:
    if (
        conversation is not None
        and conversation.conversation_type == TYPE_ADMIN_SUPPORT
        and user_can_use_employee_chat(viewer_user)
        and not user_can_manage_chat(viewer_user)
        and user is not None
        and user.pk != viewer_user.pk
        and not user_can_use_employee_chat(user)
    ):
        return avatar_for_support(conversation.company)

    employee = get_portal_employee(user)
    if employee is not None:
        return avatar_for_employee(employee)
    return avatar_for_user_profile(user)


def resolve_conversation_avatar(conversation, viewer_user: User, *, title=None) -> dict:
    if conversation.conversation_type == TYPE_GROUP:
        return avatar_for_group(conversation)

    if conversation.conversation_type == TYPE_ADMIN_SUPPORT:
        if user_can_use_employee_chat(viewer_user) and not user_can_manage_chat(viewer_user):
            return avatar_for_support(conversation.company)
        employee = _employee_participant(conversation)
        if employee is not None:
            return avatar_for_employee(employee)
        return avatar_for_support(conversation.company)

    if conversation.conversation_type == TYPE_DIRECT:
        other_user = _other_participant_user(conversation, viewer_user)
        if other_user is not None:
            return avatar_for_user_as_viewer(other_user, viewer_user, conversation=conversation)

    title = (title or '').strip()
    initial = title[0].upper() if title else '?'
    return avatar_dict(image_url=None, initials=initial, variant='direct')


def resolve_message_sender_avatar(message, viewer_user: User) -> dict:
    return avatar_for_user_as_viewer(
        message.sender_user,
        viewer_user,
        conversation=message.conversation,
    )


def avatar_for_nav_user(user: User, request=None) -> dict:
    path = getattr(request, 'path', '') if request is not None else ''
    if path.startswith('/portal/'):
        employee = get_portal_employee(user)
        if employee is not None:
            return avatar_for_employee(employee)
    return avatar_for_user_profile(user)
