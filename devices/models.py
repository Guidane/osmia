"""Electrical devices and their named connectors.

A device is anything with connectors that takes part in an electrical setup:
units the company builds (a computer, an inverter, ...), the test equipment
it builds to test them, and external equipment such as power supplies and
electronic loads. Each connector (J01, P01, ...) has numbered pins with a
label, a signal and an optional pin set (e.g. a D-sub PWR/GND pair).

The definition (name, connectors, pins) is versioned the same way as the
harness designer's device library: every change is kept as an immutable
snapshot and ``version`` points at the current one.
"""
from django.conf import settings
from django.db import models, transaction
from django.urls import reverse


class Device(models.Model):
    class Origin(models.TextChoices):
        IN_HOUSE = 'in_house', 'Made by us'
        EXTERNAL = 'external', 'External'

    class Role(models.TextChoices):
        PRODUCT = 'product', 'Product (unit we build)'
        TEST_EQUIPMENT = 'test_equipment', 'Test equipment'
        POWER_SUPPLY = 'power_supply', 'Power supply'
        ELECTRONIC_LOAD = 'electronic_load', 'Electronic / test load'
        MEASUREMENT = 'measurement', 'Measurement (DMM, scope, ...)'
        SIGNAL_SOURCE = 'signal_source', 'Signal generator / source'
        OTHER = 'other', 'Other'

    name = models.CharField(max_length=200)
    part_number = models.CharField(max_length=100, blank=True)
    origin = models.CharField(max_length=20, choices=Origin, default=Origin.IN_HOUSE)
    role = models.CharField(max_length=20, choices=Role, default=Role.PRODUCT)
    # For devices we build: the assembly (bill of materials) behind it.
    assembly = models.OneToOneField(
        'assemblies.Assembly', null=True, blank=True, on_delete=models.SET_NULL, related_name='device',
        limit_choices_to={'assembly_type': 'device'},
    )
    manufacturer = models.CharField(max_length=100, blank=True)
    model_number = models.CharField(max_length=100, blank=True)
    asset_tag = models.CharField(max_length=100, blank=True)
    color = models.CharField(max_length=7, default='#3b7dd8', help_text='Colour of the device in the harness designer.')
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='devices',
        help_text='Owner; verifies wiring to this device in harnesses.',
    )
    notes = models.TextField(blank=True)
    version = models.PositiveIntegerField(default=0, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.part_number})' if self.part_number else self.name

    def get_absolute_url(self):
        return reverse('devices:detail', args=[self.pk])

    @property
    def is_external(self):
        return self.origin == self.Origin.EXTERNAL

    # -- harness-format definition ------------------------------------------

    def definition(self):
        """The device in the harness designer's JSON format (without id/version)."""
        return {
            'name': self.name,
            'part_number': self.part_number,
            'color': self.color,
            'responsible_user_id': str(self.responsible_id) if self.responsible_id else None,
            'connectors': [
                {
                    'id': c.designator,
                    'side': c.side,
                    'pins': [
                        {'id': str(p.position), 'label': p.label, 'signal': p.signal, 'set': p.set_name}
                        for p in c.pins.all()
                    ],
                }
                for c in self.connectors.prefetch_related('pins')
            ],
        }

    @transaction.atomic
    def apply_definition(self, data):
        """Replace name/colour/owner and all connectors and pins from a
        harness-format dict. Connector part links are kept by designator."""
        self.name = (data.get('name') or self.name or 'Unnamed device').strip()
        self.part_number = (data.get('part_number') or '').strip()
        self.color = data.get('color') or self.color
        owner = data.get('responsible_user_id')
        self.responsible_id = int(owner) if str(owner or '').isdigit() else None
        self.save()
        parts = {c.designator: (c.part_id, c.description) for c in self.connectors.all()}
        self.connectors.all().delete()
        for c_index, c in enumerate(data.get('connectors') or []):
            designator = (c.get('id') or f'J{c_index + 1:02d}').strip()
            part_id, description = parts.get(designator, (None, ''))
            connector = Connector.objects.create(
                device=self, designator=designator, position=c_index,
                side=c.get('side') if c.get('side') in Connector.Side.values else Connector.Side.RIGHT,
                part_id=part_id, description=description,
            )
            Pin.objects.bulk_create(
                Pin(
                    connector=connector, position=p_index + 1,
                    label=(p.get('label') or str(p_index + 1)).strip()[:20],
                    signal=(p.get('signal') or '').strip()[:50],
                    set_name=(p.get('set') or '').strip()[:50],
                )
                for p_index, p in enumerate(c.get('pins') or [])
            )

    def snapshot(self, user=None):
        """Record the current definition as a new version if it changed.
        Returns True when a new version was created."""
        data = self.definition()
        current = self.versions.filter(version=self.version).first()
        if current is not None and current.data == data:
            return False
        last = self.versions.order_by('-version').values_list('version', flat=True).first() or 0
        DeviceVersion.objects.create(device=self, version=last + 1, data=data, created_by=user)
        self.version = last + 1
        self.save(update_fields=['version'])
        return True

    @transaction.atomic
    def activate_version(self, version):
        """Make an older version current again (like moving the harness pointer)."""
        snap = self.versions.get(version=version)
        self.apply_definition(snap.data)
        self.version = version
        self.save(update_fields=['version'])

    def to_harness(self):
        return {**self.definition(), 'id': str(self.pk), 'version': self.version, 'url': self.get_absolute_url(),
                'origin': self.origin}


