// Repository detail page: re-analyze + delete with toast feedback.
(() => {
  'use strict';

  document.addEventListener('click', async (event) => {
    const btn = event.target.closest('[data-action]');
    if (!btn) return;

    if (btn.dataset.action === 'reanalyze') {
      btn.disabled = true;
      const res = await window.DocGen.api(btn.dataset.url);
      if (res.ok) {
        window.location.href = `/analysis/${res.data.snapshot_id}/status/`;
      } else {
        btn.disabled = false;
        window.DocGen.toast((res.data && res.data.error) || 'Could not start re-analysis', 'error');
      }
    }

    if (btn.dataset.action === 'delete') {
      const name = btn.dataset.name || 'this repository';
      if (!window.confirm(`Delete "${name}"? All snapshots and documentation will be removed.`)) return;
      btn.disabled = true;
      const res = await window.DocGen.api(btn.dataset.url);
      if (res.ok) {
        window.DocGen.toast(`Deleted "${name}"`, 'success');
        window.location.href = '/repositories/';
      } else {
        btn.disabled = false;
        window.DocGen.toast((res.data && res.data.error) || 'Delete failed', 'error');
      }
    }
  });
})();
