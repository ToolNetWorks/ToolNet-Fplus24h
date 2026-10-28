from django.urls import path

from .auth import AdminLoginView, AdminLogoutView
from .views import dashboard
from .pipeline_views import pipeline_list

app_name = "adminpanel"

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("login/", AdminLoginView.as_view(), name="login"),
    path("logout/", AdminLogoutView.as_view(), name="logout"),
    path("pipelines/", pipeline_list, name="pipelines"),
]
