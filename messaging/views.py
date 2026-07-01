from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.company_access import filter_queryset_by_user_companies, get_accessible_companies
from employees.models import Employee

from .constants import TYPE_ADMIN_SUPPORT, TYPE_GROUP
from .decorators import chat_manager_required
from .models import Conversation
from .permissions import user_can_access_conversation, _chat_enabled_employees
from .services import (
    archive_conversation,
    audit_conversations,
    create_group_conversation,
    get_or_create_admin_support_conversation,
    inbox_for_user,
    mark_conversation_read,
    messages_for_conversation,
    send_message,
    serialize_message_for_user,
    unread_count_for_conversation,
    unread_count_for_user,
)


def _admin_messageable_employees(user):
    return filter_queryset_by_user_companies(
        Employee.objects.filter(
            status='active',
            user__isnull=False,
        ).select_related('company', 'user'),
        user,
    ).order_by('company__name', 'last_name', 'first_name')


def _group_participant_employees(user):
    accessible_ids = get_accessible_companies(user).values_list('pk', flat=True)
    return _chat_enabled_employees().filter(
        company_id__in=accessible_ids,
    ).select_related('company', 'user').order_by('company__name', 'last_name', 'first_name')


def _conversation_rows(user, conversations):
    rows = []
    for conversation in conversations.select_related('company'):
        last_message = conversation.messages.filter(deleted_at__isnull=True).order_by('-created_at').first()
        rows.append({
            'conversation': conversation,
            'unread': unread_count_for_conversation(conversation, user),
            'preview': (last_message.body[:80] if last_message else ''),
            'last_at': conversation.last_message_at or conversation.created_at,
            'title': _conversation_title(conversation),
        })
    return rows


def _conversation_title(conversation):
    if conversation.title:
        return conversation.title
    return conversation.get_conversation_type_display()


def _format_message_time(iso_value):
    if not iso_value:
        return ''
    parsed = parse_datetime(iso_value)
    if parsed is None:
        return iso_value[:16]
    return timezone.localtime(parsed).strftime('%b %d, %I:%M %p')


def _enrich_messages_for_display(message_dicts, user):
    enriched = []
    for message in message_dicts:
        item = dict(message)
        sender_id = item.get('sender_user_id')
        item['is_mine'] = sender_id == user.pk if sender_id is not None else False
        item['time_display'] = _format_message_time(item.get('created_at', ''))
        enriched.append(item)
    return enriched


def _participant_names(conversation):
    names = []
    for participant in conversation.participants.filter(left_at__isnull=True).select_related('user', 'employee'):
        if participant.employee_id:
            names.append(str(participant.employee))
        else:
            names.append(participant.user.get_full_name().strip() or participant.user.username)
    return names


def _chat_sidebar_context(user, *, search='', active_conversation_id=None):
    conversations = inbox_for_user(user, search=search or None)
    return {
        'conversation_rows': _conversation_rows(user, conversations),
        'search_query': search,
        'active_conversation_id': active_conversation_id,
    }


def _parse_audit_filters(request):
    filters = {}
    if request.GET.get('company'):
        filters['company_id'] = int(request.GET['company'])
    if request.GET.get('employee'):
        filters['employee_id'] = int(request.GET['employee'])
    if request.GET.get('q', '').strip():
        filters['q'] = request.GET['q'].strip()
    if request.GET.get('date_from'):
        filters['date_from'] = request.GET['date_from']
    if request.GET.get('date_to'):
        filters['date_to'] = request.GET['date_to']
    return filters


@login_required
@chat_manager_required
def inbox(request):
    search = request.GET.get('q', '').strip()
    context = _chat_sidebar_context(request.user, search=search)
    context['conversation_title'] = None
    return render(request, 'messaging/inbox.html', context)


