from decimal import Decimal

from django.conf import settings
from django.db import models, transaction
from django.db.models import F
from django.urls import reverse

from core.trees import TreeNode


class Category(TreeNode):
    class Meta(TreeNode.Meta):
        verbose_name_plural = 'categories'

    def get_absolute_url(self):
        return reverse('inventory:category_edit', args=[self.pk])


class Attribute(models.Model):
    """An attribute name defined on a category; each part stores its own value."""

    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='attributes')
    name = models.CharField(max_length=100)
    default_value = models.CharField(
        max_length=200, blank=True, help_text='Example or typical value, shown as a hint on parts.',
    )

    class Meta:
        ordering = ['category', 'name']
        constraints = [models.UniqueConstraint(fields=['category', 'name'], name='unique_attribute_per_category')]

    def __str__(self):
        return self.name


class Location(TreeNode):
    def get_absolute_url(self):
        return reverse('inventory:location_edit', args=[self.pk])


class Part(models.Model):
    class Gender(models.TextChoices):
        NONE = '', '(unspecified)'
        MALE = 'male', 'Male'
        FEMALE = 'female', 'Female'
        GENDERLESS = 'genderless', 'Genderless'

    part_number = models.CharField(max_length=50, unique=True)
    name = models.CharField('Description', max_length=200, blank=True)
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL, related_name='parts')
    location = models.ForeignKey(Location, null=True, blank=True, on_delete=models.SET_NULL, related_name='parts')
    unit = models.CharField(max_length=20, default='pcs')
    cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    reorder_level = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, help_text='Flag as low stock at or below this quantity.',
    )
    quantity_on_hand = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    # Interconnect: parts with the same family can mate (e.g. a "D-sub 25"
    # female to a "D-sub 25" male). An empty family means "not a connector".
    interconnect_family = models.CharField(max_length=100, blank=True)
    interconnect_gender = models.CharField(max_length=20, choices=Gender, blank=True)
    is_active = models.BooleanField('Active', default=True, help_text='Untick to archive the part.')

    class Meta:
        ordering = ['part_number']

    def __str__(self):
        return f'{self.part_number} · {self.name}' if self.name else self.part_number

    def get_absolute_url(self):
        return reverse('inventory:part_detail', args=[self.pk])

    @property
    def is_low_stock(self):
        return self.quantity_on_hand <= self.reorder_level

    @property
    def stock_value(self):
        return self.quantity_on_hand * self.cost

    @property
    def interconnect_label(self):
        if not self.interconnect_family:
            return ''
        return f'{self.interconnect_family} ({self.interconnect_gender})' if self.interconnect_gender else self.interconnect_family

    def mates_with(self, other):
        """True if the two parts plug into each other: same family, and
        male↔female (a blank or genderless gender mates with anything)."""
        family = self.interconnect_family.strip().lower()
        if not family or family != other.interconnect_family.strip().lower():
            return False
        genders = {self.interconnect_gender, other.interconnect_gender}
        if genders & {'', self.Gender.GENDERLESS}:
            return True
        return self.interconnect_gender != other.interconnect_gender

    def mates(self):
        if not self.interconnect_family.strip():
            return []
        candidates = Part.objects.filter(
            interconnect_family__iexact=self.interconnect_family.strip(), is_active=True,
        ).exclude(pk=self.pk)
        return [p for p in candidates if self.mates_with(p)]


class PartAttributeValue(models.Model):
    part = models.ForeignKey(Part, on_delete=models.CASCADE, related_name='attribute_values')
    attribute = models.ForeignKey(Attribute, on_delete=models.CASCADE, related_name='part_values')
    value = models.CharField(max_length=200)

    class Meta:
        ordering = ['attribute__name']
        constraints = [models.UniqueConstraint(fields=['part', 'attribute'], name='unique_value_per_part_attribute')]

    def __str__(self):
        return f'{self.attribute.name}: {self.value}'


class StockMove(models.Model):
    class Type(models.TextChoices):
        IN = 'in', 'Receipt'
        OUT = 'out', 'Issue'
        ADJUST = 'adjust', 'Adjustment'

    part = models.ForeignKey(Part, on_delete=models.PROTECT, related_name='moves')
    move_type = models.CharField('Type', max_length=10, choices=Type)
    delta = models.DecimalField(max_digits=12, decimal_places=2, help_text='Signed change to quantity on hand.')
    # The part's cost when the move happened, so later price changes don't
    # rewrite what a task or budget has already spent.
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    note = models.CharField(max_length=255, blank=True)
    # Integration with the Tasks module: materials consumed by a task.
    task = models.ForeignKey(
        'tasks.Task', null=True, blank=True, on_delete=models.SET_NULL, related_name='stock_moves',
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='stock_moves')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.get_move_type_display()} {self.delta:+} {self.part.unit} {self.part.part_number}'

    @classmethod
    @transaction.atomic
    def record(cls, part, move_type, delta, **fields):
        """Create a move and update the part's quantity on hand atomically."""
        fields.setdefault('unit_cost', part.cost)
        move = cls.objects.create(part=part, move_type=move_type, delta=Decimal(delta), **fields)
        Part.objects.filter(pk=part.pk).update(quantity_on_hand=F('quantity_on_hand') + move.delta)
        part.refresh_from_db(fields=['quantity_on_hand'])
        return move

    @classmethod
    def material_cost_by_task(cls, task_ids):
        """{task id: cost of parts issued to it, net of parts returned}."""
        costs = {}
        moves = cls.objects.filter(task_id__in=task_ids, move_type__in=[cls.Type.IN, cls.Type.OUT])
        for task_id, delta, unit_cost in moves.values_list('task_id', 'delta', 'unit_cost'):
            costs[task_id] = costs.get(task_id, Decimal(0)) - delta * unit_cost
        return {task_id: cost.quantize(Decimal('0.01')) for task_id, cost in costs.items()}
