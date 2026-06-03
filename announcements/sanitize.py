"""
HTML sanitisation for announcement rich-text bodies.

Announcements are authored by trusted HR/admin users via the Quill editor, but
we still sanitise the stored HTML to a safe allow-list so the content can be
rendered with |safe in the portal and management views without XSS risk.
"""
import nh3

# Tags Quill can emit that we keep.
_ALLOWED_TAGS = {
    'p', 'br', 'span', 'div',
    'strong', 'b', 'em', 'i', 'u', 's', 'sub', 'sup',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'blockquote', 'pre', 'code',
    'ul', 'ol', 'li',
    'a', 'img',
    'hr',
}

# Attributes kept per tag. class/style let Quill formatting (align, color,
# font, size, indent) survive; style values are CSS-sanitised by nh3.
_ALLOWED_ATTRS = {
    '*': {'class', 'style'},
    'a': {'href', 'title', 'target', 'class', 'style'},
    'img': {'src', 'alt', 'width', 'height', 'class', 'style'},
}

# Only safe URL schemes for links/images.
_ALLOWED_SCHEMES = {'http', 'https', 'mailto', 'tel'}


def clean_announcement_html(html: str) -> str:
    """Return a sanitised copy of *html* safe to render unescaped."""
    if not html:
        return ''
    return nh3.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        url_schemes=_ALLOWED_SCHEMES,
        link_rel='noopener noreferrer nofollow',
    )
