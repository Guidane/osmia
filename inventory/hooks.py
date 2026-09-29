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


# -- Automations: "A part runs low on stock" and "Issue / receive stock" ---------------

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError

from core import automation
from core.automation import Field, Param

automation.event('inventory.stock_low', 'A part runs low on stock', fields=[
    Field('part_number', 'Part number', lambda p: p.part_number),
    Field('name', 'Name', lambda p: p.name),
    Field('quantity_on_hand', 'On hand', lambda p: p.quantity_on_hand, kind='number'),
])


@automation.action('inventory.stock_move', 'Issue / receive stock', params=[
    Param('part', 'Part', 'part', required=True),
    Param('direction', 'Direction', 'select', required=True, choices=(('in', 'Receive into stock'), ('out', 'Issue from stock'))),
    Param('quantity', 'Quantity', 'number', required=True),
    Param('note', 'Note', 'text', help='Use {object} or {source} to name the record, e.g. "Spares for {source}".'),
])
def stock_move(ctx, params):
    part = Part.objects.filter(pk=params.get('part') or None).first()
    if part is None:
        raise ValidationError('The part this rule moves no longer exists.')
    try:
        quantity = Decimal(str(params.get('quantity')))
    except (InvalidOperation, TypeError):
        raise ValidationError('Quantity must be a number.')
    if quantity <= 0:
        raise ValidationError('Quantity must be more than 0.')
    issue = params.get('direction') == 'out'
    # A task that triggered the rule gets the materials booked against it.
    task = ctx.get('object') if getattr(ctx.get('object'), '_meta', None) and ctx['object']._meta.label == 'tasks.Task' else None
    StockMove.record(
        part, StockMove.Type.OUT if issue else StockMove.Type.IN, -quantity if issue else quantity,
        note=automation.render(params.get('note') or f'By rule "{getattr(ctx.get("rule"), "name", "")}"', ctx)[:255],
        task=task,
    )
    return f'{"Issued" if issue else "Received"} {quantity:g} {part.unit} {part.part_number}'
