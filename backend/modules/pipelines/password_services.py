from django.core.exceptions import ValidationError
from django.db import transaction
from .models import Pipeline
@transaction.atomic
def change_ctv_password(*, pipeline_id, new_password):
    pipeline = (
        Pipeline.objects
        .select_for_update()
        .select_related("ctv")
        .get(pk=pipeline_id)
    )
    ctv = pipeline.ctv
    if ctv.is_staff or ctv.is_superuser:
        raise ValidationError(
            "Không thể thay đổi mật khẩu quản trị."
        )
    ctv.set_password(new_password)
    ctv.save(update_fields=["password"])
    return pipeline
