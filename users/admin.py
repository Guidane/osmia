from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = BaseUserAdmin.fieldsets + (
        ('Work', {'fields': ('job_title', 'department', 'phone')}),
    )
    list_display = ('username', 'first_name', 'last_name', 'email', 'department', 'is_staff', 'is_active')
    list_filter = BaseUserAdmin.list_filter + ('department',)
