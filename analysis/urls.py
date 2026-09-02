from django.urls import path
from . import views

app_name = 'analysis'

urlpatterns = [
    path('<int:snapshot_id>/status/', views.analysis_status, name='status'),
    path('<int:snapshot_id>/progress/', views.analysis_progress, name='progress'),
    path('<int:snapshot_id>/parse-batch/', views.parse_batch, name='parse_batch'),
    path('<int:snapshot_id>/prepare-docs/', views.prepare_docs, name='prepare_docs'),
    path('<int:snapshot_id>/generate-docs-batch/', views.generate_docs_batch, name='generate_docs_batch'),
    path('<int:snapshot_id>/entities/<int:entity_id>/regenerate/', views.regenerate_entity, name='regenerate_entity'),
    path('<int:snapshot_id>/detect-drift/', views.detect_drift, name='detect_drift'),
    path('<int:snapshot_id>/browser/', views.browse_documentation, name='browser'),
    path('<int:snapshot_id>/drift/', views.drift_dashboard, name='drift'),
]
