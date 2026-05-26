from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from accounts.company_access import filter_queryset_by_user_companies, user_can_access_company
from companies.models import Company
from employees.models import Department

from .forms import AnnouncementForm
from .models import Announcement


def announcement_list(request):
    announcements = filter_queryset_by_user_companies(
        Announcement.objects.select_related('company', 'target_department', 'posted_by'),
        request.user,
    )

    company_id = request.GET.get('company', '')
    if company_id:
        announcements = announcements.filter(company_id=company_id)

    department_id = request.GET.get('department', '')
    if department_id:
        announcements = announcements.filter(target_department_id=department_id)

    active = request.GET.get('active', '')
    if active == 'active':
        announcements = announcements.filter(is_active=True)
    elif active == 'inactive':
        announcements = announcements.filter(is_active=False)

    date = request.GET.get('date', '')
    if date:
        announcements = announcements.filter(created_at__date=date)

    context = {
        'announcements': announcements,
        'companies': filter_queryset_by_user_companies(Company.objects.all(), request.user),
        'departments': filter_queryset_by_user_companies(
            Department.objects.all(), request.user
        ).select_related('company'),
        'company_filter': company_id,
        'department_filter': department_id,
        'active_filter': active,
        'date_filter': date,
    }
    return render(request, 'announcements/announcement_list.html', context)


def announcement_detail(request, pk):
    announcement = get_object_or_404(
        Announcement.objects.select_related('company', 'target_department', 'posted_by'),
        pk=pk,
    )
    if not user_can_access_company(request.user, announcement.company):
        raise PermissionDenied
    return render(request, 'announcements/announcement_detail.html', {
        'announcement': announcement,
    })


def announcement_add(request):
    form = AnnouncementForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        announcement = form.save(commit=False)
        if request.user.is_authenticated:
            announcement.posted_by = request.user
        announcement.save()
        messages.success(request, 'Announcement added successfully.')
        return redirect('announcements:announcement_detail', pk=announcement.pk)
    return render(request, 'announcements/announcement_form.html', {
        'form': form,
        'action': 'Add',
    })


def announcement_edit(request, pk):
    announcement = get_object_or_404(
        Announcement.objects.select_related('company', 'target_department', 'posted_by'),
        pk=pk,
    )
    if not user_can_access_company(request.user, announcement.company):
        raise PermissionDenied
    form = AnnouncementForm(request.POST or None, instance=announcement)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Announcement updated successfully.')
        return redirect('announcements:announcement_detail', pk=announcement.pk)
    return render(request, 'announcements/announcement_form.html', {
        'form': form,
        'announcement': announcement,
        'action': 'Edit',
    })


def announcement_delete(request, pk):
    announcement = get_object_or_404(
        Announcement.objects.select_related('company'), pk=pk
    )
    if not user_can_access_company(request.user, announcement.company):
        raise PermissionDenied
    if request.method == 'POST':
        title = announcement.title
        announcement.delete()
        messages.success(request, f'Announcement "{title}" has been deleted.')
        return redirect('announcements:announcement_list')
    return render(request, 'announcements/announcement_confirm_delete.html', {
        'announcement': announcement,
    })
