from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import Task


def load():
    if not Task.objects.exists():
        create_tasks()
    # Tasks without a department take their assignee's.
    for task in Task.objects.filter(department=None, assignee__department__isnull=False).select_related('assignee'):
        task.department = task.assignee.department
        task.save(update_fields=['department'])


def create_tasks():
    users = {u.username: u for u in get_user_model().objects.all()}
    today = timezone.localdate()
    # (title, assignee, status, priority, starts in N days, due in N days)
    rows = [
        ('Quarterly stock count', 'alice', Task.Status.IN_PROGRESS, Task.Priority.HIGH, -5, 2),
        ('Repair conveyor belt #2', 'carla', Task.Status.TODO, Task.Priority.HIGH, -4, -1),
        ('Reorganise aisle B shelving', 'bob', Task.Status.TODO, Task.Priority.NORMAL, 3, 10),
        ('Onboard new warehouse staff', 'alice', Task.Status.TODO, Task.Priority.LOW, 8, 21),
        ('Replace forklift battery', 'carla', Task.Status.DONE, Task.Priority.NORMAL, -9, -3),
    ]
    for title, who, status, priority, start_in, due_in in rows:
        Task.objects.create(
            title=title, assignee=users.get(who), created_by=users.get('admin'),
            status=status, priority=priority,
            start_date=today + timedelta(days=start_in), due_date=today + timedelta(days=due_in),
        )
