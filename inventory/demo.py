from core.trees import get_or_create_path

from .models import Attribute, Category, Part, PartAttributeValue

CATEGORY_ATTRIBUTES = {
    'Hardware > Fasteners': [('material', 'steel'), ('thread', 'M6'), ('manufacturer', 'Bossard')],
    'Hardware > Bearings': [('material', 'chrome steel'), ('bore', '20mm'), ('manufacturer', 'SKF')],
    'Electrical > Connectors': [('pins', '25'), ('manufacturer', 'Amphenol')],
    'Electrical > Contacts': [('wire size', '24-20 AWG'), ('plating', 'gold')],
    'Spare parts': [],
    'Safety': [('size', 'L')],
}

# (part number, description, category, unit, attributes); stock is in the Stock module's demo.
PARTS = [
    ('BLT-M8', 'M8 hex bolt', 'Hardware > Fasteners', 'pcs', {'material': 'steel', 'thread': 'M8'}),
    ('NUT-M8', 'M8 nut', 'Hardware > Fasteners', 'pcs', {'material': 'steel', 'thread': 'M8'}),
    ('608ZZ', 'Deep groove ball bearing', 'Hardware > Bearings', 'pcs', {'bore': '8mm', 'manufacturer': 'SKF'}),
    ('DB25-M', 'D-sub 25 plug', 'Electrical > Connectors', 'pcs', {'pins': '25'}),
    ('DB25-F', 'D-sub 25 socket', 'Electrical > Connectors', 'pcs', {'pins': '25'}),
    ('DS-PIN-C', 'D-sub crimp contact, pin', 'Electrical > Contacts', 'pcs', {'wire size': '24-20 AWG'}),
    ('DS-SKT-C', 'D-sub crimp contact, socket', 'Electrical > Contacts', 'pcs', {'wire size': '24-20 AWG'}),
    ('BELT-C2', 'Conveyor belt 2m', 'Spare parts', 'pcs', {}),
    ('BAT-FL48', 'Forklift battery 48V', 'Spare parts', 'pcs', {}),
    ('GLV-L', 'Work gloves', 'Safety', 'pair', {'size': 'L'}),
]


def load():
    """Additive: creates what's missing and fills blanks on existing demo parts."""
    for path, attrs in CATEGORY_ATTRIBUTES.items():
        category = get_or_create_path(Category, path)
        for name, typical in attrs:
            Attribute.objects.get_or_create(category=category, name=name, defaults={'default_value': typical})

    for number, name, cat, unit, values in PARTS:
        category = get_or_create_path(Category, cat)
        part, created = Part.objects.get_or_create(part_number=number, defaults={'name': name, 'category': category, 'unit': unit})
        if not created and (part.category is None or part.category.name == category.name):
            part.category = category
            part.save()
        for attr_name, value in values.items():
            PartAttributeValue.objects.get_or_create(
                part=part, attribute=category.attributes.get(name=attr_name), defaults={'value': value},
            )

    # How they go together: the plug mates with the socket; each housing takes its crimp contacts,
    # which are crimped with the D-sub crimp tool.
    parts = {p.part_number: p for p in Part.objects.filter(part_number__in=[row[0] for row in PARTS])}
    if 'DB25-M' in parts and 'DB25-F' in parts:
        parts['DB25-M'].mates_with.add(parts['DB25-F'])
    for housing, contact in (('DB25-M', 'DS-PIN-C'), ('DB25-F', 'DS-SKT-C')):
        if housing in parts and contact in parts:
            parts[housing].fits.add(parts[contact])
    from django.apps import apps
    if apps.is_installed('tools'):
        from tools.models import Tool
        crimp = Tool.objects.filter(name='D-sub crimp tool').first()
        insertion = Tool.objects.filter(name='D-sub insertion/extraction tool').first()
        for number in ('DS-PIN-C', 'DS-SKT-C'):
            if number in parts:
                parts[number].tools.add(*[t for t in (crimp, insertion) if t])
