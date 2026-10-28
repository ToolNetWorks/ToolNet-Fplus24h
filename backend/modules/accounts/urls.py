from django.contrib.auth.views import LogoutView
from django.urls import path

from .views import CTVLoginView, workspace


urlpatterns = [
    path(
        "login/",
        CTVLoginView.as_view(),
        name="ctv_login",
    ),
    path(
        "logout/",
        LogoutView.as_view(next_page="ctv_login"),
        name="ctv_logout",
    ),
    path(
        "",
        workspace,
        name="ctv_workspace",
    ),
]
