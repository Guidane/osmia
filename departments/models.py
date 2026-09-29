from django.contrib.auth import get_user_model
from django.urls import reverse

from core.trees import TreeNode


class Department(TreeNode):
    """An organisational unit, nested, e.g. ``Operations > Warehouse``."""

    class Meta(TreeNode.Meta):
        # Moved here from the Users module; the table keeps its original name,
        # so existing departments and every link to them stay as they were.
        db_table = 'users_department'

    def get_absolute_url(self):
        return reverse('departments:detail', args=[self.pk])

    def members(self, include_sub=False):
        ids = {self.pk, *self.descendant_ids()} if include_sub else {self.pk}
        return get_user_model().objects.filter(department_id__in=ids)