@login_required
@chat_manager_required
def compose(request):
    employees = _admin_messageable_employees(request.user)
    companies = get_accessible_companies(request.user)
    group_employees = _group_participant_employees(request.user)

    if request.method == 'POST':
        compose_type = request.POST.get('compose_type', TYPE_ADMIN_SUPPORT)
        if compose_type == TYPE_ADMIN_SUPPORT:
            employee = get_object_or_404(employees, pk=request.POST.get('employee_id'))
            conversation, _ = get_or_create_admin_support_conversation(request.user, employee)
            return redirect('messaging:thread', pk=conversation.pk)

        if compose_type == TYPE_GROUP:
            company = get_object_or_404(companies, pk=request.POST.get('company_id'))
            participant_ids = request.POST.getlist('participant_ids')
            participant_users = list(User.objects.filter(pk__in=participant_ids))
            group_avatar = request.FILES.get('group_avatar')
            conversation = create_group_conversation(
                request.user,
                request.POST.get('title', ''),
                participant_users,
                company,
                group_avatar=group_avatar,
            )
            return redirect('messaging:thread', pk=conversation.pk)

    return render(request, 'messaging/compose.html', {
        'employees': employees,
        'companies': companies,
        'group_employees': group_employees,
    })


@login_required
@chat_manager_required
def thread(request, pk):
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
        return redirect('messaging:thread', pk=conversation.pk)

    mark_conversation_read(conversation, request.user)
    message_list = [
        serialize_message_for_user(message, request.user)
        for message in messages_for_conversation(conversation, request.user)
    ]
    search = request.GET.get('q', '').strip()
    context = _chat_sidebar_context(
        request.user,
        search=search,
        active_conversation_id=conversation.pk,
    )
    context.update({
        'conversation': conversation,
        'conversation_title': _conversation_title(conversation),
        'chat_messages': _enrich_messages_for_display(message_list, request.user),
        'participant_names': _participant_names(conversation),
    })
    return render(request, 'messaging/thread.html', context)


@login_required
@chat_manager_required
@require_POST
def archive_conversation_view(request, pk):
    conversation = get_object_or_404(Conversation, pk=pk)
    if not user_can_access_conversation(request.user, conversation):
        raise PermissionDenied
    archive_conversation(conversation, request.user)
    return redirect('messaging:inbox')


@login_required
@chat_manager_required
def audit_list(request):
    filters = _parse_audit_filters(request)
    conversations = audit_conversations(request.user, filters)
    paginator = Paginator(conversations, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'messaging/audit_list.html', {
        'page_obj': page_obj,
        'companies': get_accessible_companies(request.user),
        'employees': filter_queryset_by_user_companies(
            Employee.objects.filter(status='active').select_related('company'),
            request.user,
        ),
        'filters': request.GET,
    })


@login_required
@chat_manager_required
def audit_detail(request, pk):
    conversation = get_object_or_404(
        Conversation.objects.select_related('company'),
        pk=pk,
    )
    if not user_can_access_conversation(request.user, conversation):
        raise PermissionDenied

    participants = conversation.participants.select_related('user', 'employee').order_by('joined_at')
    message_list = [
        serialize_message_for_user(message, request.user, include_sender_id=True)
        for message in messages_for_conversation(conversation, request.user)
    ]
    return render(request, 'messaging/audit_detail.html', {
        'conversation': conversation,
        'participants': participants,
        'chat_messages': message_list,
    })


@login_required
@chat_manager_required
def unread_api(request):
    conversations = inbox_for_user(request.user)
    preview = []
    for row in _conversation_rows(request.user, conversations[:10]):
        conversation = row['conversation']
        preview.append({
            'id': conversation.pk,
            'title': conversation.title or conversation.get_conversation_type_display(),
            'unread': row['unread'],
            'url': f'/messaging/{conversation.pk}/',
            'preview': row['preview'],
            'last_at': row['last_at'].isoformat() if row['last_at'] else '',
        })
    return JsonResponse({
        'total_unread': unread_count_for_user(request.user),
        'conversations': preview,
    })


@login_required
@chat_manager_required
def thread_api(request, pk):
    conversation = get_object_or_404(Conversation, pk=pk)
    if not user_can_access_conversation(request.user, conversation):
        raise PermissionDenied

    after_id = request.GET.get('after_id')
    after_id = int(after_id) if after_id else None
    message_list = [
        serialize_message_for_user(message, request.user)
        for message in messages_for_conversation(conversation, request.user, after_id=after_id)
    ]
    return JsonResponse({'messages': message_list})
