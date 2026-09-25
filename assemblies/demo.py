from django.contrib.auth import get_user_model

from inventory.models import Part
from tasks.models import Task

from .models import Assembly, AssemblyComponent, TaskLink


def load():
    if Assembly.objects.exists():
        return
    parts = {p.part_number: p for p in Part.objects.all()}

    def bom(assembly, *lines):
        for item, qty in lines:
            if isinstance(item, Assembly):
                AssemblyComponent.objects.create(assembly=assembly, child_assembly=item, quantity=qty)
            elif item in parts:
                AssemblyComponent.objects.create(assembly=assembly, part=parts[item], quantity=qty)

    cable = Assembly.objects.create(
        name='Sensor cable', assembly_type=Assembly.Type.HARNESS, status=Assembly.Status.COMPLETED,
        build_instructions='Crimp and solder the D-sub 25 plug and socket, 1:1 pinout.',
    )
    bom(cable, ('DB25-M', 1), ('DB25-F', 1))

    roller = Assembly.objects.create(
        name='Idler roller', assembly_type=Assembly.Type.GENERIC,
        build_instructions='Press both bearings into the roller, then fit the axle bolt and nut.',
    )
    bom(roller, ('608ZZ', 2), ('BLT-M8', 1), ('NUT-M8', 1))

    conveyor = Assembly.objects.create(
        name='Conveyor section', assembly_type=Assembly.Type.GENERIC, version='2',
        build_instructions='Mount the rollers on the frame, fit the belt, then connect the sensor cable.',
        usage_instructions='Check belt tension weekly.',
    )
    bom(conveyor, (roller, 6), (cable, 1), ('BELT-C2', 1), ('BLT-M8', 12), ('NUT-M8', 12))

    admin = get_user_model().objects.filter(username='admin').first()
    task = Task.objects.filter(title__startswith='Repair conveyor').first()
    if task:
        TaskLink.objects.create(task=task, assembly=conveyor)
    elif admin:
        task = Task.objects.create(title=f'Build {conveyor}', created_by=admin)
        TaskLink.objects.create(task=task, assembly=conveyor)
