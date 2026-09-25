from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from core.trees import sorted_by_path
from tasks.models import Task

from .forms import BudgetForm, TaskBudgetForm
from .models import Budget, Spending, TaskBudget


class BudgetListView(LoginRequiredMixin, ListView):
    model = Budget
    template_name = 'budgets/budget_list.html'  # the queryset becomes a sorted list

    def get_queryset(self):
        qs = Budget.objects.select_related('parent__parent', 'department__parent')
        if self.request.GET.get('department'):
            qs = qs.filter(department_id=self.request.GET['department'])
        return Spending().annotate(sorted_by_path(qs))


class BudgetDetailView(LoginRequiredMixin, DetailView):
    model = Budget

    def get_context_data(self, **kwargs):
        b = self.object
        spending = Spending()
        children = spending.annotate(sorted_by_path(b.children.select_related('department')))
        allocated = sum((c.amount for c in children), Decimal(0))
        tasks = list(Task.objects.filter(budget_link__budget=b).select_related('assignee'))
        for t in tasks:
            t.costs = dict(spending.by_task[t.pk])
            t.cost_total = spending.task_total(t.pk)
        spending.annotate([b])
        return super().get_context_data(
            **kwargs,
            children=children,
            allocated=allocated,
            over_allocated=allocated > b.amount,
            tasks=tasks,
            own_spent=spending.own[b.pk],
        )


class BudgetCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    model = Budget
    form_class = BudgetForm
    permission_required = 'budgets.add_budget'
    template_name = 'core/form.html'
    extra_context = {'heading': 'New budget'}

    def get_initial(self):
        parent = Budget.objects.filter(pk=self.request.GET.get('parent') or None).first()
        return {'parent': parent, 'department': parent.department if parent else None}


class BudgetUpdateView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    model = Budget
    form_class = BudgetForm
    permission_required = 'budgets.change_budget'
    template_name = 'core/form.html'

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs, heading=f'Edit {self.object}', cancel_url=self.object.get_absolute_url())


@login_required
@require_POST
def link_task(request, task_pk):
    """Set or clear the budget a task is charged to (from the task page's panel)."""
    task = get_object_or_404(Task, pk=task_pk)
    form = TaskBudgetForm(request.POST, task=task)
    if not form.is_valid():
        messages.error(request, "That budget doesn't belong to the task's department.")
    elif form.cleaned_data['budget']:
        TaskBudget.objects.update_or_create(task=task, defaults={'budget': form.cleaned_data['budget']})
        messages.success(request, f"Task charged to {form.cleaned_data['budget']}.")
    else:
        TaskBudget.objects.filter(task=task).delete()
    return redirect(task)
