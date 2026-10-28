from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import reverse_lazy
from django.views.decorators.cache import never_cache
from django.utils.decorators import method_decorator


class AdminLoginForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)

        if not user.is_superuser:
            raise forms.ValidationError(
                "Tài khoản không có quyền quản trị.",
                code="permission_denied",
            )


@method_decorator(never_cache, name="dispatch")
class AdminLoginView(LoginView):
    template_name = "adminpanel/login.html"
    authentication_form = AdminLoginForm
    redirect_authenticated_user = False

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            if request.user.is_superuser:
                from django.shortcuts import redirect
                return redirect("adminpanel:dashboard")

        return super().get(request, *args, **kwargs)

    def get_success_url(self):
        return str(reverse_lazy("adminpanel:dashboard"))


class AdminLogoutView(LogoutView):
    next_page = reverse_lazy("adminpanel:login")
