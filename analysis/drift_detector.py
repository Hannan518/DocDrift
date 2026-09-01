"""Drift detection module for comparing snapshots."""

import logging
from typing import List

from .models import Snapshot, CodeEntity, DriftFlag

logger = logging.getLogger(__name__)


class DriftDetector:
    """Detects documentation drift between snapshots."""
    
    def detect_drift(
        self,
        previous_snapshot: Snapshot,
        current_snapshot: Snapshot
    ) -> int:
        """
        Compare two snapshots and create DriftFlag records.
        
        Args:
            previous_snapshot: Earlier snapshot to compare against
            current_snapshot: Current snapshot to check for drift
        
        Returns:
            Number of drift flags created
        """
        # Build maps for O(1) lookups
        prev_entities = {
            e.qualified_name: e 
            for e in previous_snapshot.entities.all()
        }
        curr_entities = {
            e.qualified_name: e 
            for e in current_snapshot.entities.all()
        }
        
        flags = []
        
        # Check current entities
        for qname, curr_entity in curr_entities.items():
            if qname not in prev_entities:
                # NEW UNDOCUMENTED
                flags.append(self._create_new_undocumented_flag(
                    current_snapshot,
                    previous_snapshot,
                    curr_entity
                ))
            else:
                prev_entity = prev_entities[qname]
                
                # STALE DOC: body changed but doc is outdated (copied)
                if curr_entity.source_hash != prev_entity.source_hash:
                    flags.append(self._create_stale_doc_flag(
                        current_snapshot,
                        previous_snapshot,
                        prev_entity,
                        curr_entity
                    ))
                
                # SIGNATURE CHANGED: signature differs
                if curr_entity.signature != prev_entity.signature:
                    flags.append(self._create_signature_changed_flag(
                        current_snapshot,
                        previous_snapshot,
                        prev_entity,
                        curr_entity
                    ))
        
        # Check for orphaned entities
        for qname, prev_entity in prev_entities.items():
            if qname not in curr_entities:
                # ORPHANED DOC
                flags.append(self._create_orphaned_doc_flag(
                    current_snapshot,
                    previous_snapshot,
                    prev_entity
                ))
        
        # Bulk create
        if flags:
            DriftFlag.objects.bulk_create(flags)
            logger.info(f"Created {len(flags)} drift flags for snapshot {current_snapshot.id}")
        
        return len(flags)
    
    def _create_new_undocumented_flag(
        self,
        current_snapshot: Snapshot,
        previous_snapshot: Snapshot,
        curr_entity: CodeEntity
    ) -> DriftFlag:
        """Create flag for new undocumented code."""
        return DriftFlag(
            repository=current_snapshot.repository,
            flag_type='new_undocumented',
            qualified_name=curr_entity.qualified_name,
            previous_snapshot=previous_snapshot,
            current_snapshot=current_snapshot,
            previous_entity=None,
            current_entity=curr_entity,
            detail={
                'signature': curr_entity.signature,
                'file_path': curr_entity.file_path,
                'line_number': curr_entity.line_number,
                'doc_status': curr_entity.doc_source,
            }
        )
    
    def _create_stale_doc_flag(
        self,
        current_snapshot: Snapshot,
        previous_snapshot: Snapshot,
        prev_entity: CodeEntity,
        curr_entity: CodeEntity
    ) -> DriftFlag:
        """Create flag for stale documentation."""
        return DriftFlag(
            repository=current_snapshot.repository,
            flag_type='stale_doc',
            qualified_name=curr_entity.qualified_name,
            previous_snapshot=previous_snapshot,
            current_snapshot=current_snapshot,
            previous_entity=prev_entity,
            current_entity=curr_entity,
            detail={
                'old_hash': prev_entity.source_hash,
                'new_hash': curr_entity.source_hash,
                'signature': curr_entity.signature,
                'doc_is_outdated': curr_entity.doc_source == 'copied',
            }
        )
    
    def _create_signature_changed_flag(
        self,
        current_snapshot: Snapshot,
        previous_snapshot: Snapshot,
        prev_entity: CodeEntity,
        curr_entity: CodeEntity
    ) -> DriftFlag:
        """Create flag for signature change."""
        return DriftFlag(
            repository=current_snapshot.repository,
            flag_type='signature_changed',
            qualified_name=curr_entity.qualified_name,
            previous_snapshot=previous_snapshot,
            current_snapshot=current_snapshot,
            previous_entity=prev_entity,
            current_entity=curr_entity,
            detail={
                'old_signature': prev_entity.signature,
                'new_signature': curr_entity.signature,
            }
        )
    
    def _create_orphaned_doc_flag(
        self,
        current_snapshot: Snapshot,
        previous_snapshot: Snapshot,
        prev_entity: CodeEntity
    ) -> DriftFlag:
        """Create flag for orphaned documentation."""
        return DriftFlag(
            repository=current_snapshot.repository,
            flag_type='orphaned_doc',
            qualified_name=prev_entity.qualified_name,
            previous_snapshot=previous_snapshot,
            current_snapshot=current_snapshot,
            previous_entity=prev_entity,
            current_entity=None,
            detail={
                'signature': prev_entity.signature,
                'file_path': prev_entity.file_path,
            }
        )
