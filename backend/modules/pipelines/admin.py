from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import transaction
from django.urls import reverse
from django.utils.html import format_html

from .forms import PipelineCreateForm
from .models import Pipeline
from .services import (
    create_pipeline_with_ctv,
    delete_pipeline_with_ctv,
)


@admin.register(Pipeline)
class PipelineAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "ctv",
        "status",
        "ctv_controls",
        "created_at",
    )

    list_filter = ("status",)
    search_fields = ("name", "ctv__username")
    list_select_related = ("ctv",)

    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
    )

    @admin.display(description="Quản lý CTV")
    def ctv_controls(self, obj):
        User = get_user_model()
        app = User._meta.app_label
        model = User._meta.model_name

        user_url = reverse(
            f"admin:{app}_{model}_change",
            args=[obj.ctv_id],
        )

        password_url = reverse(
            f"admin:{app}_{model}_password_change",
            args=[obj.ctv_id],
        )

        return format_html(
            '<a href="{}">Sửa CTV</a> | '
            '<a href="{}">Đổi mật khẩu</a>',
            user_url,
            password_url,
        )

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return (
                ("Thông tin Pipeline", {
                    "fields": ("name", "status"),
                }),
                ("Tạo tài khoản CTV", {
                    "fields": (
                        "ctv_username",
                        "ctv_email",
                        "ctv_password",
                        "ctv_password_confirm",
                    ),
                }),
            )

        return (
            ("Thông tin Pipeline", {
                "fields": (
                    "name",
                    "status",
                    "ctv",
                ),
            }),
            ("Thông tin hệ thống", {
                "fields": (
                    "id",
                    "created_at",
                    "updated_at",
                ),
            }),
        )

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs["form"] = PipelineCreateForm

        return super().get_form(
            request, obj, **kwargs
        )

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(
            request, obj
        )

        if obj is None:
            return fields

        return (*fields, "ctv")

    def save_model(self, request, obj, form, change):
        if change:
            super().save_model(request, obj, form, change)
            return

        create_pipeline_with_ctv(
            pipeline=obj,
            username=form.cleaned_data["ctv_username"],
            email=form.cleaned_data["ctv_email"],
            password=form.cleaned_data["ctv_password"],
            admin=request.user,
        )

    def get_deleted_objects(self, objs, request):
        result = super().get_deleted_objects(
            objs, request
        )

        deleted, counts, permissions, protected = result

        for pipeline in objs:
            deleted.append(
                f"Tài khoản CTV: {pipeline.ctv.username}"
            )

        counts["Tài khoản CTV"] = len(objs)

        return deleted, counts, permissions, protected

    @transaction.atomic
    def delete_model(self, request, obj):
        delete_pipeline_with_ctv(pipeline=obj)

    @transaction.atomic
    def delete_queryset(self, request, queryset):
        for pipeline in queryset.select_related("ctv"):
            delete_pipeline_with_ctv(
                pipeline=pipeline
            )

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
