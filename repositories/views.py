from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import Count, Prefetch

from capstone.utils import parse_json_body
from .models import Repository
from .ingestion import clone_github_repo, list_python_files, cleanup_temp_directory
from .validators import validate_github_url, validate_file_count
from analysis.models import Snapshot

from git import Repo as GitRepo
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


@login_required
@require_http_methods(["GET", "POST"])
def submit_repository(request):
    """Submit a repository for analysis."""
    if request.method == "POST":
        data, error = parse_json_body(request)
        if error:
            return error

        name = (data.get('name') or '').strip()
        github_url = (data.get('github_url') or '').strip()

        if not name:
            return JsonResponse({'error': 'Repository name is required'}, status=400)
        if len(name) > 255:
            return JsonResponse({'error': 'Repository name is too long'}, status=400)

        is_valid, message = validate_github_url(github_url)
        if not is_valid:
            return JsonResponse({'error': message}, status=400)

        # Reuse an existing repository with the same name instead of
        # creating silent duplicates - each submission starts a new snapshot.
        try:
            repository, created = Repository.objects.get_or_create(
                owner=request.user,
                name=name,
                defaults={'source_type': 'github', 'github_url': github_url},
            )
        except Exception:
            return JsonResponse(
                {'error': 'A repository with this name already exists'},
                status=409
            )

        # Keep the stored URL current if the user submits the same name
        # with a different URL.
        if not created and github_url and repository.github_url != github_url:
            repository.github_url = github_url
            repository.save(update_fields=['github_url'])

        snapshot = Snapshot.objects.create(
            repository=repository,
            status='pending'
        )

        return JsonResponse({
            'repository_id': repository.id,
            'snapshot_id': snapshot.id,
            'status': 'pending',
            'existing_repository': not created,
        })

    # GET request - show form
    return render(request, 'repositories/submit.html')


@login_required
@require_http_methods(["POST"])
def prepare_analysis(request, snapshot_id):
    """
    Prepare analysis: clone the repo, validate the file count.
    Must complete in <10 seconds (shallow clone).
    """
    snapshot = get_object_or_404(
        Snapshot,
        id=snapshot_id,
        repository__owner=request.user
    )

    if snapshot.status != 'pending':
        return JsonResponse(
            {'error': 'Snapshot already processed', 'status': snapshot.status},
            status=400
        )

    try:
        temp_path = clone_github_repo(snapshot.repository.github_url)
    except Exception as e:
        logger.error("Prepare analysis failed: %s", e)
        snapshot.status = 'failed'
        snapshot.error_message = str(e)
        snapshot.save()
        return JsonResponse({'error': str(e)}, status=500)

    try:
        python_files = list_python_files(temp_path)

        is_valid, message = validate_file_count(python_files)
        if not is_valid:
            cleanup_temp_directory(temp_path)
            snapshot.status = 'failed'
            snapshot.error_message = message
            snapshot.save()
            return JsonResponse({'error': message}, status=400)

        if not python_files:
            cleanup_temp_directory(temp_path)
            message = "No Python files found in the repository"
            snapshot.status = 'failed'
            snapshot.error_message = message
            snapshot.save()
            return JsonResponse({'error': message}, status=400)

        # Capture git metadata for the UI.
        try:
            snapshot.commit_hash = GitRepo(temp_path).head.commit.hexsha
        except Exception:
            snapshot.commit_hash = None

        snapshot.temp_path = temp_path
        snapshot.total_files = len(python_files)
        snapshot.status = 'ready_to_parse'
        snapshot.save()

        return JsonResponse({
            'status': 'ready_to_parse',
            'total_files': len(python_files),
            'commit_hash': snapshot.commit_hash or ''
        })

    except Exception as e:
        logger.error("Prepare analysis failed: %s", e)
        cleanup_temp_directory(temp_path)
        snapshot.status = 'failed'
        snapshot.error_message = str(e)
        snapshot.save()
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def list_repositories(request):
    """List the user's repositories with their latest snapshot."""
    repositories = (
        Repository.objects
        .filter(owner=request.user)
        .annotate(snapshot_count=Count('snapshots', distinct=True))
        .prefetch_related(
            Prefetch('snapshots', queryset=Snapshot.objects.order_by('-timestamp'))
        )
    )
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
    snapshots = (
        repository.snapshots
        .annotate(drift_count=Count('drift_flags_as_current'))
        .order_by('-timestamp')[:10]
    )

    return render(request, 'repositories/detail.html', {
        'repository': repository,
        'snapshots': snapshots
    })


@login_required
@require_http_methods(["POST"])
def reanalyze_repository(request, repository_id):
    """Create a fresh snapshot for an existing repository."""
    repository = get_object_or_404(
        Repository,
        id=repository_id,
        owner=request.user
    )

    # Only one recently-started analysis per repository at a time. Stale
    # snapshots from abandoned tabs older than 30 minutes don't block.
    if repository.snapshots.filter(
        status__in=['pending', 'ready_to_parse', 'parsing', 'parsing_complete',
                    'generating_docs', 'docs_complete', 'detecting_drift'],
        timestamp__gte=timezone.now() - timedelta(minutes=30)
    ).exists():
        return JsonResponse(
            {'error': 'An analysis is already in progress for this repository'},
            status=409
        )

    snapshot = Snapshot.objects.create(
        repository=repository,
        status='pending'
    )

    return JsonResponse({
        'snapshot_id': snapshot.id,
        'status': 'pending'
    })


@login_required
@require_http_methods(["POST"])
def delete_repository(request, repository_id):
    """Delete a repository, its snapshots, and any cloned temp directories."""
    repository = get_object_or_404(
        Repository,
        id=repository_id,
        owner=request.user
    )

    for snapshot in repository.snapshots.only('temp_path'):
        if snapshot.temp_path:
            cleanup_temp_directory(snapshot.temp_path)

    repository.delete()

    return JsonResponse({'status': 'deleted'})
