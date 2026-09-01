// Submit page: AJAX form with inline errors + button loading state.
(() => {
  'use strict';

  const form = document.getElementById('submit-form');
  if (!form) return;

  const btn = document.getElementById('submit-btn');
  const errorBox = document.getElementById('submit-error');
  const nameInput = document.getElementById('id_name');

  // Pre-fill the name from the URL once the URL looks like a repo link.
  const urlInput = document.getElementById('id_github_url');
  urlInput.addEventListener('input', () => {
    const match = urlInput.value.match(/github\.com\/[\w.-]+\/([\w.-]+)/);
    if (match && !nameInput.dataset.touched) {
      nameInput.value = match[1].replace(/\.git$/, '');
    }
  });
  nameInput.addEventListener('input', () => { nameInput.dataset.touched = '1'; });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    errorBox.classList.add('hidden');
    btn.disabled = true;
    btn.prepend(spinner());

    const payload = {
      name: nameInput.value.trim(),
      github_url: urlInput.value.trim(),
    };

    const res = await window.DocGen.api(form.dataset.url, { body: payload });

    if (res.ok && res.data.snapshot_id) {
      window.DocGen.toast('Repository submitted — starting analysis', 'success');
      window.location.href = `/analysis/${res.data.snapshot_id}/status/`;
      return;
    }

    btn.disabled = false;
    btn.querySelector('.spinner')?.remove();
    errorBox.textContent = (res.data && res.data.error) || 'Something went wrong. Please try again.';
    errorBox.classList.remove('hidden');
  });

  function spinner() {
    const s = document.createElement('span');
    s.className = 'spinner';
    return s;
  }
})();
