from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from accounts.company_access import filter_queryset_by_user_companies, user_can_access_company

from .attachment_validation import attachment_type_for_file, validate_message_attachment
from .constants import (
    CONVERSATION_TYPE_CHOICES,
    MAX_MESSAGE_BODY_LENGTH,
    ROLE_ADMIN,
    ROLE_GROUP_CREATOR,
    ROLE_MEMBER,
    TYPE_ADMIN_SUPPORT,
    TYPE_DIRECT,
    TYPE_GROUP,
)
from .models import Conversation, ConversationParticipant, ConversationReadState, Message, MessageAttachment
from .permissions import (
    get_allowed_chat_contacts,
    get_portal_employee,
    get_support_display_name,
    user_can_access_conversation,
    user_can_manage_chat,
    user_can_use_employee_chat,
    validate_group_participant_users,
    _admin_eligible_participant_user_ids,
)


def _user_display_name(user) -> str:
    employee = get_portal_employee(user)
    if employee:
        return str(employee)
    full_name = user.get_full_name().strip()
    return full_name or user.username


def _employee_for_user(user):
    return get_portal_employee(user)


def _find_active_direct_conversation(user_a, user_b):
    conv_ids = ConversationParticipant.objects.filter(
        user=user_a,
        left_at__isnull=True,
        conversation__conversation_type=TYPE_DIRECT,
        conversation__is_archived=False,
    ).values_list('conversation_id', flat=True)
    return Conversation.objects.filter(
        pk__in=conv_ids,
        participants__user=user_b,
        participants__left_at__isnull=True,
    ).distinct().first()


def _direct_conversation_company(user_a, user_b):
    emp_a = _employee_for_user(user_a)
    emp_b = _employee_for_user(user_b)
    if emp_a and emp_b:
        return emp_a.company
    if emp_b:
        return emp_b.company
    if emp_a:
        return emp_a.company
    raise ValidationError('Direct conversations require at least one employee participant.')


def _user_in_direct_scope(initiator, other):
    if user_can_manage_chat(initiator):
        return other.pk in _admin_eligible_participant_user_ids(initiator)
    if user_can_use_employee_chat(initiator):
        contact_ids = set(get_allowed_chat_contacts(initiator).values_list('user_id', flat=True))
        return other.pk in contact_ids
    return False


def _validate_direct_participants(user_a, user_b):
    if not (_user_in_direct_scope(user_a, user_b) or _user_in_direct_scope(user_b, user_a)):
        raise PermissionDenied('You cannot start a direct conversation with this user.')


def _ensure_participant(conversation, user, *, role=ROLE_MEMBER, employee=None):
    participant, created = ConversationParticipant.objects.get_or_create(
        conversation=conversation,
        user=user,
        defaults={'role': role, 'employee': employee},
    )
    if not created and participant.left_at is not None:
        participant.left_at = None
        participant.role = role
        if employee is not None:
            participant.employee = employee
        participant.save(update_fields=['left_at', 'role', 'employee'])
    return participant


@transaction.atomic
def get_or_create_admin_support_conversation(admin_user, employee):
    if not user_can_manage_chat(admin_user):
        raise PermissionDenied('You do not have permission to manage chat.')
    if not user_can_access_company(admin_user, employee.company):
        raise PermissionDenied('You do not have access to this company.')
    if not employee.user_id:
        raise ValidationError('Employee has no linked user account.')

    existing = Conversation.objects.filter(
        company=employee.company,
        conversation_type=TYPE_ADMIN_SUPPORT,
        is_archived=False,
        participants__user=employee.user,
        participants__left_at__isnull=True,
    ).first()
    if existing:
        return existing, False

    conversation = Conversation.objects.create(
        company=employee.company,
        conversation_type=TYPE_ADMIN_SUPPORT,
        created_by=admin_user,
    )
    _ensure_participant(
        conversation, employee.user, role=ROLE_MEMBER, employee=employee,
    )
    _ensure_participant(conversation, admin_user, role=ROLE_ADMIN)
    return conversation, True


