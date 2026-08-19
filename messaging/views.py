import csv

from django.contrib import messages as django_messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.avatars import resolve_conversation_avatar, resolve_message_sender_avatar
from accounts.company_access import filter_queryset_by_user_companies, get_accessible_companies
from employees.models import Employee

from .constants import CONVERSATION_TYPE_CHOICES, TYPE_ADMIN_SUPPORT, TYPE_GROUP
from .decorators import chat_manager_required
from .models import Conversation, MessageAttachment
from .permissions import user_can_access_conversation, _chat_enabled_employees
from .services import (
    archive_conversation,
    audit_conversation_list_rows,
    audit_conversations,
    audit_conversations_queryset,
    audit_conversation_title,
    audit_export_rows,
    audit_participant_labels,
    create_group_conversation,
    enrich_audit_messages,
    get_or_create_admin_support_conversation,
    inbox_for_user,
    mark_conversation_read,
    message_preview_text,
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
        title = _conversation_title(conversation)
        preview = ''
        if last_message:
            preview = message_preview_text(last_message, user)
        rows.append({
            'conversation': conversation,
            'unread': unread_count_for_conversation(conversation, user),
            'preview': preview,
            'last_at': conversation.last_message_at or conversation.created_at,
            'title': title,
            'avatar_initial': _conversation_avatar_initial(conversation, title),
            'avatar': resolve_conversation_avatar(conversation, user, title=title),
        })
    return rows


def _conversation_avatar_initial(conversation, title):
    if conversation.conversation_type == TYPE_GROUP:
        return conversation.get_group_avatar_initial()
    title = (title or '').strip()
    return title[0].upper() if title else '?'


def _participant_count(conversation):
    return conversation.participants.filter(left_at__isnull=True).count()


def _admin_thread_display_context(user, conversation, *, mark_read=False):
    if mark_read:
        mark_conversation_read(conversation, user)
    message_qs = messages_for_conversation(conversation, user)
    title = _conversation_title(conversation)
    participant_names = _participant_names(conversation)
    return {
        'conversation': conversation,
        'conversation_title': title,
        'avatar_initial': _conversation_avatar_initial(conversation, title),
        'avatar': resolve_conversation_avatar(conversation, user, title=title),
        'chat_messages': enrich_chat_messages(message_qs, user),
        'participant_names': participant_names,
        'participant_count': _participant_count(conversation),
        'show_archive': True,
        'thread_url_name': 'messaging:thread',
        'archive_url_name': 'messaging:archive',
        'thread_api_url_name': 'messaging:thread_api',
        'unread_api_url_name': 'messaging:unread_api',
    }


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


def post_thread_message(request, conversation):
    """Handle composer POST for admin and portal thread views."""
    body = request.POST.get('body', '').strip()
    attachment = request.FILES.get('attachment')
    if not body and not attachment:
        django_messages.error(request, 'Type a message or attach an image.')
        return False
    try:
        send_message(conversation, request.user, body, attachment=attachment)
        return True
    except ValidationError as exc:
        django_messages.error(request, '; '.join(exc.messages))
        return False


def enrich_chat_messages(messages_qs, user):
    """Build template-ready chat message dicts with correct is_mine for any viewer."""
    enriched = []
    prev_sender_id = None
    for message in messages_qs:
        data = serialize_message_for_user(message, user)
        data = dict(data)
        is_mine = message.sender_user_id == user.pk
        data['is_mine'] = is_mine
        data['time_display'] = _format_message_time(data.get('created_at', ''))
        data['show_sender'] = message.sender_user_id != prev_sender_id
        data['sender_avatar'] = resolve_message_sender_avatar(message, user)
        prev_sender_id = message.sender_user_id
        enriched.append(data)
    return enriched


def messages_for_api(user, conversation, *, after_id=None, mark_read=False):
    """JSON-serializable message dicts for thread polling APIs."""
    if mark_read:
        mark_conversation_read(conversation, user)
    message_qs = messages_for_conversation(conversation, user, after_id=after_id)
    return [
        {
            'id': msg['id'],
            'body': msg['body'],
            'sender_display': msg['sender_display'],
            'created_at': msg['created_at'],
            'time_display': msg['time_display'],
            'is_mine': msg['is_mine'],
            'is_deleted': msg['is_deleted'],
            'show_sender': msg['show_sender'],
            'sender_avatar': msg['sender_avatar'],
            'attachments': msg.get('attachments', []),
        }
        for msg in enrich_chat_messages(message_qs, user)
    ]


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
    if request.GET.get('type'):
        filters['conversation_type'] = request.GET['type']
    if request.GET.get('q', '').strip():
        filters['q'] = request.GET['q'].strip()
    if request.GET.get('date_from'):
        filters['date_from'] = request.GET['date_from']
    if request.GET.get('date_to'):
        filters['date_to'] = request.GET['date_to']
    return filters


def _audit_filter_context(request, filters):
    return {
        'companies': get_accessible_companies(request.user),
        'employees': filter_queryset_by_user_companies(
            Employee.objects.filter(status='active').select_related('company'),
            request.user,
        ),
        'conversation_types': CONVERSATION_TYPE_CHOICES,
        'filters': request.GET,
        'filter_query': request.GET.urlencode(),
    }


@login_required
@chat_manager_required
def inbox(request):
    search = request.GET.get('q', '').strip()
    context = _chat_sidebar_context(request.user, search=search)
    context.update({
        'compose_url_name': 'messaging:compose',
        'thread_url_name': 'messaging:thread',
        'show_audit': True,
        'thread_api_url_name': 'messaging:thread_api',
        'unread_api_url_name': 'messaging:unread_api',
    })
    rows = context['conversation_rows']
    if rows:
        first_conversation = rows[0]['conversation']
        context['active_conversation_id'] = first_conversation.pk
        context.update(_admin_thread_display_context(request.user, first_conversation, mark_read=False))
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
        post_thread_message(request, conversation)
        return redirect('messaging:thread', pk=conversation.pk)

    search = request.GET.get('q', '').strip()
    context = _chat_sidebar_context(
        request.user,
        search=search,
        active_conversation_id=conversation.pk,
    )
    context.update({
        'compose_url_name': 'messaging:compose',
        'thread_url_name': 'messaging:thread',
        'show_audit': True,
        'thread_api_url_name': 'messaging:thread_api',
        'unread_api_url_name': 'messaging:unread_api',
    })
    context.update(_admin_thread_display_context(request.user, conversation, mark_read=True))
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
    conversations = audit_conversations_queryset(request.user, filters)
    paginator = Paginator(conversations, 25)
    page_obj = paginator.get_page(request.GET.get('page'))
    rows = audit_conversation_list_rows(request.user, page_obj.object_list)

    context = _audit_filter_context(request, filters)
    context.update({
        'page_obj': page_obj,
        'audit_rows': rows,
        'selected_conversation_id': None,
    })
    return render(request, 'messaging/audit_list.html', context)


@login_required
@chat_manager_required
def audit_export_csv(request):
    filters = _parse_audit_filters(request)
    export_rows = audit_export_rows(request.user, filters)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="chat-audit.csv"'
    writer = csv.writer(response)
    writer.writerow([
        'conversation_id', 'company', 'type', 'title', 'participants',
        'last_message_at', 'message_count', 'attachment_count', 'archived',
    ])
    for row in export_rows:
        last_at = row['last_message_at']
        writer.writerow([
            row['conversation_id'],
            row['company'],
            row['type'],
            row['title'],
            row['participants'],
            timezone.localtime(last_at).strftime('%Y-%m-%d %H:%M') if last_at else '',
            row['message_count'],
            row['attachment_count'],
            'yes' if row['is_archived'] else 'no',
        ])
    return response


@login_required
@chat_manager_required
def audit_detail(request, pk):
    filters = _parse_audit_filters(request)
    conversation = get_object_or_404(
        Conversation.objects.select_related('company'),
        pk=pk,
    )
    if not user_can_access_conversation(request.user, conversation):
        raise PermissionDenied

    sidebar_conversations = audit_conversations_queryset(request.user, filters)[:50]
    sidebar_rows = audit_conversation_list_rows(request.user, sidebar_conversations)

    participants = conversation.participants.select_related('user', 'employee').order_by('joined_at')
    message_qs = messages_for_conversation(conversation, request.user).prefetch_related('attachments')
    chat_messages = enrich_audit_messages(message_qs, request.user)

    context = _audit_filter_context(request, filters)
    context.update({
        'conversation': conversation,
        'conversation_title': audit_conversation_title(conversation),
        'participants': participants,
        'participant_labels': audit_participant_labels(conversation),
        'chat_messages': chat_messages,
        'audit_rows': sidebar_rows,
        'selected_conversation_id': conversation.pk,
        'avatar': resolve_conversation_avatar(conversation, request.user, title=audit_conversation_title(conversation)),
    })
    return render(request, 'messaging/audit_detail.html', context)


@login_required
@chat_manager_required
def unread_api(request):
    conversations = inbox_for_user(request.user)
    preview = []
    for row in _conversation_rows(request.user, conversations):
        conversation = row['conversation']
        preview.append({
            'id': conversation.pk,
            'title': row['title'],
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
    message_list = messages_for_api(
        request.user,
        conversation,
        after_id=after_id,
        mark_read=True,
    )
    return JsonResponse({'messages': message_list})


@login_required
def attachment_view(request, pk):
    attachment = get_object_or_404(
        MessageAttachment.objects.select_related('message__conversation'),
        pk=pk,
    )
    conversation = attachment.message.conversation
    if not user_can_access_conversation(request.user, conversation):
        raise PermissionDenied

    mime_type = attachment.content_type or 'application/octet-stream'
    response = FileResponse(attachment.file.open('rb'), content_type=mime_type)
    filename = attachment.original_filename or attachment.file.name.split('/')[-1]
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    return response
