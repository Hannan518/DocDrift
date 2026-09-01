from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils import timezone
import json
import logging

from .models import Repository
from .ingestion import clone_github_repo, extract_zip_upload, list_python_files
from .validators import validate_github_url, validate_upload_file, validate_file_count
from analysis.models import Snapshot
from analysis.constants import MAX_FILES_TO_PARSE

logger = logging.getLogger(__name__)


@login_required
@require_http_methods(["GET", "POST"])
def submit_repository(request):
    """Submit a repository for analysis."""
    if request.method == "POST":
        data = json.loads(request.body)
        
        name = data.get('name')
        source_type = data.get('source_type')
        
        if not name:
            return JsonResponse({'error': 'Repository name is required'}, status=400)
        
        # Validate based on source type
        if source_type == 'github':
            github_url = data.get('github_url')
            is_valid, message = validate_github_url(github_url)
            if not is_valid:
                return JsonResponse({'error': message}, status=400)
            
            # Create repository
            repository = Repository.objects.create(
                owner=request.user,
                name=name,
                source_type='github',
                github_url=github_url
            )
        
        elif source_type == 'upload':
            # For file uploads, we'll handle via a separate endpoint
            return JsonResponse({'error': 'File upload not yet implemented'}, status=400)
        
        else:
            return JsonResponse({'error': 'Invalid source type'}, status=400)
        
        # Create initial snapshot
        snapshot = Snapshot.objects.create(
            repository=repository,
            status='pending'
        )
        
        return JsonResponse({
            'repository_id': repository.id,
            'snapshot_id': snapshot.id,
            'status': 'pending'
        })
    
    # GET request - show form
    return render(request, 'repositories/submit.html')


@login_required
@require_http_methods(["POST"])
def prepare_analysis(request, snapshot_id):
    """
    Prepare analysis: clone/extract repo, validate file count.
    Must complete in <10 seconds.
    """
    snapshot = get_object_or_404(
        Snapshot,
        id=snapshot_id,
        repository__owner=request.user
    )
    
    if snapshot.status != 'pending':
        return JsonResponse({'error': 'Snapshot already processed'}, status=400)
    
    try:
        # Clone or extract
        if snapshot.repository.source_type == 'github':
            temp_path = clone_github_repo(snapshot.repository.github_url)
        else:
            temp_path = extract_zip_upload(snapshot.repository.upload_file)
        
        # Validate file count
        python_files = list_python_files(temp_path)
        is_valid, message = validate_file_count(python_files)
        
        if not is_valid:
            snapshot.status = 'failed'
            snapshot.error_message = message
            snapshot.save()
            return JsonResponse({'error': message}, status=400)
        
        # Store temp path and file count
        snapshot.temp_path = temp_path
        snapshot.total_files = len(python_files)
        snapshot.status = 'ready_to_parse'
        snapshot.save()
        
        return JsonResponse({
            'status': 'ready',
            'total_files': len(python_files)
        })
    
    except Exception as e:
        logger.error(f"Prepare analysis failed: {e}")
        snapshot.status = 'failed'
        snapshot.error_message = str(e)
        snapshot.save()
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def list_repositories(request):
    """List user's repositories."""
    repositories = Repository.objects.filter(owner=request.user)
    return render(request, 'repositories/list.html', {
        'repositories': repositories
    })


@login_required
@require_http_methods(["GET"])
def repository_detail(request, repository_id):
    """View repository details and snapshots."""
    repository = get_object_or_404(
        Repository,
        id=repository_id,
        owner=request.user
    )
    snapshots = repository.snapshots.all()[:10]  # Latest 10
    
    return render(request, 'repositories/detail.html', {
        'repository': repository,
        'snapshots': snapshots
    })
