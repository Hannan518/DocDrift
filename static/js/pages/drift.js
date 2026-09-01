// Drift dashboard: renders server-computed unified diffs (safe textContent
// rendering) and the re-analyze action.
(() => {
  'use strict';

  const dataEl = document.getElementById('flags-data');
  const flags = dataEl ? JSON.parse(dataEl.textContent) : {};

  function renderDiff(container, unifiedDiff) {
    container.textContent = '';

    if (!unifiedDiff || !unifiedDiff.trim()) {
      const empty = document.createElement('div');
      empty.style.padding = '14px';
      empty.style.color = 'var(--code-muted)';
      empty.textContent = 'No source stored for this comparison.';
      container.append(empty);
      return;
    }

    const lines = unifiedDiff.split('\n');
    let newLine = 0;
    let oldLine = 0;

    for (const line of lines) {
      const row = document.createElement('div');
      row.className = 'diff-line';

      const ln = document.createElement('span');
      ln.className = 'ln';

      const sign = document.createElement('span');
      sign.className = 'sign';

      const text = document.createElement('span');

      if (line.startsWith('@@')) {
        const m = line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
        if (m) { oldLine = parseInt(m[1], 10); newLine = parseInt(m[2], 10); }
        row.classList.add('diff-line--hunk');
        ln.textContent = '···';
        text.textContent = line;
      } else if (line.startsWith('---') || line.startsWith('+++')) {
        row.classList.add('diff-line--meta');
        ln.textContent = '···';
        text.textContent = line;
      } else if (line.startsWith('+')) {
        row.classList.add('diff-line--add');
        ln.textContent = ++newLine;
        sign.textContent = '+';
        text.textContent = line.slice(1);
      } else if (line.startsWith('-')) {
        row.classList.add('diff-line--del');
        ln.textContent = oldLine++;
        sign.textContent = '−';
        text.textContent = line.slice(1);
      } else {
        ln.textContent = oldLine++;
        newLine++;
        sign.textContent = ' ';
        text.textContent = line.slice(1);
      }

      row.append(ln, sign, text);
      container.append(row);
    }
  }

  document.addEventListener('click', async (event) => {
    const btn = event.target.closest('[data-action]');
    if (!btn) return;

    if (btn.dataset.action === 'toggle-diff') {
      const flagEl = btn.closest('[data-flag-id]');
      const container = flagEl && flagEl.querySelector('[data-diff]');
      if (!container) return;

      if (container.classList.contains('hidden')) {
        if (!container.dataset.rendered) {
          const payload = flags[flagEl.dataset.flagId] || {};
          renderDiff(container, payload.unified_diff);
          container.dataset.rendered = '1';
        }
        container.classList.remove('hidden');
        btn.textContent = 'Hide diff';
      } else {
        container.classList.add('hidden');
        btn.textContent = 'View diff';
      }
    }

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
  });
})();
