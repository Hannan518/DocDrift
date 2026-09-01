"""Shared view helpers."""
import json

from django.http import JsonResponse


def parse_json_body(request):
    """
    Parse a JSON request body safely.

    Returns:
        Tuple of (data, error_response). Exactly one is None.
        An empty body parses as {} so simple POST endpoints work unchanged.
    """
    try:
        raw = request.body.decode('utf-8') if request.body else ''
        data = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, JsonResponse({'error': 'Invalid JSON in request body'}, status=400)

    if not isinstance(data, dict):
        return None, JsonResponse({'error': 'Request body must be a JSON object'}, status=400)

    return data, None
