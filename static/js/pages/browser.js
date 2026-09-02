// Documentation browser: file tree with class nesting, live search,
// and a detail pane fed from a JSON data island (no inline payloads).
(() => {
  'use strict';

  const dataEl = document.getElementById('entities-data');
  if (!dataEl) return;

  const entities = JSON.parse(dataEl.textContent);
  const byId = new Map(entities.map((e) => [e.id, e]));

  const els = {
    tree: document.getElementById('tree'),
    search: document.getElementById('tree-search'),
    placeholder: document.getElementById('entity-placeholder'),
    view: document.getElementById('entity-view'),
    name: document.getElementById('entity-name'),
    location: document.getElementById('entity-location'),
    badge: document.getElementById('entity-doc-badge'),
    signature: document.getElementById('entity-signature'),
    doc: document.getElementById('entity-doc'),
    body: document.getElementById('entity-body'),
    regenBtn: document.getElementById('entity-regen-btn'),
  };

  // Snapshot id (for per-entity regenerate URL).
  const snapshotId = (() => {
    const m = window.location.pathname.match(/\/analysis\/(\d+)\/browser\//);
    return m ? m[1] : null;
  })();

  const KIND_ICONS = {
    class: '<svg class="kind-class" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="3"/><path d="M9 17V9h6M9 13h5"/></svg>',
    function: '<svg class="kind-function" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H4v4M16 3h4v4M8 21H4v-4M16 21h4v-4"/></svg>',
    module: '<svg class="kind-module" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>',
  };

  const BADGES = {
    generated: ['doc-badge--generated', 'LLM generated'],
    copied: ['doc-badge--copied', 'Carried from previous run'],
    existing: ['doc-badge--existing', 'From source code'],
    stale: ['doc-badge--stale', 'Stale - code changed, awaiting review'],
    none: ['doc-badge--none', 'Undocumented'],
  };

  let currentEntityId = null;

  // ---- Build tree: file -> top-level entities -> children ----
  const roots = entities.filter((e) => !e.parent_id);
  const childrenOf = new Map();
  for (const e of entities) {
    if (e.parent_id) {
      if (!childrenOf.has(e.parent_id)) childrenOf.set(e.parent_id, []);
      childrenOf.get(e.parent_id).push(e);
    }
  }

  const files = new Map();
  for (const e of roots) {
    const key = e.file_path.split(/[\\/]/).slice(-2).join('/');
    if (!files.has(key)) files.set(key, []);
    files.get(key).push(e);
  }

  function nodeEl(entity, depth) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'tree-node';
    btn.dataset.entityId = entity.id;
    btn.dataset.qname = (entity.qualified_name + ' ' + entity.name).toLowerCase();
    btn.style.paddingLeft = `${8 + depth * 14}px`;

    const icon = document.createElement('span');
    icon.className = 'entity-kind-icon';
    icon.innerHTML = KIND_ICONS[entity.entity_type] || KIND_ICONS.function;

    const name = document.createElement('span');
    name.className = 'node-name';
    name.textContent = entity.name;

    const kind = document.createElement('span');
    kind.className = 'node-kind';
    kind.textContent = entity.entity_type === 'function' ? 'fn' : 'cls';

    btn.append(icon, name, kind);
    btn.addEventListener('click', () => selectEntity(entity.id));

    const wrapper = document.createElement('div');
    wrapper.dataset.nodeFor = entity.id;
    wrapper.dataset.searchText = btn.dataset.qname;
    wrapper.append(btn);

    const kids = childrenOf.get(entity.id) || [];
    if (kids.length) {
      const children = document.createElement('div');
      children.className = 'tree-children';
      for (const kid of kids) children.append(nodeEl(kid, depth + 1));
      children.hidden = true;
      wrapper.append(children);
    }

    return wrapper;
  }

  for (const [file, fileRoots] of files) {
    const fileEl = document.createElement('div');
    fileEl.className = 'tree-file';

    const head = document.createElement('button');
    head.type = 'button';
    head.className = 'tree-file__head';
    head.innerHTML = '<svg class="chev" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 6 15 12 9 18"/></svg>';
    const nameSpan = document.createElement('span');
    nameSpan.className = 'name';
    nameSpan.textContent = file;
    nameSpan.title = file;
    head.append(nameSpan);

    const children = document.createElement('div');
    children.className = 'tree-file__children';
    for (const root of fileRoots) children.append(nodeEl(root, 0));

    head.addEventListener('click', () => fileEl.classList.toggle('is-open'));
    fileEl.append(head, children);
    els.tree.append(fileEl);
  }

  // Auto-expand files with few entities for a friendlier first render.
  if (files.size <= 8) {
    document.querySelectorAll('.tree-file').forEach((f) => f.classList.add('is-open'));
  }

  // ---- Search: match nodes and reveal all ancestors ----
  els.search.addEventListener('input', () => {
    const q = els.search.value.trim().toLowerCase();

    document.querySelectorAll('.tree-file').forEach((f) => f.classList.remove('is-open'));
    document.querySelectorAll('.tree-children').forEach((c) => { c.hidden = true; });
    document.querySelectorAll('[data-node-for]').forEach((n) => n.classList.remove('hidden'));

    if (!q) {
      if (files.size <= 8) document.querySelectorAll('.tree-file').forEach((f) => f.classList.add('is-open'));
      return;
    }

    let hits = 0;
    for (const node of document.querySelectorAll('[data-node-for]')) {
      if (node.dataset.searchText.includes(q)) {
        hits++;
        // Reveal: open enclosing file, unhide + open ancestor chains.
        node.closest('.tree-file')?.classList.add('is-open');
        let parent = node.parentElement;
        while (parent && parent !== els.tree) {
          if (parent.classList.contains('tree-children')) parent.hidden = false;
          parent.classList?.remove('hidden');
          parent = parent.parentElement;
        }
      } else {
        node.classList.add('hidden');
      }
    }

    if (hits === 0) {
      window.DocDrift.toast('No matching entities', 'info');
    }
  });

  // ---- Detail pane ----
  function selectEntity(id) {
    const entity = byId.get(id);
    if (!entity) return;
    currentEntityId = id;

    document.querySelectorAll('.tree-node').forEach((n) => n.classList.remove('is-selected'));
    document.querySelector(`[data-entity-id="${id}"]`)?.classList.add('is-selected');

    els.placeholder.classList.add('hidden');
    els.view.classList.remove('hidden');

    els.name.textContent = entity.qualified_name;
    els.location.textContent = `${entity.file_path.split(/[\\/]/).slice(-2).join('/')} · line ${entity.line_number}`;

    const [badgeClass, badgeText] = BADGES[entity.doc_source] || BADGES.none;
    els.badge.className = `doc-badge ${badgeClass}`;
    els.badge.textContent = entity.doc ? badgeText : 'Undocumented';

    // Show the regenerate button only when the doc is stale (user can
    // explicitly ask the LLM to refresh just this one).
    if (entity.doc_source === 'stale') {
      els.regenBtn.classList.remove('hidden');
      els.regenBtn.disabled = false;
      els.regenBtn.textContent = 'Regenerate doc';
    } else {
      els.regenBtn.classList.add('hidden');
    }

    els.signature.textContent = entity.signature;
    els.doc.textContent = entity.doc || 'No documentation available for this entity.';
    els.body.textContent = entity.body;
  }

  // Per-entity regenerate: POST to the analysis endpoint, swap the doc text
  // and badge in place. No reload needed.
  els.regenBtn?.addEventListener('click', async () => {
    if (!currentEntityId || !snapshotId) return;
    const url = `/analysis/${snapshotId}/entities/${currentEntityId}/regenerate/`;
    els.regenBtn.disabled = true;
    els.regenBtn.textContent = 'Regenerating…';
    try {
      const res = await window.DocDrift.api(url, { method: 'POST', body: {} });
      if (res.status >= 200 && res.status < 300) {
        const data = res.data;
        // Update local cache + DOM
        const e = byId.get(currentEntityId);
        if (e) { e.doc = data.doc; e.doc_source = data.doc_source; }
        els.doc.textContent = data.doc;
        const [badgeClass, badgeText] = BADGES[data.doc_source] || BADGES.generated;
        els.badge.className = `doc-badge ${badgeClass}`;
        els.badge.textContent = badgeText;
        window.DocDrift.toast('Documentation regenerated', 'success');
        els.regenBtn.classList.add('hidden');
      } else {
        const msg = (res.data && res.data.error) || 'Regenerate failed';
        window.DocDrift.toast(msg, 'error');
      }
    } catch (e) {
      window.DocDrift.toast('Regenerate failed', 'error');
    } finally {
      els.regenBtn.disabled = false;
      els.regenBtn.textContent = 'Regenerate doc';
    }
  });
})();
