from django import forms
from .models import InventoryItem, InventoryCategory, Supplier, StockRecord, InventoryRequest, Medication, ConsumableDetail
from home.models import Departments

class InventoryItemForm(forms.ModelForm):
    class Meta:
        model = InventoryItem
        fields = [
            'name', 'category', 'dispensing_unit', 
            'is_dispensed_as_whole', 'selling_price'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'e.g. Paracetamol 500mg'}),
            'dispensing_unit': forms.TextInput(attrs={'placeholder': 'e.g. Tablet, ml, Piece'}),
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
        self.fields['is_dispensed_as_whole'].widget.attrs.update({'class': 'peer'})

class MedicationForm(forms.ModelForm):
    class Meta:
        model = Medication
        fields = ['generic_name', 'drug_class', 'formulation']
        widgets = {
            'generic_name': forms.TextInput(attrs={'placeholder': 'e.g. Paracetamol'}),
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
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Medical Supplies Ltd'}),
            'contact_person': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Jane Smith'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 0712345678'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'e.g. info@supplier.com'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Physical office location'}),
        }

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

class InventoryPurchaseForm(forms.ModelForm):
    invoice_number = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. INV-001'}),
        help_text='Supplier invoice number for this delivery',
    )

    class Meta:
        from accounts.models import InventoryPurchase
        model = InventoryPurchase
        fields = ['date', 'supplier', 'total_amount', 'notes']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'supplier': forms.Select(attrs={'class': 'form-control'}),
            'total_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

class PurchaseItemForm(forms.ModelForm):
    class Meta:
        model = StockRecord
        fields = ['item', 'batch_number', 'expiry_date', 'quantity', 'purchase_price', 'current_location']
        widgets = {
            'item': forms.Select(attrs={'class': 'form-control purchase-item-select'}), # Add class for select2 if needed
            'batch_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Batch #'}),
            'expiry_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'purchase_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0, 'placeholder': 'Total Cost'}),
            'current_location': forms.Select(attrs={'class': 'form-control'}),
        }
    
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['item'].queryset = InventoryItem.objects.all().order_by('name')

class StockTransferForm(forms.Form):
    item = forms.ModelChoiceField(
        queryset=InventoryItem.objects.all().order_by('name'),
        widget=forms.Select(attrs={'class': 'form-select select2'})
    )
    source_location = forms.ModelChoiceField(
        queryset=Departments.objects.all(),
        label="From Department",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    destination_location = forms.ModelChoiceField(
        queryset=Departments.objects.all(),
        label="To Department",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    quantity = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Quantity to transfer'})
    )
    batch_number = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Specific Batch (Optional)'}),
        help_text="Leave empty to auto-select oldest batches (FEFO)"
    )

    def clean(self):
        cleaned_data = super().clean()
        source = cleaned_data.get('source_location')
        destination = cleaned_data.get('destination_location')

        if source and destination and source == destination:
            raise forms.ValidationError("Source and destination departments cannot be the same.")
        
        return cleaned_data
