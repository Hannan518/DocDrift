from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.conf import settings
from django.db.models import Q
import json
import logging
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from capstone.utils import parse_json_body
from .models import Snapshot, CodeEntity
from .parser import PythonASTParser
from .drift_detector import DriftDetector
from .constants import (
    PARSING_BATCH_SIZE,
    DOC_GEN_BATCH_SIZE,
    DOC_GEN_MAX_WORKERS,
    DOC_GEN_WORKER_STAGGER_S,
)
from repositories.ingestion import list_python_files, cleanup_temp_directory
from llm.gemini import GeminiDocGenerator
from llm.base import LLMConfigError

logger = logging.getLogger(__name__)

# Hard ceiling so a misbehaving client cannot request huge batches.
MAX_BATCH_LIMIT = 50


def _entities_needing_docs(snapshot):
    """Entities with no documentation at all (the LLM work-set).

    Under the review-gate policy (option A), a changed entity whose
    previous generated doc existed is NOT in this set - the drift
    dashboard owns that signal, and the user can regenerate per-entity
    via the regenerate endpoint.
    """
    return snapshot.entities.filter(
        generated_docstring__isnull=True,
        existing_docstring__isnull=True
    )


def _documented_count(snapshot):
    """Entities carrying any documentation (generated, copied, or source)."""
    return snapshot.entities.filter(
        Q(generated_docstring__isnull=False) | Q(existing_docstring__isnull=False)
    ).count()


@login_required
@require_http_methods(["POST"])
def parse_batch(request, snapshot_id):
    """Parse a batch of Python files."""
    snapshot = get_object_or_404(
        Snapshot,
        id=snapshot_id,
        repository__owner=request.user
    )

    data, error = parse_json_body(request)
    if error:
        return error
    offset = max(int(data.get('offset', 0) or 0), 0)
    limit = min(int(data.get('limit', PARSING_BATCH_SIZE) or PARSING_BATCH_SIZE), MAX_BATCH_LIMIT)

    try:
        all_files = list_python_files(snapshot.temp_path)
        batch_files = all_files[offset:offset + limit]

        if not batch_files:
            snapshot.status = 'parsing_complete'
            snapshot.save(update_fields=['status'])
            return JsonResponse({
                'parsed': 0,
                'total': len(all_files),
                'next_offset': None,
                'status': snapshot.status
            })

        parser = PythonASTParser()
        entities_to_create = []
        parent_links = []  # (child_qualified_name, parent_qualified_name)

        for file_path in batch_files:
            try:
                parsed_entities = parser.parse_file(file_path, root_path=Path(snapshot.temp_path))

                for entity in parsed_entities:
                    entities_to_create.append(CodeEntity(
                        snapshot=snapshot,
                        entity_type=entity.entity_type,
                        name=entity.name,
                        qualified_name=entity.qualified_name,
                        signature=entity.signature,
                        source_hash=entity.source_hash,
                        file_path=str(entity.file_path),
                        line_number=entity.line_number,
                        existing_docstring=entity.existing_docstring,
                        source_body=entity.source_body,
                        doc_source='existing' if entity.existing_docstring else 'none'
                    ))
                    if entity.parent_qualified_name:
                        parent_links.append(
                            (entity.qualified_name, entity.parent_qualified_name)
                        )
            except Exception as e:
                logger.error("Failed to parse %s: %s", file_path, e)
                continue

        if entities_to_create:
            CodeEntity.objects.bulk_create(entities_to_create, ignore_conflicts=True)

        # Wire up class -> method hierarchy. Parents are parsed from the same
        # batch, so a single qualified_name -> id lookup covers every link.
        if parent_links:
            names = {qn for pair in parent_links for qn in pair}
            id_map = dict(
                CodeEntity.objects
                .filter(snapshot=snapshot, qualified_name__in=names)
                .values_list('qualified_name', 'id')
            )
            updates = []
            for child_qname, parent_qname in parent_links:
                child_id = id_map.get(child_qname)
                parent_id = id_map.get(parent_qname)
                if child_id and parent_id and child_id != parent_id:
                    updates.append(CodeEntity(id=child_id, parent_id=parent_id))
            if updates:
                CodeEntity.objects.bulk_update(updates, ['parent'])

        total_files = len(all_files)
        processed = offset + len(batch_files)
        next_offset = processed if processed < total_files else None

        snapshot.status = 'parsing' if next_offset else 'parsing_complete'
        snapshot.progress_percent = int((processed / max(total_files, 1)) * 30)  # 0-30%
        snapshot.total_entities = CodeEntity.objects.filter(snapshot=snapshot).count()
        snapshot.save()

        return JsonResponse({
            'parsed': len(batch_files),
            'total': total_files,
            'next_offset': next_offset,
            'status': snapshot.status
        })

    except Exception as e:
        logger.error("Parse batch failed: %s", e)
        snapshot.status = 'failed'
        snapshot.error_message = str(e)
        snapshot.save()
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def prepare_docs(request, snapshot_id):
    """
    Prepare doc state for the current snapshot under the review-gate policy.

    - Unchanged code with a prior generated doc: copy forward (doc_source='copied').
    - Changed code with a prior generated doc: keep the old doc but mark it
      stale (doc_source='stale'). The LLM work-set excludes these so the doc
      is NOT silently regenerated. The drift dashboard owns the signal, and
      the user can regenerate per-entity via the regenerate endpoint.
    - New entities or entities with no prior doc: left in the LLM work-set.
    """
    snapshot = get_object_or_404(
        Snapshot,
        id=snapshot_id,
        repository__owner=request.user
    )

    previous = snapshot.repository.snapshots.filter(
        status='complete',
        timestamp__lt=snapshot.timestamp
    ).order_by('-timestamp').first()

    copied_count = 0
    stale_count = 0
    if previous:
        prev_entities = {
            e.qualified_name: e
            for e in previous.entities.all()
        }

        to_update = []
        for curr_entity in snapshot.entities.all():
            prev_entity = prev_entities.get(curr_entity.qualified_name)
            if not prev_entity or not prev_entity.generated_docstring:
                continue

            if curr_entity.source_hash == prev_entity.source_hash:
                # Unchanged: copy the doc forward, no LLM call.
                curr_entity.generated_docstring = prev_entity.generated_docstring
                curr_entity.doc_source = 'copied'
                curr_entity.doc_last_generated = prev_entity.doc_last_generated
                to_update.append(curr_entity)
                copied_count += 1
            else:
                # Changed: keep the prior doc so the user can review what
                # changed, but mark it stale so the drift dashboard flags it
                # and the LLM work-set skips it.
                curr_entity.generated_docstring = prev_entity.generated_docstring
                curr_entity.doc_source = 'stale'
                curr_entity.doc_last_generated = prev_entity.doc_last_generated
                to_update.append(curr_entity)
                stale_count += 1

        if to_update:
            CodeEntity.objects.bulk_update(
                to_update,
                ['generated_docstring', 'doc_source', 'doc_last_generated']
            )

    entities_needing_docs = _entities_needing_docs(snapshot).count()

    snapshot.status = 'generating_docs'
    snapshot.progress_percent = 30
    snapshot.save()

    return JsonResponse({
        'entities_to_document': entities_needing_docs,
        'entities_copied': copied_count,
        'entities_marked_stale': stale_count,
        'status': snapshot.status
    })


