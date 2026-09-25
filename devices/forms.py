from django import forms
from django.contrib.auth import get_user_model

from assemblies.models import Assembly
from inventory.models import Part

from .models import Connector, Device, Pin


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
    add_pins = forms.IntegerField(
        label='Add pins', required=False, min_value=0, max_value=500,
        help_text='Quick start: add this many numbered pins (1, 2, 3, ...) after the existing ones.',
    )

    class Meta:
        model = Connector
        fields = ['designator', 'side', 'part', 'description']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['part'].queryset = Part.objects.filter(is_active=True).select_related('category')

    def clean_designator(self):
        designator = self.cleaned_data['designator'].strip().upper()
        clash = Connector.objects.filter(device=self.instance.device, designator=designator).exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError(f'This device already has a {designator}.')
        return designator


PinFormSet = forms.inlineformset_factory(
    Connector, Pin, fields=['label', 'signal'], extra=0, can_delete=True,
    widgets={
        'label': forms.TextInput(attrs={'style': 'width: 6em'}),
    },
)