@transaction.atomic
def get_or_create_direct_conversation(user_a, user_b):
    if user_a.pk == user_b.pk:
        raise ValidationError('Cannot create a direct conversation with yourself.')

    _validate_direct_participants(user_a, user_b)

    existing = _find_active_direct_conversation(user_a, user_b)
    if existing:
        return existing, False

    company = _direct_conversation_company(user_a, user_b)
    conversation = Conversation.objects.create(
        company=company,
        conversation_type=TYPE_DIRECT,
        created_by=user_a,
    )
    for user in (user_a, user_b):
        emp = _employee_for_user(user)
        _ensure_participant(conversation, user, employee=emp)
    return conversation, True


@transaction.atomic
def create_group_conversation(creator, title, participant_users, company, *, group_avatar=None):
    title = (title or '').strip()
    if not title:
        raise ValidationError('Title is required for group conversations.')

    participant_ids = [user.pk for user in participant_users]
    validated_users = validate_group_participant_users(creator, participant_ids)

    all_users = [creator]
    seen = {creator.pk}
    for user in validated_users:
        if user.pk not in seen:
            all_users.append(user)
            seen.add(user.pk)

    if len(all_users) < 3:
        raise ValidationError('Group conversations require at least 3 participants.')

    if user_can_manage_chat(creator):
        if not user_can_access_company(creator, company):
            raise PermissionDenied('You do not have access to this company.')
    else:
        creator_employee = get_portal_employee(creator)
        if creator_employee is None or creator_employee.company_id != company.pk:
            raise PermissionDenied('Invalid company for group conversation.')

    conversation = Conversation.objects.create(
        company=company,
        conversation_type=TYPE_GROUP,
        title=title,
        created_by=creator,
    )
    if group_avatar:
        conversation.group_avatar = group_avatar
        conversation.save(update_fields=['group_avatar'])
    _ensure_participant(
        conversation, creator,
        role=ROLE_GROUP_CREATOR,
        employee=get_portal_employee(creator),
    )
    for user in all_users[1:]:
        _ensure_participant(
            conversation, user,
            role=ROLE_MEMBER,
            employee=get_portal_employee(user),
        )
    return conversation


def _ensure_sender_can_message(conversation, sender):
    if conversation.participants.filter(user=sender, left_at__isnull=True).exists():
        return

    if (
        conversation.conversation_type == TYPE_ADMIN_SUPPORT
        and user_can_manage_chat(sender)
        and user_can_access_company(sender, conversation.company)
    ):
        _ensure_participant(conversation, sender, role=ROLE_ADMIN)
        return

    raise PermissionDenied('You are not a participant in this conversation.')


@transaction.atomic
def send_message(conversation, sender, body, *, attachment=None):
    body = (body or '').strip()
    if not body and not attachment:
        raise ValidationError('Message must include text or an attachment.')
    if body and len(body) > MAX_MESSAGE_BODY_LENGTH:
        raise ValidationError(f'Message body cannot exceed {MAX_MESSAGE_BODY_LENGTH} characters.')
    if attachment:
        validate_message_attachment(attachment)

    _ensure_sender_can_message(conversation, sender)

    message = Message.objects.create(
        conversation=conversation,
        sender_user=sender,
        body=body,
    )
    if attachment:
        MessageAttachment.objects.create(
            message=message,
            file=attachment,
            original_filename=getattr(attachment, 'name', '') or 'attachment',
            content_type=(getattr(attachment, 'content_type', '') or 'application/octet-stream'),
            size_bytes=getattr(attachment, 'size', 0) or 0,
            attachment_type=attachment_type_for_file(attachment),
            uploaded_by=sender,
        )

    conversation.last_message_at = message.created_at
    conversation.save(update_fields=['last_message_at', 'updated_at'])
    return message


@transaction.atomic
def soft_delete_message(message, actor):
    if not user_can_access_conversation(actor, message.conversation):
        raise PermissionDenied('You cannot delete this message.')
    if not (user_can_manage_chat(actor) or message.sender_user_id == actor.pk):
        raise PermissionDenied('You cannot delete this message.')

    message.deleted_at = timezone.now()
    message.deleted_by = actor
    message.save(update_fields=['deleted_at', 'deleted_by'])


