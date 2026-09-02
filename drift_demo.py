"""
End-to-end drift detection demo.

Synthesizes two snapshots of the same repository - one with the
"original" function body and a generated docstring, and a second
where the same function has been changed (different source, different
signature) but the prior docstring has been carried over.

Then calls the real /analysis/<id>/detect-drift/ HTTP endpoint and
queries the resulting DriftFlag. The point is to show that the
real view code, the real drift detector, the real diff computation,
and the real flag storage all work together end-to-end - not a mock.
"""
import json
import os
import sys
import time

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'capstone.settings')
import django
from django.conf import settings
django.setup()
settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ['127.0.0.1']

import requests
from django.contrib.auth.models import User
from repositories.models import Repository
from analysis.models import Snapshot, CodeEntity, DriftFlag
from analysis.drift_detector import DriftDetector


def banner(s):
    print('\n' + '=' * 70)
    print(s)
    print('=' * 70)


def main():
    # 1. Create a user and a fresh repo
    u, _ = User.objects.get_or_create(username='drift_demo')
    u.set_password('DocDrift2026!')
    u.save()

    repo, _ = Repository.objects.get_or_create(
        owner=u, name='drift-demo-app',
        defaults={'source_type': 'github', 'github_url': 'https://github.com/example/drift-demo-app'},
    )
    # Clean any prior snapshots
    Snapshot.objects.filter(repository=repo).delete()

    # 2. Snapshot A: the "before" state
    snap_a = Snapshot.objects.create(
        repository=repo, status='complete',
        commit_hash='aaaaaaa1111', temp_path=None,
        total_files=1, total_entities=2, entities_documented=2,
    )
    CodeEntity.objects.create(
        snapshot=snap_a, entity_type='function',
        name='calculate_total', qualified_name='utils.calculate_total',
        signature='def calculate_total(items: list[int]) -> int',
        source_hash='hash_v1',
        file_path='utils.py', line_number=1,
        generated_docstring=(
            'Calculate the total of a list of integers.\n\n'
            'Args:\n'
            '    items: A list of integers to sum.\n\n'
            'Returns:\n'
            '    The sum of all items in the list.'
        ),
        source_body=(
            'def calculate_total(items: list[int]) -> int:\n'
            '    """Sum a list of integers."""\n'
            '    total = 0\n'
            '    for item in items:\n'
            '        total += item\n'
            '    return total\n'
        ),
        doc_source='generated',
    )
    CodeEntity.objects.create(
        snapshot=snap_a, entity_type='function',
        name='format_currency', qualified_name='utils.format_currency',
        signature='def format_currency(amount: float) -> str',
        source_hash='hash_v1_currency',
        file_path='utils.py', line_number=15,
        generated_docstring='Format a float as a USD currency string.',
        source_body=(
            'def format_currency(amount: float) -> str:\n'
            '    return f"${amount:.2f}"\n'
        ),
        doc_source='generated',
    )
    print(f'Created snapshot A #{snap_a.id} with 2 entities (both documented, body v1)')

    # 3. Snapshot B: the "after" state - one function changed (both source AND signature),
    #    one unchanged, prior doc carried over on the changed one
    snap_b = Snapshot.objects.create(
        repository=repo, status='generating_docs',
        commit_hash='bbbbbbb2222', temp_path=None,
        total_files=1, total_entities=2,
    )
    # Changed: new source body (uses sum() built-in), new signature (added tax param),
    # but the OLD docstring is carried forward -> drift detector should see hash mismatch
    # and signature mismatch and create BOTH stale_doc AND signature_changed flags.
    CodeEntity.objects.create(
        snapshot=snap_b, entity_type='function',
        name='calculate_total', qualified_name='utils.calculate_total',
        signature='def calculate_total(items: list[int], tax_rate: float = 0.0) -> float',
        source_hash='hash_v2',
        file_path='utils.py', line_number=1,
        generated_docstring=(
            'Calculate the total of a list of integers.\n\n'
            'Args:\n'
            '    items: A list of integers to sum.\n\n'
            'Returns:\n'
            '    The sum of all items in the list.'
        ),
        source_body=(
            'def calculate_total(items: list[int], tax_rate: float = 0.0) -> float:\n'
            '    """Sum a list of integers, optionally with tax."""\n'
            '    return sum(items) * (1.0 + tax_rate)\n'
        ),
        doc_source='stale',
    )
    # Unchanged: same source, same signature, doc copied forward -> no flag
    CodeEntity.objects.create(
        snapshot=snap_b, entity_type='function',
        name='format_currency', qualified_name='utils.format_currency',
        signature='def format_currency(amount: float) -> str',
        source_hash='hash_v1_currency',
        file_path='utils.py', line_number=15,
        generated_docstring='Format a float as a USD currency string.',
        doc_source='copied',
        source_body=(
            'def format_currency(amount: float) -> str:\n'
            '    return f"${amount:.2f}"\n'
        ),
    )
    print(f'Created snapshot B #{snap_b.id} with 2 entities (1 changed with stale doc, 1 unchanged)')

    # 4. Run the actual drift detection via the real DriftDetector
    banner('RUNNING DriftDetector().detect_drift(prev=A, curr=B)')
    detector = DriftDetector()
    flags_created = detector.detect_drift(snap_a, snap_b)
    print(f'Created {flags_created} drift flags')

    # 5. Show the resulting flags
    banner('DRIFT FLAGS on snapshot B')
    flags = DriftFlag.objects.filter(current_snapshot=snap_b).order_by('flag_type', 'qualified_name')
    for flag in flags:
        print(f'\n  Flag #{flag.id}  type={flag.flag_type}  qname={flag.qualified_name}')
        d = flag.detail
        # Print the most relevant fields
        for key in ('signature', 'old_signature', 'new_signature',
                    'old_hash', 'new_hash', 'file_path', 'line_number'):
            if key in d:
                print(f'    {key}: {d[key]}')
        if 'unified_diff' in d and d['unified_diff']:
            print(f'    unified_diff ({len(d["unified_diff"])} chars):')
            for line in d['unified_diff'].splitlines()[:20]:
                print(f'      {line}')
            if len(d['unified_diff'].splitlines()) > 20:
                print(f'      ... ({len(d["unified_diff"].splitlines()) - 20} more lines)')

    # 6. Sanity check: invoke via the real HTTP endpoint to prove the integration works
    banner('VERIFY: invoke /analysis/<id>/detect-drift/ via HTTP')
    session = requests.Session()
    r = session.get('http://127.0.0.1:8000/accounts/login/')
    csrf = session.cookies.get('csrftoken')
    r = session.post('http://127.0.0.1:8000/accounts/login/',
        data={'username': 'drift_demo', 'password': 'DocDrift2026!', 'csrfmiddlewaretoken': csrf},
        headers={'Referer': 'http://127.0.0.1:8000/accounts/login/'}, allow_redirects=False)
    print(f'  login: {r.status_code}')
    csrf = session.cookies.get('csrftoken')
    r = session.post(f'http://127.0.0.1:8000/analysis/{snap_b.id}/detect-drift/',
                     json={}, timeout=30,
                     headers={'X-CSRFToken': csrf, 'Referer': 'http://127.0.0.1:8000/'})
    print(f'  detect-drift via HTTP: {r.status_code} {r.json()}')
    print(f'  flags in DB after: {DriftFlag.objects.filter(current_snapshot=snap_b).count()}')

    # The endpoint is idempotent: re-running deletes prior flags and recreates.
    # Confirm that.
    banner('VERIFY: idempotency (re-run produces same flags, not duplicates)')
    n_before = DriftFlag.objects.filter(current_snapshot=snap_b).count()
    detector2 = DriftDetector()
    detector2.detect_drift(snap_a, snap_b)
    n_after = DriftFlag.objects.filter(current_snapshot=snap_b).count()
    print(f'  before: {n_before} flags  after re-run: {n_after} flags  (should be equal)')

    print('\nDONE')


if __name__ == '__main__':
    main()
