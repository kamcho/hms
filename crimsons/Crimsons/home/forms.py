from django import forms


class ContactForm(forms.Form):
    name = forms.CharField(
        label="Full name",
        max_length=120,
        widget=forms.TextInput(
            attrs={
                "class": "contact-input",
                "autocomplete": "name",
                "placeholder": "Your name",
            }
        ),
    )
    phone = forms.CharField(
        label="Phone",
        max_length=32,
        widget=forms.TextInput(
            attrs={
                "class": "contact-input",
                "autocomplete": "tel",
                "placeholder": "+254 …",
            }
        ),
    )
    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(
            attrs={
                "class": "contact-input",
                "autocomplete": "email",
                "placeholder": "you@example.com",
            }
        ),
    )
    message = forms.CharField(
        label="Message",
        min_length=10,
        widget=forms.Textarea(
            attrs={
                "class": "contact-textarea",
                "rows": 5,
                "placeholder": "Tell us what you need—software, SMS, AI, or a quick question.",
            }
        ),
    )
