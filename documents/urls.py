from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "documents"

urlpatterns = [
    path("", views.document_list, name="list"),
    path("login/", auth_views.LoginView.as_view(
        template_name="documents/login.html", redirect_authenticated_user=True), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("ask/", views.ask, name="ask"),
    path("export/csv/", views.export_csv, name="export_csv"),
    path("export/zip/", views.export_zip, name="export_zip"),
    path("settings/", views.user_settings, name="settings"),
    path("fields/", views.custom_fields, name="custom_fields"),
    path("fields/<int:pk>/delete/", views.custom_field_delete, name="custom_field_delete"),
    path("upload/", views.document_upload, name="upload"),
    path("<int:pk>/", views.document_detail, name="detail"),
    path("<int:pk>/status/", views.document_status, name="status"),
    path("<int:pk>/pdf/", views.serve_searchable_pdf, name="pdf"),
    path("<int:pk>/file/", views.serve_file, name="file"),
    path("<int:pk>/edit/", views.document_edit, name="edit"),
    path("<int:pk>/reprocess/<str:step>/", views.document_reprocess, name="reprocess"),
    path("<int:pk>/delete/", views.document_delete, name="delete"),
]
