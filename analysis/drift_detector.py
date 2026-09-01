"""Drift detection module for comparing snapshots."""

import difflib
import logging

from .models import DriftFlag

logger = logging.getLogger(__name__)

MAX_SOURCE_CHARS = 4000
MAX_DOC_CHARS = 2000
MAX_DIFF_CHARS = 10000


def _clip(text: str, limit: int) -> str:
    """Truncate long text for storage in the detail JSON."""
    text = text or ''
    if len(text) <= limit:
        return text
    return text[:limit] + '\n... (truncated)'


def _unified_diff(old_source: str, new_source: str) -> str:
    """Build a unified diff between two source bodies."""
    old_lines = (old_source or '').splitlines()
    new_lines = (new_source or '').splitlines()
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile='previous',
        tofile='current',
        lineterm='',
    )
    return _clip('\n'.join(diff), MAX_DIFF_CHARS)


class DriftDetector:
    """Detects documentation drift between snapshots."""

    def detect_drift(self, previous_snapshot, current_snapshot) -> int:
        """
        Compare two snapshots and create DriftFlag records.

        Idempotent: any flags from a previous detection run for the current
        snapshot are removed before new ones are created.

        Args:
            previous_snapshot: Earlier snapshot to compare against
            current_snapshot: Current snapshot to check for drift

        Returns:
            Number of drift flags created
        """
        DriftFlag.objects.filter(current_snapshot=current_snapshot).delete()

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
            prev_entity = prev_entities.get(qname)

            if prev_entity is None:
                # New entity: only drift if it ended up without any docs
                if not self._has_docs(curr_entity):
                    flags.append(self._create_new_undocumented_flag(
                        current_snapshot, previous_snapshot, curr_entity
                    ))
                continue

            # Code changed since the previous snapshot
            if curr_entity.source_hash != prev_entity.source_hash:
                flags.append(self._create_stale_doc_flag(
                    current_snapshot, previous_snapshot, prev_entity, curr_entity
                ))

            # Public interface changed
            if curr_entity.signature != prev_entity.signature:
                flags.append(self._create_signature_changed_flag(
                    current_snapshot, previous_snapshot, prev_entity, curr_entity
                ))

        # Documentation for removed entities
        for qname, prev_entity in prev_entities.items():
            if qname not in curr_entities and self._has_docs(prev_entity):
                flags.append(self._create_orphaned_doc_flag(
                    current_snapshot, previous_snapshot, prev_entity
                ))

        if flags:
            DriftFlag.objects.bulk_create(flags)
            logger.info("Created %d drift flags for snapshot %s",
                        len(flags), current_snapshot.id)

        return len(flags)

    @staticmethod
    def _has_docs(entity) -> bool:
        """Whether an entity carries any documentation."""
        return bool(entity.generated_docstring or entity.existing_docstring)

    def _create_new_undocumented_flag(
        self,
        current_snapshot,
        previous_snapshot,
        curr_entity
    ) -> DriftFlag:
        """Create flag for new code that has no documentation."""
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
        current_snapshot,
        previous_snapshot,
        prev_entity,
        curr_entity
    ) -> DriftFlag:
        """Create flag for code whose body changed since the last snapshot."""
        old_source = prev_entity.source_body or ''
        new_source = curr_entity.source_body or ''

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
                'old_source': _clip(old_source, MAX_SOURCE_CHARS),
                'new_source': _clip(new_source, MAX_SOURCE_CHARS),
                'old_doc': _clip(prev_entity.generated_docstring
                                 or prev_entity.existing_docstring or '',
                                 MAX_DOC_CHARS),
                'new_doc': _clip(curr_entity.generated_docstring
                                 or curr_entity.existing_docstring or '',
                                 MAX_DOC_CHARS),
                'unified_diff': _unified_diff(old_source, new_source),
                'file_path': curr_entity.file_path,
                'line_number': curr_entity.line_number,
            }
        )

    def _create_signature_changed_flag(
        self,
        current_snapshot,
        previous_snapshot,
        prev_entity,
        curr_entity
    ) -> DriftFlag:
        """Create flag for entities whose public signature changed."""
        old_source = prev_entity.source_body or ''
        new_source = curr_entity.source_body or ''

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
                'old_source': _clip(old_source, MAX_SOURCE_CHARS),
                'new_source': _clip(new_source, MAX_SOURCE_CHARS),
                'unified_diff': _unified_diff(old_source, new_source),
                'file_path': curr_entity.file_path,
                'line_number': curr_entity.line_number,
            }
        )

    def _create_orphaned_doc_flag(
        self,
        current_snapshot,
        previous_snapshot,
        prev_entity
    ) -> DriftFlag:
        """Create flag for documented entities that no longer exist."""
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
                'old_doc': _clip(prev_entity.generated_docstring
                                 or prev_entity.existing_docstring or '',
                                 MAX_DOC_CHARS),
            }
        )
