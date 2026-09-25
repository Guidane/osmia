from core.trees import get_or_create_path

from .models import Department, User

# As in Waggle V3, plus a Field Service team.
DEPARTMENTS = [
    'Operations > Warehouse', 'Operations > Logistics', 'Operations > Field Service',
    'Engineering > R&D', 'Engineering > QA', 'Marketing',
]

PEOPLE = [
    ('alice', 'Alice', 'Martin', 'Operations Manager', 'Operations'),
    ('bob', 'Bob', 'Nguyen', 'Warehouse Lead', 'Operations > Warehouse'),
    ('carla', 'Carla', 'Rossi', 'Technician', 'Operations > Field Service'),
]


def load():
    """Additive: creates missing departments/users and fills blank departments."""
    for path in DEPARTMENTS:
        get_or_create_path(Department, path)
    if not User.objects.filter(username='admin').exists():
        User.objects.create_superuser('admin', 'admin@example.com', 'admin', first_name='Admin')
    for username, first, last, title, dept in PEOPLE:
        department = get_or_create_path(Department, dept)
        user = User.objects.filter(username=username).first()
        if user is None:
            User.objects.create_user(
                username, f'{username}@example.com', 'demo', first_name=first, last_name=last,
                job_title=title, department=department,
            )
        elif user.department is None:
            user.department = department
            user.save(update_fields=['department'])
