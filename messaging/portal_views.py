from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .constants import TYPE_DIRECT, TYPE_GROUP
from .models import Conversation
from .permissions import (
    get_allowed_chat_contacts,
    get_portal_employee,
    user_can_access_conversation,
    user_can_use_employee_chat,
)
from .services import (
    create_group_conversation,
    get_or_create_direct_conversation,
    inbox_for_user,
    mark_conversation_read,
    messages_for_conversation,
    send_message,
    serialize_message_for_user,
    unread_count_for_conversation,
    unread_count_for_user,
)
from .views import enrich_chat_messages, messages_for_api


def portal_chat_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not user_can_use_employee_chat(request.user):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return wrapped


@portal_chat_required
def portal_inbox(request):
    search = request.GET.get('q', '').strip()
    context = _portal_chat_sidebar_context(request.user, search=search)
    context.update({
        'compose_url_name': 'portal:messages_compose',
        'thread_url_name': 'portal:messages_thread',
        'show_audit': False,
        'thread_api_url_name': 'portal:messages_thread_api',
        'unread_api_url_name': 'portal:messages_unread_api',
    })
    rows = context['conversation_rows']
    if rows:
        first_conversation = rows[0]['conversation']
        context['active_conversation_id'] = first_conversation.pk
        context.update(_portal_thread_display_context(request.user, first_conversation, mark_read=False))
    return render(request, 'portal/messages/inbox.html', context)


@portal_chat_required
def portal_compose(request):
    allowed_contacts = get_allowed_chat_contacts(request.user)
    employee = get_portal_employee(request.user)

    if request.method == 'POST':
        compose_type = request.POST.get('compose_type', TYPE_DIRECT)
        if compose_type == TYPE_DIRECT:
            contact = get_object_or_404(allowed_contacts, pk=request.POST.get('contact_employee_id'))
            conversation, _ = get_or_create_direct_conversation(request.user, contact.user)
            return redirect('portal:messages_thread', pk=conversation.pk)

        if compose_type == TYPE_GROUP:
            participant_ids = request.POST.getlist('participant_ids')
            participant_users = list(
                User.objects.filter(
                    pk__in=participant_ids,
                    employee_profile__in=allowed_contacts,
                )
            )
            group_avatar = request.FILES.get('group_avatar')
            conversation = create_group_conversation(
                request.user,
                request.POST.get('title', ''),
                participant_users,
                employee.company,
                group_avatar=group_avatar,
            )
            return redirect('portal:messages_thread', pk=conversation.pk)

    return render(request, 'portal/messages/compose.html', {
        'allowed_contacts': allowed_contacts,
        'employee': employee,
    })


@portal_chat_required
def portal_thread(request, pk):
    conversation = get_object_or_404(
        Conversation.objects.select_related('company'),
        pk=pk,
    )
    if not user_can_access_conversation(request.user, conversation):
        raise PermissionDenied

    if request.method == 'POST':
        body = request.POST.get('body', '').strip()
        if body:
            send_message(conversation, request.user, body)
        return redirect('portal:messages_thread', pk=conversation.pk)

    search = request.GET.get('q', '').strip()
    context = _portal_chat_sidebar_context(
        request.user,
        search=search,
        active_conversation_id=conversation.pk,
    )
    context.update({
        'compose_url_name': 'portal:messages_compose',
        'thread_url_name': 'portal:messages_thread',
        'show_audit': False,
        'thread_api_url_name': 'portal:messages_thread_api',
        'unread_api_url_name': 'portal:messages_unread_api',
    })
    context.update(_portal_thread_display_context(request.user, conversation, mark_read=True))
    return render(request, 'portal/messages/thread.html', context)


@portal_chat_required
def portal_unread_api(request):
    conversations = inbox_for_user(request.user)
    preview = []
    for row in _portal_conversation_rows(request.user, conversations):
        conversation = row['conversation']
        preview.append({
            'id': conversation.pk,
            'title': row['title'],
            'unread': row['unread'],
            'url': f'/portal/messages/{conversation.pk}/',
            'preview': row['preview'],
            'last_at': row['last_at'].isoformat() if row['last_at'] else '',
        })
    return JsonResponse({
        'total_unread': unread_count_for_user(request.user),
        'conversations': preview,
    })