class Connector(models.Model):
    class Side(models.TextChoices):
        LEFT = 'left', 'Left'
        RIGHT = 'right', 'Right'

    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='connectors')
    designator = models.CharField(max_length=20, help_text='e.g. J01 (jack on the device) or P01 (plug).')
    side = models.CharField(max_length=5, choices=Side, default=Side.RIGHT, help_text='Where it sits in the harness designer.')
    part = models.ForeignKey(
        'inventory.Part', null=True, blank=True, on_delete=models.SET_NULL, related_name='device_connectors',
        verbose_name='Physical connector', help_text='The connector part, e.g. a D-sub 25 socket. Gives the interconnect family and gender.',
    )
    description = models.CharField(max_length=200, blank=True, help_text='e.g. "Main power in".')
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['position', 'designator']
        constraints = [models.UniqueConstraint(fields=['device', 'designator'], name='unique_connector_designator')]

    def __str__(self):
        return f'{self.device.name} {self.designator}'

    @property
    def mating_designator(self):
        """The harness-side connector name: J01 mates with P01 and vice versa."""
        prefix, rest = self.designator[:1].upper(), self.designator[1:]
        return ('P' if prefix != 'P' else 'J') + rest

    def signal_summary(self):
        signals = [p.signal for p in self.pins.all() if p.signal]
        return ', '.join(sorted(set(signals)))


class Pin(models.Model):
    connector = models.ForeignKey(Connector, on_delete=models.CASCADE, related_name='pins')
    position = models.PositiveIntegerField()
    label = models.CharField(max_length=20, help_text='The number printed on the connector, e.g. 13.')
    signal = models.CharField(max_length=50, blank=True, help_text='e.g. PWR, GND, CAN_H.')
    set_name = models.CharField('Pin set', max_length=50, blank=True, help_text='Groups pins wired together, e.g. "Set 1".')

    class Meta:
        ordering = ['position']
        constraints = [models.UniqueConstraint(fields=['connector', 'position'], name='unique_pin_position')]

    def __str__(self):
        return f'{self.connector} pin {self.label}'


class DeviceVersion(models.Model):
    """An immutable snapshot of a device definition, in harness format."""

    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='versions')
    version = models.PositiveIntegerField()
    data = models.JSONField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-version']
        constraints = [models.UniqueConstraint(fields=['device', 'version'], name='unique_device_version')]

    def __str__(self):
        return f'{self.device.name} v{self.version}'
