from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.fields import GenericRelation
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
    """A place parts are kept, e.g. Warehouse > Rack row A > Rack 1 > Shelf A.

    Its ``code`` joins the labels down the tree (A + 1 + A = "A1A"), which is
    what goes on the shelf. ``path`` and ``code`` are stored so long lists of
    locations don't have to walk up the tree for every row.
    """
    label = models.CharField(max_length=20, blank=True,
                             help_text="Short code, e.g. A or 1. A location's code joins the labels down the tree: "
                                       'rack row A, rack 1, shelf A is A1A.')
    code = models.CharField(max_length=200, blank=True, editable=False, db_index=True)
    path = models.CharField(max_length=500, blank=True, editable=False)
    images = GenericRelation('core.Image')  # e.g. photos of the shelf or bin
    audit_ignore = ('path',)  # follows the names; logging it would repeat every rename

    class Meta(TreeNode.Meta):
        constraints = [models.UniqueConstraint(fields=['parent', 'label'], condition=~models.Q(label=''),
                                               name='unique_location_label_per_parent')]

    def __str__(self):
        path = self.full_path()
        return f'{path} ({self.code})' if self.code else path

    def full_path(self, sep=' > '):
        if self.path and sep == ' > ':
            return self.path
        return super().full_path(sep)

    def get_absolute_url(self):
        return reverse('inventory:location_detail', args=[self.pk])

    def refresh_path(self):
        parent = self.parent
        self.path = f'{parent.full_path()} > {self.name}' if parent else self.name
        self.code = (parent.code if parent else '') + self.label

    def save(self, *args, **kwargs):
        old = (self.path, self.code)
        self.refresh_path()
        if kwargs.get('update_fields') is not None:
            kwargs['update_fields'] = {*kwargs['update_fields'], 'path', 'code'}
        super().save(*args, **kwargs)
        if old != (self.path, self.code):
            for child in self.children.all():
                child.parent = self  # the saved one, so the child sees the new path
                child.save()


class Part(models.Model):
    part_number = models.CharField(max_length=50, unique=True)
    name = models.CharField('Description', max_length=200, blank=True)
    images = GenericRelation('core.Image')  # pictures, shown with {% image_gallery %}
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL, related_name='parts')
    location = models.ForeignKey(Location, null=True, blank=True, on_delete=models.SET_NULL, related_name='parts')
    unit = models.CharField(max_length=20, default='pcs')
    cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    reorder_level = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, help_text='Flag as low stock at or below this quantity.',
    )
    quantity_on_hand = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
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
        TRANSFER = 'transfer', 'Transfer'  # moved to another location; quantity unchanged

    part = models.ForeignKey(Part, on_delete=models.PROTECT, related_name='moves')
    move_type = models.CharField('Type', max_length=10, choices=Type)
    delta = models.DecimalField(max_digits=12, decimal_places=2, help_text='Signed change to quantity on hand.')
    # The part's cost when the move happened, so later price changes don't
    # rewrite what a task or budget has already spent.
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    note = models.CharField(max_length=255, blank=True)
    # Transfers: where the part's stock was moved from and to.
    from_location = models.ForeignKey(Location, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    to_location = models.ForeignKey(Location, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
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
        was_low = part.is_low_stock
        part.refresh_from_db(fields=['quantity_on_hand'])
        if part.is_low_stock and not was_low:
            # Automations: "A part runs low on stock"
            from core import automation
            automation.emit('inventory.stock_low', part)
        return move

    @classmethod
    @transaction.atomic
    def transfer(cls, part, location, user=None, note=''):
        """Move all of a part's stock to ``location``, and log it. Returns the
        move, or None if the part is already there."""
        if part.location_id == getattr(location, 'pk', None):
            return None
        move = cls.objects.create(part=part, move_type=cls.Type.TRANSFER, delta=0, unit_cost=part.cost,
                                  from_location=part.location, to_location=location, user=user, note=note)
        part.location = location
        part.save(update_fields=['location'])
        return move

    @classmethod
    def material_cost_by_task(cls, task_ids):
        """{task id: cost of parts issued to it, net of parts returned}."""
        costs = {}
        moves = cls.objects.filter(task_id__in=task_ids, move_type__in=[cls.Type.IN, cls.Type.OUT])
        for task_id, delta, unit_cost in moves.values_list('task_id', 'delta', 'unit_cost'):
            costs[task_id] = costs.get(task_id, Decimal(0)) - delta * unit_cost
        return {task_id: cost.quantize(Decimal('0.01')) for task_id, cost in costs.items()}
