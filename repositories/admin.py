from django.contrib import admin
from .models import Repository


@admin.register(Repository)
class RepositoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'owner', 'source_type', 'created_at']
    list_filter = ['source_type', 'created_at']
    search_fields = ['name', 'owner__username']
    raw_id_fields = ['owner']