@login_required
@require_http_methods(["POST"])
def generate_docs_batch(request, snapshot_id):
    """
    Generate docs for a batch of undocumented entities.

    Cursor-based: the client sends `after_id` (the last entity id it saw)
    and receives `next_after_id` (null when the work-set is exhausted).
    Unlike offset pagination, this stays correct while entities leave the
    work-set as they become documented.
    """
    snapshot = get_object_or_404(
        Snapshot,
        id=snapshot_id,
        repository__owner=request.user
    )

    data, error = parse_json_body(request)
    if error:
        return error
    after_id = max(int(data.get('after_id', 0) or 0), 0)
    limit = min(int(data.get('limit', DOC_GEN_BATCH_SIZE) or DOC_GEN_BATCH_SIZE), MAX_BATCH_LIMIT)

    try:
        entities = list(
            _entities_needing_docs(snapshot)
            .filter(id__gt=after_id)
            .order_by('id')[:limit]
        )

        if not entities:
            # Cursor exhausted. `remaining` > 0 here means prior failures -
            # the client may retry them with a fresh cursor.
            remaining = _entities_needing_docs(snapshot).count()
            snapshot.status = 'docs_complete'
            total_entities = max(snapshot.total_entities, 1)
            snapshot.progress_percent = 30 + int(
                (_documented_count(snapshot) / total_entities) * 60
            )
            snapshot.entities_documented = _documented_count(snapshot)
            snapshot.save()

            return JsonResponse({
                'processed': 0,
                'succeeded': 0,
                'failed': 0,
                'remaining': remaining,
                'next_after_id': None,
                'status': snapshot.status
            })

        snapshot.status = 'generating_docs'
        snapshot.save(update_fields=['status'])

        llm_client = GeminiDocGenerator(api_key=settings.GEMINI_API_KEY)

        def generate_one(entity, index):
            """Worker: LLM call only - no database access from threads."""
            # Stagger worker startup so the burst is spread over ~1.25s
            # for a 5-entity batch. Keeps a free-tier 15 req/min quota
            # from 429ing the whole batch in lockstep.
            if DOC_GEN_WORKER_STAGGER_S > 0 and index > 0:
                time.sleep(index * DOC_GEN_WORKER_STAGGER_S)
            try:
                docstring = llm_client.generate_docstring(
                    entity_type=entity.entity_type,
                    name=entity.name,
                    signature=entity.signature,
                    body=entity.source_body
                )
                return (entity, docstring, None)
            except LLMConfigError as e:
                return (entity, None, e)
            except Exception as e:
                logger.error("Doc generation failed for %s: %s",
                             entity.qualified_name, e)
                return (entity, None, e)

        results = []
        with ThreadPoolExecutor(max_workers=DOC_GEN_MAX_WORKERS) as executor:
            futures = [
                executor.submit(generate_one, e, i)
                for i, e in enumerate(entities)
            ]
            for future in futures:
                results.append(future.result())

        # A configuration error fails every entity - abort the batch.
        config_errors = [err for _, _, err in results if isinstance(err, LLMConfigError)]
        if config_errors:
            message = str(config_errors[0])
            logger.error("Aborting doc generation for snapshot %s: %s", snapshot.id, message)
            snapshot.status = 'failed'
            snapshot.error_message = message
            snapshot.save()
            return JsonResponse({'error': message}, status=502)

        # Single bulk write from the request thread (no concurrent SQLite writes).
        now = timezone.now()
        to_update = []
        for entity, docstring, err in results:
            if docstring:
                entity.generated_docstring = docstring
                entity.doc_source = 'generated'
                entity.doc_last_generated = now
                to_update.append(entity)

        if to_update:
            CodeEntity.objects.bulk_update(
                to_update,
                ['generated_docstring', 'doc_source', 'doc_last_generated']
            )

        succeeded = len(to_update)
        failed = len(entities) - succeeded
        remaining = _entities_needing_docs(snapshot).count()
        next_after_id = entities[-1].id if len(entities) == limit else None

        total_entities = max(snapshot.total_entities, 1)
        documented = _documented_count(snapshot)
        snapshot.progress_percent = 30 + int((documented / total_entities) * 60)
        snapshot.entities_documented = documented
        # Cursor exhausted -> docs_complete even if failures remain; the
        # client decides whether to retry them with a fresh cursor.
        snapshot.status = 'generating_docs' if next_after_id is not None else 'docs_complete'
        snapshot.save()

        return JsonResponse({
            'processed': len(entities),
            'succeeded': succeeded,
            'failed': failed,
            'remaining': remaining,
            'next_after_id': next_after_id,
            'status': snapshot.status
        })

    except Exception as e:
        logger.error("Generate docs batch failed: %s", e)
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def regenerate_entity(request, snapshot_id, entity_id):
    """
    Regenerate a single entity's docstring via the LLM.

    The review-gate path: when an entity is flagged stale_doc, the user
    can ask the model to refresh just that one doc without re-running
    the entire analysis. The new doc replaces the stale one, and the
    stale flag for that entity is removed (since it's no longer stale -
    either the doc is fresh, or the user can decide the new doc matches
    the new code).
    """
    from django.utils import timezone as tz
    from llm.gemini import GeminiDocGenerator
    from llm.base import LLMConfigError

    entity = get_object_or_404(
        CodeEntity,
        id=entity_id,
        snapshot_id=snapshot_id,
        snapshot__repository__owner=request.user,
    )

    try:
        llm_client = GeminiDocGenerator(api_key=settings.GEMINI_API_KEY)
        new_doc = llm_client.generate_docstring(
            entity_type=entity.entity_type,
            name=entity.name,
            signature=entity.signature,
            body=entity.source_body or '',
        )
    except LLMConfigError as e:
        return JsonResponse({'error': str(e)}, status=502)
    except Exception as e:
        logger.error("Per-entity regen failed for %s: %s", entity.qualified_name, e)
        return JsonResponse({'error': str(e)}, status=500)

    entity.generated_docstring = new_doc
    entity.doc_source = 'generated'
    entity.doc_last_generated = tz.now()
    entity.save(update_fields=['generated_docstring', 'doc_source', 'doc_last_generated'])

    # The user has explicitly refreshed the doc, so any stale_doc flag
    # for this entity is no longer a real warning.
    from .models import DriftFlag
    DriftFlag.objects.filter(
        current_entity=entity,
        flag_type='stale_doc',
    ).delete()

    # Refresh documented count on the snapshot.
    snapshot = entity.snapshot
    snapshot.entities_documented = _documented_count(snapshot)
    snapshot.save(update_fields=['entities_documented'])

    return JsonResponse({
        'id': entity.id,
        'doc': new_doc,
        'doc_source': entity.doc_source,
        'doc_last_generated': entity.doc_last_generated.isoformat(),
    })


