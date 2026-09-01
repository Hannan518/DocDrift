from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.conf import settings
import json
import logging
from pathlib import Path

from .models import Snapshot, CodeEntity, DriftFlag
from .parser import PythonASTParser
from .drift_detector import DriftDetector
from .constants import PARSING_BATCH_SIZE, DOC_GEN_BATCH_SIZE
from repositories.ingestion import list_python_files
from llm.gemini import GeminiDocGenerator

logger = logging.getLogger(__name__)


@login_required
@require_http_methods(["POST"])
def parse_batch(request, snapshot_id):
    """Parse a batch of Python files."""
    snapshot = get_object_or_404(
        Snapshot,
        id=snapshot_id,
        repository__owner=request.user
    )
    
    data = json.loads(request.body)
    offset = data.get('offset', 0)
    limit = data.get('limit', PARSING_BATCH_SIZE)
    
    try:
        # Get list of Python files
        all_files = list_python_files(snapshot.temp_path)
        batch_files = all_files[offset:offset + limit]
        
        if not batch_files:
            return JsonResponse({
                'parsed': 0,
                'total': len(all_files),
                'next_offset': None,
                'status': 'parsing_complete'
            })
        
        # Parse files
        parser = PythonASTParser()
        entities_to_create = []
        
        for file_path in batch_files:
            try:
                parsed_entities = parser.parse_file(file_path)
                
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
                        doc_source='none'
                    ))
            except Exception as e:
                logger.error(f"Failed to parse {file_path}: {e}")
                continue
        
        # Bulk create entities
        if entities_to_create:
            CodeEntity.objects.bulk_create(entities_to_create)
        
        # Update snapshot
        total_files = len(all_files)
        processed = offset + len(batch_files)
        next_offset = processed if processed < total_files else None
        
        snapshot.status = 'parsing' if next_offset else 'parsing_complete'
        snapshot.progress_percent = int((processed / total_files) * 30)  # 0-30%
        snapshot.total_entities = CodeEntity.objects.filter(snapshot=snapshot).count()
        snapshot.save()
        
        return JsonResponse({
            'parsed': len(batch_files),
            'total': total_files,
            'next_offset': next_offset,
            'status': snapshot.status
        })
    
    except Exception as e:
        logger.error(f"Parse batch failed: {e}")
        snapshot.status = 'failed'
        snapshot.error_message = str(e)
        snapshot.save()
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def prepare_docs(request, snapshot_id):
    """Copy forward unchanged docs from previous snapshot."""
    snapshot = get_object_or_404(
        Snapshot,
        id=snapshot_id,
        repository__owner=request.user
    )
    
    # Get previous snapshot
    previous = snapshot.repository.snapshots.filter(
        status='complete',
        timestamp__lt=snapshot.timestamp
    ).order_by('-timestamp').first()
    
    if not previous:
        # First snapshot - all entities need doc generation
        entities_needing_docs = snapshot.entities.filter(
            generated_docstring__isnull=True,
            existing_docstring__isnull=True
        ).count()
        
        return JsonResponse({
            'entities_to_document': entities_needing_docs,
            'entities_copied': 0
        })
    
    # Build previous entity map
    prev_entities = {
        e.qualified_name: e 
        for e in previous.entities.select_related()
    }
    
    copied_count = 0
    current_entities = snapshot.entities.all()
    
    for curr_entity in current_entities:
        prev_entity = prev_entities.get(curr_entity.qualified_name)
        
        if prev_entity and curr_entity.source_hash == prev_entity.source_hash:
            # Code unchanged - copy documentation forward
            curr_entity.generated_docstring = prev_entity.generated_docstring
            curr_entity.doc_source = 'copied'
            curr_entity.doc_last_generated = prev_entity.doc_last_generated
            curr_entity.save()
            copied_count += 1
    
    entities_needing_docs = snapshot.entities.filter(
        generated_docstring__isnull=True,
        existing_docstring__isnull=True
    ).count()
    
    return JsonResponse({
        'entities_to_document': entities_needing_docs,
        'entities_copied': copied_count
    })


