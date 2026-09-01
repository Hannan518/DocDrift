from django.db import models
from django.contrib.auth.models import User


class Repository(models.Model):
    """Repository model for storing GitHub or uploaded codebases."""
    
    SOURCE_TYPES = [
        ('github', 'GitHub URL'),
        ('upload', 'Zip Upload'),
    ]
    
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='repositories')
    name = models.CharField(max_length=255)
    source_type = models.CharField(max_length=10, choices=SOURCE_TYPES)
    github_url = models.URLField(null=True, blank=True)
    upload_file = models.FileField(upload_to='uploads/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        unique_together = [['owner', 'name']]
        indexes = [
            models.Index(fields=['owner', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.owner.username}/{self.name}"