@login_required
@require_http_methods(["POST"])
def detect_drift(request, snapshot_id):
    """Detect drift between current and previous snapshot."""
    snapshot = get_object_or_404(
        Snapshot,
        id=snapshot_id,
        repository__owner=request.user
    )

    try:
        snapshot.status = 'detecting_drift'
        snapshot.progress_percent = 92
        snapshot.save(update_fields=['status', 'progress_percent'])

        previous = snapshot.repository.snapshots.filter(
            status='complete',
            timestamp__lt=snapshot.timestamp
        ).order_by('-timestamp').first()

        flags_created = 0
        if previous:
            detector = DriftDetector()
            flags_created = detector.detect_drift(previous, snapshot)

        snapshot.status = 'complete'
        snapshot.progress_percent = 100

        # The cloned source is only needed for parsing - clean it up.
        if snapshot.temp_path:
            cleanup_temp_directory(snapshot.temp_path)
            snapshot.temp_path = None

        snapshot.save()

        return JsonResponse({
            'status': 'complete',
            'drift_flags_created': flags_created
        })

    except Exception as e:
        logger.error("Drift detection failed: %s", e)
        snapshot.status = 'failed'
        snapshot.error_message = str(e)
        snapshot.save()
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def analysis_status(request, snapshot_id):
    """Analysis progress page (client-driven pipeline orchestrator)."""
    snapshot = get_object_or_404(
        Snapshot,
        id=snapshot_id,
        repository__owner=request.user
    )

    return render(request, 'analysis/status.html', {
        'snapshot': snapshot
    })


