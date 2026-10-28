from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Pipeline


@transaction.atomic
def create_pipeline_with_ctv(
    *,
    pipeline,
    username,
    email,
    password,
):
    User = get_user_model()

    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,
        is_staff=False,
        is_superuser=False,
    )

    pipeline.ctv = user
    pipeline.full_clean()
    pipeline.save()

    return pipeline


@transaction.atomic
def delete_pipeline_with_ctv(*, pipeline):
    current = (
        Pipeline.objects
        .select_for_update()
        .select_related("ctv")
        .get(pk=pipeline.pk)
    )

    ctv = current.ctv

    if ctv.is_staff or ctv.is_superuser:
        raise ValidationError(
            "Không được xóa tài khoản quản trị."
        )

    # Xóa Pipeline trước do quan hệ PROTECT.
    current.delete()

    # Chỉ xóa CTV gắn với Pipeline này.
    ctv.delete()
