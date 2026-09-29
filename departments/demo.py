from core.trees import get_or_create_path

from .models import Department

# As in Waggle V3, plus a Field Service team.
DEPARTMENTS = [
    'Operations > Warehouse', 'Operations > Logistics', 'Operations > Field Service',
    'Engineering > R&D', 'Engineering > QA', 'Marketing',
]


def load():
    for path in DEPARTMENTS:
        get_or_create_path(Department, path)
