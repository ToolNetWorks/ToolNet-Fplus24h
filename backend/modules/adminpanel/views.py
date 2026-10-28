from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.views.decorators.cache import never_cache

from modules.pipelines.models import Pipeline


@login_required(login_url="/control/login/")
@never_cache
def dashboard(request):
    if not request.user.is_superuser:
        raise PermissionDenied(
            "Chỉ Admin được truy cập."
        )

    pipelines = Pipeline.objects.select_related(
        "ctv"
    )

    context = {
        "total_pipelines": pipelines.count(),
        "total_ctv": pipelines.count(),
        "active_pipelines": pipelines.filter(
            status=Pipeline.Status.ACTIVE
        ).count(),
        "disabled_pipelines": pipelines.filter(
            status=Pipeline.Status.DISABLED
        ).count(),
        "pipelines": pipelines.order_by(
            "-created_at"
        )[:10],
    }

    return render(
        request,
        "adminpanel/dashboard.html",
        context,
    )
