from django.db import models
from django.utils import timezone


class Snapshot(models.Model):
    """Snapshot of a repository at a point in time."""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('parsing', 'Parsing Code'),
        ('parsing_complete', 'Parsing Complete'),
        ('generating_docs', 'Generating Documentation'),
        ('docs_complete', 'Documentation Complete'),
        ('detecting_drift', 'Detecting Drift'),
        ('complete', 'Complete'),
        ('failed', 'Failed'),
    ]
    
    repository = models.ForeignKey(
        'repositories.Repository',
        on_delete=models.CASCADE,
        related_name='snapshots'
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error_message = models.TextField(null=True, blank=True)
    progress_percent = models.IntegerField(default=0)
    total_files = models.IntegerField(default=0)
    total_entities = models.IntegerField(default=0)
    entities_documented = models.IntegerField(default=0)
    commit_hash = models.CharField(max_length=40, null=True, blank=True)
    temp_path = models.CharField(max_length=512, null=True, blank=True)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['repository', '-timestamp']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f"{self.repository.name} - {self.timestamp.strftime('%Y-%m-%d %H:%M')}"


class CodeEntity(models.Model):
    """A code entity (module, class, function) extracted from a repository."""
    
    ENTITY_TYPES = [
        ('module', 'Module'),
        ('class', 'Class'),
        ('function', 'Function'),
    ]
    
    DOC_SOURCE_CHOICES = [
        ('generated', 'LLM Generated'),
        ('copied', 'Copied from Previous Snapshot'),
        ('existing', 'Existing in Source Code'),
        ('none', 'No Documentation'),
    ]
    
    snapshot = models.ForeignKey(Snapshot, on_delete=models.CASCADE, related_name='entities')
    entity_type = models.CharField(max_length=10, choices=ENTITY_TYPES)
    name = models.CharField(max_length=255)
    qualified_name = models.CharField(max_length=1024)
    signature = models.TextField()
    source_hash = models.CharField(max_length=64)
    file_path = models.CharField(max_length=512)
    line_number = models.IntegerField()
    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='children'
    )
    existing_docstring = models.TextField(null=True, blank=True)
    generated_docstring = models.TextField(null=True, blank=True)
    doc_source = models.CharField(max_length=10, choices=DOC_SOURCE_CHOICES, default='none')
    doc_last_generated = models.DateTimeField(null=True, blank=True)
    source_body = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = [['snapshot', 'qualified_name']]
        indexes = [
            models.Index(fields=['snapshot', 'entity_type']),
            models.Index(fields=['snapshot', 'qualified_name']),
        ]
    
    def __str__(self):
        return f"{self.entity_type}: {self.qualified_name}"


class DriftFlag(models.Model):
    """Flag indicating documentation drift between snapshots."""
    
    FLAG_TYPES = [
        ('stale_doc', 'Stale Documentation'),
        ('new_undocumented', 'New Undocumented Code'),
        ('orphaned_doc', 'Orphaned Documentation'),
        ('signature_changed', 'Signature Changed'),
    ]
    
    repository = models.ForeignKey(
        'repositories.Repository',
        on_delete=models.CASCADE,
        related_name='drift_flags'
    )
    flag_type = models.CharField(max_length=20, choices=FLAG_TYPES)
    qualified_name = models.CharField(max_length=1024)
    previous_snapshot = models.ForeignKey(
        Snapshot,
        null=True,
        on_delete=models.SET_NULL,
        related_name='drift_flags_as_previous'
    )
    current_snapshot = models.ForeignKey(
        Snapshot,
        on_delete=models.CASCADE,
        related_name='drift_flags_as_current'
    )
    previous_entity = models.ForeignKey(
        CodeEntity,
        null=True,
        on_delete=models.SET_NULL,
        related_name='drift_flags_previous'
    )
    current_entity = models.ForeignKey(
        CodeEntity,
        null=True,
        on_delete=models.SET_NULL,
        related_name='drift_flags_current'
    )
    detail = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['flag_type', 'qualified_name']
        indexes = [
            models.Index(fields=['repository', 'current_snapshot']),
            models.Index(fields=['flag_type']),
        ]
    
    def __str__(self):
        return f"{self.flag_type}: {self.qualified_name}"
