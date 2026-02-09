from django import forms
from .models import InventoryItem, InventoryCategory, Supplier, StockRecord, InventoryRequest, Medication, ConsumableDetail

class InventoryItemForm(forms.ModelForm):
    class Meta:
        model = InventoryItem
        fields = [
            'name', 'category', 'item_type', 'description', 
            'dispensing_unit', 'packaging_unit', 'units_per_pack', 
            'is_dispensed_as_whole', 'reorder_level', 'selling_price'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'e.g. Paracetamol 500mg'}),
            'description': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Optional description...'}),
            'dispensing_unit': forms.TextInput(attrs={'placeholder': 'e.g. Tablet, ml, Piece'}),
            'packaging_unit': forms.TextInput(attrs={'placeholder': 'e.g. Box of 100'}),
            'reorder_level': forms.NumberInput(attrs={'min': 0}),
            'selling_price': forms.NumberInput(attrs={'step': '0.01', 'min': 0}),
        }

    buying_price = forms.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={'step': '0.01', 'min': 0, 'placeholder': 'Optional: For Profit Calculation'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['packaging_unit'].required = False
        self.fields['units_per_pack'].required = False
        self.fields['description'].required = False
        self.fields['is_dispensed_as_whole'].widget.attrs.update({'class': 'peer'})

class MedicationForm(forms.ModelForm):
    class Meta:
        model = Medication
        fields = ['generic_name', 'drug_class', 'formulation', 'strength', 'is_controlled']
        widgets = {
            'generic_name': forms.TextInput(attrs={'placeholder': 'e.g. Paracetamol'}),
            'strength': forms.TextInput(attrs={'placeholder': 'e.g. 500mg'}),
            'is_controlled': forms.CheckboxInput(attrs={'class': 'peer'}),
        }

class ConsumableDetailForm(forms.ModelForm):
    class Meta:
        model = ConsumableDetail
        fields = ['material', 'is_sterile', 'size']
        widgets = {
            'material': forms.TextInput(attrs={'placeholder': 'e.g. Plastic, Glass'}),
            'size': forms.TextInput(attrs={'placeholder': 'e.g. 60ml, 21G'}),
            'is_sterile': forms.CheckboxInput(attrs={'class': 'peer'}),
        }

class InventoryCategoryForm(forms.ModelForm):
    class Meta:
        model = InventoryCategory
        fields = ['name', 'description']

class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ['name', 'contact_person', 'phone', 'email', 'address']

class StockRecordForm(forms.ModelForm):
    class Meta:
        model = StockRecord
        fields = ['batch_number', 'quantity', 'expiry_date', 'supplier', 'purchase_price', 'current_location']
        widgets = {
            'batch_number': forms.TextInput(attrs={'placeholder': 'e.g. BATCH-2024-001'}),
            'expiry_date': forms.DateInput(attrs={'type': 'date'}),
            'quantity': forms.NumberInput(attrs={'min': 1}),
            'purchase_price': forms.NumberInput(attrs={'step': '0.01', 'min': 0}),
        }

class InventoryRequestForm(forms.ModelForm):
    class Meta:
        model = InventoryRequest
        fields = ['item', 'quantity', 'location']
        widgets = {
            'item': forms.Select(attrs={'class': 'form-select'}),
            'quantity': forms.NumberInput(attrs={'min': 1, 'class': 'form-control'}),
            'location': forms.Select(attrs={'class': 'form-select'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['item'].queryset = InventoryItem.objects.all().order_by('name')
        self.fields['item'].empty_label = "Select an item"
        self.fields['location'].empty_label = "Select a location"
