from django.contrib import admin
from .models import Snapshot, CodeEntity, DriftFlag


@admin.register(Snapshot)
class SnapshotAdmin(admin.ModelAdmin):
    list_display = ['repository', 'status', 'timestamp', 'progress_percent']
    list_filter = ['status', 'timestamp']
    search_fields = ['repository__name']
    raw_id_fields = ['repository']


@admin.register(CodeEntity)
class CodeEntityAdmin(admin.ModelAdmin):
    list_display = ['name', 'entity_type', 'qualified_name', 'doc_source', 'snapshot']
    list_filter = ['entity_type', 'doc_source']
    search_fields = ['name', 'qualified_name']
    raw_id_fields = ['snapshot', 'parent']


@admin.register(DriftFlag)
class DriftFlagAdmin(admin.ModelAdmin):
    list_display = ['flag_type', 'qualified_name', 'current_snapshot', 'created_at']
    list_filter = ['flag_type', 'created_at']
    search_fields = ['qualified_name']
    raw_id_fields = ['current_snapshot', 'previous_snapshot']
