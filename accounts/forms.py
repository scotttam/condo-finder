from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db.models import Q


class EmailAuthenticationForm(AuthenticationForm):
    """Log in with an email address. Usernames are the lowercased email."""

    username = forms.EmailField(label="Email", widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"}))
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "That email and password do not match an account.",
    }

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()


class SignupForm(forms.Form):
    display_name = forms.CharField(max_length=60, label="Your name",
                                   help_text="Shown on your comments and votes, and in the Feed.")
    email = forms.EmailField(label="Email", widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="Password again", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def clean_display_name(self):
        return self.cleaned_data["display_name"].strip()

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if get_user_model().objects.filter(Q(username__iexact=email) | Q(email__iexact=email)).exists():
            raise ValidationError("An account with this email already exists. Log in instead.")
        return email

    def clean(self):
        cleaned = super().clean()
        first, second = cleaned.get("password1"), cleaned.get("password2")
        if first and second and first != second:
            self.add_error("password2", "The passwords do not match.")
        elif first:
            email = cleaned.get("email", "")
            try:
                validate_password(first, user=get_user_model()(username=email, email=email))
            except ValidationError as error:
                self.add_error("password1", error)
        return cleaned
