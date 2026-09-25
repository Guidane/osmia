from decimal import Decimal

from django import forms

from core.trees import TreeNodeForm
from tasks.models import Task

from .models import Attribute, Category, Location, Part, PartAttributeValue, StockMove


class CategoryForm(TreeNodeForm):
    class Meta(TreeNodeForm.Meta):
        model = Category


class LocationForm(TreeNodeForm):
    class Meta(TreeNodeForm.Meta):
        model = Location


AttributeFormSet = forms.inlineformset_factory(
    Category, Attribute, fields=['name', 'default_value'], extra=2, can_delete=True,
)


class PartForm(forms.ModelForm):
    """Part fields plus one ``attr_<id>`` field per category attribute.

    Fields for every category are rendered; the page shows only those of the
    selected category, and only those are saved.
    """

    class Meta:
        model = Part
        fields = [
            'part_number', 'name', 'category', 'location', 'unit', 'cost', 'reorder_level',
            'interconnect_family', 'interconnect_gender', 'is_active',
        ]
        help_texts = {'interconnect_family': 'e.g. "D-sub 25". Parts in the same family can mate.'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].queryset = Category.objects.select_related('parent')
        self.fields['location'].queryset = Location.objects.select_related('parent')
        current = {}
        if self.instance.pk:
            current = {v.attribute_id: v.value for v in self.instance.attribute_values.all()}
        self.attribute_groups = []
        attributes = Attribute.objects.select_related('category__parent').order_by('category_id', 'name')
        for attr in attributes:
            name = f'attr_{attr.pk}'
            self.fields[name] = forms.CharField(
                label=attr.name, required=False, max_length=200, initial=current.get(attr.pk, ''),
                widget=forms.TextInput(attrs={'placeholder': attr.default_value}),
            )
            if not self.attribute_groups or self.attribute_groups[-1]['category'] != attr.category:
                self.attribute_groups.append({'category': attr.category, 'fields': []})
            self.attribute_groups[-1]['fields'].append(name)

    def base_fields_bound(self):
        return [self[name] for name in self._meta.fields]

    def attribute_fields_bound(self):
        return [
            {'category': g['category'], 'fields': [self[n] for n in g['fields']]}
            for g in self.attribute_groups
        ]

    def save(self, commit=True):
        part = super().save(commit=commit)
        if commit:
            self.save_attribute_values(part)
        return part

    def save_attribute_values(self, part):
        valid = set(part.category.attributes.values_list('pk', flat=True)) if part.category else set()
        # Values for attributes outside the part's category no longer apply.
        part.attribute_values.exclude(attribute_id__in=valid).delete()
        for attr_id in valid:
            value = self.cleaned_data.get(f'attr_{attr_id}', '').strip()
            if value:
                PartAttributeValue.objects.update_or_create(part=part, attribute_id=attr_id, defaults={'value': value})
            else:
                part.attribute_values.filter(attribute_id=attr_id).delete()


class StockMoveForm(forms.Form):
    part = forms.ModelChoiceField(Part.objects.filter(is_active=True))
    move_type = forms.ChoiceField(label='Type', choices=StockMove.Type.choices)
    quantity = forms.DecimalField(
        min_value=Decimal('0'), decimal_places=2,
        help_text='For receipts and issues, the amount moved. For adjustments, the counted quantity on hand.',
    )
    task = forms.ModelChoiceField(
        Task.objects.exclude(status=Task.Status.DONE), required=False,
        help_text='Optional: the task these materials are for.',
    )
    note = forms.CharField(max_length=255, required=False)

    def clean(self):
        data = super().clean()
        part, move_type, qty = data.get('part'), data.get('move_type'), data.get('quantity')
        if part is None or qty is None:
            return data
        if move_type in (StockMove.Type.IN, StockMove.Type.OUT) and qty == 0:
            self.add_error('quantity', 'Enter a quantity greater than zero.')
        if move_type == StockMove.Type.OUT and qty > part.quantity_on_hand:
            self.add_error('quantity', f'Only {part.quantity_on_hand} {part.unit} on hand.')
        return data

    def save(self, user):
        d = self.cleaned_data
        part, qty = d['part'], d['quantity']
        delta = {
            StockMove.Type.IN: qty,
            StockMove.Type.OUT: -qty,
            StockMove.Type.ADJUST: qty - part.quantity_on_hand,
        }[d['move_type']]
        return StockMove.record(part, d['move_type'], delta, task=d['task'], note=d['note'], user=user)
