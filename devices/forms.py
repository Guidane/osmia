from django import forms
from django.contrib.auth import get_user_model

from assemblies.models import Assembly
from inventory.models import Part

from .models import Connector, Device, Pin, Signal


class DeviceForm(forms.ModelForm):
    class Meta:
        model = Device
        fields = [
            'name', 'part_number', 'origin', 'role', 'assembly', 'manufacturer', 'model_number', 'asset_tag',
            'color', 'responsible', 'notes',
        ]
        widgets = {'color': forms.TextInput(attrs={'type': 'color'}), 'notes': forms.Textarea(attrs={'rows': 3})}
        help_texts = {'assembly': 'For devices we build: the assembly (type "Device") with its bill of materials.'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        taken = Device.objects.exclude(pk=self.instance.pk).exclude(assembly=None).values('assembly_id')
        self.fields['assembly'].queryset = Assembly.objects.filter(assembly_type=Assembly.Type.DEVICE).exclude(pk__in=taken)
        self.fields['responsible'].queryset = get_user_model().objects.filter(is_active=True)

    def clean(self):
        data = super().clean()
        if data.get('origin') == Device.Origin.EXTERNAL and data.get('assembly'):
            self.add_error('assembly', 'External devices are not built by us, so they have no assembly.')
        return data


class ConnectorForm(forms.ModelForm):
    class Meta:
        model = Connector
        fields = ['designator', 'side', 'gender', 'part', 'details', 'description']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['part'].queryset = Part.objects.filter(is_active=True).select_related('category')

    def clean_designator(self):
        designator = self.cleaned_data['designator'].strip().upper()
        clash = Connector.objects.filter(device=self.instance.device, designator=designator).exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError(f'This device already has a {designator}.')
        return designator


class PinForm(forms.ModelForm):
    signal = forms.ChoiceField(required=False)

    class Meta:
        model = Pin
        fields = ['label', 'signal', 'tag', 'set_number', 'set_type']
        widgets = {
            'label': forms.TextInput(attrs={'style': 'width: 6em'}),
            'tag': forms.TextInput(attrs={'style': 'width: 10em'}),
            'set_number': forms.NumberInput(attrs={'style': 'width: 5em', 'min': 1}),
        }

    def __init__(self, *args, signals=None, **kwargs):
        super().__init__(*args, **kwargs)
        names = list(signals if signals is not None else Signal.objects.values_list('name', flat=True))
        current = self.instance.signal if self.instance.pk else ''
        if current and current not in names:
            names.append(current)  # an old value that isn't in the list yet
        self.fields['signal'].choices = [('', '—')] + [(n, n) for n in names]

    def clean_tag(self):
        return (self.cleaned_data.get('tag') or '').strip()


class BasePinFormSet(forms.BaseInlineFormSet):
    def __init__(self, *args, **kwargs):
        self._signals = list(Signal.objects.values_list('name', flat=True))
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        return {**super().get_form_kwargs(index), 'signals': self._signals}

    def clean(self):
        super().clean()
        seen = {}
        for form in self.forms:
            if not hasattr(form, 'cleaned_data') or form.cleaned_data.get('DELETE'):
                continue
            tag = (form.cleaned_data.get('tag') or '').strip()
            if not tag:
                continue
            if tag.lower() in seen:
                form.add_error('tag', f'Pin {seen[tag.lower()]} already has the tag {tag}; tags are unique within a connector.')
            else:
                seen[tag.lower()] = form.cleaned_data.get('label') or '?'


PinFormSet = forms.inlineformset_factory(
    Connector, Pin, form=PinForm, formset=BasePinFormSet, extra=0, can_delete=True,
)


class SignalForm(forms.ModelForm):
    class Meta:
        model = Signal
        fields = ['name', 'description']
        widgets = {'name': forms.TextInput(attrs={'style': 'width: 12em'}), 'description': forms.TextInput(attrs={'style': 'width: 28em'})}

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if Signal.objects.filter(name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(f'There is already a signal {name}.')
        return name
