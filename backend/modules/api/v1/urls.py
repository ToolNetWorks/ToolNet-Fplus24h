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
    admin_login,
    admin_me,
    admin_logout,
)
from .pipelines.list_views import PipelineCollectionAPIView
from .pipelines.status_views import PipelineStatusAPIView
from .pipelines.password_views import CTVPasswordAPIView

urlpatterns = [
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
    path("auth/csrf/", csrf_token, name="auth-csrf"),
    path("auth/login/", admin_login, name="auth-login"),
    path("auth/me/", admin_me, name="auth-me"),
    path("auth/logout/", admin_logout, name="auth-logout"),
]
