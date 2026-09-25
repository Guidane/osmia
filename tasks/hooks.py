from django.urls import reverse
from django.utils import timezone

from core import hooks

from .models import Task


@hooks.register('dashboard_widgets')
def my_open_tasks(request):
    count = Task.objects.filter(assignee=request.user).exclude(status=Task.Status.DONE).count()
    return hooks.Widget('My open tasks', count, reverse('tasks:mine'))


@hooks.register('dashboard_widgets')
def overdue_tasks(request):
    count = Task.objects.exclude(status=Task.Status.DONE).filter(due_date__lt=timezone.localdate()).count()
    return hooks.Widget('Overdue tasks', count, reverse('tasks:list'), tone='warn' if count else 'ok')


@hooks.register('user_detail_panels')
def user_tasks(request, user):
    tasks = user.assigned_tasks.exclude(status=Task.Status.DONE).select_related('assignee')
    return hooks.panel(
        'Open tasks', 'tasks/_user_panel.html', {'tasks': tasks, 'person': user}, request, order=10,
    )
