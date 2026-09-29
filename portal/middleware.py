from django.conf import settings


class DevMobileCorsMiddleware:
    """Small CORS helper for the included local Capacitor/browser preview.
    Production origins should be explicitly configured before deployment.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "OPTIONS" and request.path.startswith("/api/v1/"):
            from django.http import HttpResponse
            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)
        origin = request.headers.get("Origin", "")
        allowed = origin in set(settings.MOBILE_ALLOWED_ORIGINS)
        if allowed:
            response["Access-Control-Allow-Origin"] = origin
            response["Vary"] = "Origin"
            response["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-CSRFToken"
            response["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
        return response
