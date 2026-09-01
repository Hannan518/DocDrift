// Analysis orchestrator: drives the pipeline with sequential batches.
// Loop-safety: every loop advances a server-issued cursor (next_offset /
// next_after_id) and terminates when the cursor is null. Failed doc-gen
// entities are retried once with a fresh cursor, then the run finishes.
(() => {
  'use strict';

  const cfg = window.DOCGEN_SNAPSHOT;
  if (!cfg) return;

  const els = {
    message: document.getElementById('status-message'),
    progressBar: document.getElementById('progress-bar'),
    progressText: document.getElementById('progress-text'),
    errorBox: document.getElementById('error-container'),
    errorText: document.getElementById('error-message'),
    successBox: document.getElementById('success-banner'),
    successText: document.getElementById('success-message'),
    retryBtn: document.getElementById('retry-btn'),
  };

  const PARSE_BATCH = 10;
  const DOC_BATCH = 10;
  const MAX_DOCGEN_ROUNDS = 4; // 1 initial pass + up to 3 retry passes

  const errorEl = document.getElementById('snapshot-error-message');
  const serverError = errorEl ? JSON.parse(errorEl.textContent) : null;

  const steps = {
    set(n, state) {
      const step = document.querySelector(`[data-step="${n}"]`);
      if (step) step.className = `step step--${state}`;
      if (n < 5 && (state === 'done' || state === 'active')) {
        const line = document.querySelector(`[data-line="${n}"]`);
        if (line) line.className = `step-line step-line--${state}`;
      }
    },
    doneUpTo(n, activeErrorStep = null) {
      for (let i = 1; i <= n; i++) this.set(i, 'done');
      if (activeErrorStep) this.set(activeErrorStep, 'error');
      else if (n < 5) this.set(n + 1, 'active');
    },
  };

  function updateUI(message, progress) {
    if (message) els.message.textContent = message;
    if (progress != null) {
      els.progressBar.style.width = `${progress}%`;
      els.progressText.textContent = `${Math.round(progress)}%`;
    }
  }

  function showError(message, step = null) {
    els.errorText.textContent = message || 'Something went wrong during analysis.';
    els.errorBox.classList.remove('hidden');
    els.message.textContent = 'Analysis failed';
    if (step) steps.set(step, 'error');
  }

  async function api(url, body) {
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': window.DocGen.csrf(),
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
      let data = null;
      try { data = await response.json(); } catch { data = null; }
      return { ok: response.ok, status: response.status, data: data || {} };
    } catch (err) {
      return { ok: false, status: 0, data: { error: 'Network error: ' + err.message } };
    }
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  async function runPrepare() {
    updateUI('Cloning repository…', 2);
    const res = await api(cfg.urls.prepare);
    if (!res.ok) throw { message: res.data.error || 'Failed to clone repository', step: 1 };
    updateUI(`Cloned — ${res.data.total_files} Python files found`, 4);
  }

  async function runParsing() {
    updateUI('Parsing Python files…', 5);
    let offset = 0;
    for (;;) {
      const res = await api(cfg.urls.parseBatch, { offset, limit: PARSE_BATCH });
      if (!res.ok) throw { message: res.data.error || 'Parsing failed', step: 2 };
      const { total, parsed, next_offset: next } = res.data;
      updateUI(`Parsing files (${offset + parsed}/${total})`, 5 + ((offset + parsed) / Math.max(total, 1)) * 25);
      if (next == null) break; // cursor exhausted - guaranteed termination
      offset = next;
      await sleep(50);
    }
  }

  async function runPrepareDocs() {
    const res = await api(cfg.urls.prepareDocs);
    if (!res.ok) throw { message: res.data.error || 'Doc preparation failed', step: 3 };
    updateUI(res.data.entities_to_document > 0
      ? `Copied ${res.data.entities_copied} unchanged docs — generating ${res.data.entities_to_document}`
      : `All ${res.data.entities_copied} docs carried over from the previous snapshot`, 32);
  }

  async function runDocGeneration() {
    let documentedTotal = null;

    for (let round = 0; round < MAX_DOCGEN_ROUNDS; round++) {
      let afterId = 0;
      let failures = 0;

      for (;;) {
        const res = await api(cfg.urls.generateDocs, { after_id: afterId, limit: DOC_BATCH });
        if (!res.ok) throw { message: res.data.error || 'Doc generation failed', step: 4 };

        const { succeeded, failed, remaining, next_after_id: next } = res.data;
        failures = Math.max(failures, failed || 0);

        if (remaining != null) {
          // Total = documented + still-needed gives a stable denominator.
          documentedTotal = documentedTotal == null
            ? remaining + (succeeded || 0)
            : documentedTotal;
          const done = documentedTotal - remaining;
          updateUI(
            `Generating documentation (${done}/${documentedTotal})`,
            32 + (done / Math.max(documentedTotal, 1)) * 56
          );
        }

        if (next == null) break; // cursor exhausted
        afterId = next;
        await sleep(50);
      }

      if (failures === 0 || round === MAX_DOCGEN_ROUNDS - 1) break;
      updateUI('Retrying entities that failed doc generation…');
      await sleep(1500);
    }
  }

  async function runDriftDetection() {
    updateUI('Detecting drift from previous snapshot…', 92);
    const res = await api(cfg.urls.detectDrift);
    if (!res.ok) throw { message: res.data.error || 'Drift detection failed', step: 5 };
    updateUI(`Drift detection complete — ${res.data.drift_flags_created || 0} flag(s)`, 96);
  }

  // Pipeline stage order; resume point is derived from the persisted status.
  const PHASES = { prepare: 0, parse: 1, copyDocs: 2, genDocs: 3, drift: 4 };

  function startPhase(status) {
    if (status === 'pending') return PHASES.prepare;
    if (['ready_to_parse', 'parsing'].includes(status)) return PHASES.parse;
    if (status === 'parsing_complete') return PHASES.copyDocs;
    if (status === 'generating_docs') return PHASES.genDocs;
    if (['docs_complete', 'detecting_drift'].includes(status)) return PHASES.drift;
    return PHASES.prepare;
  }

  async function run() {
    const s = cfg.status;

    if (s === 'complete') {
      window.location.href = cfg.urls.browser;
      return;
    }

    if (s === 'failed') {
      steps.doneUpTo(5, 3);
      showError(serverError || 'Analysis failed. Try re-analyzing.');
      return;
    }

    const from = startPhase(s);

    try {
      if (from === PHASES.prepare) {
        steps.doneUpTo(0);
        await runPrepare();
      }

      if (from <= PHASES.parse) {
        steps.doneUpTo(1);
        await runParsing();
      }

      if (from <= PHASES.copyDocs) {
        steps.doneUpTo(2);
        await runPrepareDocs();
      }

      if (from <= PHASES.genDocs) {
        steps.doneUpTo(3);
        await runDocGeneration();
      }

      steps.doneUpTo(4);
      await runDriftDetection();

      steps.doneUpTo(5);
      els.successBox.classList.remove('hidden');
      els.successText.textContent = 'Analysis complete — opening documentation…';
      updateUI('Analysis complete', 100);
      await sleep(900);
      window.location.href = cfg.urls.browser;
    } catch (err) {
      const message = err && err.message ? err.message : String(err);
      showError(message, err && err.step);
    }
  }

  els.retryBtn.addEventListener('click', () => window.location.reload());

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', run);
  } else {
    run();
  }
})();