@portal_chat_required
def portal_thread_api(request, pk):
    conversation = get_object_or_404(Conversation, pk=pk)
    if not user_can_access_conversation(request.user, conversation):
        raise PermissionDenied

    after_id = request.GET.get('after_id')
    after_id = int(after_id) if after_id else None
    message_list = messages_for_api(
        request.user,
        conversation,
        after_id=after_id,
        mark_read=True,
    )
    return JsonResponse({'messages': message_list})


def _portal_avatar_initial(conversation, user):
    from .constants import TYPE_GROUP

    if conversation.conversation_type == TYPE_GROUP:
        return conversation.get_group_avatar_initial()
    title = _portal_conversation_title(conversation, user)
    title = (title or '').strip()
    return title[0].upper() if title else '?'


def _portal_thread_display_context(user, conversation, *, mark_read=False):
    if mark_read:
        mark_conversation_read(conversation, user)
    message_qs = messages_for_conversation(conversation, user)
    participant_names = _portal_participant_names(conversation, user)
    title = _portal_conversation_title(conversation, user)
    return {
        'conversation': conversation,
        'conversation_title': title,
        'avatar_initial': _portal_avatar_initial(conversation, user),
        'chat_messages': enrich_chat_messages(message_qs, user),
        'participant_names': participant_names,
        'participant_count': conversation.participants.filter(left_at__isnull=True).count(),
        'show_archive': False,
        'thread_url_name': 'portal:messages_thread',
        'thread_api_url_name': 'portal:messages_thread_api',
        'unread_api_url_name': 'portal:messages_unread_api',
    }


def _portal_conversation_rows(user, conversations):
    rows = []
    for conversation in conversations.select_related('company'):
        last_message = conversation.messages.filter(deleted_at__isnull=True).order_by('-created_at').first()
        preview = ''
        if last_message:
            preview = serialize_message_for_user(last_message, user)['body'][:80]
        rows.append({
            'conversation': conversation,
            'unread': unread_count_for_conversation(conversation, user),
            'preview': preview,
            'last_at': conversation.last_message_at or conversation.created_at,
            'title': _portal_conversation_title(conversation, user),
            'avatar_initial': _portal_avatar_initial(conversation, user),
        })
    return rows


def _portal_chat_sidebar_context(user, *, search='', active_conversation_id=None):
    conversations = inbox_for_user(user, search=search or None)
    return {
        'conversation_rows': _portal_conversation_rows(user, conversations),
        'search_query': search,
        'active_conversation_id': active_conversation_id,
    }


def _portal_conversation_title(conversation, user):
    from .constants import TYPE_ADMIN_SUPPORT, TYPE_DIRECT

    if conversation.title:
        return conversation.title
    if conversation.conversation_type == TYPE_ADMIN_SUPPORT:
        from .permissions import get_support_display_name
        return get_support_display_name(conversation.company)
    if conversation.conversation_type == TYPE_DIRECT:
        other_names = _portal_participant_names(conversation, user)
        if other_names:
            return other_names[0]
    return conversation.get_conversation_type_display()


def _portal_participant_names(conversation, user):
    from .constants import TYPE_ADMIN_SUPPORT
    from .permissions import get_support_display_name

    names = []
    for participant in conversation.participants.filter(left_at__isnull=True).select_related('user', 'employee'):
        if participant.user_id == user.pk:
            continue
        if conversation.conversation_type == TYPE_ADMIN_SUPPORT and user_can_use_employee_chat(user):
            if not user_can_use_employee_chat(participant.user) or get_portal_employee(participant.user) is None:
                names.append(get_support_display_name(conversation.company))
                continue
        if participant.employee_id:
            names.append(str(participant.employee))
        else:
            names.append(participant.user.get_full_name().strip() or participant.user.username)
    return names
