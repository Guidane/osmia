from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from core import hooks

from .models import LogEntry


def history_panel(request, record):
    """The last few changes to a record, at the bottom of its page."""
    ct = ContentType.objects.get_for_model(record)
    entries = LogEntry.objects.filter(content_type=ct, object_id=record.pk).select_related('user')[:5]
    if not entries:
        return None
    return hooks.panel('History', 'audit/_history_panel.html', {
        'entries': entries, 'url': reverse('audit:history', args=[ct.pk, record.pk]),
    }, request, order=900)


for name in ('user_detail_panels', 'task_detail_panels', 'part_detail_panels', 'department_detail_panels',
             'assembly_detail_panels', 'device_detail_panels', 'order_detail_panels', 'budget_detail_panels'):
    hooks.register(name)(history_panel)


@hooks.register('dashboard_widgets')
def changes_today(request):
    from datetime import timedelta

    from django.utils import timezone
    count = LogEntry.objects.filter(created_at__gte=timezone.now() - timedelta(days=1)).count()
    return hooks.Widget('Changes in the last 24 h', count, reverse('audit:list'))