@transaction.atomic
def archive_conversation(conversation, actor):
    if not user_can_access_conversation(actor, conversation):
        raise PermissionDenied('You cannot archive this conversation.')
    if not (
        user_can_manage_chat(actor)
        or conversation.created_by_id == actor.pk
        or conversation.participants.filter(user=actor, left_at__isnull=True).exists()
    ):
        raise PermissionDenied('You cannot archive this conversation.')

    conversation.is_archived = True
    conversation.archived_at = timezone.now()
    conversation.archived_by = actor
    conversation.save(update_fields=['is_archived', 'archived_at', 'archived_by', 'updated_at'])


@transaction.atomic
def mark_conversation_read(conversation, user):
    if not user_can_access_conversation(user, conversation):
        raise PermissionDenied('You cannot access this conversation.')

    ConversationReadState.objects.update_or_create(
        conversation=conversation,
        user=user,
        defaults={'last_read_at': timezone.now()},
    )


def unread_count_for_conversation(conversation, user):
    if not user_can_access_conversation(user, conversation):
        return 0

    read_state = ConversationReadState.objects.filter(
        conversation=conversation, user=user,
    ).first()
    messages = conversation.messages.filter(
        deleted_at__isnull=True,
    ).exclude(sender_user=user)
    if read_state:
        messages = messages.filter(created_at__gt=read_state.last_read_at)
    return messages.count()


def unread_count_for_user(user):
    if not user.is_authenticated:
        return 0

    conversation_ids = ConversationParticipant.objects.filter(
        user=user,
        left_at__isnull=True,
        conversation__is_archived=False,
    ).values_list('conversation_id', flat=True)

    total = 0
    for conversation in Conversation.objects.filter(pk__in=conversation_ids):
        total += unread_count_for_conversation(conversation, user)
    return total


def inbox_for_user(user, *, search=None, archived=False):
    if not user.is_authenticated:
        return Conversation.objects.none()

    qs = Conversation.objects.filter(
        participants__user=user,
        participants__left_at__isnull=True,
        is_archived=archived,
    ).distinct()

    if user_can_manage_chat(user):
        qs = filter_queryset_by_user_companies(qs, user)

    if search:
        qs = qs.filter(
            Q(title__icontains=search)
            | Q(messages__body__icontains=search)
        ).distinct()

    return qs.order_by('-last_message_at', '-created_at')


def messages_for_conversation(conversation, user, *, after_id=None):
    if not user_can_access_conversation(user, conversation):
        raise PermissionDenied('You cannot access this conversation.')

    qs = conversation.messages.select_related('sender_user').prefetch_related('attachments').order_by('created_at')
    if after_id is not None:
        qs = qs.filter(pk__gt=after_id)
    return qs


def search_messages(user, query, filters=None):
    filters = filters or {}
    if not query:
        return Message.objects.none()

    conversations = inbox_for_user(user, archived=filters.get('archived', False))
    if user_can_manage_chat(user) and filters.get('company_id'):
        conversations = conversations.filter(company_id=filters['company_id'])

    messages = Message.objects.filter(
        conversation__in=conversations,
        body__icontains=query,
        deleted_at__isnull=True,
    ).select_related('conversation', 'sender_user').order_by('-created_at')

    if filters.get('date_from'):
        messages = messages.filter(created_at__gte=filters['date_from'])
    if filters.get('date_to'):
        messages = messages.filter(created_at__lte=filters['date_to'])

    return messages


def audit_conversations(user, filters=None):
    if not user_can_manage_chat(user):
        return Conversation.objects.none()

    filters = filters or {}
    qs = filter_queryset_by_user_companies(Conversation.objects.all(), user)

    if filters.get('company_id'):
        qs = qs.filter(company_id=filters['company_id'])

    if filters.get('employee_id'):
        qs = qs.filter(
            participants__employee_id=filters['employee_id'],
            participants__left_at__isnull=True,
        ).distinct()

    if filters.get('q'):
        qs = qs.filter(_audit_search_q(filters['q'])).distinct()

    if filters.get('date_from'):
        qs = qs.filter(last_message_at__gte=_audit_filter_datetime_start(filters['date_from']))
    if filters.get('date_to'):
        qs = qs.filter(last_message_at__lte=_audit_filter_datetime_end(filters['date_to']))

    if filters.get('conversation_type'):
        qs = qs.filter(conversation_type=filters['conversation_type'])

    return qs.order_by('-last_message_at', '-created_at')


