from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from core import hooks
from core.trees import sorted_by_path

from .forms import DepartmentForm, ProfileForm, UserCreateForm, UserEditForm
from .models import Department, User


class UserListView(LoginRequiredMixin, ListView):
    model = User
    paginate_by = 50

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs, departments=sorted_by_path(Department.objects.select_related('parent')))

    def get_queryset(self):
        qs = super().get_queryset().select_related('department__parent')
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
                | Q(email__icontains=q) | Q(department__name__icontains=q)
            )
        department = Department.objects.filter(pk=self.request.GET.get('department') or None).first()
        if department:
            qs = qs.filter(department_id__in={department.pk, *department.descendant_ids()})
        if self.request.GET.get('show') != 'all':
            qs = qs.filter(is_active=True)
        return qs


class UserDetailView(LoginRequiredMixin, DetailView):
    model = User
    context_object_name = 'person'  # `user` is the logged-in user in templates

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['panels'] = hooks.collect('user_detail_panels', self.request, self.object)
        ctx['can_edit'] = self.request.user.has_perm('users.change_user') or self.request.user == self.object
        return ctx


class UserCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    model = User
    form_class = UserCreateForm
    permission_required = 'users.add_user'
    template_name = 'core/form.html'
    extra_context = {'heading': 'New user'}

    def form_valid(self, form):
        messages.success(self.request, 'User created.')
        return super().form_valid(form)


class UserUpdateView(LoginRequiredMixin, UpdateView):
    model = User
    template_name = 'core/form.html'

    def get_form_class(self):
        if self.request.user.has_perm('users.change_user'):
            return UserEditForm
        if self.request.user == self.get_object():
            return ProfileForm
        raise PermissionDenied

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['heading'] = f'Edit {self.object}'
        ctx['cancel_url'] = self.object.get_absolute_url()
        return ctx

    def form_valid(self, form):
        messages.success(self.request, 'Saved.')
        return super().form_valid(form)


# -- Departments (nested) ------------------------------------------------------

class DepartmentListView(LoginRequiredMixin, ListView):
    model = Department
    template_name = 'users/department_list.html'  # the queryset becomes a sorted list

    def get_queryset(self):
        return sorted_by_path(
            Department.objects.select_related('parent').annotate(member_count=Count('users', distinct=True))
        )


class DepartmentDetailView(LoginRequiredMixin, DetailView):
    model = Department

    def get_context_data(self, **kwargs):
        d = self.object
        return super().get_context_data(
            **kwargs,
            members=d.members(include_sub=True).select_related('department__parent'),
            children=sorted_by_path(d.children.all()),
            panels=hooks.collect('department_detail_panels', self.request, d),
        )


class DepartmentCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    model = Department
    form_class = DepartmentForm
    permission_required = 'users.add_department'
    template_name = 'core/form.html'
    extra_context = {'heading': 'New department'}

    def get_initial(self):
        return {'parent': self.request.GET.get('parent')}


class DepartmentUpdateView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    model = Department
    form_class = DepartmentForm
    permission_required = 'users.change_department'
    template_name = 'core/form.html'

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs, heading=f'Edit {self.object}', cancel_url=self.object.get_absolute_url())
