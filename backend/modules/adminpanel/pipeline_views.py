from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from modules.pipelines.models import Pipeline


@login_required(login_url="/control/login/")
@never_cache
@require_GET
def pipeline_list(request):
    if not request.user.is_superuser:
        raise PermissionDenied

    search = request.GET.get("q", "").strip()[:100]
    status = request.GET.get("status", "").strip()

    pipelines = Pipeline.objects.select_related("ctv")

    if search:
        pipelines = pipelines.filter(
            Q(name__icontains=search)
            | Q(ctv__username__icontains=search)
        )

    allowed_statuses = {
        Pipeline.Status.ACTIVE,
        Pipeline.Status.DISABLED,
    }

    if status in allowed_statuses:
        pipelines = pipelines.filter(status=status)
    else:
        status = ""

    paginator = Paginator(
        pipelines.order_by("-created_at", "-id"),
        20,
    )

    page = paginator.get_page(
        request.GET.get("page")
    )

    return render(
        request,
        "adminpanel/pipelines/list.html",
        {
            "pipelines": page.object_list,
            "page_obj": page,
            "search": search,
            "status": status,
            "total_results": paginator.count,
        },
    )
