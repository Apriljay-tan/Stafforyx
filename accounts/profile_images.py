from django.core.exceptions import ValidationError

ALLOWED_PROFILE_IMAGE_TYPES = {
    'image/jpeg',
    'image/png',
    'image/webp',
}
ALLOWED_PROFILE_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
MAX_PROFILE_PHOTO_BYTES = 5 * 1024 * 1024


def validate_profile_image(uploaded_file):
    if uploaded_file is None:
        return

    content_type = getattr(uploaded_file, 'content_type', '') or ''
    if content_type and content_type not in ALLOWED_PROFILE_IMAGE_TYPES:
        raise ValidationError('Profile photo must be a JPG, PNG, or WebP image.')

    name = (getattr(uploaded_file, 'name', '') or '').lower()
    if name and not any(name.endswith(ext) for ext in ALLOWED_PROFILE_IMAGE_EXTENSIONS):
        raise ValidationError('Profile photo must be a JPG, PNG, or WebP image.')

    size = getattr(uploaded_file, 'size', 0) or 0
    if size > MAX_PROFILE_PHOTO_BYTES:
        raise ValidationError('Profile photo must be 5 MB or smaller.')
