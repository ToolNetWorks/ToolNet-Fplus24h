from django.core.exceptions import ValidationError
from django.db import transaction
from .models import Pipeline
@transaction.atomic
def update_pipeline_and_ctv(*, pipeline_id, changes):
    pipeline = (
        Pipeline.objects
        .select_for_update()
        .select_related("ctv")
        .get(pk=pipeline_id)
    )
    ctv = type(pipeline.ctv).objects.select_for_update().get(
        pk=pipeline.ctv_id
    )
    if ctv.is_staff or ctv.is_superuser:
        raise ValidationError(
            "Không thể chỉnh sửa tài khoản quản trị."
        )
    if "name" in changes:
        pipeline.name = changes["name"]
    if "ctv_username" in changes:
        ctv.username = changes["ctv_username"]
    if "ctv_email" in changes:
        ctv.email = changes["ctv_email"]
    ctv.full_clean()
    pipeline.full_clean()
    ctv.save(update_fields=["username", "email"])
    pipeline.save()
    return pipeline
