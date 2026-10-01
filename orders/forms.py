from decimal import Decimal

from django import forms

from budgets.models import Budget
from inventory.models import Part

from .models import Order, OrderLine


class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['supplier', 'budget', 'notes']
        widgets = {'notes': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['budget'].queryset = Budget.objects.select_related('parent__parent')


class OrderLineForm(forms.ModelForm):
    class Meta:
        model = OrderLine
        fields = ['part', 'quantity', 'unit_price']
        widgets = {'part': forms.HiddenInput}  # picked with the part picker below the lines

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['part'].queryset = Part.objects.all()
        self.fields['quantity'].min_value = Decimal('0.01')
        self.fields['quantity'].widget.attrs.update(step='any', min='0.01')
        self.fields['unit_price'].widget.attrs.update(step='any', min='0', placeholder='0.00')
        self.fields['unit_price'].required = False
        if not self.instance.pk:
            # A new line starts blank (price shown as a 0.00 hint), so a row left empty isn't taken as filled in.
            self.initial['unit_price'] = None

    def clean_unit_price(self):
        return self.cleaned_data.get('unit_price') or Decimal(0)


    def part_label(self):
        """The line's part as text, also for a new line picked on the page."""
        part = getattr(self.instance, 'part', None) if self.instance.part_id else None
        if part is None and self.is_bound:
            value = self.data.get(self.add_prefix('part'))
            part = Part.objects.filter(pk=value).first() if str(value or '').isdigit() else None
        return part


OrderLineFormSet = forms.inlineformset_factory(Order, OrderLine, form=OrderLineForm, extra=0, can_delete=True)
