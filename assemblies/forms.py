from decimal import Decimal

from django import forms

from inventory.models import Part

from .models import Assembly


class AssemblyForm(forms.ModelForm):
    class Meta:
        model = Assembly
        fields = ['name', 'assembly_type', 'status', 'version', 'build_instructions', 'usage_instructions']
        widgets = {
            'build_instructions': forms.Textarea(attrs={'rows': 6}),
            'usage_instructions': forms.Textarea(attrs={'rows': 4}),
        }


def component_choices(assembly):
    """Grouped choices: ``p:<id>`` for parts and ``a:<id>`` for sub-assemblies.

    Assemblies that already contain this one are left out, since adding them
    would create a cycle.
    """
    in_use = set(assembly.components.values_list('part_id', flat=True)) if assembly.pk else set()
    parts = Part.objects.filter(is_active=True) | Part.objects.filter(pk__in=in_use - {None})
    assemblies = Assembly.objects.all()
    if assembly.pk:
        assemblies = assemblies.exclude(pk__in={assembly.pk, *assembly.ancestor_ids()})
    return [
        ('', '(choose)'),
        ('Parts', [(f'p:{p.pk}', str(p)) for p in parts.distinct().order_by('part_number')]),
        ('Sub-assemblies', [(f'a:{a.pk}', str(a)) for a in assemblies]),
    ]


class ComponentForm(forms.Form):
    component = forms.ChoiceField(required=False)
    quantity = forms.DecimalField(min_value=Decimal('0.001'), decimal_places=3, initial=1, required=False)

    def __init__(self, *args, choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['component'].choices = choices
        self.fields['quantity'].widget.attrs.update(step='any', style='width: 7em')

    def clean(self):
        data = super().clean()
        if data.get('component') and not data.get('quantity'):
            self.add_error('quantity', 'Enter a quantity.')
        return data


class BaseComponentFormSet(forms.BaseFormSet):
    def clean(self):
        if any(self.errors):
            return
        seen = set()
        for form in self.forms:
            if self.can_delete and self._should_delete_form(form):
                continue
            ref = form.cleaned_data.get('component')
            if not ref:
                continue
            if ref in seen:
                form.add_error('component', 'Listed twice. Combine the quantities on one row.')
            seen.add(ref)

    def lines(self):
        """(ref, quantity) for every filled-in, non-deleted row."""
        for form in self.forms:
            if self.can_delete and self._should_delete_form(form):
                continue
            if form.cleaned_data.get('component'):
                yield form.cleaned_data['component'], form.cleaned_data['quantity']


ComponentFormSet = forms.formset_factory(ComponentForm, formset=BaseComponentFormSet, extra=2, can_delete=True)


class LinkTaskForm(forms.Form):
    assembly = forms.ModelChoiceField(Assembly.objects.all(), required=False, empty_label='(none)')