def _audit_filter_datetime_start(value):
    from datetime import datetime, time
    from django.utils.dateparse import parse_date, parse_datetime

    parsed = parse_datetime(value)
    if parsed is not None:
        return parsed
    date_value = parse_date(value)
    if date_value is None:
        return value
    return timezone.make_aware(datetime.combine(date_value, time.min))


def _audit_filter_datetime_end(value):
    from datetime import datetime, time
    from django.utils.dateparse import parse_date, parse_datetime

    parsed = parse_datetime(value)
    if parsed is not None:
        return parsed
    date_value = parse_date(value)
    if date_value is None:
        return value
    return timezone.make_aware(datetime.combine(date_value, time.max))


def _audit_search_q(term):
    return (
        Q(title__icontains=term)
        | Q(messages__body__icontains=term)
        | Q(participants__user__username__icontains=term)
        | Q(participants__user__first_name__icontains=term)
        | Q(participants__user__last_name__icontains=term)
        | Q(participants__employee__first_name__icontains=term)
        | Q(participants__employee__last_name__icontains=term)
        | Q(participants__employee__employee_id__icontains=term)
    )


def audit_conversations_queryset(user, filters=None):
    """Alias for audit_conversations with annotations for list/export."""
    qs = audit_conversations(user, filters)
    return qs.annotate(
        message_count=Count('messages', distinct=True),
        attachment_count=Count('messages__attachments', distinct=True),
        active_participant_count=Count(
            'participants',
            filter=Q(participants__left_at__isnull=True),
            distinct=True,
        ),
    )


def audit_conversation_attachment_flags(conversation):
    types = set(
        MessageAttachment.objects.filter(message__conversation=conversation)
        .values_list('attachment_type', flat=True)
        .distinct()
    )
    return {
        'has_image': 'image' in types,
        'has_gif': 'gif' in types,
        'has_voice': 'voice' in types,
    }


def audit_conversation_title(conversation):
    if conversation.title:
        return conversation.title
    return conversation.get_conversation_type_display()


def audit_participant_labels(conversation):
    labels = []
    for participant in conversation.participants.filter(left_at__isnull=True).select_related('user', 'employee'):
        if participant.employee_id:
            labels.append(str(participant.employee))
        else:
            labels.append(participant.user.get_full_name().strip() or participant.user.username)
    return labels


def audit_conversation_list_rows(user, conversations_qs):
    rows = []
    for conversation in conversations_qs.select_related('company'):
        last_message = (
            conversation.messages
            .select_related('sender_user')
            .prefetch_related('attachments')
            .order_by('-created_at')
            .first()
        )
        preview = message_preview_text(last_message, user) if last_message else ''
        flags = audit_conversation_attachment_flags(conversation)
        rows.append({
            'conversation': conversation,
            'title': audit_conversation_title(conversation),
            'preview': preview,
            'last_at': conversation.last_message_at or conversation.created_at,
            'participant_count': getattr(
                conversation, 'active_participant_count', None,
            ) or conversation.participants.filter(left_at__isnull=True).count(),
            'message_count': getattr(conversation, 'message_count', None) or conversation.messages.count(),
            'attachment_count': getattr(conversation, 'attachment_count', None) or MessageAttachment.objects.filter(
                message__conversation=conversation,
            ).count(),
            'participants_label': ', '.join(audit_participant_labels(conversation)),
            'avatar': resolve_conversation_avatar_for_audit(conversation, user),
            **flags,
        })
    return rows


def resolve_conversation_avatar_for_audit(conversation, user):
    from accounts.avatars import resolve_conversation_avatar
    return resolve_conversation_avatar(conversation, user, title=audit_conversation_title(conversation))


def _employee_reference_user(conversation):
    participant = (
        conversation.participants
        .filter(left_at__isnull=True, employee__isnull=False)
        .select_related('user')
        .first()
    )
    return participant.user if participant else None


