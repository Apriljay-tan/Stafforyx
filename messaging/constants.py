TYPE_DIRECT = 'direct'
TYPE_ADMIN_SUPPORT = 'admin_support'
TYPE_GROUP = 'group'

CONVERSATION_TYPE_CHOICES = [
    (TYPE_DIRECT, 'Direct'),
    (TYPE_ADMIN_SUPPORT, 'Admin Support'),
    (TYPE_GROUP, 'Group'),
]
CONVERSATION_TYPE_VALUES = [c[0] for c in CONVERSATION_TYPE_CHOICES]

ROLE_MEMBER = 'member'
ROLE_GROUP_CREATOR = 'group_creator'
ROLE_ADMIN = 'admin'

PARTICIPANT_ROLE_CHOICES = [
    (ROLE_MEMBER, 'Member'),
    (ROLE_GROUP_CREATOR, 'Group Creator'),
    (ROLE_ADMIN, 'Admin'),
]

MAX_MESSAGE_BODY_LENGTH = 5000
