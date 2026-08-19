from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
import datetime

from companies.models import Company
from employees.models import Employee
from messaging.constants import TYPE_ADMIN_SUPPORT, TYPE_DIRECT
from messaging.models import Conversation, ConversationParticipant, Message, ConversationReadState


class MessagingModelTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Acme', email='a@acme.test')
        self.admin = User.objects.create_user('admin1', password='x')
        self.employee_user = User.objects.create_user('emp1', password='x')
        self.employee = Employee.objects.create(
            company=self.company,
            employee_id='E001',
            first_name='Ana',
            last_name='Reyes',
            email='ana@acme.test',
            date_hired=datetime.date(2024, 1, 1),
            user=self.employee_user,
        )

    def test_create_admin_support_conversation(self):
        conv = Conversation.objects.create(
            company=self.company,
            conversation_type=TYPE_ADMIN_SUPPORT,
            created_by=self.admin,
        )
        ConversationParticipant.objects.create(
            conversation=conv,
            user=self.employee_user,
            employee=self.employee,
        )
        ConversationParticipant.objects.create(
            conversation=conv,
            user=self.admin,
            role='admin',
        )
        msg = Message.objects.create(
            conversation=conv,
            sender_user=self.admin,
            body='Hello',
        )
        self.assertEqual(msg.sender_user, self.admin)
        self.assertIsNone(msg.deleted_at)

    def test_read_state_unique(self):
        conv = Conversation.objects.create(
            company=self.company,
            conversation_type=TYPE_DIRECT,
            created_by=self.admin,
        )
        ConversationReadState.objects.create(
            conversation=conv,
            user=self.admin,
            last_read_at=timezone.now(),
        )
        self.assertEqual(ConversationReadState.objects.filter(conversation=conv, user=self.admin).count(), 1)
