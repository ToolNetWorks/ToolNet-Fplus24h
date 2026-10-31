from .system_config.views import (
    DatabaseConfigAPIView,
    R2ConfigAPIView,
    R2TestAPIView,
    R2ResetToEnvAPIView,
    AIProviderListCreateAPIView,
    AIProviderDetailAPIView,
    AIProviderTestAPIView,
    AIProviderAdHocTestAPIView,
    AIProviderSetDefaultAPIView,
    AIProviderRotateKeyAPIView,
    ServicesHealthAPIView,
    SystemConfigAuditLogAPIView,
)
from .publishing.report_views import (
    PipelineReportSummaryAPIView, PipelineReportBatchesAPIView,
    PipelineReportBatchDetailAPIView, PipelineReportGroupsAPIView,
    PipelineReportAccountsAPIView,
)
from .publishing.review_case_views import (
    ReviewCaseListCreateAPIView, ReviewCaseDetailAPIView, ReviewCaseActionAPIView,
)
from .publishing.review_sla_views import ReviewSLAAPIView
from .publishing.integrity_audit_views import PublishingIntegrityAuditAPIView
from .publishing.operations_health_views import OperationsHealthAPIView
from .publishing.manual_handoff_views import (
    ManualHandoffAPIView, HandoffQueueAPIView,
)
from .publishing.pilot_views import PublishingPilotReadinessAPIView
from .publishing.performance_views import PipelinePerformanceAPIView
from .publishing.release_views import PipelineReleaseReadinessAPIView
from .publishing.caption_views import (CaptionSettingsAPIView, CaptionSamplesAPIView,
    CaptionSampleDetailAPIView, CaptionJobListAPIView, CaptionJobAPIView)
from .publishing.security_audit_views import PublishingSecurityAuditAPIView
from .publishing.worker_reliability_views import WorkerGuardAPIView
from .publishing.alert_views import PublishingAlertsAPIView, PublishingAlertActionAPIView, PublishingAlertEventsAPIView
from .publishing.reconciliation_views import PublishingReconciliationAPIView
from .publishing.readback_views import PublishingJobReadbackAPIView
from .publishing.post_verification_views import PublishingJobVerificationAPIView
from .publishing.scheduler_tick_views import SchedulerTickStatusAPIView
from .publishing.scheduler_views import (
    PipelineScheduleListCreateAPIView, PipelineScheduleDetailAPIView,
    SchedulePreviewAPIView, ScheduleRunAPIView, ScheduleBatchListAPIView,
    AccountGroupEligibilityAPIView, GroupSchedulingHealthAPIView,
)
from .publishing.facebook_group_preflight_views import FacebookGroupPreflightAPIView
from .publishing.job_views import (
    PublishingJobListCreateAPIView,
    PublishingJobDetailAPIView,
    PublishingJobCancelAPIView,
)
from .publishing.media_policy_views import PipelineMediaPolicyAPIView
from .albums.bulk_views import AlbumBulkStatusAPIView
from .facebook_groups.bulk_views import FacebookGroupBulkStatusAPIView
from .proxies.check_views import ProxyCheckAPIView
from .proxies.views import (
    ProxyListCreateAPIView,
    ProxyBulkAPIView,
    ProxyDetailAPIView,
)
from .albums.image_reorder_views import AlbumImageReorderAPIView
from .albums.image_delete_views import AlbumImageDeleteAPIView
from .albums.image_content_views import AlbumImageContentAPIView
from .albums.image_list_views import AlbumImageCollectionAPIView
from .albums.upload_views import AlbumImageUploadAPIView
from .albums.detail_views import AlbumDetailAPIView
from .albums.views import AlbumCollectionAPIView
from .facebook_groups.views import FacebookGroupCollectionAPIView, FacebookGroupDetailAPIView
from .ctv.admin_views import (
    CTVAdminAuditLogAPIView,
    CTVCollectionAPIView,
)
from .ctv.session_views import AuthLandingAPIView
from .ctv.workspace_views import CTVWorkspaceAPIView
from .facebook_accounts.list_views import FacebookAccountListAPIView
from .facebook_accounts.upload_views import FacebookCookieUploadAPIView
from .pipelines.delete_views import PipelineDetailAPIView
from .pipelines.edit_views import PipelineEditAPIView
from django.urls import path

from .views import AdminOverviewView
from .auth_views import (
    csrf_token,
    unified_login,
    admin_login,
    admin_me,
    admin_logout,
)
from .pipelines.list_views import PipelineCollectionAPIView
from .pipelines.status_views import PipelineStatusAPIView
from .pipelines.password_views import CTVPasswordAPIView

