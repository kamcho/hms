from django import forms
from .models import User

class SignUpForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Create Password'}))
    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirm Password'}))
    
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'id_number', 'phone', 'role', 'password']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First Name'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last Name'}),
            'id_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ID Number'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone Number'}),
            'role': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Exclude 'Admin' from the role choices
        choices = [choice for choice in User.roles if choice[0] != 'Admin']
        self.fields['role'].choices = choices
        
        # Make fields required
        self.fields['first_name'].required = True
        self.fields['last_name'].required = True
        self.fields['phone'].required = True

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if password != confirm_password:
            raise forms.ValidationError("Passwords do not match")
        return cleaned_data

    def clean_id_number(self):
        id_number = self.cleaned_data.get('id_number')
        if User.objects.filter(id_number=id_number).exists():
            raise forms.ValidationError("A user with this ID Number already exists.")
        return id_number
