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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['part'].queryset = Part.objects.filter(is_active=True)
        self.fields['quantity'].min_value = Decimal('0.01')
        self.fields['quantity'].widget.attrs.update(step='any', min='0.01')
        self.fields['unit_price'].widget.attrs.update(step='any', min='0')


OrderLineFormSet = forms.inlineformset_factory(Order, OrderLine, form=OrderLineForm, extra=2, can_delete=True)
