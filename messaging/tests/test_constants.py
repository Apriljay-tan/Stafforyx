from django.test import SimpleTestCase

from messaging.constants import (
    TYPE_ADMIN_SUPPORT,
    TYPE_DIRECT,
    TYPE_GROUP,
    CONVERSATION_TYPE_VALUES,
    ROLE_ADMIN,
    ROLE_GROUP_CREATOR,
    ROLE_MEMBER,
)


class ConstantsTests(SimpleTestCase):
    def test_conversation_types(self):
        self.assertEqual(CONVERSATION_TYPE_VALUES, [TYPE_DIRECT, TYPE_ADMIN_SUPPORT, TYPE_GROUP])

    def test_roles_exist(self):
        self.assertEqual(ROLE_MEMBER, 'member')
        self.assertEqual(ROLE_GROUP_CREATOR, 'group_creator')
        self.assertEqual(ROLE_ADMIN, 'admin')
