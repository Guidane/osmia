from django.contrib.auth import get_user_model

from assemblies.models import Assembly, AssemblyComponent
from inventory.models import Part

from .models import Connector, Device, Pin


def _pins(connector, rows):
    """rows: (label, signal, set name)."""
    for i, (label, signal, set_name) in enumerate(rows, start=1):
        Pin.objects.create(connector=connector, position=i, label=label, signal=signal, set_name=set_name)


def load():
    if Device.objects.exists():
        return
    parts = {p.part_number: p for p in Part.objects.all()}
    users = {u.username: u for u in get_user_model().objects.all()}
    carla, bob = users.get('carla'), users.get('bob')

    # A unit we build: its assembly holds the BOM, the device its connectors.
    pdu_assembly = Assembly.objects.create(
        name='Power distribution unit', assembly_type=Assembly.Type.DEVICE,
        build_instructions='Fit both D-sub 25 sockets to the front panel and wire per the pinout.',
    )
    for number in ('DB25-F', 'BLT-M8', 'NUT-M8'):
        if number in parts:
            AssemblyComponent.objects.create(assembly=pdu_assembly, part=parts[number], quantity=2 if number == 'DB25-F' else 4)
    pdu = Device.objects.create(
        name='Power distribution unit', part_number='PDU-100', assembly=pdu_assembly,
        role=Device.Role.PRODUCT, color='#2e8b57', responsible=carla,
    )
    j01 = Connector.objects.create(device=pdu, designator='J01', side='left', position=1,
                                   part=parts.get('DB25-F'), description='Power in')
    _pins(j01, [('1', 'PWR', 'Set 1'), ('13', 'GND', 'Set 1'), ('2', 'PWR', 'Set 2'), ('14', 'GND', 'Set 2')])
    j02 = Connector.objects.create(device=pdu, designator='J02', side='right', position=2,
                                   part=parts.get('DB25-F'), description='Control bus')
    _pins(j02, [('1', 'CAN_H', 'CAN'), ('2', 'CAN_L', 'CAN'), ('3', 'GND', '')])
    pdu.snapshot()

    # Test equipment we build to test the units.
    tester = Device.objects.create(
        name='PDU test controller', part_number='TC-01', role=Device.Role.TEST_EQUIPMENT, color='#8a4fbf', responsible=bob,
    )
    p01 = Connector.objects.create(device=tester, designator='J01', side='left', position=1,
                                   part=parts.get('DB25-M'), description='To unit under test')
    _pins(p01, [('1', 'CAN_H', 'CAN'), ('2', 'CAN_L', 'CAN'), ('3', 'GND', '')])
    tester.snapshot()

    # External equipment.
    psu = Device.objects.create(
        name='Bench power supply', origin=Device.Origin.EXTERNAL, role=Device.Role.POWER_SUPPLY,
        manufacturer='Generic', model_number='PSU-3005', asset_tag='LAB-0042', color='#d9822b',
    )
    out = Connector.objects.create(device=psu, designator='J01', side='right', position=1, description='Output terminals')
    _pins(out, [('+', 'PWR', 'Out'), ('-', 'GND', 'Out')])
    psu.snapshot()

    load_dev = Device.objects.create(
        name='Electronic load', origin=Device.Origin.EXTERNAL, role=Device.Role.ELECTRONIC_LOAD,
        manufacturer='Generic', model_number='EL-150', asset_tag='LAB-0057', color='#c0392b',
    )
    inp = Connector.objects.create(device=load_dev, designator='J01', side='left', position=1, description='Load input')
    _pins(inp, [('+', 'PWR', 'In'), ('-', 'GND', 'In')])
    load_dev.snapshot()