urlpatterns = [
    path("pipelines/<uuid:pipeline_id>/caption-config/",
         CaptionSettingsAPIView.as_view(), name="caption-config"),
    path("pipelines/<uuid:pipeline_id>/caption-samples/",
         CaptionSamplesAPIView.as_view(), name="caption-samples"),
    path("pipelines/<uuid:pipeline_id>/caption-samples/<uuid:sample_id>/",
         CaptionSampleDetailAPIView.as_view(), name="caption-sample-detail"),
    path("pipelines/<uuid:pipeline_id>/caption-jobs/",
         CaptionJobListAPIView.as_view(), name="caption-jobs"),
    path("pipelines/<uuid:pipeline_id>/publishing-jobs/<uuid:job_id>/caption/",
         CaptionJobAPIView.as_view(), name="job-caption"),
    path("pipelines/<uuid:pipeline_id>/release-readiness/",
         PipelineReleaseReadinessAPIView.as_view(), name="pipeline-release-readiness"),
    path("pipelines/<uuid:pipeline_id>/performance/",
         PipelinePerformanceAPIView.as_view(), name="pipeline-performance"),
    path("pipelines/<uuid:pipeline_id>/security-audit/",
         PublishingSecurityAuditAPIView.as_view(), name="pipeline-security-audit"),
    path("pipelines/<uuid:pipeline_id>/pilot-readiness/",
         PublishingPilotReadinessAPIView.as_view(), name="pipeline-pilot-readiness"),
    path("pipelines/<uuid:pipeline_id>/publishing-jobs/<uuid:job_id>/manual-handoff/",
         ManualHandoffAPIView.as_view(), name="publishing-manual-handoff"),
    path("pipelines/<uuid:pipeline_id>/handoff-queue/",
         HandoffQueueAPIView.as_view(), name="pipeline-handoff-queue"),
    path("pipelines/<uuid:pipeline_id>/worker-guard/",
         WorkerGuardAPIView.as_view(), name="pipeline-worker-guard"),
    path("pipelines/<uuid:pipeline_id>/operational-alerts/",
         PublishingAlertsAPIView.as_view(), name="pipeline-operational-alerts"),
    path("pipelines/<uuid:pipeline_id>/operational-alerts/<uuid:alert_id>/actions/",
         PublishingAlertActionAPIView.as_view(), name="pipeline-operational-alert-actions"),
    path("pipelines/<uuid:pipeline_id>/operational-alerts/<uuid:alert_id>/events/",
         PublishingAlertEventsAPIView.as_view(), name="pipeline-operational-alert-events"),
    path("pipelines/<uuid:pipeline_id>/operations-health/",
         OperationsHealthAPIView.as_view(), name="pipeline-operations-health"),
    path(
        "pipelines/<uuid:pipeline_id>/integrity-audit/",
        PublishingIntegrityAuditAPIView.as_view(), name="pipeline-integrity-audit",
    ),
    path(
        "pipelines/<uuid:pipeline_id>/publishing-jobs/<uuid:job_id>/readback/",
        PublishingJobReadbackAPIView.as_view(), name="publishing-job-readback",
    ),
    path(
        "pipelines/<uuid:pipeline_id>/publishing-jobs/<uuid:job_id>/verification/",
        PublishingJobVerificationAPIView.as_view(), name="publishing-job-verification",
    ),
    path(
        "pipelines/<uuid:pipeline_id>/review-sla/",
        ReviewSLAAPIView.as_view(), name="pipeline-review-sla",
    ),
    path(
        "pipelines/<uuid:pipeline_id>/review-cases/",
        ReviewCaseListCreateAPIView.as_view(), name="review-cases",
    ),
    path(
        "pipelines/<uuid:pipeline_id>/review-cases/<uuid:case_id>/",
        ReviewCaseDetailAPIView.as_view(), name="review-case-detail",
    ),
    path(
        "pipelines/<uuid:pipeline_id>/review-cases/<uuid:case_id>/actions/",
        ReviewCaseActionAPIView.as_view(), name="review-case-actions",
    ),
    path(
        "pipelines/<uuid:pipeline_id>/publishing-reconciliation/",
        PublishingReconciliationAPIView.as_view(), name="publishing-reconciliation",
    ),
    # Read-only Pipeline reporting (Step 9.7.5).
    path("pipelines/<uuid:pipeline_id>/reports/summary/",
         PipelineReportSummaryAPIView.as_view(), name="pipeline-report-summary"),
    path("pipelines/<uuid:pipeline_id>/reports/batches/",
         PipelineReportBatchesAPIView.as_view(), name="pipeline-report-batches"),
    path("pipelines/<uuid:pipeline_id>/reports/batches/<uuid:batch_id>/",
         PipelineReportBatchDetailAPIView.as_view(), name="pipeline-report-batch-detail"),
    path("pipelines/<uuid:pipeline_id>/reports/groups/",
         PipelineReportGroupsAPIView.as_view(), name="pipeline-report-groups"),
    path("pipelines/<uuid:pipeline_id>/reports/accounts/",
         PipelineReportAccountsAPIView.as_view(), name="pipeline-report-accounts"),
    path(
        "pipelines/<uuid:pipeline_id>/scheduler-ticks/status/",
        SchedulerTickStatusAPIView.as_view(),
        name="scheduler-tick-status",
    ),
    path(
        "pipelines/<uuid:pipeline_id>/schedules/",
        PipelineScheduleListCreateAPIView.as_view(), name="pipeline-schedules",
    ),
    path(
        "pipelines/<uuid:pipeline_id>/schedules/<uuid:schedule_id>/",
        PipelineScheduleDetailAPIView.as_view(), name="pipeline-schedule-detail",
    ),
    path(
        "pipelines/<uuid:pipeline_id>/schedules/<uuid:schedule_id>/preview/",
        SchedulePreviewAPIView.as_view(), name="pipeline-schedule-preview",
    ),
    path(
        "pipelines/<uuid:pipeline_id>/schedules/<uuid:schedule_id>/run/",
        ScheduleRunAPIView.as_view(), name="pipeline-schedule-run",
    ),
    path(
        "pipelines/<uuid:pipeline_id>/schedules/<uuid:schedule_id>/batches/",
        ScheduleBatchListAPIView.as_view(), name="pipeline-schedule-batches",
    ),
    path(
        "pipelines/<uuid:pipeline_id>/group-eligibility/",
        AccountGroupEligibilityAPIView.as_view(), name="pipeline-group-eligibility",
    ),
    path(
        "pipelines/<uuid:pipeline_id>/group-health/",
        GroupSchedulingHealthAPIView.as_view(), name="pipeline-group-health",
    ),

    path(
        "pipelines/<uuid:pipeline_id>/publishing-jobs/<uuid:job_id>/preflight/",
        FacebookGroupPreflightAPIView.as_view(),
        name="facebook-group-preflight",
    ),

    path(
        "pipelines/<uuid:pipeline_id>/publishing-jobs/",
        PublishingJobListCreateAPIView.as_view(),
        name="publishing-job-list-create",
    ),
    path(
        "pipelines/<uuid:pipeline_id>/publishing-jobs/<uuid:job_id>/cancel/",
        PublishingJobCancelAPIView.as_view(),
        name="publishing-job-cancel",
    ),
    path(
        "pipelines/<uuid:pipeline_id>/publishing-jobs/<uuid:job_id>/",
        PublishingJobDetailAPIView.as_view(),
        name="publishing-job-detail",
    ),

    path(
        "pipelines/<uuid:pipeline_id>/media-policy/",
        PipelineMediaPolicyAPIView.as_view(),
        name="pipeline-media-policy",
    ),

    path(
        "pipelines/<uuid:pipeline_id>/albums/bulk-status/",
        AlbumBulkStatusAPIView.as_view(),
        name="album-bulk-status",
    ),

    path(
        "pipelines/<uuid:pipeline_id>/facebook-groups/bulk-status/",
        FacebookGroupBulkStatusAPIView.as_view(),
        name="facebook-group-bulk-status",
    ),

    path(
        "pipelines/<uuid:pipeline_id>/proxies/<uuid:proxy_id>/check/",
        ProxyCheckAPIView.as_view(),
        name="proxy-check",
    ),
    path(
        "pipelines/<uuid:pipeline_id>/proxies/",
        ProxyListCreateAPIView.as_view(),
        name="proxy-list-create",
    ),
    path(
        "pipelines/<uuid:pipeline_id>/proxies/bulk/",
        ProxyBulkAPIView.as_view(),
        name="proxy-bulk",
    ),
    path(
        "pipelines/<uuid:pipeline_id>/proxies/<uuid:proxy_id>/",
        ProxyDetailAPIView.as_view(),
        name="proxy-detail",
    ),
    path("pipelines/<uuid:pipeline_id>/albums/<uuid:album_id>/images/reorder/", AlbumImageReorderAPIView.as_view(), name="album-image-reorder"),
    path("pipelines/<uuid:pipeline_id>/albums/<uuid:album_id>/images/<uuid:image_id>/", AlbumImageDeleteAPIView.as_view(), name="album-image-delete"),
    path("pipelines/<uuid:pipeline_id>/albums/<uuid:album_id>/images/<uuid:image_id>/content/", AlbumImageContentAPIView.as_view(), name="album-image-content"),
    path("pipelines/<uuid:pipeline_id>/albums/<uuid:album_id>/images/", AlbumImageCollectionAPIView.as_view(), name="album-image-upload"),
    path("pipelines/<uuid:pipeline_id>/albums/<uuid:album_id>/", AlbumDetailAPIView.as_view(), name="album-detail"),
    path("pipelines/<uuid:pipeline_id>/albums/", AlbumCollectionAPIView.as_view(), name="album-collection"),
    path("pipelines/<uuid:pipeline_id>/facebook-groups/<uuid:group_id>/", FacebookGroupDetailAPIView.as_view(), name="facebook-group-detail"),
    path("pipelines/<uuid:pipeline_id>/facebook-groups/", FacebookGroupCollectionAPIView.as_view(), name="facebook-group-collection"),
    path("auth/landing/", AuthLandingAPIView.as_view(), name="auth-landing"),
    path("ctv/workspace/", CTVWorkspaceAPIView.as_view(), name="ctv-workspace"),
    path("pipelines/<uuid:pipeline_id>/facebook-accounts/", FacebookAccountListAPIView.as_view(), name="facebook-account-list"),
    path("pipelines/<uuid:pipeline_id>/facebook-accounts/cookie-upload/", FacebookCookieUploadAPIView.as_view(), name="facebook-cookie-upload"),
    path(
        "admin/ctv/",
        CTVCollectionAPIView.as_view(),
        name="admin-ctv-list-create",
    ),
    path(
        "admin/ctv/audit-log/",
        CTVAdminAuditLogAPIView.as_view(),
        name="admin-ctv-audit-log",
    ),
    path(
        "admin/ctv/<uuid:pipeline_id>/status/",
        PipelineStatusAPIView.as_view(),
        name="admin-ctv-status",
    ),
    path(
        "admin/ctv/<uuid:pipeline_id>/password/",
        CTVPasswordAPIView.as_view(),
        name="admin-ctv-password-reset",
    ),
    path(
        "admin/pipelines/<uuid:pipeline_id>/ctv/password/",
        CTVPasswordAPIView.as_view(),
        name="admin-ctv-password",
    ),
    path(
        "admin/pipelines/<str:pipeline_id>/status/",
        PipelineStatusAPIView.as_view(),
        name="admin-pipeline-status",
    ),
    path(
        "admin/pipelines/",
        PipelineCollectionAPIView.as_view(),
        name="admin-pipeline-create",
    ),
    path(
        "admin/pipelines/<uuid:pipeline_id>/",
        PipelineDetailAPIView.as_view(),
        name="admin-pipeline-edit",
    ),
    path(
        "admin/overview/",
        AdminOverviewView.as_view(),
        name="admin-overview",
    ),
    path("admin/config/database/", DatabaseConfigAPIView.as_view(), name="admin-config-database"),
    path("admin/config/r2/", R2ConfigAPIView.as_view(), name="admin-config-r2"),
    path("admin/config/r2/test/", R2TestAPIView.as_view(), name="admin-config-r2-test"),
    path("admin/config/r2/reset/", R2ResetToEnvAPIView.as_view(), name="admin-config-r2-reset"),
    path("admin/config/ai-providers/", AIProviderListCreateAPIView.as_view(), name="admin-config-ai-providers"),
    path("admin/config/ai-providers/test-ad-hoc/", AIProviderAdHocTestAPIView.as_view(), name="admin-config-ai-providers-adhoc-test"),
    path("admin/config/ai-providers/<uuid:provider_id>/", AIProviderDetailAPIView.as_view(), name="admin-config-ai-provider-detail"),
    path("admin/config/ai-providers/<uuid:provider_id>/test/", AIProviderTestAPIView.as_view(), name="admin-config-ai-provider-test"),
    path("admin/config/ai-providers/<uuid:provider_id>/set-default/", AIProviderSetDefaultAPIView.as_view(), name="admin-config-ai-provider-set-default"),
    path("admin/config/ai-providers/<uuid:provider_id>/rotate-key/", AIProviderRotateKeyAPIView.as_view(), name="admin-config-ai-provider-rotate-key"),
    path("admin/config/services/", ServicesHealthAPIView.as_view(), name="admin-config-services"),
    path("admin/config/audit-log/", SystemConfigAuditLogAPIView.as_view(), name="admin-config-audit-log"),
    path("auth/csrf/", csrf_token, name="auth-csrf"),
    path("auth/login/", admin_login, name="auth-login"),
    path("auth/me/", admin_me, name="auth-me"),
    path("auth/logout/", admin_logout, name="auth-logout"),
]
