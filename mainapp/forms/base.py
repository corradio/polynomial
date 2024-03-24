from django import forms


class BaseModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("label_suffix", "")  # Removes ":" as label suffix
        super().__init__(*args, **kwargs)
