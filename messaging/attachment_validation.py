from django.core.exceptions import ValidationError

from .constants import (
    ATTACHMENT_TYPE_GIF,
    ATTACHMENT_TYPE_IMAGE,
    ATTACHMENT_TYPE_VOICE,
)

ALLOWED_IMAGE_TYPES = {
    'image/jpeg',
    'image/png',
    'image/webp',
    'image/gif',
}
ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}

ALLOWED_VOICE_TYPES = {
    'audio/webm',
    'audio/mpeg',
    'audio/mp3',
    'audio/mp4',
    'audio/x-m4a',
    'audio/wav',
    'audio/x-wav',
    'audio/ogg',
    'application/ogg',
    'video/webm',
}
ALLOWED_VOICE_EXTENSIONS = {'.webm', '.mp3', '.m4a', '.wav', '.ogg'}

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


def is_voice_attachment(uploaded_file) -> bool:
    content_type = (getattr(uploaded_file, 'content_type', '') or '').lower()
    name = (getattr(uploaded_file, 'name', '') or '').lower()
    if content_type in ALLOWED_VOICE_TYPES:
        return True
    return bool(name and any(name.endswith(ext) for ext in ALLOWED_VOICE_EXTENSIONS))


def is_image_attachment(uploaded_file) -> bool:
    content_type = (getattr(uploaded_file, 'content_type', '') or '').lower()
    name = (getattr(uploaded_file, 'name', '') or '').lower()
    if content_type in ALLOWED_IMAGE_TYPES:
        return True
    return bool(name and any(name.endswith(ext) for ext in ALLOWED_IMAGE_EXTENSIONS))


def attachment_type_for_file(uploaded_file) -> str:
    if is_voice_attachment(uploaded_file):
        return ATTACHMENT_TYPE_VOICE
    name = (getattr(uploaded_file, 'name', '') or '').lower()
    content_type = (getattr(uploaded_file, 'content_type', '') or '').lower()
    if content_type == 'image/gif' or name.endswith('.gif'):
        return ATTACHMENT_TYPE_GIF
    return ATTACHMENT_TYPE_IMAGE


def _validate_size(uploaded_file):
    size = getattr(uploaded_file, 'size', 0) or 0
    if size > MAX_ATTACHMENT_BYTES:
        raise ValidationError('Attachment must be 10 MB or smaller.')


def validate_voice_attachment(uploaded_file):
    if uploaded_file is None:
        raise ValidationError('No attachment provided.')
    if not is_voice_attachment(uploaded_file):
        raise ValidationError('Voice attachment must be a WebM, MP3, M4A, WAV, or OGG audio file.')
    _validate_size(uploaded_file)


def validate_image_attachment(uploaded_file):
    if uploaded_file is None:
        raise ValidationError('No attachment provided.')
    if not is_image_attachment(uploaded_file):
        raise ValidationError('Attachment must be a JPG, PNG, WebP, or GIF image.')
    _validate_size(uploaded_file)


def validate_message_attachment(uploaded_file):
    if uploaded_file is None:
        raise ValidationError('No attachment provided.')
    if is_voice_attachment(uploaded_file):
        validate_voice_attachment(uploaded_file)
    elif is_image_attachment(uploaded_file):
        validate_image_attachment(uploaded_file)
    else:
        raise ValidationError(
            'Unsupported attachment. Use an image (JPG, PNG, WebP, GIF) '
            'or voice audio (WebM, MP3, M4A, WAV, OGG).'
        )
