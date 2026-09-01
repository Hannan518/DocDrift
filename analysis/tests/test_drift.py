import pytest
from django.contrib.auth.models import User
from repositories.models import Repository
from analysis.models import Snapshot, CodeEntity, DriftFlag
from analysis.drift_detector import DriftDetector


@pytest.fixture
def user(db):
    return User.objects.create_user(username='testuser', password='testpass')


@pytest.fixture
def repository(user):
    return Repository.objects.create(
        owner=user,
        name='test-repo',
        source_type='github',
        github_url='https://github.com/test/repo'
    )


@pytest.fixture
def detector():
    return DriftDetector()


class TestDriftDetector:
    """Tests for drift detection."""
    
    def test_new_undocumented_entity(self, detector, repository):
        # Create snapshots
        prev_snapshot = Snapshot.objects.create(
            repository=repository,
            status='complete'
        )
        curr_snapshot = Snapshot.objects.create(
            repository=repository,
            status='complete'
        )
        
        # Previous has one entity
        CodeEntity.objects.create(
            snapshot=prev_snapshot,
            entity_type='function',
            name='old_func',
            qualified_name='module.old_func',
            signature='def old_func()',
            source_hash='hash1',
            file_path='module.py',
            line_number=1,
            doc_source='generated'
        )
        
        # Current has old entity + new entity
        CodeEntity.objects.create(
            snapshot=curr_snapshot,
            entity_type='function',
            name='old_func',
            qualified_name='module.old_func',
            signature='def old_func()',
            source_hash='hash1',
            file_path='module.py',
            line_number=1,
            doc_source='copied'
        )
        CodeEntity.objects.create(
            snapshot=curr_snapshot,
            entity_type='function',
            name='new_func',
            qualified_name='module.new_func',
            signature='def new_func()',
            source_hash='hash2',
            file_path='module.py',
            line_number=10,
            doc_source='generated'
        )
        
        # Detect drift
        count = detector.detect_drift(prev_snapshot, curr_snapshot)
        
        assert count == 1
        flags = DriftFlag.objects.filter(current_snapshot=curr_snapshot)
        assert flags.count() == 1
        assert flags.first().flag_type == 'new_undocumented'
        assert flags.first().qualified_name == 'module.new_func'
    
    def test_stale_doc_flag(self, detector, repository):
        prev_snapshot = Snapshot.objects.create(
            repository=repository,
            status='complete'
        )
        curr_snapshot = Snapshot.objects.create(
            repository=repository,
            status='complete'
        )
        
        # Previous entity
        prev_entity = CodeEntity.objects.create(
            snapshot=prev_snapshot,
            entity_type='function',
            name='changed_func',
            qualified_name='module.changed_func',
            signature='def changed_func()',
            source_hash='old_hash',
            file_path='module.py',
            line_number=1,
            doc_source='generated',
            generated_docstring='Old doc'
        )
        
        # Current entity with changed code but copied doc
        curr_entity = CodeEntity.objects.create(
            snapshot=curr_snapshot,
            entity_type='function',
            name='changed_func',
            qualified_name='module.changed_func',
            signature='def changed_func()',
            source_hash='new_hash',  # Changed!
            file_path='module.py',
            line_number=1,
            doc_source='copied',
            generated_docstring='Old doc'
        )
        
        count = detector.detect_drift(prev_snapshot, curr_snapshot)
        
        assert count >= 1
        stale_flags = DriftFlag.objects.filter(
            current_snapshot=curr_snapshot,
            flag_type='stale_doc'
        )
        assert stale_flags.count() == 1
        flag = stale_flags.first()
        assert flag.detail['old_hash'] == 'old_hash'
        assert flag.detail['new_hash'] == 'new_hash'
    
    def test_signature_changed_flag(self, detector, repository):
        prev_snapshot = Snapshot.objects.create(
            repository=repository,
            status='complete'
        )
        curr_snapshot = Snapshot.objects.create(
            repository=repository,
            status='complete'
        )
        
        # Previous entity
        CodeEntity.objects.create(
            snapshot=prev_snapshot,
            entity_type='function',
            name='func',
            qualified_name='module.func',
            signature='def func(x)',
            source_hash='hash1',
            file_path='module.py',
            line_number=1
        )
        
        # Current with changed signature
        CodeEntity.objects.create(
            snapshot=curr_snapshot,
            entity_type='function',
            name='func',
            qualified_name='module.func',
            signature='def func(x, y)',  # Changed!
            source_hash='hash1',
            file_path='module.py',
            line_number=1
        )
        
        count = detector.detect_drift(prev_snapshot, curr_snapshot)
        
        sig_flags = DriftFlag.objects.filter(
            current_snapshot=curr_snapshot,
            flag_type='signature_changed'
        )
        assert sig_flags.count() == 1
        flag = sig_flags.first()
        assert flag.detail['old_signature'] == 'def func(x)'
        assert flag.detail['new_signature'] == 'def func(x, y)'
    
    def test_orphaned_doc_flag(self, detector, repository):
        prev_snapshot = Snapshot.objects.create(
            repository=repository,
            status='complete'
        )
        curr_snapshot = Snapshot.objects.create(
            repository=repository,
            status='complete'
        )

        # Previous has documented entity (entity must have docs to be orphaned)
        CodeEntity.objects.create(
            snapshot=prev_snapshot,
            entity_type='function',
            name='removed_func',
            qualified_name='module.removed_func',
            signature='def removed_func()',
            source_hash='hash1',
            file_path='module.py',
            line_number=1,
            doc_source='generated',
            generated_docstring='Old doc for removed function',
        )

        # Current snapshot is empty (function removed)

        count = detector.detect_drift(prev_snapshot, curr_snapshot)

        assert count == 1
        orphan_flags = DriftFlag.objects.filter(
            current_snapshot=curr_snapshot,
            flag_type='orphaned_doc'
        )
        assert orphan_flags.count() == 1
        assert orphan_flags.first().qualified_name == 'module.removed_func'

    def test_orphaned_no_flag_when_undocumented(self, detector, repository):
        """Removed entity that never had docs should not produce a flag."""
        prev_snapshot = Snapshot.objects.create(
            repository=repository, status='complete'
        )
        curr_snapshot = Snapshot.objects.create(
            repository=repository, status='complete'
        )

        CodeEntity.objects.create(
            snapshot=prev_snapshot,
            entity_type='function',
            name='undoc_removed',
            qualified_name='module.undoc_removed',
            signature='def undoc_removed()',
            source_hash='h',
            file_path='module.py',
            line_number=1,
        )

        count = detector.detect_drift(prev_snapshot, curr_snapshot)
        assert count == 0

    def test_idempotent_on_rerun(self, detector, repository):
        """Running detect_drift twice should not duplicate flags."""
        prev = Snapshot.objects.create(repository=repository, status='complete')
        curr = Snapshot.objects.create(repository=repository, status='complete')

        for snapshot in (prev, curr):
            CodeEntity.objects.create(
                snapshot=snapshot,
                entity_type='function',
                name='f',
                qualified_name='m.f',
                signature='def f()',
                source_hash='h1',
                file_path='m.py',
                line_number=1,
            )
        CodeEntity.objects.create(
            snapshot=curr,
            entity_type='function',
            name='g',
            qualified_name='m.g',
            signature='def g()',
            source_hash='h2',
            file_path='m.py',
            line_number=10,
        )

        first = detector.detect_drift(prev, curr)
        second = detector.detect_drift(prev, curr)
        assert first == second
        assert DriftFlag.objects.filter(current_snapshot=curr).count() == first

    def test_new_entity_with_doc_no_flag(self, detector, repository):
        """A new entity that already has docs should not be flagged."""
        prev = Snapshot.objects.create(repository=repository, status='complete')
        curr = Snapshot.objects.create(repository=repository, status='complete')

        CodeEntity.objects.create(
            snapshot=curr,
            entity_type='function',
            name='new_documented',
            qualified_name='m.new_documented',
            signature='def new_documented()',
            source_hash='h',
            file_path='m.py',
            line_number=1,
            doc_source='generated',
            generated_docstring='Already documented',
        )

        count = detector.detect_drift(prev, curr)
        assert count == 0
    
    def test_no_drift_when_unchanged(self, detector, repository):
        prev_snapshot = Snapshot.objects.create(
            repository=repository,
            status='complete'
        )
        curr_snapshot = Snapshot.objects.create(
            repository=repository,
            status='complete'
        )
        
        # Same entity in both snapshots
        for snapshot in [prev_snapshot, curr_snapshot]:
            CodeEntity.objects.create(
                snapshot=snapshot,
                entity_type='function',
                name='unchanged_func',
                qualified_name='module.unchanged_func',
                signature='def unchanged_func()',
                source_hash='same_hash',
                file_path='module.py',
                line_number=1
            )
        
        count = detector.detect_drift(prev_snapshot, curr_snapshot)
        
        # No flags should be created
        assert count == 0
        assert DriftFlag.objects.filter(current_snapshot=curr_snapshot).count() == 0
