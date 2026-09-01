import json

import pytest
from django.test import RequestFactory
from django.http import JsonResponse

from capstone.utils import parse_json_body


pytestmark = pytest.mark.django_db


class TestParseJsonBody:
    """Shared JSON body parser used by every POST view."""

    def test_empty_body_returns_empty_dict(self):
        rf = RequestFactory()
        request = rf.post('/x/')
        data, error = parse_json_body(request)
        assert data == {}
        assert error is None

    def test_valid_json(self):
        rf = RequestFactory()
        request = rf.post(
            '/x/',
            data=json.dumps({'a': 1}),
            content_type='application/json',
        )
        data, error = parse_json_body(request)
        assert error is None
        assert data == {'a': 1}

    def test_invalid_json_returns_400(self):
        rf = RequestFactory()
        request = rf.post(
            '/x/', data='{not json', content_type='application/json'
        )
        data, error = parse_json_body(request)
        assert data is None
        assert isinstance(error, JsonResponse)
        assert error.status_code == 400

    def test_top_level_array_rejected(self):
        rf = RequestFactory()
        request = rf.post(
            '/x/', data='[1,2,3]', content_type='application/json'
        )
        data, error = parse_json_body(request)
        assert data is None
        assert error.status_code == 400
