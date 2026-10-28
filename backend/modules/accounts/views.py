from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache

from modules.pipelines.models import Pipeline
from .forms import CTVLoginForm


class CTVLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = CTVLoginForm

    def get_success_url(self):
        return reverse("ctv_workspace")


@login_required(login_url="/ctv/login/")
@never_cache
def workspace(request):
    user = request.user

    if user.is_staff or user.is_superuser:
        raise PermissionDenied

    pipeline = Pipeline.objects.filter(
        ctv=user,
        status=Pipeline.Status.ACTIVE,
    ).first()

    if pipeline is None:
        logout(request)
        return redirect("ctv_login")

    return render(
        request,
        "accounts/workspace.html",
        {"pipeline": pipeline},
    )
