from django.core.exceptions import ValidationError

ALLOWED_ATTACHMENT_TYPES = {
    'image/jpeg',
    'image/png',
    'image/webp',
    'image/gif',
}
ALLOWED_ATTACHMENT_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024

ATTACHMENT_TYPE_IMAGE = 'image'
ATTACHMENT_TYPE_GIF = 'gif'


def attachment_type_for_file(uploaded_file) -> str:
    content_type = (getattr(uploaded_file, 'content_type', '') or '').lower()
    name = (getattr(uploaded_file, 'name', '') or '').lower()
    if content_type == 'image/gif' or name.endswith('.gif'):
        return ATTACHMENT_TYPE_GIF
    return ATTACHMENT_TYPE_IMAGE


def validate_message_attachment(uploaded_file):
    if uploaded_file is None:
        raise ValidationError('No attachment provided.')

    content_type = (getattr(uploaded_file, 'content_type', '') or '').lower()
    if content_type and content_type not in ALLOWED_ATTACHMENT_TYPES:
        raise ValidationError('Attachment must be a JPG, PNG, WebP, or GIF image.')

    name = (getattr(uploaded_file, 'name', '') or '').lower()
    if name and not any(name.endswith(ext) for ext in ALLOWED_ATTACHMENT_EXTENSIONS):
        raise ValidationError('Attachment must be a JPG, PNG, WebP, or GIF image.')

    size = getattr(uploaded_file, 'size', 0) or 0
    if size > MAX_ATTACHMENT_BYTES:
        raise ValidationError('Attachment must be 10 MB or smaller.')
