from django import forms

from core.trees import TreeNodeForm
from users.models import Department

from .models import Budget


class BudgetForm(TreeNodeForm):
    class Meta:
        model = Budget
        fields = ['name', 'budget_number', 'amount', 'parent', 'department']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['department'].queryset = Department.objects.select_related('parent__parent')
        self.fields['parent'].label = 'Parent budget'


class TaskBudgetForm(forms.Form):
    """A task's budget must belong to the task's department (as in Waggle V3)."""

    budget = forms.ModelChoiceField(Budget.objects.none(), required=False, empty_label='(none)')

    def __init__(self, *args, task, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Budget.objects.filter(department=task.department) if task.department_id else Budget.objects.none()
        self.fields['budget'].queryset = qs.select_related('parent__parent')
