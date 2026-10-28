from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import Pipeline


class PipelineCreateForm(forms.ModelForm):
    ctv_username = forms.CharField(
        label="Tên đăng nhập CTV",
        max_length=150,
    )

    ctv_email = forms.EmailField(
        label="Email CTV",
    )

    ctv_password = forms.CharField(
        label="Mật khẩu CTV",
        widget=forms.PasswordInput,
    )

    ctv_password_confirm = forms.CharField(
        label="Xác nhận mật khẩu",
        widget=forms.PasswordInput,
    )

    class Meta:
        model = Pipeline
        fields = ("name", "status")

    def clean_ctv_username(self):
        username = self.cleaned_data["ctv_username"].strip()
        User = get_user_model()

        field = User._meta.get_field(User.USERNAME_FIELD)

        for validator in field.validators:
            validator(username)

        if User.objects.filter(
            username__iexact=username
        ).exists():
            raise forms.ValidationError(
                "Tên đăng nhập đã tồn tại."
            )

        return username

    def clean(self):
        cleaned = super().clean()

        password = cleaned.get("ctv_password")
        confirmation = cleaned.get("ctv_password_confirm")
        username = cleaned.get("ctv_username")

        if not password or not confirmation:
            return cleaned

        if password != confirmation:
            self.add_error(
                "ctv_password_confirm",
                "Mật khẩu xác nhận không khớp.",
            )
            return cleaned

        User = get_user_model()
        user = User(username=username or "")

        try:
            validate_password(password, user)
        except ValidationError as error:
            self.add_error("ctv_password", error)

        return cleaned
