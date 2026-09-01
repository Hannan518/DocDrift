// Repository list page: delete + re-analyze with toast feedback.
(() => {
  'use strict';

  document.addEventListener('click', async (event) => {
    const btn = event.target.closest('[data-action]');
    if (!btn) return;

    const action = btn.dataset.action;
    const url = btn.dataset.url;
    const card = btn.closest('[data-repo-card]');
    const name = card ? card.dataset.repoName : 'this repository';

    if (action === 'delete') {
      if (!window.confirm(`Delete "${name}"? All snapshots and documentation will be removed.`)) return;
      btn.disabled = true;
      const res = await window.DocGen.api(url);
      if (res.ok) {
        window.DocGen.toast(`Deleted "${name}"`, 'success');
        card.remove();
        if (!document.querySelector('[data-repo-card]')) window.location.reload();
      } else {
        btn.disabled = false;
        window.DocGen.toast((res.data && res.data.error) || 'Delete failed', 'error');
      }
    }

    if (action === 'reanalyze') {
      btn.disabled = true;
      const res = await window.DocGen.api(url);
      if (res.ok) {
        window.location.href = `/analysis/${res.data.snapshot_id}/status/`;
      } else {
        btn.disabled = false;
        window.DocGen.toast((res.data && res.data.error) || 'Could not start re-analysis', 'error');
      }
    }
  });
})();
