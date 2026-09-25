from django.contrib.auth.models import AbstractUser
from django.db import models
from django.urls import reverse

from core.trees import TreeNode


class Department(TreeNode):
    """An organisational unit, nested, e.g. ``Operations > Warehouse``."""

    def get_absolute_url(self):
        return reverse('users:department_detail', args=[self.pk])

    def members(self, include_sub=False):
        ids = {self.pk, *self.descendant_ids()} if include_sub else {self.pk}
        return User.objects.filter(department_id__in=ids)


class User(AbstractUser):
    job_title = models.CharField(max_length=100, blank=True)
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL, related_name='users',
    )
    phone = models.CharField(max_length=30, blank=True)

    class Meta:
        ordering = ['first_name', 'last_name', 'username']

    def __str__(self):
        return self.get_full_name() or self.username

    def get_absolute_url(self):
        return reverse('users:detail', args=[self.pk])
