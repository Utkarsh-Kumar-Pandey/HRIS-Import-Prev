from django.urls import include, path

urlpatterns = [
    path("", include("importer.urls")),
]
