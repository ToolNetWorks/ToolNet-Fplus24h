from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from .models import Pipeline
User = get_user_model()
def find_related_blockers(pipeline):
    """
    Fail closed when related records exist.
    Inspect Django's registered reverse relationships.
    Do not cascade-delete unrelated business data.
    """
    blockers = []
    ctv = pipeline.ctv
    database = pipeline._state.db
    for obj in (pipeline, ctv):
        for relation in obj._meta.get_fields(
            include_hidden=True
        ):
            if not relation.auto_created:
                continue
            if relation.concrete or not relation.is_relation:
                continue
            related_model = relation.related_model
            if related_model is None:
                continue
            # This is the known Pipeline -> CTV relation.
            if (
                isinstance(obj, User)
                and related_model is Pipeline
                and getattr(
                    getattr(relation, "field", None),
                    "name",
                    None,
                ) == "ctv"
            ):
                continue
            if relation.one_to_many or relation.one_to_one:
                source_field = getattr(
                    relation,
                    "field",
                    None,
                )
                if source_field is None:
                    raise ValidationError(
                        "Không thể xác minh quan hệ dữ liệu."
                    )
                exists = (
                    related_model._base_manager
                    .using(database)
                    .filter(**{
                        source_field.name: obj.pk
                    })
                    .exists()
                )
                if exists:
                    blockers.append(
                        related_model._meta.label
                    )
                continue
            if relation.many_to_many:
                accessor = relation.get_accessor_name()
                if not accessor:
                    raise ValidationError(
                        "Không thể xác minh quan hệ M2M."
                    )
                manager = getattr(obj, accessor, None)
                if manager is None:
                    raise ValidationError(
                        "Không thể xác minh quan hệ M2M."
                    )
                if manager.exists():
                    blockers.append(
                        related_model._meta.label
                    )
    return sorted(set(blockers))
def get_delete_preview(pipeline):
    blockers = find_related_blockers(pipeline)
    if pipeline.ctv.is_staff or pipeline.ctv.is_superuser:
        blockers.append("Tài khoản có quyền quản trị")
    return {
        "pipeline_id": str(pipeline.pk),
        "pipeline_name": pipeline.name,
        "ctv_username": pipeline.ctv.username,
        "can_delete": len(blockers) == 0,
        "blockers": blockers,
    }
@transaction.atomic
def delete_pipeline_and_ctv(
    *,
    pipeline_id,
    confirm_name,
    confirm_username,
):
    pipeline = (
        Pipeline.objects
        .select_for_update()
        .select_related("ctv")
        .get(pk=pipeline_id)
    )
    ctv = (
        User.objects
        .select_for_update()
        .get(pk=pipeline.ctv_id)
    )
    if ctv.is_staff or ctv.is_superuser:
        raise ValidationError(
            "Không được xóa tài khoản quản trị."
        )
    if confirm_name != pipeline.name:
        raise ValidationError(
            "Tên Pipeline xác nhận không khớp."
        )
    if confirm_username != ctv.username:
        raise ValidationError(
            "Username CTV xác nhận không khớp."
        )
    preview = get_delete_preview(pipeline)
    if not preview["can_delete"]:
        raise ValidationError(
            "Pipeline hoặc CTV đang có dữ liệu liên quan. "
            "Không thể xóa."
        )
    deleted_pipeline_id = str(pipeline.pk)
    deleted_ctv_id = ctv.pk
    pipeline.delete()
    ctv.delete()
    return {
        "pipeline_id": deleted_pipeline_id,
        "ctv_id": deleted_ctv_id,
    }
