from django.contrib.auth import get_user_model

from core.trees import get_or_create_path
from tasks.models import Task

from .models import Attribute, Category, Location, Part, PartAttributeValue, StockMove


CATEGORY_ATTRIBUTES = {
    'Hardware > Fasteners': [('material', 'steel'), ('thread', 'M6'), ('manufacturer', 'Bossard')],
    'Hardware > Bearings': [('material', 'chrome steel'), ('bore', '20mm'), ('manufacturer', 'SKF')],
    'Electrical > Connectors': [('pins', '25'), ('manufacturer', 'Amphenol')],
    'Spare parts': [],
    'Safety': [('size', 'L')],
}

# (part number, description, category, location, unit, cost, reorder at, opening qty, attributes)
PARTS = [
    ('BLT-M8', 'M8 hex bolt', 'Hardware > Fasteners', 'Warehouse > Aisle 1 > Bin A1', 'pcs', '0.12', 200, 500,
     {'material': 'steel', 'thread': 'M8'}),
    ('NUT-M8', 'M8 nut', 'Hardware > Fasteners', 'Warehouse > Aisle 1 > Bin A1', 'pcs', '0.05', 200, 150,
     {'material': 'steel', 'thread': 'M8'}),
    ('608ZZ', 'Deep groove ball bearing', 'Hardware > Bearings', 'Warehouse > Aisle 1 > Shelf 3', 'pcs', '1.80', 10, 40,
     {'bore': '8mm', 'manufacturer': 'SKF'}),
    ('DB25-M', 'D-sub 25 plug', 'Electrical > Connectors', 'Warehouse > Aisle 2 > Drawer 4', 'pcs', '2.40', 10, 30,
     {'pins': '25'}),
    ('DB25-F', 'D-sub 25 socket', 'Electrical > Connectors', 'Warehouse > Aisle 2 > Drawer 4', 'pcs', '2.60', 10, 8,
     {'pins': '25'}),
    ('BELT-C2', 'Conveyor belt 2m', 'Spare parts', 'Warehouse > Cage', 'pcs', '89.00', 1, 3, {}),
    ('BAT-FL48', 'Forklift battery 48V', 'Spare parts', 'Warehouse > Cage', 'pcs', '1250.00', 1, 1, {}),
    ('GLV-L', 'Work gloves', 'Safety', 'Warehouse > Aisle 2 > Drawer 1', 'pair', '3.50', 20, 12, {'size': 'L'}),
]


def load():
    """Additive: creates what's missing and fills blanks on existing demo parts,
    without touching their stock."""
    first_run = not Part.objects.exists()
    for path, attrs in CATEGORY_ATTRIBUTES.items():
        category = get_or_create_path(Category, path)
        for name, typical in attrs:
            Attribute.objects.get_or_create(category=category, name=name, defaults={'default_value': typical})

    bob = get_user_model().objects.filter(username='bob').first()
    for number, name, cat, loc, unit, cost, reorder, qty, values in PARTS:
        category, location = get_or_create_path(Category, cat), get_or_create_path(Location, loc)
        part, created = Part.objects.get_or_create(part_number=number, defaults={
            'name': name, 'category': category, 'location': location, 'unit': unit, 'cost': cost,
            'reorder_level': reorder,
        })
        if not created:
            if part.location is None:
                part.location = location
            if part.category is None or part.category.name == category.name:
                part.category = category
            part.save()
        for attr_name, value in values.items():
            PartAttributeValue.objects.get_or_create(
                part=part, attribute=category.attributes.get(name=attr_name), defaults={'value': value},
            )
        if created:
            StockMove.record(part, StockMove.Type.IN, qty, user=bob, note='Opening stock')

    repair = Task.objects.filter(title__startswith='Repair conveyor').first()
    if first_run and repair:
        belt = Part.objects.get(part_number='BELT-C2')
        StockMove.record(belt, StockMove.Type.OUT, -1, user=repair.assignee, task=repair, note='Replacement belt')
