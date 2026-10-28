from django import forms
from django.contrib.auth.forms import AuthenticationForm

from modules.pipelines.models import Pipeline


class CTVLoginForm(AuthenticationForm):

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)

        if user.is_staff or user.is_superuser:
            raise forms.ValidationError(
                "Trang đăng nhập chỉ dành cho CTV."
            )

        has_pipeline = Pipeline.objects.filter(
            ctv=user,
            status=Pipeline.Status.ACTIVE,
        ).exists()

        if not has_pipeline:
            raise forms.ValidationError(
                "Pipeline chưa được cấp hoặc đã bị khóa."
            )
