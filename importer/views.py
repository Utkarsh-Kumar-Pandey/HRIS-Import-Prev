from django.shortcuts import render

from .core import UploadError, analyze_upload


def upload_view(request):
    if request.method == "POST":
        uploaded_file = request.FILES.get("hris_file")
        if uploaded_file is None:
            return render(
                request,
                "importer/upload.html",
                {"upload_error": "Please choose a CSV file."},
                status=400,
            )

        try:
            result = analyze_upload(uploaded_file)
        except UploadError as exc:
            return render(
                request,
                "importer/upload.html",
                {"upload_error": str(exc)},
                status=400,
            )

        return render(request, "importer/results.html", {"result": result})

    return render(request, "importer/upload.html")
