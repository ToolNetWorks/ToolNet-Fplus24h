from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import CTVAdminAuditLog, Pipeline


def log_ctv_admin_action(
    *,
    admin,
    action,
    pipeline,
    ctv=None,
):
    """Write an audit row without exposing credentials or secrets."""
    if admin is None or not getattr(admin, "pk", None):
        return None

    if ctv is None:
        ctv = pipeline.ctv

    return CTVAdminAuditLog.objects.create(
        admin=admin,
        admin_username=admin.get_username(),
        action=action,
        pipeline_id=pipeline.pk,
        pipeline_name=pipeline.name,
        ctv_id=ctv.pk if ctv is not None else None,
        ctv_username=ctv.username if ctv is not None else "",
    )


@transaction.atomic
def create_pipeline_with_ctv(
    *,
    pipeline,
    username,
    email,
    password,
    admin=None,
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

    log_ctv_admin_action(
        admin=admin,
        action=CTVAdminAuditLog.Action.CREATE_CTV,
        pipeline=pipeline,
        ctv=user,
    )

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
