from django import forms
from django.contrib.auth.forms import AuthenticationForm


class EmailAuthenticationForm(AuthenticationForm):
    """Log in with an email address. Usernames are the lowercased email."""

    username = forms.EmailField(label="Email", widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"}))
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "That email and password do not match an account.",
    }

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()
