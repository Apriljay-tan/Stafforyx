from django.contrib.auth.models import User
from django.db import models

from companies.models import Company
from employees.models import Employee

from .constants import (
    CONVERSATION_TYPE_CHOICES,
    MAX_MESSAGE_BODY_LENGTH,
    PARTICIPANT_ROLE_CHOICES,
    TYPE_GROUP,
)


class Conversation(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='conversations')
    conversation_type = models.CharField(max_length=20, choices=CONVERSATION_TYPE_CHOICES)
    title = models.CharField(max_length=150, blank=True, default='')
    group_avatar = models.ImageField(
        upload_to='messaging/group_avatars/',
        blank=True,
        null=True,
        help_text='Optional logo for official group conversations.',
    )
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='created_conversations')
    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='archived_conversations',
    )
    last_message_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-last_message_at', '-created_at']
        indexes = [
            models.Index(fields=['company', '-last_message_at']),
            models.Index(fields=['conversation_type', 'company']),
        ]

    def __str__(self):
        return self.title or f'{self.get_conversation_type_display()} #{self.pk}'

    def get_group_avatar_initial(self):
        if self.conversation_type != TYPE_GROUP:
            return ''
        title = (self.title or '').strip()
        if not title:
            return 'G'
        return title[0].upper()


class ConversationParticipant(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='participants')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversation_participations')
    employee = models.ForeignKey(Employee, null=True, blank=True, on_delete=models.SET_NULL)
    role = models.CharField(max_length=20, choices=PARTICIPANT_ROLE_CHOICES, default='member')
    joined_at = models.DateTimeField(auto_now_add=True)
    left_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [('conversation', 'user')]
        indexes = [models.Index(fields=['user', 'left_at'])]

    @property
    def is_active(self):
        return self.left_at is None


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    sender_user = models.ForeignKey(User, on_delete=models.PROTECT, related_name='sent_messages')
    body = models.TextField(max_length=MAX_MESSAGE_BODY_LENGTH)
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='deleted_messages',
    )

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
        ]

    def __str__(self):
        return f'Message {self.pk} in conversation {self.conversation_id}'


class ConversationReadState(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='read_states')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversation_read_states')
    last_read_at = models.DateTimeField()

    class Meta:
        unique_together = [('conversation', 'user')]
