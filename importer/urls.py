from django.urls import path

from .views import upload_view

app_name = "importer"

urlpatterns = [
    path("", upload_view, name="upload"),
]