def employee_visible_sender_display(message):
    employee_user = _employee_reference_user(message.conversation)
    if employee_user is None:
        return _user_display_name(message.sender_user)
    return _sender_display_for_viewer(message, employee_user)


def _real_sender_label(user):
    name = _user_display_name(user)
    username = user.username
    if name and name != username:
        return f'{name} ({username})'
    return username


def serialize_audit_message(message, auditor_user):
    from accounts.avatars import avatar_for_user_profile

    real_display = _real_sender_label(message.sender_user)
    employee_display = employee_visible_sender_display(message)
    persona_masked = employee_display != _user_display_name(message.sender_user)

    body = message.body
    if message.deleted_at:
        body_display = body
        deleted_note = 'Deleted'
    else:
        body_display = body
        deleted_note = ''

    return {
        'id': message.pk,
        'body': body_display,
        'created_at': message.created_at.isoformat(),
        'time_display': timezone.localtime(message.created_at).strftime('%b %d, %Y %I:%M %p'),
        'sender_real_display': real_display,
        'sender_employee_display': employee_display,
        'sender_persona_masked': persona_masked,
        'sender_user_id': message.sender_user_id,
        'is_deleted': bool(message.deleted_at),
        'deleted_note': deleted_note,
        'attachments': _serialize_attachments(message, auditor_user),
        'sender_avatar': avatar_for_user_profile(message.sender_user),
    }


def enrich_audit_messages(messages_qs, auditor_user):
    return [serialize_audit_message(message, auditor_user) for message in messages_qs]


def audit_export_rows(user, filters=None):
    rows = []
    for conversation in audit_conversations_queryset(user, filters).select_related('company'):
        rows.append({
            'conversation_id': conversation.pk,
            'company': conversation.company.name,
            'type': conversation.get_conversation_type_display(),
            'title': audit_conversation_title(conversation),
            'participants': '; '.join(audit_participant_labels(conversation)),
            'last_message_at': conversation.last_message_at,
            'message_count': conversation.message_count,
            'attachment_count': conversation.attachment_count,
            'is_archived': conversation.is_archived,
        })
    return rows


def _serialize_attachments(message, viewer_user):
    is_manager = user_can_manage_chat(viewer_user)
    if message.deleted_at and not is_manager:
        return []

    from django.urls import reverse

    items = []
    for attachment in message.attachments.all():
        items.append({
            'id': attachment.pk,
            'url': reverse('messaging:attachment_view', args=[attachment.pk]),
            'attachment_type': attachment.attachment_type,
            'original_filename': attachment.original_filename,
            'content_type': attachment.content_type,
        })
    return items


def message_preview_text(message, viewer_user) -> str:
    data = serialize_message_for_user(message, viewer_user)
    body = (data.get('body') or '').strip()
    attachments = data.get('attachments') or []
    if attachments and not body:
        attachment_type = attachments[0]['attachment_type']
        if attachment_type == 'gif':
            return 'GIF'
        if attachment_type == 'voice':
            return 'Voice message'
        return 'Photo'
    if body:
        return body[:80]
    return ''


def serialize_message_for_user(message, viewer_user, *, include_sender_id=None):
    conversation = message.conversation
    is_manager = user_can_manage_chat(viewer_user)

    if message.deleted_at and not is_manager:
        body = '[Message removed]'
    else:
        body = message.body

    sender_display = _sender_display_for_viewer(message, viewer_user)

    data = {
        'id': message.pk,
        'body': body,
        'sender_display': sender_display,
        'created_at': message.created_at.isoformat(),
        'is_deleted': bool(message.deleted_at),
        'attachments': _serialize_attachments(message, viewer_user),
    }

    if include_sender_id is None:
        include_sender_id = is_manager
    if include_sender_id:
        data['sender_user_id'] = message.sender_user_id

    return data


def _sender_display_for_viewer(message, viewer_user):
    conversation = message.conversation
    if (
        conversation.conversation_type == TYPE_ADMIN_SUPPORT
        and user_can_use_employee_chat(viewer_user)
        and not user_can_manage_chat(viewer_user)
        and message.sender_user_id != viewer_user.pk
    ):
        return get_support_display_name(conversation.company)
    return _user_display_name(message.sender_user)
