"""
Contract tests for the document-generation endpoint.

These tests stub the LLM client so we can verify the work-set cursor
advances correctly without burning real API calls.
"""

import json
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from analysis.models import Snapshot, CodeEntity
from repositories.models import Repository


pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db):
    return User.objects.create_user(username='u', password='p')


@pytest.fixture
def repo(user):
    return Repository.objects.create(
        owner=user,
        name='r',
        source_type='github',
        github_url='https://github.com/u/r',
    )


@pytest.fixture
def snapshot(repo):
    return Snapshot.objects.create(
        repository=repo,
        status='generating_docs',
        temp_path='',
    )


def _make_undocumented(snapshot, n):
    """Create n entities that need docs (no existing/generated docstring)."""
    objs = []
    for i in range(n):
        objs.append(CodeEntity(
            snapshot=snapshot,
            entity_type='function',
            name=f'f{i}',
            qualified_name=f'm.f{i}',
            signature='def f()',
            source_hash=f'h{i}',
            file_path='m.py',
            line_number=i,
            source_body='def f(): pass',
        ))
    CodeEntity.objects.bulk_create(objs)
    return CodeEntity.objects.filter(snapshot=snapshot).order_by('id')


def _doc_payload(**overrides):
    body = {'after_id': 0, 'limit': 10}
    body.update(overrides)
    return json.dumps(body)


@patch('analysis.views.GeminiDocGenerator')
def test_cursor_advances_and_terminates(mock_llm_cls, user, snapshot):
    """The cursor should drain all entities and signal exhaustion with null."""
    # Three undocumented entities, batch size 1. The view returns next_after_id
    # for partial batches; once the work-set is empty it returns next_after_id=null.
    _make_undocumented(snapshot, 3)

    mock_instance = mock_llm_cls.return_value
    mock_instance.generate_docstring.return_value = 'doc'

    client = Client()
    client.force_login(user)

    last_id = 0
    rounds = 0
    while True:
        rounds += 1
        response = client.post(
            reverse('analysis:generate_docs_batch', args=[snapshot.id]),
            data=_doc_payload(after_id=last_id, limit=1),
            content_type='application/json',
        )
        assert response.status_code == 200
        payload = response.json()
        if payload['next_after_id'] is None:
            break
        last_id = payload['next_after_id']
        if rounds > 10:
            pytest.fail('Did not terminate')

    # Three productive rounds (1 entity each) plus a final empty-cursor round.
    assert rounds == 4
    assert CodeEntity.objects.filter(
        snapshot=snapshot, doc_source='generated'
    ).count() == 3


@patch('analysis.views.GeminiDocGenerator')
def test_unchanged_entity_is_skipped(mock_llm_cls, user, snapshot):
    """Entities with existing docstrings must not appear in the work-set."""
    CodeEntity.objects.create(
        snapshot=snapshot,
        entity_type='function',
        name='has_doc',
        qualified_name='m.has_doc',
        signature='def has_doc()',
        source_hash='h',
        file_path='m.py',
        line_number=1,
        existing_docstring='Already documented.',
        doc_source='existing',
    )
    CodeEntity.objects.create(
        snapshot=snapshot,
        entity_type='function',
        name='needs_doc',
        qualified_name='m.needs_doc',
        signature='def needs_doc()',
        source_hash='h2',
        file_path='m.py',
        line_number=2,
        source_body='def needs_doc(): pass',
    )

    mock_instance = mock_llm_cls.return_value
    mock_instance.generate_docstring.return_value = 'generated'

    client = Client()
    client.force_login(user)
    response = client.post(
        reverse('analysis:generate_docs_batch', args=[snapshot.id]),
        data=_doc_payload(after_id=0, limit=10),
        content_type='application/json',
    )
    payload = response.json()
    assert payload['processed'] == 1
    assert payload['next_after_id'] is None
    # The LLM was called only for the undocumented one.
    assert mock_instance.generate_docstring.call_count == 1
    # The documented one kept its existing doc.
    has_doc = CodeEntity.objects.get(qualified_name='m.has_doc')
    assert has_doc.generated_docstring in (None, '')
    assert has_doc.existing_docstring == 'Already documented.'


@patch('analysis.views.GeminiDocGenerator')
def test_no_duplicate_writes_across_calls(mock_llm_cls, user, snapshot):
    """
    A second pass starting from after_id=0 must skip entities that were
    already documented in the first pass (the cursor must reflect a
    shrinking work-set, not a snapshot of qualified_name keys).
    """
    _make_undocumented(snapshot, 3)
    mock_instance = mock_llm_cls.return_value
    mock_instance.generate_docstring.return_value = 'doc'

    client = Client()
    client.force_login(user)

    # First pass: limit 1 forces three round-trips.
    last = 0
    while True:
        r = client.post(
            reverse('analysis:generate_docs_batch', args=[snapshot.id]),
            data=_doc_payload(after_id=last, limit=1),
            content_type='application/json',
        )
        last = r.json()['next_after_id'] or 0
        if r.json()['next_after_id'] is None:
            break

    # Second pass: nothing to do.
    r = client.post(
        reverse('analysis:generate_docs_batch', args=[snapshot.id]),
        data=_doc_payload(after_id=0, limit=10),
        content_type='application/json',
    )
    assert r.json()['processed'] == 0
    assert r.json()['next_after_id'] is None
    # The LLM was called exactly 3 times across both passes.
    assert mock_instance.generate_docstring.call_count == 3


@patch('analysis.views.GeminiDocGenerator')
def test_offset_pagination_no_longer_used(mock_llm_cls, user, snapshot):
    """Client must use after_id, not offset - confirm the response shape."""
    _make_undocumented(snapshot, 2)
    mock_instance = mock_llm_cls.return_value
    mock_instance.generate_docstring.return_value = 'doc'

    client = Client()
    client.force_login(user)
    r = client.post(
        reverse('analysis:generate_docs_batch', args=[snapshot.id]),
        data=_doc_payload(after_id=0, limit=10),
        content_type='application/json',
    )
    payload = r.json()
    assert 'next_after_id' in payload
    assert 'remaining' in payload
    # No leftover offset key in the contract.
    assert 'next_offset' not in payload


@patch('analysis.views.GeminiDocGenerator')
def test_invalid_json_returns_400(mock_llm_cls, user, snapshot):
    client = Client()
    client.force_login(user)
    response = client.post(
        reverse('analysis:generate_docs_batch', args=[snapshot.id]),
        data='{not json',
        content_type='application/json',
    )
    assert response.status_code == 400


def test_browser_data_island_is_a_json_array(user, snapshot):
    """
    The browser template renders {{ entities_json|json_script:'entities-data' }}.
    The view must hand a Python list (or dict) to the template — not a
    pre-encoded JSON string — or the data island is double-encoded and the
    client sees a quoted string instead of an array.
    """
    CodeEntity.objects.create(
        snapshot=snapshot,
        entity_type='function',
        name='f',
        qualified_name='m.f',
        signature='def f()',
        source_hash='h',
        file_path='m.py',
        line_number=1,
    )
    client = Client()
    client.force_login(user)
    response = client.get(reverse('analysis:browser', args=[snapshot.id]))
    import json
    import re
    m = re.search(
        r'<script id="entities-data" type="application/json">(.*?)</script>',
        response.content.decode(),
        re.DOTALL,
    )
    assert m, 'data island missing from browser page'
    parsed = json.loads(m.group(1))
    assert isinstance(parsed, list), (
        'data island must be a JSON array, got %r' % type(parsed).__name__
    )
    assert len(parsed) == 1
    assert parsed[0]['name'] == 'f'