@login_required
@require_http_methods(["GET"])
def analysis_progress(request, snapshot_id):
    """JSON progress endpoint for status polling / resume."""
    snapshot = get_object_or_404(
        Snapshot,
        id=snapshot_id,
        repository__owner=request.user
    )

    return JsonResponse({
        'status': snapshot.status,
        'progress': snapshot.progress_percent,
        'error_message': snapshot.error_message,
        'total_files': snapshot.total_files,
        'total_entities': snapshot.total_entities,
        'entities_documented': snapshot.entities_documented,
    })


@login_required
@require_http_methods(["GET"])
def browse_documentation(request, snapshot_id):
    """View documentation browser."""
    snapshot = get_object_or_404(
        Snapshot,
        id=snapshot_id,
        repository__owner=request.user
    )

    entities = (
        snapshot.entities
        .select_related('parent')
        .order_by('file_path', 'line_number')
    )
    entity_data = [
        {
            'id': e.id,
            'name': e.name,
            'qualified_name': e.qualified_name,
            'entity_type': e.entity_type,
            'signature': e.signature,
            'file_path': e.file_path,
            'line_number': e.line_number,
            'parent_id': e.parent_id,
            'doc': e.generated_docstring or e.existing_docstring or '',
            'doc_source': e.doc_source,
            'body': e.source_body or '',
        }
        for e in entities
    ]

    return render(request, 'analysis/browser.html', {
        'snapshot': snapshot,
        'entities_json': entity_data,
        'total_entities': len(entity_data),
        'documented_count': sum(1 for e in entity_data if e['doc']),
    })


@login_required
@require_http_methods(["GET"])
def drift_dashboard(request, snapshot_id):
    """View drift dashboard."""
    snapshot = get_object_or_404(
        Snapshot,
        id=snapshot_id,
        repository__owner=request.user
    )

    all_flags = list(
        snapshot.drift_flags_as_current
        .select_related('current_entity', 'previous_entity')
        .order_by('flag_type', 'qualified_name')
    )

    grouped = {'stale_doc': [], 'new_undocumented': [],
               'signature_changed': [], 'orphaned_doc': []}
    for flag in all_flags:
        grouped.setdefault(flag.flag_type, []).append(flag)

    # Per-flag diff payloads for the client, keyed by flag id.
    flags_json = {
        str(flag.id): {
            'unified_diff': flag.detail.get('unified_diff', ''),
            'old_source': flag.detail.get('old_source', ''),
            'new_source': flag.detail.get('new_source', ''),
            'old_doc': flag.detail.get('old_doc', ''),
            'new_doc': flag.detail.get('new_doc', ''),
            'file_path': flag.detail.get('file_path', ''),
        }
        for flag in all_flags
        if flag.flag_type in ('stale_doc', 'signature_changed')
    }

    return render(request, 'analysis/drift.html', {
        'snapshot': snapshot,
        'stale_count': len(grouped['stale_doc']),
        'new_count': len(grouped['new_undocumented']),
        'signature_count': len(grouped['signature_changed']),
        'orphaned_count': len(grouped['orphaned_doc']),
        'stale_flags': grouped['stale_doc'],
        'new_flags': grouped['new_undocumented'],
        'signature_flags': grouped['signature_changed'],
        'orphaned_flags': grouped['orphaned_doc'],
        'flags_json': flags_json,
    })
