from django.db.models import F
from django.urls import reverse

from core import hooks

from .models import Part, StockMove


@hooks.register('task_costs')
def material_costs(task_ids):
    return hooks.Costs('Materials', StockMove.material_cost_by_task(task_ids))


@hooks.register('dashboard_widgets')
def low_stock(request):
    count = Part.objects.filter(is_active=True, quantity_on_hand__lte=F('reorder_level')).count()
    return hooks.Widget('Low-stock parts', count, reverse('inventory:part_list') + '?low=1', tone='warn' if count else 'ok')


@hooks.register('task_detail_panels')
def task_materials(request, task):
    moves = task.stock_moves.select_related('part', 'user')
    return hooks.panel('Materials', 'inventory/_task_panel.html', {'moves': moves, 'task': task}, request)


@hooks.register('user_detail_panels')
def user_stock_moves(request, user):
    moves = user.stock_moves.select_related('part', 'task')[:10]
    if not moves:
        return None
    return hooks.panel('Recent stock moves', 'inventory/_moves_table.html', {'moves': moves}, request, order=20)
