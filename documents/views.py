from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from companies.models import Company
from employees.models import Employee

from .forms import EmployeeDocumentForm
from .models import EmployeeDocument


def employee_document_list(request):
    documents = EmployeeDocument.objects.select_related(
        'company', 'employee', 'employee__department', 'uploaded_by'
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
        'employees': Employee.objects.all().order_by('last_name', 'first_name'),
        'companies': Company.objects.all(),
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


def employee_document_delete(request, pk):
    document = get_object_or_404(
        EmployeeDocument.objects.select_related('employee', 'company'),
        pk=pk,
    )
    if request.method == 'POST':
        title = document.title
        document.delete()
        messages.success(request, f'Document "{title}" has been deleted.')
        return redirect('documents:employee_document_list')
    return render(request, 'documents/employee_document_confirm_delete.html', {
        'document': document,
    })
