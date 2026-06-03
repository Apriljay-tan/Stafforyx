import os

from django import forms

from .models import Announcement
from .sanitize import clean_announcement_html


def _bootstrap(form):
    for field in form.fields.values():
        widget = field.widget
        if isinstance(widget, forms.CheckboxInput):
            widget.attrs.setdefault('class', 'form-check-input')
        elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
            widget.attrs.setdefault('class', 'form-select')
        elif isinstance(widget, forms.ClearableFileInput):
            widget.attrs.setdefault('class', 'form-control')
        else:
            widget.attrs.setdefault('class', 'form-control')


ALLOWED_ATTACHMENT_EXTS = {'.pdf', '.doc', '.docx'}


class AnnouncementForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = ['company', 'title', 'content', 'attachment', 'target_department', 'is_active']
        widgets = {
            # Quill mounts over this textarea; it stays hidden and receives the HTML on submit.
            'content': forms.Textarea(attrs={'rows': 6, 'id': 'id_content'}),
            'attachment': forms.ClearableFileInput(attrs={'accept': '.pdf,.doc,.docx'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['content'].required = False
        self.fields['attachment'].required = False
        _bootstrap(self)

    def clean_content(self):
        return clean_announcement_html(self.cleaned_data.get('content', '') or '')

    def clean_attachment(self):
        f = self.cleaned_data.get('attachment')
        if f and hasattr(f, 'name'):
            ext = os.path.splitext(f.name)[1].lower()
            if ext not in ALLOWED_ATTACHMENT_EXTS:
                raise forms.ValidationError('Attachment must be a PDF or Word document (.pdf, .doc, .docx).')
        return f

    def clean(self):
        cleaned = super().clean()
        # Strip Quill's empty placeholder so a blank editor counts as empty.
        content = (cleaned.get('content') or '').strip()
        if content in ('<p><br></p>', '<p></p>', '<br>'):
            content = ''
            cleaned['content'] = ''
        if not content and not cleaned.get('attachment'):
            raise forms.ValidationError(
                'Add a message in the editor or attach a PDF/Word file (or both).'
            )
        return cleaned
