import mimetypes
import os

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render

from accounts.company_access import filter_queryset_by_user_companies, user_can_access_company
from companies.models import Company
from employees.models import Employee

from .forms import EmployeeDocumentForm
from .models import EmployeeDocument


def employee_document_list(request):
    documents = filter_queryset_by_user_companies(
        EmployeeDocument.objects.select_related(
            'company', 'employee', 'employee__department', 'uploaded_by'
        ),
        request.user,
    )

    employee_id = request.GET.get('employee', '')
    if employee_id:
        documents = documents.filter(employee_id=employee_id)

    document_type = request.GET.get('document_type', '')
    if document_type:
        documents = documents.filter(document_type=document_type)

    company_id = request.GET.get('company', '')
    if company_id:
        documents = documents.filter(company_id=company_id)

    expiration_date = request.GET.get('expiration_date', '')
    if expiration_date:
        documents = documents.filter(expiration_date=expiration_date)

    context = {
        'documents': documents,
        'employees': filter_queryset_by_user_companies(
            Employee.objects.all(), request.user
        ).order_by('last_name', 'first_name'),
        'companies': filter_queryset_by_user_companies(Company.objects.all(), request.user),
        'document_type_choices': EmployeeDocument.DOCUMENT_TYPE_CHOICES,
        'employee_filter': employee_id,
        'document_type_filter': document_type,
        'company_filter': company_id,
        'expiration_date_filter': expiration_date,
    }
    return render(request, 'documents/employee_document_list.html', context)


def employee_document_add(request):
    form = EmployeeDocumentForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        document = form.save(commit=False)
        if request.user.is_authenticated:
            document.uploaded_by = request.user
        document.save()
        messages.success(request, 'Employee document added successfully.')
        return redirect('documents:employee_document_list')
    return render(request, 'documents/employee_document_form.html', {
        'form': form,
        'action': 'Add',
    })


def employee_document_edit(request, pk):
    document = get_object_or_404(
        EmployeeDocument.objects.select_related('company', 'employee', 'uploaded_by'),
        pk=pk,
    )
    if not user_can_access_company(request.user, document.company):
        raise PermissionDenied
    form = EmployeeDocumentForm(request.POST or None, request.FILES or None, instance=document)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Employee document updated successfully.')
        return redirect('documents:employee_document_list')
    return render(request, 'documents/employee_document_form.html', {
        'form': form,
        'document': document,
        'action': 'Edit',
    })


def employee_document_download(request, pk):
    """Serve a document file through Django — only authenticated users with documents access."""
    document = get_object_or_404(EmployeeDocument.objects.select_related('company'), pk=pk)
    if not user_can_access_company(request.user, document.company):
        raise PermissionDenied
    if not document.file:
        raise Http404
    file_path = document.file.path
    if not os.path.exists(file_path):
        raise Http404
    content_type, _ = mimetypes.guess_type(file_path)
    content_type = content_type or 'application/octet-stream'
    return FileResponse(open(file_path, 'rb'), content_type=content_type,
                        as_attachment=False, filename=os.path.basename(file_path))


def employee_document_delete(request, pk):
    document = get_object_or_404(
        EmployeeDocument.objects.select_related('employee', 'company'),
        pk=pk,
    )
    if not user_can_access_company(request.user, document.company):
        raise PermissionDenied
    if request.method == 'POST':
        title = document.title
        document.delete()
        messages.success(request, f'Document "{title}" has been deleted.')
        return redirect('documents:employee_document_list')
    return render(request, 'documents/employee_document_confirm_delete.html', {
        'document': document,
    })
