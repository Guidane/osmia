from django import forms
from django.contrib.auth.forms import UserCreationForm

from departments.models import Department

from .models import User

PROFILE_FIELDS = ['first_name', 'last_name', 'email', 'job_title', 'phone']


class DepartmentFieldMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['department'].queryset = Department.objects.select_related('parent__parent')


class UserCreateForm(DepartmentFieldMixin, UserCreationForm):
    class Meta:
        model = User
        fields = ['username', *PROFILE_FIELDS, 'department', 'is_staff']


class UserEditForm(DepartmentFieldMixin, forms.ModelForm):
    """For managers editing any user."""

    class Meta:
        model = User
        fields = ['username', *PROFILE_FIELDS, 'department', 'is_staff', 'is_active']


class ProfileForm(forms.ModelForm):
    """For users editing their own profile. Departments are assigned by managers."""

    class Meta:
        model = User
        fields = PROFILE_FIELDS