@login_required
@require_http_methods(["POST"])
def generate_docs_batch(request, snapshot_id):
    """Generate docs for a batch of entities (only NEW entities)."""
    snapshot = get_object_or_404(
        Snapshot,
        id=snapshot_id,
        repository__owner=request.user
    )
    
    data = json.loads(request.body)
    offset = data.get('offset', 0)
    limit = data.get('limit', DOC_GEN_BATCH_SIZE)
    
    try:
        # Only generate for NEW entities (not ones with copied stale docs)
        previous = snapshot.repository.snapshots.filter(
            status='complete',
            timestamp__lt=snapshot.timestamp
        ).order_by('-timestamp').first()
        
        if previous:
            prev_qualified_names = set(
                previous.entities.values_list('qualified_name', flat=True)
            )
            
            # Only generate for genuinely new entities
            entities = snapshot.entities.filter(
                generated_docstring__isnull=True,
                existing_docstring__isnull=True
            ).exclude(
                qualified_name__in=prev_qualified_names
            ).order_by('id')[offset:offset + limit]
        else:
            # First snapshot - generate for all
            entities = snapshot.entities.filter(
                generated_docstring__isnull=True,
                existing_docstring__isnull=True
            ).order_by('id')[offset:offset + limit]
        
        if not entities:
            return JsonResponse({
                'processed': 0,
                'remaining': 0,
                'status': 'docs_complete'
            })
        
        # Generate docs
        llm_client = GeminiDocGenerator(api_key=settings.GEMINI_API_KEY)
        
        for entity in entities:
            try:
                entity.generated_docstring = llm_client.generate_docstring(
                    entity_type=entity.entity_type,
                    name=entity.name,
                    signature=entity.signature,
                    body=entity.source_body
                )
                entity.doc_source = 'generated'
                entity.doc_last_generated = timezone.now()
                entity.save()
            except Exception as e:
                logger.error(f"Doc generation failed for {entity.qualified_name}: {e}")
                # Continue with next entity
        
        # Count remaining
        total_remaining = snapshot.entities.filter(
            generated_docstring__isnull=True,
            existing_docstring__isnull=True
        ).count()
        
        # Update progress (30-90% for doc generation)
        total_entities = snapshot.total_entities or 1
        documented = snapshot.entities.exclude(generated_docstring__isnull=True).count()
        snapshot.progress_percent = 30 + int((documented / total_entities) * 60)
        snapshot.status = 'generating_docs' if total_remaining > 0 else 'docs_complete'
        snapshot.entities_documented = documented
        snapshot.save()
        
        return JsonResponse({
            'processed': len(entities),
            'remaining': total_remaining,
            'status': snapshot.status
        })
    
    except Exception as e:
        logger.error(f"Generate docs batch failed: {e}")
        return JsonResponse({'error': str(e)}, status=500)


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
        snapshot.progress_percent = 90
        snapshot.save()
        
        # Get previous snapshot
        previous = snapshot.repository.snapshots.filter(
            status='complete',
            timestamp__lt=snapshot.timestamp
        ).order_by('-timestamp').first()
        
        if not previous:
            # No previous snapshot - mark complete
            snapshot.status = 'complete'
            snapshot.progress_percent = 100
            snapshot.save()
            
            return JsonResponse({
                'status': 'complete',
                'drift_flags_created': 0
            })
        
        # Detect drift
        detector = DriftDetector()
        flags_created = detector.detect_drift(previous, snapshot)
        
        # Mark complete
        snapshot.status = 'complete'
        snapshot.progress_percent = 100
        snapshot.save()
        
        return JsonResponse({
            'status': 'complete',
            'drift_flags_created': flags_created
        })
    
    except Exception as e:
        logger.error(f"Drift detection failed: {e}")
        snapshot.status = 'failed'
        snapshot.error_message = str(e)
        snapshot.save()
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def analysis_status(request, snapshot_id):
    """Get analysis status."""
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
def browse_documentation(request, snapshot_id):
    """View documentation browser."""
    snapshot = get_object_or_404(
        Snapshot,
        id=snapshot_id,
        repository__owner=request.user
    )
    
    return render(request, 'analysis/browser.html', {
        'snapshot': snapshot
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
    
    return render(request, 'analysis/drift.html', {
        'snapshot': snapshot
    })
