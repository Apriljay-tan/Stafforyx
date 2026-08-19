from django.contrib import admin

from .models import Conversation, ConversationParticipant, ConversationReadState, Message


class ReadOnlyModelAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Conversation)
class ConversationAdmin(ReadOnlyModelAdmin):
    list_display = ('id', 'company', 'conversation_type', 'title', 'created_by', 'last_message_at', 'is_archived')


@admin.register(ConversationParticipant)
class ConversationParticipantAdmin(ReadOnlyModelAdmin):
    list_display = ('id', 'conversation', 'user', 'employee', 'role', 'joined_at', 'left_at')


@admin.register(Message)
class MessageAdmin(ReadOnlyModelAdmin):
    list_display = ('id', 'conversation', 'sender_user', 'created_at', 'deleted_at')


@admin.register(ConversationReadState)
class ConversationReadStateAdmin(ReadOnlyModelAdmin):
    list_display = ('id', 'conversation', 'user', 'last_read_at')
